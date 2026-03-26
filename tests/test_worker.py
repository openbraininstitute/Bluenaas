import unittest
from unittest.mock import MagicMock, patch

from app.constants import NULL_CID
from app.worker import LoggingWorker


class TestLoggingWorker(unittest.TestCase):
    @patch("app.worker.setup_logging")
    @patch("app.worker.Worker.__init__", return_value=None)
    def test_init_calls_setup_logging(self, mock_super_init, mock_setup):
        LoggingWorker()
        mock_setup.assert_called_once()

    @patch("app.worker.setup_logging")
    @patch("app.worker.Worker.__init__", return_value=None)
    @patch("app.worker.Worker.perform_job", return_value=True)
    @patch("app.worker.logger")
    def test_perform_job_uses_cid(self, mock_logger, mock_perform, mock_init, mock_setup):
        worker = LoggingWorker()
        job = MagicMock()
        job.meta = {"cid": "xk9abr2m"}
        queue = MagicMock()

        worker.perform_job(job, queue)

        mock_logger.contextualize.assert_called_once_with(cid="xk9abr2m")

    @patch("app.worker.setup_logging")
    @patch("app.worker.Worker.__init__", return_value=None)
    @patch("app.worker.Worker.perform_job", return_value=True)
    @patch("app.worker.logger")
    def test_perform_job_missing_cid_falls_back(
        self, mock_logger, mock_perform, mock_init, mock_setup
    ):
        worker = LoggingWorker()
        job = MagicMock()
        job.meta = {}
        queue = MagicMock()

        worker.perform_job(job, queue)

        mock_logger.contextualize.assert_called_once_with(cid=NULL_CID)


if __name__ == "__main__":
    unittest.main()
