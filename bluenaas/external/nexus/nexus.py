"""Nexus module."""

import zipfile
from pathlib import Path
from urllib.parse import quote_plus, unquote
from loguru import logger
import requests

HTTP_TIMEOUT = 10  # seconds

model_dir = Path("/opt/blue-naas/") / "models"
defaultIdBaseUrl = "https://bbp.epfl.ch/data/bbp/mmb-point-neuron-framework-model"


class Nexus:
    """Nexus class to help downloading the emodel files needed for simulation."""

    # pylint: disable=missing-function-docstring
    def __init__(self, params):
        self.headers = {}
        self.model_self_url = params["model_self_url"]
        base_and_id = self.model_self_url.split("/")
        self.model_id = unquote(base_and_id[-1])
        self.model_uuid = self.model_id.split("/")[-1]
        # join all except the last part (id)
        self.nexus_base = f'{"/".join(base_and_id[:-1])}/'
        self.headers.update({"Authorization": params["token"]})

    def fetch_resource_by_id(self, resource_id):
        endpoint = self.compose_url(resource_id)
        r = requests.get(endpoint, headers=self.headers, timeout=HTTP_TIMEOUT)
        if not r.ok:
            raise Exception("Error fetching resource", r.json())
        return r.json()

    def fetch_resource_by_self(self, resource_self):
        r = requests.get(resource_self, headers=self.headers, timeout=HTTP_TIMEOUT)
        if not r.ok:
            raise Exception("Error fetching resource", r.json())
        return r.json()

    def fetch_file_by_url(self, file_url):
        r = requests.get(file_url, headers=self.headers, timeout=HTTP_TIMEOUT)
        if not r.ok:
            raise Exception("Error fetching file", r.status_code)
        return r

    def compose_url(self, url):
        return self.nexus_base + quote_plus(url, safe=":")

    def get_workflow_id(self, emodel_resource):
        return emodel_resource["generation"]["activity"]["followedWorkflow"]["@id"]

    def get_configuration_id(self, emodel_resource):
        workflow_id = self.get_workflow_id(emodel_resource)
        workflow_resource = self.fetch_resource_by_id(workflow_id)

        configuration = None
        for part in workflow_resource["hasPart"]:
            if part["@type"] == "EModelConfiguration":
                configuration = part
                break

        if configuration is None:
            raise Exception("No E-Model configuration found")

        return configuration["@id"]

    def get_emodel_configuration(self, emodel_resource):
        configuration_id = self.get_configuration_id(emodel_resource)
        return self.fetch_resource_by_id(configuration_id)

    def get_morphology(self, morph_id):
        morphology_resource = self.fetch_resource_by_id(morph_id)

        distributions = morphology_resource["distribution"]
        if not isinstance(distributions, list):
            raise Exception("NeuronMorphology distribution is not an array")

        swc = None
        for distribution in distributions:
            if distribution["encodingFormat"] == "application/swc":
                swc = distribution
                break

        if swc is None:
            raise Exception("SWC format not found in NeuronMorphology distribution")

        file = self.fetch_file_by_url(swc["contentUrl"])

        return {"name": swc["name"], "content": file.text}

    def get_emodel_morphology(self, configuration):
        morphology = None
        for item in configuration["uses"]:
            if item["@type"] == "NeuronMorphology":
                morphology = item
                break
        if morphology is None:
            raise Exception("NeuronMorphology not found")

        return self.get_morphology(morphology["@id"])

    def get_memodel_morphology(self, memodel_resource):
        morphology_id = None
        for haspart in memodel_resource["hasPart"]:
            if haspart["@type"] == "NeuronMorphology":
                morphology_id = haspart["@id"]
        if morphology_id is None:
            raise Exception("No Morphology found in ME-Model")

        return self.get_morphology(morphology_id)

    def get_mechanisms(self, configuration):
        # fetch only SubCellularModelScripts. Morphologies will be fetched later
        scripts = []
        for config in configuration["uses"]:
            if config["@type"] != "NeuronMorphology":
                scripts.append(config)

        model_resources = []
        for script in scripts:
            script_resource = self.fetch_resource_by_id(script["@id"])
            model_resources.append(script_resource)

        # TODO: Add these configuration to the model
        extra_mechanisms = [
            "https://openbluebrain.com/api/nexus/v1/resources/bbp/mmb-point-neuron-framework-model/_/https:%2F%2Fbbp.epfl.ch%2Fneurosciencegraph%2Fdata%2Fsynapticphysiologymodels%2Fe3c32384-5cb1-4dd3-a8c9-f6c23bea6b27",
            "https://openbluebrain.com/api/nexus/v1/resources/bbp/mmb-point-neuron-framework-model/_/https:%2F%2Fbbp.epfl.ch%2Fneurosciencegraph%2Fdata%2Fsynapticphysiologymodels%2F3965bc40-ca30-475b-98be-cfa3e22057b5",
        ]
        for extra_mech in extra_mechanisms:
            mech = self.fetch_resource_by_self(extra_mech)
            model_resources.append(mech)

        mechanisms = []
        for model_resource in model_resources:
            distribution = model_resource["distribution"]
            if isinstance(distribution, list):
                distribution = list(
                    filter(
                        lambda x: x["encodingFormat"] == "application/mod"
                        or x["encodingFormat"] == "application/neuron-mod",
                        distribution,
                    )
                )[0]

            file = self.fetch_file_by_url(distribution["contentUrl"])
            mechanisms.append({"name": distribution["name"], "content": file.text})

        return mechanisms

    def get_script_resource(self, emodel_resource):
        workflow_id = self.get_workflow_id(emodel_resource)
        workflow_resource = self.fetch_resource_by_id(workflow_id)

        script = None
        for generated in workflow_resource["generates"]:
            if generated["@type"] == "EModelScript":
                script = generated
                break

        if script is None:
            raise Exception("No E-Model script found")

        return self.fetch_resource_by_id(script["@id"])

    def get_hoc_file(self, emodel_resource):
        emodel_script = self.get_script_resource(emodel_resource)
        distribution = emodel_script["distribution"]

        if isinstance(distribution, list):
            for dist in distribution:
                if dist["encodingFormat"] == "application/hoc":
                    distribution = dist
                    break

        emodel_script_url = distribution["contentUrl"]

        r = self.fetch_file_by_url(emodel_script_url)
        return r.text

    def create_compressed_file(self, hoc_file, morphology_obj, mechanisms):
        final_compressed_file = model_dir / f"{self.model_uuid}.tar"

        with zipfile.ZipFile(final_compressed_file, mode="w") as archive:
            archive.writestr("cell.hoc", hoc_file)

            morph_name = morphology_obj["name"]
            archive.writestr(
                f"morphology/{morph_name}",
                morphology_obj["content"],
            )

            for mechanism in mechanisms:
                mech_name = mechanism["name"]
                archive.writestr(
                    f"mechanisms/{mech_name}",
                    mechanism["content"],
                )

    def create_file(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def copy_file_content(self, source_file: Path, target_file: Path):
        with open(source_file, "r") as src, open(target_file, "w") as dst:
            dst.write(src.read())

    def create_model_folder(self, hoc_file, morphology_obj, mechanisms):
        output_dir = model_dir / self.model_uuid
        self.create_file(output_dir / "cell.hoc", hoc_file)

        morph_name = morphology_obj["name"]
        self.create_file(
            output_dir / "morphology" / morph_name, morphology_obj["content"]
        )

        for mechanism in mechanisms:
            mech_name = mechanism["name"]
            self.create_file(
                output_dir / "mechanisms" / mech_name, mechanism["content"]
            )

        self.copy_file_content(
            Path("/app/bluenaas/config/VecStim.mod"),
            output_dir / "mechanisms" / "VecStim.mod",
        )

    def get_emodel_resource(self, resource):
        if "MEModel" in resource["@type"]:
            logger.debug("Model is ME-Model")
            emodel_id = None
            if "hasPart" not in resource:
                raise AttributeError("ME-Model resource has no 'hasPart' metadata")
            for haspart in resource["hasPart"]:
                if haspart["@type"] == "EModel":
                    emodel_id = haspart["@id"]
            if emodel_id is None:
                raise Exception("No E-Model found in ME-Model")
            emodel_resource = self.fetch_resource_by_id(emodel_id)
        else:
            logger.debug("Model is E-Model")
            emodel_resource = resource
        return emodel_resource

    def download_model(self):
        logger.debug("Getting model...")
        resource = self.fetch_resource_by_id(self.model_id)
        # could be E-Model or ME-Model
        emodel_resource = self.get_emodel_resource(resource)
        logger.debug("E-Model resource fetched")
        configuration = self.get_emodel_configuration(emodel_resource)
        logger.debug("E-Model configuration fetched")
        mechanisms = self.get_mechanisms(configuration)
        logger.debug("E-Model mechanisms fetched")
        hoc_file = self.get_hoc_file(emodel_resource)
        logger.debug("E-Model hoc file fetched")
        if "MEModel" in resource["@type"]:
            logger.debug("Fetching Morphology from ME-Model")
            morphology_obj = self.get_memodel_morphology(resource)
        else:
            logger.debug("Fetching Morphology from E-Model")
            morphology_obj = self.get_emodel_morphology(configuration)
        logger.debug("Morphology fetched")
        self.create_model_folder(hoc_file, morphology_obj, mechanisms)
        logger.debug("E-Model folder created")

    def get_currents(self):
        resource = self.fetch_resource_by_id(self.model_id)

        if "MEModel" in resource["@type"]:
            logger.debug("Getting currents from ME-Model")
            return [resource["holding_current"], resource["threshold_current"]]

        logger.debug("Getting currents from E-Model")
        emodel_resource = self.get_emodel_resource(resource)
        emodel_script = self.get_script_resource(emodel_resource)

        return [
            0
            if "holding_current" not in emodel_script
            else emodel_script["holding_current"],
            0
            if "threshold_current" not in emodel_script
            else emodel_script["threshold_current"],
        ]

    def get_model_uuid(self):
        return self.model_uuid
