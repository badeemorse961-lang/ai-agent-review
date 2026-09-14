from __future__ import annotations

import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from application_boundary import ControlCenterService
from api_server import create_server


def _request(server, method: str, path: str, body: dict | None = None):
    host, port = server.server_address
    url = f"http://{host}:{port}{path}"
    payload = None
    headers = {}
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=payload, headers=headers, method=method)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_health_and_capabilities() -> None:
    server = create_server(service=ControlCenterService(autowire_core=False), port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _request(server, "GET", "/health")
        assert status == 200
        assert body["status"] == "ok"
        assert body["api_version"] == "v1"

        status, body = _request(server, "GET", "/api/v1/capabilities")
        assert status == 200
        assert "refresh_dashboard" in body["intents"]
        assert "run_task" in body["intents"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_structured_application_intent_dispatch() -> None:
    service = ControlCenterService(autowire_core=False)
    server = create_server(service=service, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _request(
            server,
            "POST",
            "/api/v1/intents",
            {"kind": "refresh_dashboard", "payload": {}},
        )
        assert status == 200
        assert body["status"] == "OK"
        assert body["data"]["project"] is None

        status, body = _request(
            server,
            "POST",
            "/api/v1/intents",
            {"kind": "not_a_real_intent", "payload": {}},
        )
        assert status == 400
        assert body["status"] == "REJECTED"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_adapter_rejects_non_json_payload() -> None:
    server = create_server(service=ControlCenterService(autowire_core=False), port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        request = Request(
            f"http://{host}:{port}/api/v1/intents",
            data=b"{}",
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        try:
            urlopen(request, timeout=5)
            raise AssertionError("request unexpectedly succeeded")
        except HTTPError as exc:
            assert exc.code == 415
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
