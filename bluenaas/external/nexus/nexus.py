"""Nexus module."""

from datetime import datetime
from typing import Optional, Sequence, Any
import json
import zipfile
from pathlib import Path
from urllib.parse import quote_plus, unquote, urlencode
from loguru import logger
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bluenaas.domains.simulation import (
    SingleNeuronSimulationConfig,
    StimulationItemResponse,
    SimulationStatus,
)
from bluenaas.domains.nexus import (
    NexusSimulationPayload,
    BaseNexusSimulationResource,
)
from bluenaas.config.settings import settings
from bluenaas.utils.ensure_list import ensure_list
from bluenaas.utils.generate_id import generate_id
from bluenaas.core.exceptions import ResourceDeprecationError, SimulationError
from bluenaas.external.base import Service


HTTP_TIMEOUT = 10  # seconds

model_dir = Path("/opt/blue-naas/") / "models"
defaultIdBaseUrl = "https://bbp.epfl.ch/data/bbp/mmb-point-neuron-framework-model"

HOC_FORMATS = ["application/x-neuron-hoc", "application/neuron-hoc", "application/hoc"]


ENCODING_FORMAT_MAP = {
    "h5": "application/x-hdf5",
    "hdf5": "application/x-hdf5",
    "asc": "application/asc",
    "swc": "application/swc",
}


def extract_org_project_from_id(url) -> dict[str, str | None]:
    """Extracts the org and project of a resource id"""
    parts = url.split("/")
    if len(parts) >= 3:
        org_project = parts[-4:-2]
        return {"org": org_project[0], "project": org_project[1]}
    else:
        return {"org": None, "project": None}  # Handle URLs with fewer than 3 parts


def construct_time_range(
    start_date: Optional[datetime], end_date: Optional[datetime]
) -> str:
    """
    Constructs a time range string based on the given start and end dates.

    Args:
        start_date (Optional[datetime]): The start date of the range.
        end_date (Optional[datetime]): The end date of the range.

    Returns:
        str: The constructed time range string in the format 'start..end'.
    """
    start_str = start_date.strftime("%Y-%m-%dT%H:%M:%SZ") if start_date else "*"
    end_str = end_date.strftime("%Y-%m-%dT%H:%M:%SZ") if end_date else "*"

    return "{}..{}".format(start_str, end_str)


