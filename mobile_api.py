import argparse
import hmac
import json
import os
import ssl
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import error, request


DEFAULT_UPSTREAM_URL = "https://api.deepjudge.ai/v1/search"


@dataclass(frozen=True)
class APIConfig:
    upstream_url: str
    upstream_api_key: str | None
    upstream_api_key_header: str
    mobile_api_token: str | None
    allow_origin: str
    timeout_seconds: float


def load_config() -> APIConfig:
    return APIConfig(
        upstream_url=os.getenv("DEEPJUDGE_SEARCH_URL", DEFAULT_UPSTREAM_URL),
        upstream_api_key=os.getenv("DEEPJUDGE_API_KEY"),
        upstream_api_key_header=os.getenv("DEEPJUDGE_API_KEY_HEADER", "Authorization"),
        mobile_api_token=os.getenv("MOBILE_API_TOKEN"),
        allow_origin=os.getenv("MOBILE_API_ALLOW_ORIGIN", "*"),
        timeout_seconds=float(os.getenv("DEEPJUDGE_TIMEOUT_SECONDS", "30")),
    )


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode("utf-8")


def _error_payload(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def _extract_results(payload: Any) -> list[Any]:
    if isinstance(payload, dict):
        for key in ("results", "data", "items", "documents"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    if isinstance(payload, list):
        return payload
    return []


def _normalize_result(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"text": str(item)}

    score = item.get("score")
    if score is None:
        score = item.get("relevance")

    normalized = {
        "id": item.get("id") or item.get("document_id") or item.get("slug"),
        "title": item.get("title") or item.get("name"),
        "text": item.get("snippet")
        or item.get("summary")
        or item.get("excerpt")
        or item.get("content")
        or item.get("text"),
        "url": item.get("url") or item.get("link"),
        "score": score,
        "source": item.get("source") or item.get("court"),
        "metadata": item.get("metadata"),
    }
    return {key: value for key, value in normalized.items() if value is not None}


def normalize_search_response(upstream_payload: Any, query: str) -> dict[str, Any]:
    request_id = None
    answer = None
    if isinstance(upstream_payload, dict):
        request_id = upstream_payload.get("request_id") or upstream_payload.get("id")
        answer = upstream_payload.get("answer") or upstream_payload.get("summary")

    results = [_normalize_result(item) for item in _extract_results(upstream_payload)]
    response = {
        "ok": True,
        "query": query,
        "result_count": len(results),
        "results": results,
        "request_id": request_id or str(uuid.uuid4()),
    }
    if answer:
        response["answer"] = answer
    return response


def perform_upstream_search(config: APIConfig, payload: dict[str, Any]) -> Any:
    if not config.upstream_api_key:
        raise RuntimeError("DEEPJUDGE_API_KEY is required for search requests.")

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if config.upstream_api_key_header.lower() == "authorization":
        headers["Authorization"] = "Bearer " + config.upstream_api_key
    else:
        headers[config.upstream_api_key_header] = config.upstream_api_key

    upstream_request = request.Request(
        config.upstream_url,
        data=_json_bytes(payload),
        headers=headers,
        method="POST",
    )
    with request.urlopen(upstream_request, timeout=config.timeout_seconds) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read().decode(charset)
        return json.loads(body) if body else {}


class MobileAPIHandler(BaseHTTPRequestHandler):
    server_version = "DeepJudgeMobileAPI/1.0"

    @property
    def config(self) -> APIConfig:
        return self.server.config  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any], extra_headers: dict[str, str] | None = None) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", self.config.allow_origin)
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-API-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if not raw_length:
            raise ValueError("Request body is required.")

        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Content-Length must be a number.") from exc

        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must be valid JSON.") from exc

        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        return payload

    def _is_authorized(self) -> bool:
        expected = self.config.mobile_api_token
        if not expected:
            return True

        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return hmac.compare_digest(auth_header[len("Bearer ") :], expected)

        token_header = self.headers.get("X-API-Token", "")
        return bool(token_header) and hmac.compare_digest(token_header, expected)

    def _require_auth(self) -> bool:
        if self._is_authorized():
            return True

        self._send_json(
            HTTPStatus.UNAUTHORIZED,
            _error_payload("unauthorized", "A valid mobile API token is required."),
            extra_headers={"WWW-Authenticate": "Bearer"},
        )
        return False

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", self.config.allow_origin)
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-API-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            self._send_json(
                HTTPStatus.OK,
                {"status": "ok", "service": "deepjudge-mobile-api"},
            )
            return

        self._send_json(HTTPStatus.NOT_FOUND, _error_payload("not_found", "Route not found."))

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/api/search":
            self._send_json(HTTPStatus.NOT_FOUND, _error_payload("not_found", "Route not found."))
            return

        if not self._require_auth():
            return

        try:
            payload = self._read_json_body()
            query = payload.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ValueError("'query' must be a non-empty string.")

            top_k = payload.get("top_k", 5)
            if not isinstance(top_k, int) or not 1 <= top_k <= 20:
                raise ValueError("'top_k' must be an integer between 1 and 20.")

            upstream_payload = {
                "query": query.strip(),
                "top_k": top_k,
            }
            if "filters" in payload:
                upstream_payload["filters"] = payload["filters"]

            upstream_response = perform_upstream_search(self.config, upstream_payload)
            self._send_json(
                HTTPStatus.OK,
                normalize_search_response(upstream_response, query=query.strip()),
            )
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, _error_payload("bad_request", str(exc)))
        except RuntimeError as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, _error_payload("server_error", str(exc)))
        except error.HTTPError:
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                _error_payload("upstream_error", "The upstream legal search service returned an error."),
            )
        except error.URLError:
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                _error_payload("upstream_unreachable", "The upstream legal search service could not be reached."),
            )


def create_server(host: str, port: int, config: APIConfig | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), MobileAPIHandler)
    server.config = config or load_config()  # type: ignore[attr-defined]
    return server


def run_server(host: str, port: int, certfile: str | None = None, keyfile: str | None = None) -> None:
    server = create_server(host, port)
    if certfile and keyfile:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=certfile, keyfile=keyfile)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    else:
        scheme = "http"

    print(f"DeepJudge mobile API listening on {scheme}://{host}:{port}")
    server.serve_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the DeepJudge mobile-friendly API proxy.")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--certfile", default=os.getenv("TLS_CERTFILE"))
    parser.add_argument("--keyfile", default=os.getenv("TLS_KEYFILE"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_server(args.host, args.port, certfile=args.certfile, keyfile=args.keyfile)


if __name__ == "__main__":
    main()
