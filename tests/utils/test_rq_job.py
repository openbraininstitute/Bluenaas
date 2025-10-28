import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from rq.job import JobStatus as RQJobStatus

from app.utils.rq_job import _job_status_monitor


class TestJobStatusMonitor(unittest.TestCase):
    """Test suite for _job_status_monitor function."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_job = Mock()
        self.mock_job.id = "test-job-123"

    @patch("app.utils.rq_job.JobStream")
    @patch("app.utils.rq_job.run_async")
    def test_on_success_callback_executed_only_once(self, mock_run_async, mock_stream):
        """Test that on_success callback is executed exactly once when job finishes."""

        async def test():
            on_success = AsyncMock()

            # Simulate job going through states: QUEUED -> STARTED -> FINISHED -> FINISHED
            status_sequence = [
                RQJobStatus.QUEUED,
                RQJobStatus.STARTED,
                RQJobStatus.FINISHED,
                RQJobStatus.FINISHED,  # Should not trigger callback again
            ]

            call_count = [0]

            def get_status_side_effect():
                idx = call_count[0]
                call_count[0] += 1
                if idx < len(status_sequence):
                    return status_sequence[idx]
                return RQJobStatus.FINISHED

            async def run_async_side_effect(fn):
                return fn()

            mock_run_async.side_effect = run_async_side_effect
            self.mock_job.get_status.side_effect = get_status_side_effect

            await _job_status_monitor(
                self.mock_job,
                poll_interval=0.01,
                on_success=on_success,
            )

            # Verify on_success was called exactly once
            on_success.assert_called_once()

        asyncio.run(test())

    @patch("app.utils.rq_job.JobStream")
    @patch("app.utils.rq_job.run_async")
    def test_on_failure_callback_executed_only_once(self, mock_run_async, mock_stream):
        """Test that on_failure callback is executed exactly once when job fails."""

        async def test():
            on_failure = AsyncMock()

            # Simulate job going through states: QUEUED -> STARTED -> FAILED -> FAILED
            status_sequence = [
                RQJobStatus.QUEUED,
                RQJobStatus.STARTED,
                RQJobStatus.FAILED,
                RQJobStatus.FAILED,  # Should not trigger callback again
            ]

            call_count = [0]

            def get_status_side_effect():
                idx = call_count[0]
                call_count[0] += 1
                if idx < len(status_sequence):
                    return status_sequence[idx]
                return RQJobStatus.FAILED

            async def run_async_side_effect(fn):
                return fn()

            mock_run_async.side_effect = run_async_side_effect
            self.mock_job.get_status.side_effect = get_status_side_effect

            await _job_status_monitor(
                self.mock_job,
                poll_interval=0.01,
                on_failure=on_failure,
            )

            # Verify on_failure was called exactly once
            on_failure.assert_called_once()

        asyncio.run(test())

    @patch("app.utils.rq_job.JobStream")
    @patch("app.utils.rq_job.run_async")
    def test_on_start_callback_executed_only_first_time(self, mock_run_async, mock_stream):
        """Test that on_start callback is executed only the first time job enters STARTED state."""

        async def test():
            on_start = AsyncMock()

            # Simulate job going through states with STARTED appearing multiple times
            status_sequence = [
                RQJobStatus.QUEUED,
                RQJobStatus.STARTED,  # Should trigger callback
                RQJobStatus.STARTED,  # Should NOT trigger callback (same state)
                RQJobStatus.STARTED,  # Should NOT trigger callback (same state)
                RQJobStatus.FINISHED,
            ]

            call_count = [0]

            def get_status_side_effect():
                idx = call_count[0]
                call_count[0] += 1
                if idx < len(status_sequence):
                    return status_sequence[idx]
                return RQJobStatus.FINISHED

            async def run_async_side_effect(fn):
                return fn()

            mock_run_async.side_effect = run_async_side_effect
            self.mock_job.get_status.side_effect = get_status_side_effect

            await _job_status_monitor(
                self.mock_job,
                poll_interval=0.01,
                on_start=on_start,
            )

            # Verify on_start was called exactly once
            on_start.assert_called_once()

        asyncio.run(test())

    @patch("app.utils.rq_job.JobStream")
    @patch("app.utils.rq_job.run_async")
    def test_all_callbacks_work_together(self, mock_run_async, mock_stream):
        """Test that all callbacks work correctly when used together."""

        async def test():
            on_start = AsyncMock()
            on_success = AsyncMock()
            on_failure = AsyncMock()

            status_sequence = [
                RQJobStatus.SCHEDULED,
                RQJobStatus.QUEUED,
                RQJobStatus.STARTED,
                RQJobStatus.STARTED,  # Should not trigger on_start again
                RQJobStatus.FINISHED,
            ]

            call_count = [0]

            def get_status_side_effect():
                idx = call_count[0]
                call_count[0] += 1
                if idx < len(status_sequence):
                    return status_sequence[idx]
                return RQJobStatus.FINISHED

            async def run_async_side_effect(fn):
                return fn()

            mock_run_async.side_effect = run_async_side_effect
            self.mock_job.get_status.side_effect = get_status_side_effect

            await _job_status_monitor(
                self.mock_job,
                poll_interval=0.01,
                on_start=on_start,
                on_success=on_success,
                on_failure=on_failure,
            )

            # Verify callbacks were called correctly
            on_start.assert_called_once()
            on_success.assert_called_once()
            on_failure.assert_not_called()

        asyncio.run(test())

    @patch("app.utils.rq_job.JobStream")
    @patch("app.utils.rq_job.run_async")
    def test_no_callbacks_when_none_provided(self, mock_run_async, mock_stream):
        """Test that monitor works correctly when no callbacks are provided."""

        async def test():
            status_sequence = [
                RQJobStatus.QUEUED,
                RQJobStatus.STARTED,
                RQJobStatus.FINISHED,
            ]

            call_count = [0]

            def get_status_side_effect():
                idx = call_count[0]
                call_count[0] += 1
                if idx < len(status_sequence):
                    return status_sequence[idx]
                return RQJobStatus.FINISHED

            async def run_async_side_effect(fn):
                return fn()

            mock_run_async.side_effect = run_async_side_effect
            self.mock_job.get_status.side_effect = get_status_side_effect

            # Should not raise any exceptions
            await _job_status_monitor(
                self.mock_job,
                poll_interval=0.01,
            )

        asyncio.run(test())

    @patch("app.utils.rq_job.JobStream")
    @patch("app.utils.rq_job.run_async")
    def test_queue_position_updates(self, mock_run_async, mock_stream):
        """Test that queue position updates are sent correctly."""

        async def test():
            mock_stream_instance = mock_stream.return_value

            status_sequence = [RQJobStatus.QUEUED] * 3 + [RQJobStatus.FINISHED]
            position_sequence = [5, 3, 1]

            call_count = [0]
            position_index = [0]

            def get_status_side_effect():
                idx = call_count[0]
                call_count[0] += 1
                if idx < len(status_sequence):
                    return status_sequence[idx]
                return RQJobStatus.FINISHED

            def get_position_side_effect():
                idx = position_index[0]
                position_index[0] += 1
                if idx < len(position_sequence):
                    return position_sequence[idx]
                return None

            async_call_count = [0]

            def run_async_router(fn):
                async_call_count[0] += 1
                # Every other call is get_position
                if async_call_count[0] % 2 == 0:
                    return get_position_side_effect()
                return get_status_side_effect()

            mock_run_async.side_effect = run_async_router

            await _job_status_monitor(
                self.mock_job,
                poll_interval=0.01,
            )

            # Verify position updates were sent (positions 5, 3, 1 are all different)
            assert mock_stream_instance.send_status.call_count >= 3

        asyncio.run(test())

    @patch("app.utils.rq_job.JobStream")
    @patch("app.utils.rq_job.run_async")
    @patch("app.utils.rq_job.logger")
    def test_exception_handling_in_monitor(self, mock_logger, mock_run_async, mock_stream):
        """Test that exceptions in the monitor loop are caught and logged."""

        async def test():
            mock_run_async.side_effect = Exception("Test error")

            # Should not raise exception, but log it
            await _job_status_monitor(
                self.mock_job,
                poll_interval=0.01,
            )

            # Verify error was logged
            mock_logger.error.assert_called_once()
            assert "Error monitoring job status" in str(mock_logger.error.call_args)

        asyncio.run(test())

    @patch("app.utils.rq_job.JobStream")
    @patch("app.utils.rq_job.run_async")
    def test_callback_execution_order_on_failure(self, mock_run_async, mock_stream):
        """Test callback execution and state when job fails."""

        async def test():
            on_start = AsyncMock()
            on_failure = AsyncMock()
            execution_order = []

            async def track_start():
                execution_order.append("start")

            async def track_failure():
                execution_order.append("failure")

            on_start.side_effect = track_start
            on_failure.side_effect = track_failure

            status_sequence = [
                RQJobStatus.QUEUED,
                RQJobStatus.STARTED,
                RQJobStatus.FAILED,
            ]

            call_count = [0]

            def get_status_side_effect():
                idx = call_count[0]
                call_count[0] += 1
                if idx < len(status_sequence):
                    return status_sequence[idx]
                return RQJobStatus.FAILED

            # Mock run_async to actually execute the lambda
            async def run_async_side_effect(fn):
                return fn()

            mock_run_async.side_effect = run_async_side_effect
            self.mock_job.get_status.side_effect = get_status_side_effect

            await _job_status_monitor(
                self.mock_job,
                poll_interval=0.01,
                on_start=on_start,
                on_failure=on_failure,
            )

            # Verify execution order
            self.assertEqual(execution_order, ["start", "failure"])

        asyncio.run(test())

    @patch("app.utils.rq_job.JobStream")
    @patch("app.utils.rq_job.run_async")
    def test_monitor_stops_after_terminal_state(self, mock_run_async, mock_stream):
        """Test that monitor stops polling after reaching a terminal state."""

        async def test():
            on_success = AsyncMock()

            call_count = [0]

            def get_status_side_effect():
                call_count[0] += 1
                if call_count[0] <= 3:
                    return RQJobStatus.QUEUED
                return RQJobStatus.FINISHED

            # Mock run_async to actually execute the lambda
            async def run_async_side_effect(fn):
                return fn()

            mock_run_async.side_effect = run_async_side_effect
            self.mock_job.get_status.side_effect = get_status_side_effect

            await _job_status_monitor(
                self.mock_job,
                poll_interval=0.01,
                on_success=on_success,
            )

            # Should have made exactly 4 status calls (3 QUEUED + 1 FINISHED)
            # and then stopped
            self.assertEqual(call_count[0], 4)

        asyncio.run(test())


if __name__ == "__main__":
    unittest.main()
