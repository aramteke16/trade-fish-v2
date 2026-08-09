"""Web UI smoke tests: auth flow, dashboard, settings save."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-pass")
    from tradefish.web.app import app
    with TestClient(app) as c:
        yield c


def login(client):
    return client.post("/login", data={"password": "test-pass"}, follow_redirects=False)


def test_unauthenticated_redirects_to_login(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/login"


def test_wrong_password_rejected(client):
    resp = client.post("/login", data={"password": "nope"})
    assert "wrong password" in resp.text


def test_login_and_dashboard(client):
    assert login(client).status_code == 303
    resp = client.get("/")
    assert resp.status_code == 200
    assert "pipeline health" in resp.text
    assert "daily_collect" in resp.text


def test_activity_feed(client):
    login(client)
    from tradefish import log
    log.BUFFER.append({"ts": "10:00:00", "level": "INFO", "name": "test", "msg": "hi"})
    data = client.get("/api/activity").json()
    assert data["status"]["state"] in ("idle", "running")
    assert any(l["msg"] == "hi" for l in data["logs"])


def test_settings_save_secret_and_param(client):
    login(client)
    resp = client.post("/settings", data={
        "DEEPSEEK_API_KEY": "sk-new-key-1234",
        "LLM_PROVIDER": "deepseek",
        "top_k": "10",
    }, follow_redirects=True)
    assert resp.status_code == 200
    page = client.get("/settings").text
    assert "••••1234" in page            # secret masked, last 4 shown
    assert 'value="10"' in page          # strategy override visible

    from tradefish import config
    assert config.get("DEEPSEEK_API_KEY") == "sk-new-key-1234"
    assert config.strategy("top_k") == 10
