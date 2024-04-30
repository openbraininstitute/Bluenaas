'''Nexus module.'''

import urllib.parse
import zipfile
from pathlib import Path

import requests

from .settings import L

# TODO: this will change when AWS models are ready
NEXUS_BASE = 'https://bbp.epfl.ch/nexus/v1/resources/bbp/mmb-point-neuron-framework-model/_/'
NEXUS_ID_BASE = 'https://bbp.epfl.ch/data/bbp/mmb-point-neuron-framework-model/'
QUERY_ENDPOINT = 'https://bbp.epfl.ch/nexus/v1/views/bbp/mmb-point-neuron-framework-model/https%3A%2F%2Fbbp.epfl.ch%2Fneurosciencegraph%2Fdata%2Fviews%2Fes%2Fdataset/_search'  # noqa: E501 # pylint: disable=line-too-long
HTTP_TIMEOUT = 10  # seconds

model_dir = Path('/opt/blue-naas/') / 'models'


class Nexus:
    '''Nexus class to help downloading the emodel files needed for simulation.'''

    # pylint: disable=missing-function-docstring
    def __init__(self, params):
        self.headers = {}
        self.emodel_uuid = params['emodel_id']
        self.emodel_id = NEXUS_ID_BASE + self.emodel_uuid
        self.headers.update({'Authorization': params['token']})

    def fetch_resource_by_id(self, resource_id):
        endpoint = self.compose_url(resource_id)
        r = requests.get(endpoint, headers=self.headers, timeout=HTTP_TIMEOUT)
        if not r.ok:
            raise Exception('Error fetching resource', r.status_code)
        return r.json()

    def fetch_file_by_url(self, file_url):
        r = requests.get(file_url, headers=self.headers, timeout=HTTP_TIMEOUT)
        if not r.ok:
            raise Exception('Error fetching file', r.status_code)
        return r

    def compose_url(self, url):
        return NEXUS_BASE + urllib.parse.quote_plus(url)

    def get_workflow_id(self, emodel_resource):
        return emodel_resource['generation']['activity']['followedWorkflow']['@id']

    def get_configuration_id(self, emodel_resource):
        workflow_id = self.get_workflow_id(emodel_resource)
        workflow_resource = self.fetch_resource_by_id(workflow_id)

        configuration = None
        for part in workflow_resource['hasPart']:
            if part['@type'] == 'EModelConfiguration':
                configuration = part
                break

        if configuration is None:
            raise Exception('No E-Model configuration found')

        return configuration['@id']

    def get_emodel_configuration(self, emodel_resource):
        configuration_id = self.get_configuration_id(emodel_resource)
        return self.fetch_resource_by_id(configuration_id)

    def get_morphology(self, configuration):
        morphology = None
        for item in configuration['uses']:
            if item['@type'] == 'NeuronMorphology':
                morphology = item
                break

        if morphology is None:
            raise Exception('NeuronMorphology not found')

        morphology_resource = self.fetch_resource_by_id(morphology['@id'])

        distributions = morphology_resource['distribution']
        if not isinstance(distributions, list):
            raise Exception('NeuronMorphology distribution is not an array')

        swc = None
        for distribution in distributions:
            if distribution['encodingFormat'] == 'application/swc':
                swc = distribution
                break

        if swc is None:
            raise Exception('SWC format not found in NeuronMorphology distribution')

        file = self.fetch_file_by_url(swc['contentUrl'])

        return {'name': swc['name'], 'content': file.text}

    def get_mechanisms(self, configuration):
        # fetch only SubCellularModelScripts. Morphologies will be fetched later
        scripts = []
        for config in configuration['uses']:
            if config['@type'] != 'NeuronMorphology':
                scripts.append(config)

        model_resources = []
        for script in scripts:
            script_resource = self.fetch_resource_by_id(script['@id'])
            model_resources.append(script_resource)

        mechanisms = []
        for model_resource in model_resources:
            distribution = model_resource['distribution']
            file = self.fetch_file_by_url(distribution['contentUrl'])
            mechanisms.append({'name': distribution['name'], 'content': file.text})

        return mechanisms

    def query_es(self, query):
        r = requests.post(
            QUERY_ENDPOINT,
            json=query,
            headers=self.headers,
            timeout=HTTP_TIMEOUT
        )
        if not r.ok:
            raise Exception('Error executing query', r.status_code)

        results = []
        j = r.json()
        for hint in j['hits']['hits']:
            results.append(hint['_source'])

        return results

    def get_script_resource(self, emodel_resource):
        workflow_id = self.get_workflow_id(emodel_resource)
        workflow_resource = self.fetch_resource_by_id(workflow_id)

        script = None
        for generated in workflow_resource['generates']:
            if generated['@type'] == 'EModelScript':
                script = generated
                break

        if script is None:
            raise Exception('No E-Model script found')

        return self.fetch_resource_by_id(script['@id'])

    def get_hoc_file(self, emodel_resource):
        emodel_script = self.get_script_resource(emodel_resource)
        distribution = emodel_script['distribution']

        if isinstance(distribution, list):
            for dist in distribution:
                if dist['encodingFormat'] == 'application/hoc':
                    distribution = dist
                    break

        emodel_script_url = distribution['contentUrl']

        r = self.fetch_file_by_url(emodel_script_url)
        return r.text

    def create_compressed_file(self, hoc_file, morphology_obj, mechanisms):
        final_compressed_file = model_dir / f'{self.emodel_uuid}.tar'

        with zipfile.ZipFile(final_compressed_file, mode='w') as archive:
            archive.writestr('cell.hoc', hoc_file)

            morph_name = morphology_obj['name']
            archive.writestr(
                f'morphology/{morph_name}',
                morphology_obj['content'],
            )

            for mechanism in mechanisms:
                mech_name = mechanism['name']
                archive.writestr(
                    f'mechanisms/{mech_name}',
                    mechanism['content'],
                )

    def create_file(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

    def create_model_folder(self, hoc_file, morphology_obj, mechanisms):
        output_dir = model_dir / self.emodel_uuid
        self.create_file(output_dir / 'cell.hoc', hoc_file)

        morph_name = morphology_obj['name']
        self.create_file(output_dir / 'morphology' / morph_name, morphology_obj['content'])

        for mechanism in mechanisms:
            mech_name = mechanism['name']
            self.create_file(output_dir / 'mechanisms' / mech_name, mechanism['content'])

    def download_model(self):
        L.debug('Creating zip model...')
        emodel_resource = self.fetch_resource_by_id(self.emodel_id)
        L.debug('E-Model resource fetched')
        configuration = self.get_emodel_configuration(emodel_resource)
        L.debug('E-Model configuration fetched')
        mechanisms = self.get_mechanisms(configuration)
        L.debug('E-Model mechanisms fetched')
        hoc_file = self.get_hoc_file(emodel_resource)
        L.debug('E-Model hoc file fetched')
        morphology_obj = self.get_morphology(configuration)
        L.debug('E-Model morphology fetched')
        self.create_model_folder(hoc_file, morphology_obj, mechanisms)
        L.debug('E-Model folder created')
