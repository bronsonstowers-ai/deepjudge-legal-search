import json
import threading
import unittest
from http import HTTPStatus
from urllib import error, request
from unittest import mock

import mobile_api


class MobileAPITestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.config = mobile_api.APIConfig(
            upstream_url="https://example.com/search",
            upstream_api_key="test-upstream-key",
            upstream_api_key_header="Authorization",
            mobile_api_token="iphone-secret",
            allow_origin="*",
            timeout_seconds=5,
        )
        self.server = mobile_api.create_server("127.0.0.1", 0, config=self.config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
        token: str | None = None,
        use_bearer: bool = False,
    ):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        if token is not None:
            if use_bearer:
                headers["Authorization"] = "Bearer " + token
            else:
                headers["X-API-Token"] = token
        req = request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        return request.urlopen(req, timeout=5)

    def test_health_endpoint_returns_json(self) -> None:
        with self._request("/health") as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, HTTPStatus.OK)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "deepjudge-mobile-api")

    def test_search_requires_token_when_configured(self) -> None:
        with self.assertRaises(error.HTTPError) as exc:
            self._request("/api/search", method="POST", payload={"query": "Miranda rights"})
        self.assertEqual(exc.exception.code, HTTPStatus.UNAUTHORIZED)
        payload = json.loads(exc.exception.read().decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "unauthorized")

    @mock.patch("mobile_api.perform_upstream_search")
    def test_search_returns_clean_normalized_response(self, perform_upstream_search: mock.Mock) -> None:
        perform_upstream_search.return_value = {
            "request_id": "req_123",
            "results": [
                {
                    "id": "doc-1",
                    "title": "Roe v. Wade",
                    "snippet": "Sample legal summary",
                    "url": "https://example.com/cases/roe",
                    "score": 0.98,
                    "court": "Supreme Court",
                }
            ],
        }

        with self._request(
            "/api/search",
            method="POST",
            payload={"query": "Roe v Wade", "top_k": 1},
            token="iphone-secret",
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(response.status, HTTPStatus.OK)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["query"], "Roe v Wade")
        self.assertEqual(payload["result_count"], 1)
        self.assertEqual(payload["request_id"], "req_123")
        self.assertEqual(
            payload["results"][0],
            {
                "id": "doc-1",
                "title": "Roe v. Wade",
                "text": "Sample legal summary",
                "url": "https://example.com/cases/roe",
                "score": 0.98,
                "source": "Supreme Court",
            },
        )
        perform_upstream_search.assert_called_once_with(
            self.config,
            {"query": "Roe v Wade", "top_k": 1},
        )

    @mock.patch("mobile_api.perform_upstream_search")
    def test_search_accepts_bearer_token(self, perform_upstream_search: mock.Mock) -> None:
        perform_upstream_search.return_value = {"results": []}

        with self._request(
            "/api/search",
            method="POST",
            payload={"query": "Miranda"},
            token="iphone-secret",
            use_bearer=True,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(response.status, HTTPStatus.OK)
        self.assertTrue(payload["ok"])

    def test_search_rejects_blank_queries(self) -> None:
        with self.assertRaises(error.HTTPError) as exc:
            self._request(
                "/api/search",
                method="POST",
                payload={"query": "   "},
                token="iphone-secret",
            )
        self.assertEqual(exc.exception.code, HTTPStatus.BAD_REQUEST)
        payload = json.loads(exc.exception.read().decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "bad_request")

    def test_search_rejects_invalid_top_k(self) -> None:
        with self.assertRaises(error.HTTPError) as exc:
            self._request(
                "/api/search",
                method="POST",
                payload={"query": "Miranda", "top_k": 50},
                token="iphone-secret",
            )
        self.assertEqual(exc.exception.code, HTTPStatus.BAD_REQUEST)
        payload = json.loads(exc.exception.read().decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "bad_request")

    @mock.patch("mobile_api.perform_upstream_search")
    def test_search_preserves_zero_score(self, perform_upstream_search: mock.Mock) -> None:
        perform_upstream_search.return_value = {
            "results": [
                {
                    "title": "Example",
                    "snippet": "Zero score should not be dropped",
                    "score": 0,
                }
            ]
        }

        with self._request(
            "/api/search",
            method="POST",
            payload={"query": "zero score"},
            token="iphone-secret",
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(response.status, HTTPStatus.OK)
        self.assertEqual(payload["results"][0]["score"], 0)


if __name__ == "__main__":
    unittest.main()
