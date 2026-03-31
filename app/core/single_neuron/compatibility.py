import json
from uuid import UUID

from entitysdk import Client
from filelock import FileLock
from loguru import logger

from app.constants import DIR_LOCK_FILE_NAME
from app.core.single_neuron.single_neuron import SingleNeuronCandidate
from app.domains.neuron_model import CompatibilityCheckResponse
from app.infrastructure.storage import get_compatibility_result_location


RESULT_FILE_NAME = "result.json"


class CompatibilityChecker:
    """Orchestrates a morphology + emodel compatibility check with result caching."""

    def __init__(self, morphology_id: UUID, emodel_id: UUID, client: Client):
        self.morphology_id = morphology_id
        self.emodel_id = emodel_id
        self.candidate = SingleNeuronCandidate(morphology_id, emodel_id, client)
        self.result_path = get_compatibility_result_location(morphology_id, emodel_id)

    def get_cached_result(self) -> CompatibilityCheckResponse | None:
        result_file = self.result_path / RESULT_FILE_NAME
        if result_file.exists():
            logger.debug("Found cached compatibility result")
            return CompatibilityCheckResponse(**json.loads(result_file.read_text()))
        return None

    def run(self) -> CompatibilityCheckResponse:
        cached = self.get_cached_result()
        if cached is not None:
            return cached

        compatible = True
        error = None

        try:
            self.candidate.init()
        except Exception as ex:
            logger.warning(f"Compatibility check failed: {ex}")
            compatible = False
            error = str(ex)
        finally:
            self.candidate.cleanup()

        result = CompatibilityCheckResponse(
            compatible=compatible,
            morphology_id=self.morphology_id,
            emodel_id=self.emodel_id,
            error=error,
        )

        lock = FileLock(self.result_path / DIR_LOCK_FILE_NAME)
        with lock.acquire(timeout=2 * 60):
            result_file = self.result_path / RESULT_FILE_NAME
            result_file.write_text(result.model_dump_json())

        return result
