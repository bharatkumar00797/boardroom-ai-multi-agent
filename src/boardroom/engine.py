"""Moderator / orchestrator: runs the opening round, debate rounds and the final vote."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from boardroom.agents.prompts import critique_prompt, opening_prompt, system_prompt
from boardroom.agents.roles import Role, get_roles
from boardroom.guard import clean_model_text, scan_scenario, scan_text
from boardroom.llm.base import LLMError, LLMProvider, Message
from boardroom.memo import build_memo
from boardroom.models import Critique, DecisionMemo, Position, Scenario

MAX_ROUNDS = 5
ProgressHook = Callable[[str, Position], None]


@dataclass
class DebateConfig:
    rounds: int = 2
    roles: list[str] | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.rounds <= MAX_ROUNDS:
            raise ValueError(f"rounds must be between 0 and {MAX_ROUNDS}")


_JSON_OBJECT = re.compile(r"\{.*\}", re.S)


def parse_reply(text: str) -> dict[str, Any]:
    """Extract the first JSON object from a model reply (tolerates code fences / prose)."""
    match = _JSON_OBJECT.search(text)
    if not match:
        raise ValueError("no JSON object in reply")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    return data


def to_position(
    data: dict[str, Any], role: Role, scenario: Scenario, round_no: int, peers: set[str]
) -> Position:
    """Validate a model reply against the scenario; unknown ids and bad scores are rejected."""
    option_ids = [o.id for o in scenario.options]
    raw_scores = data.get("scores")
    if not isinstance(raw_scores, dict):
        raise ValueError("scores must be an object")
    scores: dict[str, float] = {}
    for oid in option_ids:
        value = raw_scores.get(oid)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"missing or non-numeric score for {oid}")
        scores[oid] = round(max(0.0, min(10.0, float(value))), 2)
    raw_rationale = data.get("rationale") if isinstance(data.get("rationale"), dict) else {}
    assert isinstance(raw_rationale, dict)
    rationale = {oid: clean_model_text(raw_rationale.get(oid, "")) for oid in option_ids}
    preferred = data.get("preferred")
    if preferred not in option_ids:
        preferred = max(scores, key=lambda o: (scores[o], o))
    concerns = [clean_model_text(c, 300) for c in _list(data.get("concerns"))][:6]
    blockers = (
        sorted({str(b) for b in _list(data.get("blockers")) if b in option_ids})
        if role.can_block
        else []
    )
    critiques = []
    for item in _list(data.get("critiques"))[:3]:
        if (
            isinstance(item, dict)
            and item.get("target_role") in peers
            and item.get("option_id") in option_ids
        ):
            critiques.append(
                Critique(
                    target_role=str(item["target_role"]),
                    option_id=str(item["option_id"]),
                    point=clean_model_text(item.get("point", ""), 300),
                )
            )
    for text in [*rationale.values(), *concerns, *(c.point for c in critiques)]:
        if scan_text(text):
            concerns.append("reply contained instruction-like text; it was kept as data only")
            break
    return Position(
        role_id=role.id,
        round=round_no,
        scores=scores,
        rationale=rationale,
        preferred=str(preferred),
        concerns=concerns,
        blockers=blockers,
        critiques=critiques,
    )


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _abstain(role: Role, scenario: Scenario, round_no: int, reason: str) -> Position:
    return Position(
        role_id=role.id,
        round=round_no,
        scores={o.id: 5.0 for o in scenario.options},
        rationale={o.id: "" for o in scenario.options},
        preferred=scenario.options[0].id,
        concerns=[f"abstained: {reason}"],
        fallback=True,
    )


class Boardroom:
    """Runs a structured multi-agent debate and returns a decision memo."""

    def __init__(
        self,
        provider: LLMProvider,
        config: DebateConfig | None = None,
        on_progress: ProgressHook | None = None,
    ) -> None:
        self.provider = provider
        self.config = config or DebateConfig()
        self.roles = get_roles(self.config.roles)
        self.on_progress = on_progress

    def _ask(self, role: Role, scenario: Scenario, prompt: str, round_no: int) -> Position:
        messages = [Message("system", system_prompt(role)), Message("user", prompt)]
        peers = {r.id for r in self.roles if r.id != role.id}
        last_error = "no reply"
        for _attempt in range(2):
            try:
                reply = self.provider.complete(messages).content
                return to_position(parse_reply(reply), role, scenario, round_no, peers)
            except LLMError as exc:
                return _abstain(role, scenario, round_no, f"provider error ({exc})"[:200])
            except (ValueError, TypeError) as exc:
                last_error = str(exc)[:200]
                messages += [
                    Message("assistant", reply[:2000]),
                    Message(
                        "user", f"Invalid reply ({last_error}). Reply with the JSON object only."
                    ),
                ]
        return _abstain(role, scenario, round_no, f"invalid reply ({last_error})")

    def _emit(self, stage: str, position: Position) -> None:
        if self.on_progress:
            self.on_progress(stage, position)

    def run(self, scenario: Scenario) -> DecisionMemo:
        flags = scan_scenario(scenario)
        rounds: list[list[Position]] = []
        opening = []
        for role in self.roles:
            position = self._ask(role, scenario, opening_prompt(role, scenario), 0)
            opening.append(position)
            self._emit("opening", position)
        rounds.append(opening)
        for round_no in range(1, self.config.rounds + 1):
            previous = {p.role_id: p for p in rounds[-1]}
            current = []
            for role in self.roles:
                own = previous[role.id]
                peers = [p for rid, p in previous.items() if rid != role.id and not p.fallback]
                if own.fallback or not peers:
                    position = own.model_copy(update={"round": round_no})
                else:
                    prompt = critique_prompt(role, scenario, own, peers, round_no)
                    position = self._ask(role, scenario, prompt, round_no)
                current.append(position)
                self._emit(f"round {round_no}", position)
            rounds.append(current)
        return build_memo(scenario, self.roles, rounds, flags, self.provider.name)
