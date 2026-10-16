import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from entitysdk.models import TaskConfig
from entitysdk.types import ActivityStatus
from obi_one.types import TaskType

from app.job.handlers.ion_channel import build as ion_channel_build
from app.job.handlers.single_neuron import build as memodel_build
from app.services.worker.task_config import run_task_config

CONFIG_ID = UUID("11111111-1111-1111-1111-111111111111")
EXECUTION_ID = UUID("22222222-2222-2222-2222-222222222222")
OUTPUT_ROOT = Path("/storage/single-neuron/build/22")

MODULE = "app.services.worker.task_config"


class TestRunTaskConfigWorker(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        patches = {
            "client": patch(f"{MODULE}.Client", return_value=self.client),
            "rm_dir": patch(f"{MODULE}.rm_dir"),
            "run_task_type": patch(f"{MODULE}.run_task_type"),
        }
        self.mocks = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    def _run(self):
        run_task_config(
            TaskType.memodel_build,
            CONFIG_ID,
            output_root=OUTPUT_ROOT,
            execution_id=EXECUTION_ID,
            access_token="token",
            project_context=Mock(),
        )

    def _statuses(self):
        return [
            c.kwargs["attrs_or_entity"]["status"] for c in self.client.update_entity.call_args_list
        ]

    def test_runs_the_obi_one_task_for_the_config(self):
        self._run()

        self.mocks["run_task_type"].assert_called_once_with(
            task_type=TaskType.memodel_build,
            entity_type=TaskConfig,
            entity_id=str(CONFIG_ID),
            scan_output_root=str(OUTPUT_ROOT),
            db_client=self.client,
            execution_activity_id=str(EXECUTION_ID),
        )
        self.assertEqual(self._statuses(), [ActivityStatus.running, ActivityStatus.done])
        self.mocks["rm_dir"].assert_called_once_with(OUTPUT_ROOT)

    def test_a_failed_task_marks_the_execution_as_error_and_reraises(self):
        self.mocks["run_task_type"].side_effect = RuntimeError("task failed")

        with self.assertRaises(RuntimeError):
            self._run()

        self.assertEqual(self._statuses(), [ActivityStatus.running, ActivityStatus.error])
        self.mocks["rm_dir"].assert_called_once_with(OUTPUT_ROOT)


class TestHandlers(unittest.TestCase):
    def _run_handler(self, handler, location_fn_name):
        with (
            patch.object(handler, location_fn_name, return_value=OUTPUT_ROOT) as location,
            patch.object(handler, "run_task_config") as run,
        ):
            handler.run(
                CONFIG_ID,
                execution_id=EXECUTION_ID,
                access_token="token",
                project_context="context",
            )
        location.assert_called_once_with(EXECUTION_ID)
        return run.call_args

    def test_ion_channel_build_runs_the_fitting_task(self):
        call = self._run_handler(ion_channel_build, "get_ion_channel_build_location")

        self.assertEqual(call.args, (TaskType.ion_channel_fitting, CONFIG_ID))
        self.assertEqual(call.kwargs["output_root"], OUTPUT_ROOT)
        self.assertEqual(call.kwargs["execution_id"], EXECUTION_ID)

    def test_memodel_build_runs_the_memodel_build_task(self):
        call = self._run_handler(memodel_build, "get_single_neuron_build_location")

        self.assertEqual(call.args, (TaskType.memodel_build, CONFIG_ID))
        self.assertEqual(call.kwargs["output_root"], OUTPUT_ROOT)
        self.assertEqual(call.kwargs["execution_id"], EXECUTION_ID)


if __name__ == "__main__":
    unittest.main()
