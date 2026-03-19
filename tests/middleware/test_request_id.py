import unittest

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.context import cid_var
from app.middleware.request_id import add_request_id_middleware


class TestRequestIdMiddleware(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.middleware("http")(add_request_id_middleware)

        self.captured_cid = None

        @self.app.get("/test")
        async def test_route(request: Request):
            self.captured_cid = cid_var.get()
            return {"cid": request.state.cid, "request_id": request.state.request_id}

        self.client = TestClient(self.app)

    def test_response_has_x_request_id_header(self):
        resp = self.client.get("/test")
        self.assertIn("x-request-id", resp.headers)
        rid = resp.headers["x-request-id"]
        self.assertEqual(len(rid), 8)
        # Should not be a UUID (no dashes, much shorter)
        self.assertNotIn("-", rid)

    def test_each_request_gets_unique_cid(self):
        ids = set()
        for _ in range(10):
            resp = self.client.get("/test")
            ids.add(resp.headers["x-request-id"])
        self.assertEqual(len(ids), 10)

    def test_cid_var_is_set_during_request(self):
        resp = self.client.get("/test")
        body = resp.json()
        rid = resp.headers["x-request-id"]
        # The route captured cid_var; it should match the header
        self.assertEqual(body["cid"], rid)
        self.assertEqual(body["request_id"], rid)

    def test_cid_var_is_reset_after_request(self):
        self.client.get("/test")
        # After request completes, cid_var should be back to default
        self.assertIsNone(cid_var.get())


if __name__ == "__main__":
    unittest.main()
