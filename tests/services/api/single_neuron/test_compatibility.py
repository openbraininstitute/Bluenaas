import asyncio
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.core.api import ApiResponse
from app.services.api.single_neuron.compatibility import check_compatibility_service


MORPH_ID = UUID("11111111-1111-1111-1111-111111111111")
EMODEL_ID = UUID("22222222-2222-2222-2222-222222222222")


class TestCheckCompatibilityService(unittest.TestCase):
    @patch("app.services.api.single_neuron.compatibility.get_job_data")
    @patch("app.services.api.single_neuron.compatibility.dispatch")
    def test_returns_api_response_with_compatible_result(self, mock_dispatch, mock_get_job_data):
        mock_job = Mock()
        mock_job.id = "job-1"
        mock_stream = AsyncMock()

        async def fake_dispatch(*args, **kwargs):
            return mock_job, mock_stream

        mock_dispatch.side_effect = fake_dispatch

        async def fake_get_job_data(stream):
            return {
                "compatible": True,
                "morphology_id": str(MORPH_ID),
                "emodel_id": str(EMODEL_ID),
                "error": None,
            }

        mock_get_job_data.side_effect = fake_get_job_data

        async def test():
            result = await check_compatibility_service(
                MORPH_ID,
                EMODEL_ID,
                job_queue=Mock(),
                access_token="token",
                project_context=Mock(),
            )
            return result

        result = asyncio.run(test())

        self.assertIsInstance(result, ApiResponse)
        self.assertEqual(result.message, "Compatibility check completed")
        self.assertIsNotNone(result.data)
        self.assertTrue(result.data.compatible)
        self.assertEqual(result.data.morphology_id, MORPH_ID)

    @patch("app.services.api.single_neuron.compatibility.get_job_data")
    @patch("app.services.api.single_neuron.compatibility.dispatch")
    def test_returns_api_response_with_incompatible_result(self, mock_dispatch, mock_get_job_data):
        mock_job = Mock()
        mock_job.id = "job-2"
        mock_stream = AsyncMock()

        async def fake_dispatch(*args, **kwargs):
            return mock_job, mock_stream

        mock_dispatch.side_effect = fake_dispatch

        async def fake_get_job_data(stream):
            return {
                "compatible": False,
                "morphology_id": str(MORPH_ID),
                "emodel_id": str(EMODEL_ID),
                "error": "Single neuron model instantiation failed",
            }

        mock_get_job_data.side_effect = fake_get_job_data

        async def test():
            result = await check_compatibility_service(
                MORPH_ID,
                EMODEL_ID,
                job_queue=Mock(),
                access_token="token",
                project_context=Mock(),
            )
            return result

        result = asyncio.run(test())

        self.assertFalse(result.data.compatible)
        self.assertIsNotNone(result.data.error)

    @patch("app.services.api.single_neuron.compatibility.get_job_data")
    @patch("app.services.api.single_neuron.compatibility.dispatch")
    def test_dispatches_with_correct_job_fn(self, mock_dispatch, mock_get_job_data):
        from app.job import JobFn

        mock_job = Mock()
        mock_job.id = "job-3"
        mock_stream = AsyncMock()

        async def fake_dispatch(*args, **kwargs):
            return mock_job, mock_stream

        mock_dispatch.side_effect = fake_dispatch

        async def fake_get_job_data(stream):
            return {
                "compatible": True,
                "morphology_id": str(MORPH_ID),
                "emodel_id": str(EMODEL_ID),
                "error": None,
            }

        mock_get_job_data.side_effect = fake_get_job_data

        mock_queue = Mock()
        mock_project_context = Mock()

        async def test():
            await check_compatibility_service(
                MORPH_ID,
                EMODEL_ID,
                job_queue=mock_queue,
                access_token="my-token",
                project_context=mock_project_context,
            )

        asyncio.run(test())

        mock_dispatch.assert_called_once_with(
            mock_queue,
            JobFn.CHECK_COMPATIBILITY,
            job_args=(MORPH_ID, EMODEL_ID),
            job_kwargs={
                "access_token": "my-token",
                "project_context": mock_project_context,
            },
        )


if __name__ == "__main__":
    unittest.main()
