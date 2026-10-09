"""Command line interface: `boardroom scenarios` and `boardroom run`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from pydantic import ValidationError

from boardroom import __version__
from boardroom.config import Settings
from boardroom.engine import MAX_ROUNDS, Boardroom, DebateConfig
from boardroom.llm import build_provider
from boardroom.memo import render_markdown
from boardroom.models import Position
from boardroom.scenario import list_scenarios, load_file, load_packaged


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="boardroom", description="Multi-agent AI business decision engine."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scenarios", help="list the packaged example scenarios")
    run = sub.add_parser("run", help="debate a decision and print the decision memo")
    run.add_argument("scenario", help="packaged scenario id or path to a scenario JSON file")
    run.add_argument("--rounds", type=int, default=None, help=f"debate rounds (0-{MAX_ROUNDS})")
    run.add_argument("--roles", default="", help="comma-separated role ids (default: all)")
    run.add_argument("--format", choices=["markdown", "json"], default="markdown")
    run.add_argument("--out", type=Path, default=None, help="write the memo to this file")
    run.add_argument("--quiet", action="store_true", help="do not print live progress")
    serve = sub.add_parser("serve", help="start the REST API and web dashboard")
    serve.add_argument(
        "--host",
        default=os.getenv("HOST", "127.0.0.1"),
        help="bind address (default: $HOST or 127.0.0.1)",
    )
    serve.add_argument("--port", type=int, default=None, help="port (default: $PORT or 8000)")
    serve.add_argument("--dev", action="store_true", help="dev mode: no API key required")
    return parser


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from boardroom.api import create_app
    from boardroom.api.settings import ApiSettings

    try:
        port = args.port or int(os.getenv("PORT") or 8000)
        settings = ApiSettings.from_env()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.dev:
        settings = replace(settings, dev_mode=True)
    if settings.access_mode == "dev" and args.host not in {"127.0.0.1", "::1", "localhost"}:
        print("warning: dev mode without API keys is exposed beyond localhost", file=sys.stderr)
    mode = {
        "api-key": "API-key auth",
        "dev": "dev mode (no auth)",
        "public-demo": "public demo (packaged scenarios + mock provider)",
    }[settings.access_mode]
    sync = " | sync debates" if settings.sync_runs else ""
    print(f"BoardRoom AI {__version__} on http://{args.host}:{port} | {mode}{sync}", flush=True)
    uvicorn.run(create_app(settings), host=args.host, port=port, log_level="info")
    return 0


def _progress(stage: str, position: Position) -> None:
    print(
        f"[{stage}] {position.role_id:<9} prefers {position.preferred} "
        f"({position.scores[position.preferred]:.1f})",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "scenarios":
        for name in list_scenarios():
            print(f"{name:<26} {load_packaged(name).title}")
        return 0
    try:
        settings = Settings.from_env()
        path = Path(args.scenario)
        scenario = load_file(path) if path.suffix == ".json" else load_packaged(args.scenario)
        rounds = settings.rounds if args.rounds is None else args.rounds
        roles = [r.strip() for r in args.roles.split(",") if r.strip()] or None
        engine = Boardroom(
            build_provider(settings),
            DebateConfig(rounds=rounds, roles=roles),
            on_progress=None if args.quiet else _progress,
        )
    except (KeyError, ValueError, ValidationError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    memo = engine.run(scenario)
    output = (
        json.dumps(memo.model_dump(), indent=2) + "\n"
        if args.format == "json"
        else render_markdown(memo)
    )
    if args.out:
        args.out.write_text(output, "utf-8")
        print(f"memo written to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(output)
    return 0
