from __future__ import annotations

import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from boardroom.api import create_app
from boardroom.api.security import ApiKeyAuth, RateLimiter
from boardroom.api.settings import ApiSettings
from boardroom.config import Settings
from boardroom.scenario import load_packaged

DEV = ApiSettings(dev_mode=True, sync_runs=True)


def client(settings: ApiSettings = DEV, **kwargs: Any) -> TestClient:
    return TestClient(create_app(settings, Settings(), **kwargs))


def custom_scenario() -> dict[str, Any]:
    data = load_packaged("cloud-migration").model_dump()
    data["id"] = "custom-one"
    return data


def test_healthz_and_config() -> None:
    c = client()
    health = c.get("/healthz").json()
    assert health["status"] == "ok"
    cfg = c.get("/api/config").json()
    assert cfg["access_mode"] == "dev"
    assert cfg["custom_scenarios_allowed"] is True
    assert "cloud-migration" in cfg["scenarios"]


def test_openapi_lists_decision_routes() -> None:
    paths = client().get("/openapi.json").json()["paths"]
    assert "/api/decisions" in paths
    assert "/api/decisions/{decision_id}/events" in paths


def test_scenarios_and_roles() -> None:
    c = client()
    ids = [s["id"] for s in c.get("/api/scenarios").json()["scenarios"]]
    assert "market-expansion" in ids
    assert c.get("/api/scenarios/market-expansion").json()["options"]
    assert c.get("/api/scenarios/nope").status_code == 404
    roles = c.get("/api/roles").json()["roles"]
    assert len(roles) == 5 and any(r["can_block"] for r in roles)


def test_sync_decision_returns_memo_and_events() -> None:
    res = client().post("/api/decisions", json={"scenario_id": "market-expansion", "rounds": 1})
    assert res.status_code == 200
    body = res.json()
    assert body["state"] == "finished"
    assert body["memo"]["recommendation"] == "uae"
    assert body["events"] and body["events"][0]["stage"] == "opening"


def test_memo_markdown_and_events_cursor() -> None:
    c = client()
    created = c.post("/api/decisions", json={"scenario_id": "cloud-migration"}).json()
    did = created["id"]
    page = c.get(f"/api/decisions/{did}/events", params={"since": 0}).json()
    assert page["done"] is True
    assert page["next_cursor"] == len(page["events"]) == created["event_count"]
    tail = c.get(f"/api/decisions/{did}/events", params={"since": page["next_cursor"]}).json()
    assert tail["events"] == []
    md = c.get(f"/api/decisions/{did}/memo.md")
    assert md.headers["content-type"].startswith("text/markdown")
    assert "phased-replatform" in md.text or "Phased" in md.text
    assert c.get("/api/decisions").json()["decisions"][0]["id"] == did


def test_async_mode_returns_202_then_finishes() -> None:
    c = client(ApiSettings(dev_mode=True))
    with c:
        res = c.post("/api/decisions", json={"scenario_id": "cloud-migration"})
        assert res.status_code == 202
        did = res.json()["id"]
        for _ in range(100):
            detail = c.get(f"/api/decisions/{did}").json()
            if detail["state"] == "finished":
                break
            time.sleep(0.05)
        assert detail["memo"]["recommendation"] == "phased-replatform"


def test_custom_scenario_in_dev_mode() -> None:
    res = client().post("/api/decisions", json={"scenario": custom_scenario(), "rounds": 0})
    assert res.status_code == 200
    assert res.json()["scenario_id"] == "custom-one"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"scenario_id": "cloud-migration", "scenario": custom_scenario()},
        {"scenario_id": "does-not-exist"},
        {"scenario_id": "cloud-migration", "rounds": 99},
        {"scenario_id": "cloud-migration", "roles": ["cfo", "intern"]},
        {"scenario_id": "cloud-migration", "unexpected": 1},
    ],
)
def test_invalid_requests_are_rejected(payload: dict[str, Any]) -> None:
    assert client().post("/api/decisions", json=payload).status_code == 422


