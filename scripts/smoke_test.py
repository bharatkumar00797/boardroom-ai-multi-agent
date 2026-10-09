#!/usr/bin/env python3
"""End-to-end smoke test against a running server (stdlib only).

Usage: python3 scripts/smoke_test.py [BASE_URL] [--api-key KEY]

Checks health, the dashboard and its security headers, then runs every packaged scenario through
the API (works with background and sync mode) and checks the board reaches the expected
recommendation and the Markdown memo renders. Exits non-zero on the first failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

# The recommendation the deterministic mock panel reaches for each packaged scenario.
EXPECTED = {
    "ai-support-build-vs-buy": "build",
    "cloud-migration": "phased-replatform",
    "market-expansion": "uae",
}


class Client:
    def __init__(self, base: str, api_key: str | None) -> None:
        self.base = base.rstrip("/")
        self.api_key = api_key

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any, Any]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("X-API-Key", self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                raw = res.read().decode()
                status, headers = res.status, res.headers
        except urllib.error.HTTPError as err:
            raw, status, headers = err.read().decode(), err.code, err.headers
        ctype = headers.get("content-type", "")
        return status, (json.loads(raw) if "json" in ctype else raw), headers


def check(cond: bool, message: str) -> None:
    if not cond:
        print(f"FAIL {message}")
        sys.exit(1)


def run_scenario(c: Client, scenario_id: str, expected: str) -> None:
    status, body, _ = c.request("POST", "/api/decisions", {"scenario_id": scenario_id})
    check(status in (200, 202), f"{scenario_id}: create returned {status}: {body}")
    did = body["id"]
    deadline = time.monotonic() + 60
    while body["state"] not in ("finished", "error"):
        check(time.monotonic() < deadline, f"{scenario_id}: debate timed out")
        time.sleep(0.3)
        _, body, _ = c.request("GET", f"/api/decisions/{did}")
    check(body["state"] == "finished", f"{scenario_id}: state {body['state']} {body.get('error')}")
    got = body["memo"]["recommendation"]
    check(got == expected, f"{scenario_id}: recommended {got}, expected {expected}")
    status, events, _ = c.request("GET", f"/api/decisions/{did}/events?since=0")
    check(status == 200 and events["events"], f"{scenario_id}: no debate events")
    status, md, _ = c.request("GET", f"/api/decisions/{did}/memo.md")
    check(status == 200 and "#" in md, f"{scenario_id}: memo markdown missing")
    print(f"PASS {scenario_id} -> {got} ({body['memo']['confidence']} confidence)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()
    c = Client(args.base, args.api_key)

    status, health, _ = c.request("GET", "/healthz")
    check(status == 200 and health.get("status") == "ok", f"healthz returned {status}")
    status, page, headers = c.request("GET", "/")
    check(status == 200 and "BoardRoom AI" in page, "dashboard did not render")
    check("script-src 'self'" in headers.get("content-security-policy", ""), "CSP missing")
    print(f"PASS health + dashboard (version {health['version']})")

    _, cfg, _ = c.request("GET", "/api/config")
    missing = sorted(set(EXPECTED) - set(cfg["scenarios"]))
    check(not missing, f"scenarios not served: {missing}")
    for scenario_id, expected in EXPECTED.items():
        run_scenario(c, scenario_id, expected)
    print(f"ALL PASS ({len(EXPECTED) + 1})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
