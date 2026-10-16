import asyncio
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from entitysdk.models import TaskActivity, TaskConfig
from entitysdk.types import ActivityStatus, TaskActivityType, TaskConfigType
from obp_accounting_sdk.constants import ServiceSubtype

from app.core.exceptions import AppError, JobFailedError
from app.job import JobFn
from app.services.api.task_config import ION_CHANNEL_BUILD, MEMODEL_BUILD, run_task_config

CONFIG_ID = UUID("11111111-1111-1111-1111-111111111111")
EXECUTION_ID = UUID("22222222-2222-2222-2222-222222222222")
JOB_ID = UUID("33333333-3333-3333-3333-333333333333")

MODULE = "app.services.api.task_config"


class TestRunTaskConfig(unittest.TestCase):
    run_spec = ION_CHANNEL_BUILD

    def setUp(self):
        self.client = Mock()
        self.client.get_entity.return_value = TaskConfig(
            id=CONFIG_ID,
            name="Config 0",
            description="Config 0",
            task_config_type=self.run_spec.config_type,
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
        self.oneshot_session = mocks["session"]

    def _run(self):
        return asyncio.run(
            run_task_config(
                CONFIG_ID,
                self.run_spec,
                auth=Mock(access_token="token"),
                project_context=Mock(project_id="project"),
                job_queue=Mock(),
            )
        )

    def test_registers_a_pending_execution_that_used_the_config(self):
        launch = self._run()

        (execution,), _ = self.client.register_entity.call_args
        self.assertIsInstance(execution, TaskActivity)
        self.assertEqual(execution.task_activity_type, self.run_spec.activity_type)
        self.assertEqual(execution.status, ActivityStatus.pending)
        self.assertEqual(execution.used, [self.client.get_entity.return_value])
        self.assertEqual(launch.job_id, JOB_ID)
        self.assertEqual(launch.execution_id, EXECUTION_ID)

    def test_charges_the_task_service(self):
        self._run()

        kwargs = self.oneshot_session.call_args.kwargs
        self.assertEqual(kwargs["subtype"], self.run_spec.service_subtype)
        self.assertEqual(kwargs["count"], 1)

    def test_hands_the_worker_the_config_and_its_execution(self):
        self._run()

        (_, job_fn), kwargs = self.dispatch.call_args
        self.assertEqual(job_fn, self.run_spec.job_fn)
        self.assertEqual(kwargs["timeout"], self.run_spec.timeout)
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


class TestRunMEModelBuild(TestRunTaskConfig):
    run_spec = MEMODEL_BUILD


class TestRunSpecs(unittest.TestCase):
    def test_ion_channel_build(self):
        self.assertEqual(ION_CHANNEL_BUILD.config_type, TaskConfigType.ion_channel_modeling__config)
        self.assertEqual(
            ION_CHANNEL_BUILD.activity_type, TaskActivityType.ion_channel_modeling__execution
        )
        self.assertEqual(ION_CHANNEL_BUILD.service_subtype, ServiceSubtype.ION_CHANNEL_BUILD)
        self.assertEqual(ION_CHANNEL_BUILD.job_fn, JobFn.RUN_ION_CHANNEL_BUILD)

    def test_memodel_build(self):
        self.assertEqual(MEMODEL_BUILD.config_type, TaskConfigType.memodel_build__config)
        self.assertEqual(MEMODEL_BUILD.activity_type, TaskActivityType.memodel_build__execution)
        self.assertEqual(MEMODEL_BUILD.service_subtype, ServiceSubtype.SINGLE_CELL_BUILD)
        self.assertEqual(MEMODEL_BUILD.job_fn, JobFn.RUN_MEMODEL_BUILD)


if __name__ == "__main__":
    unittest.main()
