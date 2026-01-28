import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from fastapi.testclient import TestClient


class TestCORS(unittest.TestCase):
    @patch.dict(os.environ, {"CORS_ORIGIN_REGEX": r"https://.*\.example\.com"})
    def test_cors_origin_regex_allows_matching_origin(self):
        from importlib import reload
        from app.config import settings as settings_module
        from app import app as app_module

        reload(settings_module)
        reload(app_module)

        client = TestClient(app_module.app)
        response = client.options("/", headers={"Origin": "https://subdomain.example.com"})

        self.assertEqual(
            response.headers.get("access-control-allow-origin"), "https://subdomain.example.com"
        )

    @patch.dict(os.environ, {"CORS_ORIGIN_REGEX": r"https://.*\.example\.com"})
    def test_cors_origin_regex_blocks_non_matching_origin(self):
        from importlib import reload
        from app.config import settings as settings_module
        from app import app as app_module

        reload(settings_module)
        reload(app_module)

        client = TestClient(app_module.app)
        response = client.options("/", headers={"Origin": "https://malicious.com"})

        self.assertIsNone(response.headers.get("access-control-allow-origin"))


if __name__ == "__main__":
    unittest.main()
