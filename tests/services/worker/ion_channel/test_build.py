import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from entitysdk.models import TaskConfig
from entitysdk.types import ActivityStatus
from obi_one.types import TaskType

from app.services.worker.ion_channel.build import run_ion_channel_build

CONFIG_ID = UUID("11111111-1111-1111-1111-111111111111")
EXECUTION_ID = UUID("22222222-2222-2222-2222-222222222222")

MODULE = "app.services.worker.ion_channel.build"


class TestRunIonChannelBuildWorker(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.output_root = Path("/storage/ion-channel/build/22")
        patches = {
            "client": patch(f"{MODULE}.Client", return_value=self.client),
            "location": patch(
                f"{MODULE}.get_ion_channel_build_location", return_value=self.output_root
            ),
            "rm_dir": patch(f"{MODULE}.rm_dir"),
            "run_task_type": patch(f"{MODULE}.run_task_type"),
        }
        self.mocks = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    def _run(self):
        run_ion_channel_build(
            CONFIG_ID,
            execution_id=EXECUTION_ID,
            access_token="token",
            project_context=Mock(),
        )

    def _statuses(self):
        return [
            c.kwargs["attrs_or_entity"]["status"] for c in self.client.update_entity.call_args_list
        ]

    def test_runs_the_obi_one_fitting_task_for_the_config(self):
        self._run()

        self.mocks["run_task_type"].assert_called_once_with(
            task_type=TaskType.ion_channel_fitting,
            entity_type=TaskConfig,
            entity_id=str(CONFIG_ID),
            scan_output_root=str(self.output_root),
            db_client=self.client,
            execution_activity_id=str(EXECUTION_ID),
        )
        self.assertEqual(self._statuses(), [ActivityStatus.running, ActivityStatus.done])
        self.mocks["rm_dir"].assert_called_once_with(self.output_root)

    def test_a_failed_fit_marks_the_execution_as_error_and_reraises(self):
        self.mocks["run_task_type"].side_effect = RuntimeError("fit failed")

        with self.assertRaises(RuntimeError):
            self._run()

        self.assertEqual(self._statuses(), [ActivityStatus.running, ActivityStatus.error])
        self.mocks["rm_dir"].assert_called_once_with(self.output_root)


if __name__ == "__main__":
    unittest.main()