def test_public_demo_restrictions_and_ownership() -> None:
    c = client(ApiSettings(sync_runs=True))
    assert c.get("/api/config").json()["access_mode"] == "public-demo"
    assert c.post("/api/decisions", json={"scenario": custom_scenario()}).status_code == 403
    res = c.post(
        "/api/decisions", json={"scenario_id": "cloud-migration", "provider": "configured"}
    )
    assert res.status_code == 403
    ok = c.post("/api/decisions", json={"scenario_id": "cloud-migration"})
    assert ok.status_code == 200 and ok.json()["provider"] == "mock"
    did = ok.json()["id"]
    other = TestClient(c.app, client=("203.0.113.9", 5000))
    assert other.get(f"/api/decisions/{did}").status_code == 404
    assert other.get("/api/decisions").json()["decisions"] == []


def test_api_key_mode() -> None:
    c = client(ApiSettings(api_keys=("s3cret-key",), sync_runs=True))
    assert c.get("/healthz").status_code == 200
    assert c.get("/api/scenarios").status_code == 401
    assert c.get("/api/scenarios", headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.get("/api/scenarios", headers={"X-API-Key": "s3cret-key"}).status_code == 200
    bearer = {"Authorization": "Bearer s3cret-key"}
    res = c.post("/api/decisions", json={"scenario": custom_scenario()}, headers=bearer)
    assert res.status_code == 200
    assert c.get("/api/config", headers=bearer).json()["authenticated"] is True


def test_general_rate_limit() -> None:
    c = client(ApiSettings(dev_mode=True, rate_limit_per_minute=3))
    codes = [c.get("/api/roles").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_decision_rate_limit_counts_only_valid_requests() -> None:
    c = client(ApiSettings(dev_mode=True, sync_runs=True, decision_limit_per_minute=1))
    assert c.post("/api/decisions", json={"scenario_id": "bad-id"}).status_code == 422
    assert c.post("/api/decisions", json={"scenario_id": "cloud-migration"}).status_code == 200
    res = c.post("/api/decisions", json={"scenario_id": "cloud-migration"})
    assert res.status_code == 429 and "retry-after" in res.headers


def test_body_limit() -> None:
    big = json.dumps({"scenario_id": "cloud-migration", "pad": "x" * 70_000})
    res = client().post("/api/decisions", content=big, headers={"Content-Type": "application/json"})
    assert res.status_code == 413


def test_security_headers_and_dashboard() -> None:
    c = client()
    page = c.get("/")
    assert page.status_code == 200 and "BoardRoom AI" in page.text
    csp = page.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp
    assert page.headers["x-frame-options"] == "DENY"
    assert c.get("/api/roles").headers["cache-control"] == "no-store"
    assert c.get("/static/app.js").status_code == 200
    assert "innerHTML" not in c.get("/static/app.js").text


def test_crashing_run_is_reported_as_error() -> None:
    def boom(*_: Any) -> Any:
        raise RuntimeError("provider exploded")

    res = client(run_fn=boom).post("/api/decisions", json={"scenario_id": "cloud-migration"})
    assert res.status_code == 200
    assert res.json()["state"] == "error" and "exploded" in res.json()["error"]


def test_queue_full_returns_503() -> None:
    import threading

    gate = threading.Event()

    def slow(scenario: Any, settings: Any, config: Any, hook: Any) -> Any:
        gate.wait(5)
        raise RuntimeError("stopped")

    c = client(ApiSettings(dev_mode=True, max_queued_runs=1), run_fn=slow)
    with c:
        assert c.post("/api/decisions", json={"scenario_id": "cloud-migration"}).status_code == 202
        res = c.post("/api/decisions", json={"scenario_id": "cloud-migration"})
        assert res.status_code == 503
        gate.set()


def test_api_key_auth_and_rate_limiter_units() -> None:
    auth = ApiKeyAuth(("a", "b"))
    assert auth.enabled and auth.verify("b") and auth.verify("c") is None
    assert auth.verify(None) is None
    now = [0.0]
    limiter = RateLimiter(2, 10, clock=lambda: now[0])
    assert limiter.check("x") is None and limiter.check("x") is None
    assert limiter.check("x") == pytest.approx(10)
    now[0] = 10.5
    assert limiter.check("x") is None


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOARDROOM_API_KEYS", "k1, k2")
    monkeypatch.setenv("VERCEL", "1")
    s = ApiSettings.from_env()
    assert s.api_keys == ("k1", "k2") and s.access_mode == "api-key" and s.sync_runs


def test_cli_serve_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    from boardroom import cli

    seen: dict[str, Any] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    monkeypatch.setenv("PORT", "9123")
    assert cli.main(["serve", "--dev"]) == 0
    assert seen["port"] == 9123 and seen["host"] == "127.0.0.1"
