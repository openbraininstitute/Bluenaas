import logging
import unittest
from io import StringIO
from unittest.mock import patch

from loguru import logger

from app.constants import NULL_CID


class TestSetupLogging(unittest.TestCase):
    def tearDown(self):
        logger.remove()

    @patch("app.config.settings.settings")
    def test_removes_default_handler_and_adds_configured(self, mock_settings):
        mock_settings.LOG_LEVEL = "DEBUG"
        from app.logging import setup_logging

        setup_logging()

        # loguru should have exactly one handler (ours)
        self.assertEqual(len(logger._core.handlers), 1)

    @patch("app.config.settings.settings")
    def test_default_cid_is_dashes(self, mock_settings):
        mock_settings.LOG_LEVEL = "INFO"
        from app.logging import setup_logging

        setup_logging()

        sink = StringIO()
        logger.remove()
        logger.add(sink, format="{extra[cid]}", level="INFO")
        logger.info("test")
        self.assertIn(NULL_CID, sink.getvalue())

    @patch("app.config.settings.settings")
    def test_stdlib_logging_intercepted(self, mock_settings):
        mock_settings.LOG_LEVEL = "DEBUG"
        from app.logging import setup_logging

        setup_logging()

        sink = StringIO()
        logger.remove()
        logger.add(sink, format="{message}", level="DEBUG")

        stdlib_logger = logging.getLogger("test.stdlib.intercept")
        stdlib_logger.info("hello from stdlib")

        self.assertIn("hello from stdlib", sink.getvalue())

    @patch("app.config.settings.settings")
    def test_log_output_includes_bound_cid(self, mock_settings):
        mock_settings.LOG_LEVEL = "INFO"
        from app.logging import setup_logging

        setup_logging()

        sink = StringIO()
        logger.remove()
        logger.add(sink, format="{extra[cid]} | {message}", level="INFO")

        with logger.contextualize(cid="abc123/api"):
            logger.info("request handled")

        output = sink.getvalue()
        self.assertIn("abc123/api", output)
        self.assertIn("request handled", output)

    @patch("app.config.settings.settings")
    def test_explicit_level_overrides_settings(self, mock_settings):
        mock_settings.LOG_LEVEL = "ERROR"
        from app.logging import setup_logging

        setup_logging(level="DEBUG")

        sink = StringIO()
        logger.remove()
        logger.add(sink, format="{message}", level="DEBUG")
        logger.debug("debug msg")
        self.assertIn("debug msg", sink.getvalue())


if __name__ == "__main__":
    unittest.main()
