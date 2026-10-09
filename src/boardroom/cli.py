"""Command line interface: `boardroom scenarios` and `boardroom run`."""

from __future__ import annotations

import argparse
import json
import sys
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
    return parser


def _progress(stage: str, position: Position) -> None:
    print(
        f"[{stage}] {position.role_id:<9} prefers {position.preferred} "
        f"({position.scores[position.preferred]:.1f})",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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
