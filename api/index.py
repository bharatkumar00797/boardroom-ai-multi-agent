"""Serverless entrypoint (Vercel): exposes the BoardRoom AI FastAPI app as ``app``.

Serverless functions freeze or discard background threads once a response is sent, so debates
run synchronously inside ``POST /api/decisions`` (``BOARDROOM_SYNC_RUNS`` is switched on
automatically when ``VERCEL`` is set, and set here as a fallback). Unless API keys are configured
the deployment is a public demo: packaged scenarios and the offline mock provider.

Decisions live in memory per function instance, so the full memo and transcript are returned in
the POST response itself.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("BOARDROOM_SYNC_RUNS", "true")
os.environ.setdefault("BOARDROOM_MAX_CONCURRENT_RUNS", "1")

from boardroom.api import create_app  # noqa: E402  (path setup must run first)

app = create_app()