class Nexus(Service):
    """Nexus class to help download the emodel files needed for simulation."""

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
        self.fetch_cache = {}

    def fetch_resource_by_id(self, resource_id):
        if resource_id in self.fetch_cache:
            return self.fetch_cache[resource_id]

        org, project = extract_org_project_from_id(self.nexus_base).values()
        if org is None or project is None:
            raise Exception("org or project are missing")

        endpoint = f"{settings.NEXUS_ROOT_URI}/resolvers/{org}/{project}/_/{quote_plus(resource_id, safe=":")}"
        r = requests.get(endpoint, headers=self.headers, timeout=HTTP_TIMEOUT)
        if not r.ok:
            raise Exception("Error fetching resource", r.json())

        resource = r.json()
        self.fetch_cache[resource_id] = resource

        return resource

    def update_resource_by_id(
        self, org_label, project_label, resource_id, previous_rev, payload
    ):
        endpoint = f"{settings.NEXUS_ROOT_URI}/resources/{org_label}/{project_label}/_/{quote_plus(resource_id)}?rev={previous_rev}"
        payload_without_metadata = {
            k: v for k, v in payload.items() if not k.startswith("_")
        }

        r = requests.put(
            endpoint,
            headers=self.content_modification_headers(),
            data=json.dumps(payload_without_metadata),
            timeout=HTTP_TIMEOUT,
        )
        if not r.ok:
            raise Exception("Error updating resource", r.json())
        return r.json()

    def fetch_resource_by_self(self, resource_self):
        r = requests.get(resource_self, headers=self.headers, timeout=HTTP_TIMEOUT)
        if not r.ok:
            raise Exception("Error fetching resource", r.json())
        return r.json()

    def fetch_resource_for_org_project(self, org_label, project_label, resource_id):
        endpoint = f"{settings.NEXUS_ROOT_URI}/resolvers/{org_label}/{project_label}/_/{quote_plus(resource_id, safe=":")}"
        r = requests.get(
            endpoint,
            headers=self.headers,
            timeout=HTTP_TIMEOUT,
        )
        if not r.ok:
            raise Exception("Error fetching resource", r.json())
        return r.json()

    def deprecate_resource(self, org_label, project_label, resource_id, previous_rev):
        endpoint = f"{settings.NEXUS_ROOT_URI}/resources/{org_label}/{project_label}/_/{quote_plus(resource_id)}?rev={previous_rev}"
        r = requests.delete(
            endpoint,
            headers=self.content_modification_headers(),
            timeout=HTTP_TIMEOUT,
        )
        if not r.ok:
            raise ResourceDeprecationError("Error deprecating resource", r.json())
        return r.json()

    def fetch_resources_of_type(
        self,
        org_label: Optional[str],
        project_label: Optional[str],
        res_types: Sequence[str],
        offset: int,
        size: int,
        created_at_start: Optional[datetime],
        created_at_end: Optional[datetime],
    ):
        query_params = [("type", res_type) for res_type in res_types]
        query_params.append(("size", str(size)))
        query_params.append(("from", str(offset)))
        query_params.append(
            ("createdAt", construct_time_range(created_at_start, created_at_end))
        )
        query_params.append(("deprecated", "false"))

        # Sort resources in descending time of creation (i.e. newest first)
        query_params.append(("sort", "-_createdAt"))
        query_params.append(("sort", "-_updatedAt"))

        if org_label is None and project_label is None:
            endpoint = f"{settings.NEXUS_ROOT_URI}/resources?{urlencode(query_params)}"
        else:
            endpoint = f"{settings.NEXUS_ROOT_URI}/resources/{org_label}/{project_label}?{urlencode(query_params)}"

        r = requests.get(
            endpoint,
            headers=self.headers,
            timeout=HTTP_TIMEOUT,
        )
        if not r.ok:
            raise Exception("Error fetching resource", r.json())
        return r.json()

    def fetch_file_by_url(self, file_url):
        r = requests.get(file_url, headers=self.headers, timeout=HTTP_TIMEOUT)
        if not r.ok:
            raise Exception("Error fetching file", r.json())
        return r

    def fetch_file_metadata(self, file_url):
        r = requests.get(
            file_url,
            headers=self.headers | {"Accept": "application/ld+json"},
            timeout=HTTP_TIMEOUT,
        )
        if not r.ok:
            raise Exception("Error fetching file", r.json())
        return r

    def content_modification_headers(self):
        return self.headers | {
            "Content-Type": "application/json",
            "Accept": "*/*",
        }

    def save_file_to_nexus(
        self,
        payload: dict,
        content_type: str,
        filename: str,
        file_url: str,
        org_id: str,
        project_id: str,
    ) -> dict:
        stringified_data = json.dumps(payload)

        # Prepare the files for the POST request
        files = {"file": (filename, stringified_data, content_type)}
        file_headers = self.headers | {
            # mandatory to upload to a S3 storage (AWS)
            "x-nxs-file-content-length": str(len(stringified_data))
        }

        response = requests.post(
            file_url, headers=file_headers, files=files, timeout=HTTP_TIMEOUT
        )

        if not response.ok:
            raise Exception("Error saving file to nexus", response.json())
        return response.json()

    def create_nexus_distribution(
        self, payload: dict, filename: str, org_id: str, project_id: str
    ):
        content_type = "application/json"
        file_url = f"{settings.NEXUS_ROOT_URI}/files/{org_id}/{project_id}"

        saved_file = self.save_file_to_nexus(
            payload=payload,
            content_type=content_type,
            filename=filename,
            file_url=file_url,
            org_id=org_id,
            project_id=project_id,
        )

        distribution_url = f"{settings.NEXUS_ROOT_URI}/files/{org_id}/{project_id}/{quote_plus(saved_file["@id"])}"
        distribution = {
            "@type": "DataDownload",
            "name": saved_file["_filename"],
            "contentSize": {
                "unitCode": "bytes",
                "value": saved_file["_bytes"],
            },
            "contentUrl": distribution_url,
            "encodingFormat": saved_file["_mediaType"],
            "digest": {
                "algorithm": saved_file["_digest"]["_algorithm"],
                "value": saved_file["_digest"]["_value"],
            },
        }
        return distribution

    def update_json_nexus_distribution(
        self, file_url: str, filename: str, data_to_add: dict
    ):
        file_metadata = self.fetch_file_metadata(file_url=file_url).json()
        current_distribution = self.fetch_file_by_url(file_url=file_url).json()

        updated_json = current_distribution | data_to_add
        file_content = json.dumps(updated_json)
        # Prepare the files for the PUT request
        files = {"file": (filename, file_content, "application/json")}
        file_headers = self.headers | {
            # mandatory in order to upload to a S3 storage (AWS)
            "x-nxs-file-content-length": str(len(file_content))
        }

        response = requests.put(
            f"{file_url}?rev={file_metadata["_rev"]}",
            headers=file_headers,
            files=files,
            timeout=30,  # The request to write the distribution with simulation results sometimes takes more than 10 seconds.
        )

        if not response.ok:
            raise Exception(
                f"Error updating distribution: {response.status_code}", response.json()
            )
        return response.json()

    def compose_url(self, url):
        return self.nexus_base + quote_plus(url, safe=":")

    def get_workflow_id(self, emodel_resource):
        return emodel_resource["generation"]["activity"]["followedWorkflow"]["@id"]

    def get_configuration_id(self, emodel_resource):
        workflow_id = self.get_workflow_id(emodel_resource)
        workflow_resource = self.fetch_resource_by_id(workflow_id)

        configuration = None
        workflow_resource_list = ensure_list(workflow_resource["hasPart"])
        for part in workflow_resource_list:
            if part["@type"] == "EModelConfiguration":
                configuration = part
                break

        if configuration is None:
            raise Exception("No E-Model configuration found")

        return configuration["@id"]

    def get_emodel_configuration(self, emodel_resource):
        configuration_id = self.get_configuration_id(emodel_resource)
        return self.fetch_resource_by_id(configuration_id)

    def get_emodel_morph_format(self, emodel_configuration_resource):
        configuration_distribution = ensure_list(
            emodel_configuration_resource["distribution"]
        )
        configuration = self.fetch_file_by_url(
            configuration_distribution[0]["contentUrl"]
        ).json()
        emodel_morph_format = configuration.get("morphology", {}).get("format", None)

        return emodel_morph_format

    def find_distrbution_by_encoding_format(self, resource, encoding_format):
        distributions = ensure_list(resource["distribution"])
        for distribution in distributions:
            if distribution["encodingFormat"] == encoding_format:
                return distribution
        return None

    def get_morphology(self, morph_id, morph_format="asc"):
        morphology_resource = self.fetch_resource_by_id(morph_id)

        encoding_format = ENCODING_FORMAT_MAP.get(morph_format)
        assert encoding_format, f"Morphology format {morph_format} not supported"

        morph_distribution = self.find_distrbution_by_encoding_format(
            morphology_resource, encoding_format
        )

        if morph_distribution is None:
            secondary_morph_format = "swc" if morph_format == "asc" else "asc"
            morph_distribution = self.find_distrbution_by_encoding_format(
                morphology_resource, ENCODING_FORMAT_MAP.get(secondary_morph_format)
            )

        if morph_distribution is None:
            raise Exception(
                f"{morph_format.upper()} or {secondary_morph_format.upper()} format not found in NeuronMorphology distribution"
            )

        file = self.fetch_file_by_url(morph_distribution["contentUrl"])

        return {"name": morph_distribution["name"], "content": file.text}

    def get_emodel_morphology(self, configuration, morph_format):
        morphology = None
        for item in configuration["uses"]:
            if item["@type"] == "NeuronMorphology":
                morphology = item
                break
        if morphology is None:
            raise Exception("NeuronMorphology not found")

        return self.get_morphology(morphology["@id"], morph_format)

    def get_memodel_morphology(self, memodel_resource, morph_format):
        morphology_id = None
        for haspart in ensure_list(memodel_resource["hasPart"]):
            if haspart.get("@type") == "NeuronMorphology":
                morphology_id = haspart.get("@id")
        if morphology_id is None:
            raise Exception("No Morphology found in ME-Model")

        return self.get_morphology(morphology_id, morph_format)

    def get_mechanisms(self, configuration):
        # fetch only SubCellularModelScripts. Morphologies will be fetched later
        scripts = []
        for config in ensure_list(configuration["uses"]):
            if config.get("@type") != "NeuronMorphology":
                scripts.append(config)

        # model_resources = []
        # TODO: Add these configuration to the model
        extra_mechanisms = [
            f"{settings.NEXUS_ROOT_URI}/resources/bbp/mmb-point-neuron-framework-model/_/https:%2F%2Fbbp.epfl.ch%2Fneurosciencegraph%2Fdata%2Fsynapticphysiologymodels%2Fe3c32384-5cb1-4dd3-a8c9-f6c23bea6b27",
            f"{settings.NEXUS_ROOT_URI}/resources/bbp/mmb-point-neuron-framework-model/_/https:%2F%2Fbbp.epfl.ch%2Fneurosciencegraph%2Fdata%2Fsynapticphysiologymodels%2F3965bc40-ca30-475b-98be-cfa3e22057b5",
        ]

        def fetch_mechanism(model_resource):
            distributions = ensure_list(model_resource["distribution"])
            distribution = list(
                filter(
                    lambda x: x.get("encodingFormat") == "application/mod"
                    or x.get("encodingFormat") == "application/neuron-mod",
                    distributions,
                )
            )[0]

            file = self.fetch_file_by_url(distribution["contentUrl"])
            return {"name": distribution["name"], "content": file.text}

        def fetch_mechanism_from_script(script):
            script_resource = self.fetch_resource_by_id(script["@id"])
            return fetch_mechanism(script_resource)

        def fetch_extra_mechanism(extra_mech_self):
            mechanism_resource = self.fetch_resource_by_self(extra_mech_self)
            return fetch_mechanism(mechanism_resource)

        mechanisms = []

        with ThreadPoolExecutor() as executor:
            script_mech_futures = [
                executor.submit(fetch_mechanism_from_script, script)
                for script in scripts
            ]
            extra_mech_futures = [
                executor.submit(fetch_extra_mechanism, extra_mech)
                for extra_mech in extra_mechanisms
            ]
            for future in as_completed(script_mech_futures + extra_mech_futures):
                mechanisms.append(future.result())

        return mechanisms

    def get_script_resource(self, emodel_resource):
        workflow_id = self.get_workflow_id(emodel_resource)
        workflow_resource = self.fetch_resource_by_id(workflow_id)

        script = None
        for generated in ensure_list(workflow_resource["generates"]):
            if generated["@type"] == "EModelScript":
                script = generated
                break

        if script is None:
            raise Exception("No E-Model script found")

        return self.fetch_resource_by_id(script["@id"])

    def get_hoc_file(self, emodel_resource):
        emodel_script = self.get_script_resource(emodel_resource)

        distribution = None

        for dist in ensure_list(emodel_script["distribution"]):
            if dist["encodingFormat"] in HOC_FORMATS:
                distribution = dist
                break

        if distribution is None:
            raise Exception("No HOC file found")

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
        resource = self.fetch_resource_by_id(self.model_id)
        # could be E-Model or ME-Model

        emodel_resource = self.get_emodel_resource(resource)
        logger.debug("E-Model resource fetched")

        configuration_resource = self.get_emodel_configuration(emodel_resource)
        logger.debug("E-Model configuration fetched")

        emodel_morph_format = self.get_emodel_morph_format(configuration_resource)
        logger.debug(f"E-Model morph format fetched: {emodel_morph_format}")

        with ThreadPoolExecutor() as executor:
            futures = [
                # HOC file
                executor.submit(self.get_hoc_file, emodel_resource),
                # Morphology
                executor.submit(
                    self.get_memodel_morphology, resource, emodel_morph_format
                )
                if "MEModel" in resource["@type"]
                else executor.submit(
                    self.get_emodel_morphology,
                    configuration_resource,
                    emodel_morph_format,
                ),
                # Mechanisms
                executor.submit(self.get_mechanisms, configuration_resource),
            ]

            hoc_file, morphology_obj, mechanisms = [f.result() for f in futures]

        self.create_model_folder(hoc_file, morphology_obj, mechanisms)
        logger.debug("E-Model folder created")

    def get_currents(self) -> list[float]:
        resource = self.fetch_resource_by_id(self.model_id)
        # TODO: this should be the right way to do it when analysis is ready
        # With the changes to ME-model shape
        # if (
        #     "MEModel" in resource["@type"]
        #     and resource["validated"] is True
        #     and "parameter" in resource
        # ):
        #     logger.debug("Getting currents from ME-Model")
        #     param_dict = {
        #         param["name"]: param["value"] for param in resource["parameter"]
        #     }
        #     holding_current = param_dict.get("holding_current")
        #     threshold_current = param_dict.get("threshold_current")
        #     logger.debug(
        #         f"currents are: holding: {holding_current}, threshold: {threshold_current}"
        #     )
        #     return [holding_current, threshold_current]

        if "MEModel" in resource["@type"] and resource["validated"]:
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

    def create_simulation_resource(
        self,
        simulation_config: SingleNeuronSimulationConfig,
        stimulus_plot_data: list[StimulationItemResponse],
        status: SimulationStatus,
        org_id: str,
        project_id: str,
    ) -> dict:
        # Step 1: Get me_model
        try:
            model = self.fetch_resource_by_id(self.model_id)
        except Exception:
            raise SimulationError(f"No me_model with self {self.model_id} found")

        # Step 2: Create distribution resource
        distribution = self.create_simulation_distribution(
            model_self=self.model_id,
            config=simulation_config,
            stimulus_plot_data=stimulus_plot_data,
            org_id=org_id,
            project_id=project_id,
            results=None,
        )
        # Step 3: Create simulation resource with status = "PENDING"
        try:
            sim_name = (
                "single-neuron-simulation-{}".format(generate_id(10))
                if simulation_config.type == "single-neuron-simulation"
                else "synaptome-simulation-{}".format(generate_id(10))
            )
            description = "background simulation created by bluenaas api"
            simulation_resource = self.prepare_nexus_simulation(
                sim_name=sim_name,
                description=description,
                config=simulation_config,
                model=model,
                status=status,
                distribution=distribution,
            )
            simulation_resource_url = f"{settings.NEXUS_ROOT_URI}/resources/{org_id}/{project_id}?indexing=sync"
            simulation_response = requests.post(
                url=simulation_resource_url,
                headers=self.content_modification_headers(),
                data=simulation_resource.model_dump_json(by_alias=True),
                timeout=HTTP_TIMEOUT,
            )
            simulation_response.raise_for_status()
            return simulation_response.json()
        except Exception as error:
            raise SimulationError(
                f"Failed to create simulation resource {error} {simulation_response.json()}"
            )

    def update_simulation_status(
        self,
        org_id: str,
        project_id: str,
        resource_self: str,
        status: SimulationStatus,
        is_draft: bool,
        err: Optional[str] = None,
    ):
        try:
            simulation_resource = self.fetch_resource_by_self(resource_self)

            updated_resource = simulation_resource | {
                "status": status,
                "isDraft": is_draft,
                **({"error": err} if err is not None else {}),
            }

            return self.update_resource_by_id(
                org_label=org_id,
                project_label=project_id,
                resource_id=simulation_resource["@id"],
                previous_rev=simulation_resource["_rev"],
                payload=updated_resource,
            )
        except Exception as e:
            logger.exception(
                f"Could not update simulation resource {resource_self} with status {status}. Exception {e}"
            )
            raise SimulationError(
                f"Could not update simulation resource {resource_self} with status {status}"
            )

    def create_simulation_distribution(
        self,
        model_self: str,
        config: SingleNeuronSimulationConfig,
        stimulus_plot_data: list[StimulationItemResponse],
        org_id: str,
        project_id: str,
        results: Optional[dict],
    ) -> dict[str, Any]:
        # Step 1: Create a distribution file to save results.
        try:
            simulation_config = SingleNeuronSimulationConfig.model_validate(config)
            distribution_payload = NexusSimulationPayload(
                config=simulation_config,
                simulation=results,
                stimulus=stimulus_plot_data,
            )
            distribution_name = (
                "simulation-config-single-neuron.json"
                if simulation_config.type == "single-neuron-simulation"
                else "simulation-config-synaptome.json"
            )
            distribution_resource = self.create_nexus_distribution(
                payload=distribution_payload.model_dump(by_alias=True),
                filename=distribution_name,
                org_id=org_id,
                project_id=project_id,
            )
            return distribution_resource
        except Exception as e:
            dist_id = f"ORG {org_id} PROJECT {project_id} MODEL {model_self}"
            logger.exception(
                f"Could not create distribution with simulation results for resource {dist_id}. Exception {e}"
            )
            raise SimulationError(
                f"Could not create distribution with simulation results for resource {dist_id}"
            )

    def prepare_nexus_simulation(
        self,
        sim_name: str,
        description: str,
        config: SingleNeuronSimulationConfig,
        model: dict,
        status: str,
        distribution: dict[str, Any],
    ):
        record_locations = [
            f"{r.section}_{r.offset}" for r in ensure_list(config.record_from)
        ]

        return BaseNexusSimulationResource(
            type=["Entity", "SingleNeuronSimulation"]
            if config.type == "single-neuron-simulation"
            else ["Entity", "SynaptomeSimulation"],
            name=sim_name,
            description=description,
            context="https://bbp.neuroshapes.org",
            distribution=distribution,
            injectionLocation=config.current_injection.inject_to,
            recordingLocation=ensure_list(record_locations),
            brainLocation=model["brainLocation"],
            # Model can be MEModel or SingleNeuronSynaptome
            used={"@type": model["@type"], "@id": model["@id"]},
            isDraft=True,
            status=status,
        )

    def update_simulation_with_final_results(
        self,
        simulation_resource_self: str,
        org_id: str,
        project_id: str,
        status: SimulationStatus,
        results: dict,
    ):
        """
        Called when simulation finished successfully.
        This function updates simulation status to success and adds the final simulation result to the distribution.
        """
        # Step 1: Update the distribution file with results
        try:
            simulation_resource = self.fetch_resource_by_self(
                resource_self=simulation_resource_self
            )

            distribution = ensure_list(simulation_resource["distribution"])[0]
            distribution_url = distribution["contentUrl"]

            self.update_json_nexus_distribution(
                file_url=distribution_url,
                filename=distribution["name"],
                data_to_add={"simulation": results},
            )
        except Exception as e:
            logger.exception(
                f"Could not update distribution with simulation results for resource {simulation_resource['_self']}. Exception {e}"
            )
            raise SimulationError(
                f"Could not update distribution with simulation results for resource {simulation_resource['_self']}"
            )

        # Step 2: Update status of simulation resource to success
        try:
            return self.update_simulation_status(
                org_id=org_id,
                project_id=project_id,
                resource_self=simulation_resource["_self"],
                status=status,
                is_draft=True,
            )
        except Exception as e:
            logger.exception(
                f"Could not update simulation resource {simulation_resource['_self']} with status {status}. Exception {e}"
            )
            raise SimulationError(
                f"Could not update simulation resource {simulation_resource['_self']} with status {status}"
            )
