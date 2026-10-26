import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DISABLE_TRACKER", "1")
    import app.main as main
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


def test_dashboard_and_settings(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    r = client.put("/api/settings", json={"latitude": 47.6, "longitude": -122.3, "flightaware_api_key": "k"})
    assert r.status_code == 200
    assert r.json()["flightaware_api_key"] != "k"
    assert client.get("/api/settings").json()["latitude"] == 47.6
    bad = client.put("/api/settings", json={"latitude": 200})
    assert bad.status_code == 422
    status = client.get("/api/status").json()
    assert status["board"]["rows"] == 3 and status["board"]["cols"] == 15


def test_manual_message_preview(client):
    r = client.post("/api/board/message", json={"lines": ["HELLO", "WORLD"], "hold_minutes": 1})
    assert r.status_code == 200
    board = client.get("/api/status").json()["board"]
    assert board["lines"] == ["HELLO", "WORLD"]
    assert board["source"] == "manual"


def test_password(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DISABLE_TRACKER", "1")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pw")
    import app.main as main
    importlib.reload(main)
    with TestClient(main.app) as c:
        assert c.get("/api/settings").status_code == 401
        assert c.get("/api/settings", auth=("admin", "pw")).status_code == 200
        assert c.get("/healthz").status_code == 200
    monkeypatch.delenv("DASHBOARD_PASSWORD")
    importlib.reload(main)
