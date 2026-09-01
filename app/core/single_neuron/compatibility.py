import json
from uuid import UUID

from entitysdk import Client
from filelock import FileLock
from loguru import logger
from pydantic import ValidationError

from app.constants import DIR_LOCK_FILE_NAME
from app.core.exceptions import SingleNeuronInitError
from app.core.single_neuron.single_neuron import SingleNeuronCandidate
from app.domains.neuron_model import CompatibilityCheckResponse, CompatibilityStatus
from app.infrastructure.storage import get_compatibility_result_location
from app.utils.neuron_output import scrub_neuron_output


# Bumped from "result.json": earlier results only ever recorded the constant string
# "Single neuron model instantiation failed", and failures were cached unconditionally.
# Renaming the file retires them without an ops step.
RESULT_FILE_NAME = "result-v2.json"


class CompatibilityChecker:
    """Orchestrates a morphology + emodel compatibility check with result caching."""

    def __init__(self, morphology_id: UUID, emodel_id: UUID, client: Client):
        self.morphology_id = morphology_id
        self.emodel_id = emodel_id
        self.candidate = SingleNeuronCandidate(morphology_id, emodel_id, client)
        self.result_path = get_compatibility_result_location(morphology_id, emodel_id)

    def get_cached_result(self) -> CompatibilityCheckResponse | None:
        result_file = self.result_path / RESULT_FILE_NAME

        if not result_file.exists():
            return None

        try:
            result = CompatibilityCheckResponse(**json.loads(result_file.read_text()))
        except (OSError, ValueError, ValidationError) as ex:
            logger.warning(f"Ignoring unreadable compatibility cache {result_file}: {ex}")
            return None

        logger.debug("Found cached compatibility result")
        return result

    def run(self) -> CompatibilityCheckResponse:
        cached = self.get_cached_result()
        if cached is not None:
            return cached

        result = self._check()

        # A check that could not run tells us nothing about the models, so caching it
        # would make a transient failure permanent for that pair.
        if result.status is not CompatibilityStatus.check_failed:
            self._cache(result)

        return result

    def _check(self) -> CompatibilityCheckResponse:
        try:
            self.candidate.init()

        except SingleNeuronInitError as ex:
            logger.warning(
                f"Models are incompatible (morphology={self.morphology_id}, "
                f"emodel={self.emodel_id}): {ex.message}\n{ex.details or ''}"
            )
            return self._result(CompatibilityStatus.incompatible, ex.message, ex.details)

        except Exception as ex:
            details = getattr(ex, "details", None)
            logger.opt(exception=True).error(
                f"Compatibility check could not run (morphology={self.morphology_id}, "
                f"emodel={self.emodel_id}): {type(ex).__name__}: {ex}\n{details or ''}"
            )
            return self._result(CompatibilityStatus.check_failed, str(ex), details)

        else:
            return self._result(CompatibilityStatus.compatible)

        finally:
            self.candidate.cleanup()

    def _result(
        self,
        status: CompatibilityStatus,
        error: str | None = None,
        details: str | None = None,
    ) -> CompatibilityCheckResponse:
        """Build the response, scrubbing whatever reaches the user.

        The unscrubbed text has already gone to the log, so the server-side record
        stays strictly more informative than what the UI shows.
        """
        return CompatibilityCheckResponse(
            status=status,
            morphology_id=self.morphology_id,
            emodel_id=self.emodel_id,
            error=scrub_neuron_output(error) or None if error else None,
            details=scrub_neuron_output(details) or None if details else None,
        )

    def _cache(self, result: CompatibilityCheckResponse) -> None:
        lock = FileLock(self.result_path / DIR_LOCK_FILE_NAME)

        with lock.acquire(timeout=2 * 60):
            result_file = self.result_path / RESULT_FILE_NAME
            result_file.write_text(result.model_dump_json())
