import asyncio
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from entitysdk.models import TaskActivity, TaskConfig
from entitysdk.types import ActivityStatus, TaskActivityType, TaskConfigType

from app.core.exceptions import AppError, JobFailedError
from app.services.api.ion_channel.build import run_ion_channel_build

CONFIG_ID = UUID("11111111-1111-1111-1111-111111111111")
EXECUTION_ID = UUID("22222222-2222-2222-2222-222222222222")
JOB_ID = UUID("33333333-3333-3333-3333-333333333333")

MODULE = "app.services.api.ion_channel.build"


class TestRunIonChannelBuild(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.get_entity.return_value = TaskConfig(
            id=CONFIG_ID,
            name="Ion channel modeling 0",
            description="Ion channel modeling 0",
            task_config_type=TaskConfigType.ion_channel_modeling__config,
            meta={},
        )
        self.client.register_entity.return_value = Mock(id=EXECUTION_ID)
        self.accounting_session = Mock(start=AsyncMock(), finish=AsyncMock())

        patches = {
            "client": patch(f"{MODULE}.Client", return_value=self.client),
            "reservation": patch(f"{MODULE}.make_accounting_reservation_async", AsyncMock()),
            "session": patch(
                f"{MODULE}.async_accounting_session_factory.oneshot_session",
                return_value=self.accounting_session,
            ),
            "dispatch": patch(
                f"{MODULE}.dispatch", AsyncMock(return_value=(Mock(id=str(JOB_ID)), None))
            ),
        }
        mocks = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)
        self.dispatch = mocks["dispatch"]

    def _run(self):
        return asyncio.run(
            run_ion_channel_build(
                CONFIG_ID,
                auth=Mock(access_token="token"),
                project_context=Mock(project_id="project"),
                job_queue=Mock(),
            )
        )

    def test_registers_a_pending_execution_that_used_the_config(self):
        launch = self._run()

        (execution,), _ = self.client.register_entity.call_args
        self.assertIsInstance(execution, TaskActivity)
        self.assertEqual(
            execution.task_activity_type, TaskActivityType.ion_channel_modeling__execution
        )
        self.assertEqual(execution.status, ActivityStatus.pending)
        self.assertEqual(execution.used, [self.client.get_entity.return_value])
        self.assertEqual(launch.job_id, JOB_ID)
        self.assertEqual(launch.execution_id, EXECUTION_ID)

    def test_hands_the_worker_the_config_and_its_execution(self):
        self._run()

        kwargs = self.dispatch.call_args.kwargs
        self.assertEqual(kwargs["job_args"], (CONFIG_ID,))
        self.assertEqual(kwargs["job_kwargs"]["execution_id"], EXECUTION_ID)

    def test_a_failed_job_fails_the_execution_and_releases_the_credits(self):
        self._run()

        on_failure = self.dispatch.call_args.kwargs["on_failure"]
        asyncio.run(on_failure(JobFailedError))

        update = self.client.update_entity.call_args.kwargs
        self.assertEqual(update["entity_id"], EXECUTION_ID)
        self.assertEqual(update["attrs_or_entity"]["status"], ActivityStatus.error)
        self.accounting_session.finish.assert_awaited_once_with(exc_type=JobFailedError)

    def test_releases_the_credits_when_the_execution_cannot_be_registered(self):
        self.client.register_entity.side_effect = RuntimeError("entitycore down")

        with self.assertRaises(RuntimeError):
            self._run()

        self.accounting_session.finish.assert_awaited_once_with(exc_type=RuntimeError)
        self.dispatch.assert_not_called()

    def test_a_failed_dispatch_fails_the_execution_and_releases_the_credits(self):
        self.dispatch.side_effect = ConnectionError("redis down")

        with self.assertRaises(ConnectionError):
            self._run()

        self.accounting_session.finish.assert_awaited_once_with(exc_type=ConnectionError)
        update = self.client.update_entity.call_args.kwargs
        self.assertEqual(update["attrs_or_entity"]["status"], ActivityStatus.error)

    def test_rejects_a_config_of_another_task_before_charging(self):
        self.client.get_entity.return_value = self.client.get_entity.return_value.model_copy(
            update={"task_config_type": TaskConfigType.circuit_extraction__config}
        )

        with self.assertRaises(AppError):
            self._run()

        self.client.register_entity.assert_not_called()
        self.dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
