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
        mock_settings.LOG_LEVEL_LIBS = "WARNING"
        from app.logging import setup_logging

        setup_logging()

        # loguru should have exactly one handler (ours)
        self.assertEqual(len(logger._core.handlers), 1)

    @patch("app.config.settings.settings")
    def test_default_cid_is_dashes(self, mock_settings):
        mock_settings.LOG_LEVEL = "INFO"
        mock_settings.LOG_LEVEL_LIBS = "WARNING"
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
        mock_settings.LOG_LEVEL_LIBS = "DEBUG"
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
        mock_settings.LOG_LEVEL_LIBS = "WARNING"
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
        mock_settings.LOG_LEVEL_LIBS = "WARNING"
        from app.logging import setup_logging

        setup_logging(level="DEBUG")

        sink = StringIO()
        logger.remove()
        logger.add(sink, format="{message}", level="DEBUG")
        logger.debug("debug msg")
        self.assertIn("debug msg", sink.getvalue())

    @patch("app.config.settings.settings")
    def test_filter_allows_app_debug_blocks_lib_debug(self, mock_settings):
        """App DEBUG messages pass; library DEBUG messages are blocked."""
        mock_settings.LOG_LEVEL = "DEBUG"
        mock_settings.LOG_LEVEL_LIBS = "WARNING"
        mock_settings.LOG_SHOW_CID = False
        mock_settings.LOG_SHOW_SOURCE = False
        from app.logging import setup_logging

        sink = StringIO()
        setup_logging()
        # Replace stderr handler with our sink, keeping the same filter
        handler_id = list(logger._core.handlers.keys())[0]
        handler = logger._core.handlers[handler_id]
        filter_fn = handler._filter
        logger.remove()
        logger.add(sink, format="{name} | {level} | {message}", level="DEBUG", filter=filter_fn)

        # App debug — should pass
        logger.patch(lambda r: r.update(name="app.services.worker")).debug("app debug msg")
        # Lib debug — should be blocked
        logger.patch(lambda r: r.update(name="httpx")).debug("lib debug msg")
        # Lib warning — should pass
        logger.patch(lambda r: r.update(name="httpx")).warning("lib warning msg")

        output = sink.getvalue()
        self.assertIn("app debug msg", output)
        self.assertNotIn("lib debug msg", output)
        self.assertIn("lib warning msg", output)

    @patch("app.config.settings.settings")
    def test_filter_lib_level_controls_all_libraries(self, mock_settings):
        """LOG_LEVEL_LIBS applies to all non-app loggers uniformly."""
        mock_settings.LOG_LEVEL = "INFO"
        mock_settings.LOG_LEVEL_LIBS = "ERROR"
        mock_settings.LOG_SHOW_CID = False
        mock_settings.LOG_SHOW_SOURCE = False
        from app.logging import setup_logging

        sink = StringIO()
        setup_logging()
        handler_id = list(logger._core.handlers.keys())[0]
        handler = logger._core.handlers[handler_id]
        filter_fn = handler._filter
        logger.remove()
        logger.add(sink, format="{name} | {level} | {message}", level="DEBUG", filter=filter_fn)

        # Various library loggers at WARNING — all should be blocked (lib level is ERROR)
        for lib in ("bluecellulab", "uvicorn.access", "httpcore", "matplotlib"):
            logger.patch(lambda r, n=lib: r.update(name=n)).warning(f"{lib} warning")

        # Library error — should pass
        logger.patch(lambda r: r.update(name="bluecellulab")).error("lib error msg")

        output = sink.getvalue()
        for lib in ("bluecellulab", "uvicorn.access", "httpcore", "matplotlib"):
            self.assertNotIn(f"{lib} warning", output)
        self.assertIn("lib error msg", output)


if __name__ == "__main__":
    unittest.main()
