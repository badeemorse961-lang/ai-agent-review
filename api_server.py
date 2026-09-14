from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from application_boundary import ApplicationIntent, ControlCenterService

API_VERSION = "v1"
SERVICE_NAME = "ai-agent-control-center"
MAX_REQUEST_BYTES = 256_000


class ApplicationHttpError(ValueError):
    """Raised for malformed HTTP application requests."""


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _read_json(handler: BaseHTTPRequestHandler) -> Any:
    length_header = handler.headers.get("Content-Length")
    if length_header is None:
        raise ApplicationHttpError("Content-Length header is required")
    try:
        length = int(length_header)
    except ValueError as exc:
        raise ApplicationHttpError("Content-Length must be an integer") from exc
    if length < 0 or length > MAX_REQUEST_BYTES:
        raise ApplicationHttpError("Request body is too large")
    raw = handler.rfile.read(length)
    if len(raw) != length:
        raise ApplicationHttpError("Request body is incomplete")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApplicationHttpError("Request body must be valid UTF-8 JSON") from exc


def create_handler(service_factory: Callable[[], ControlCenterService]):
    """Create a thin HTTP adapter over the existing application boundary."""

    class ControlCenterHTTPHandler(BaseHTTPRequestHandler):
        server_version = "AI-Agent-HTTP/1.0"

        def _send_json(self, status: int, payload: Any) -> None:
            body = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _service(self) -> ControlCenterService:
            service = getattr(self.server, "application_service", None)
            if service is None:
                service = service_factory()
                self.server.application_service = service
            return service

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/health":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "service": SERVICE_NAME,
                        "api_version": API_VERSION,
                    },
                )
                return

            if path == f"/api/{API_VERSION}/capabilities":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "service": SERVICE_NAME,
                        "api_version": API_VERSION,
                        "intents": [
                            "select_project",
                            "refresh_dashboard",
                            "send_leader_goal",
                            "run_task",
                            "refresh_connections",
                            "sync_external_secret_sources",
                            "git_snapshot",
                            "session_evidence",
                        ],
                    },
                )
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path != f"/api/{API_VERSION}/intents":
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return

            content_type = self.headers.get("Content-Type", "")
            if not content_type.lower().startswith("application/json"):
                self._send_json(
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    {"error": "Content-Type must be application/json"},
                )
                return

            try:
                document = _read_json(self)
                if not isinstance(document, dict):
                    raise ApplicationHttpError("Request JSON must be an object")
                kind = document.get("kind")
                payload = document.get("payload", {})
                if not isinstance(kind, str) or not kind.strip():
                    raise ApplicationHttpError("kind must be a non-empty string")
                if not isinstance(payload, dict):
                    raise ApplicationHttpError("payload must be an object")

                result = self._service().dispatch(
                    ApplicationIntent(kind=kind, payload=payload)
                )
            except ApplicationHttpError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return

            if result.status == "REJECTED":
                status = HTTPStatus.BAD_REQUEST
            elif result.status == "BLOCKED":
                status = HTTPStatus.CONFLICT
            elif result.status == "ERROR":
                status = HTTPStatus.INTERNAL_SERVER_ERROR
            else:
                status = HTTPStatus.OK

            self._send_json(
                status,
                {
                    "status": result.status,
                    "data": dict(result.data),
                    "error": result.error,
                },
            )

        def log_message(self, format: str, *args: Any) -> None:
            # Keep the adapter quiet by default. The Core remains responsible for
            # bounded, redacted operational evidence.
            del format, args

    return ControlCenterHTTPHandler


def create_server(
    *,
    workspace_root: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    service: ControlCenterService | None = None,
) -> ThreadingHTTPServer:
    """Create a loopback HTTP server over the existing application boundary.

    The server is deliberately loopback-only by default and exposes structured
    application intents; it does not accept shell commands or raw Core calls.
    """
    if not isinstance(port, int) or not 0 <= port <= 65_535:
        raise ValueError("port must be an integer between 0 and 65535")

    def factory() -> ControlCenterService:
        return service or ControlCenterService(workspace_root=workspace_root)

    server = ThreadingHTTPServer((host, port), create_handler(factory))
    if service is not None:
        server.application_service = service
    return server


def serve_forever(*, workspace_root: Path | None = None, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = create_server(workspace_root=workspace_root, host=host, port=port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI-Agent Control Center HTTP adapter")
    parser.add_argument("--workspace-root", type=Path, default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve_forever(
        workspace_root=args.workspace_root,
        host=args.host,
        port=args.port,
    )
