"""Tests that the public widget CORS shim is scoped to /widget/* only."""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.interfaces.http.middleware.widget_cors import PublicWidgetCORSMiddleware  # noqa: E402


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/widget/ping")
    def widget_ping():
        return {"ok": True}

    @app.get("/other/ping")
    def other_ping():
        return {"ok": True}

    app.add_middleware(PublicWidgetCORSMiddleware)
    return TestClient(app)


def test_widget_preflight_is_answered_credential_less():
    client = _client()
    resp = client.options(
        "/widget/ping",
        headers={"Origin": "https://acme.com", "Access-Control-Request-Method": "POST"},
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "https://acme.com"
    assert resp.headers["access-control-allow-credentials"] == "false"
    assert "POST" in resp.headers["access-control-allow-methods"]


def test_widget_response_reflects_origin():
    client = _client()
    resp = client.get("/widget/ping", headers={"Origin": "https://acme.com"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://acme.com"


def test_non_widget_path_is_untouched():
    client = _client()
    resp = client.get("/other/ping", headers={"Origin": "https://acme.com"})
    assert resp.status_code == 200
    # the shim must not add widget CORS headers to non-widget paths
    assert "access-control-allow-origin" not in resp.headers
