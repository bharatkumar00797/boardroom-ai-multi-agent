"""Deterministic offline model used by default, in demos and in tests.

It reads the JSON brief appended to every agent prompt and answers the way a
disciplined executive with the role's priorities would: utility scoring over the
option attributes in the opening round, then partial convergence toward well-argued
peer positions (with explicit critiques) in debate rounds. Same input, same output.
"""

from __future__ import annotations

import json
from typing import Any

from boardroom.agents.prompts import BRIEF_MARKER
from boardroom.llm.base import Completion, LLMError, LLMProvider, Message, Usage
from boardroom.models import ATTRIBUTE_LABELS

PERSUASION = 0.3
"""How far (0-1) an agent moves toward the panel mean per debate round."""


def utility(attributes: dict[str, float], priorities: dict[str, float]) -> float:
    total = sum(abs(w) for w in priorities.values()) or 1.0
    raw = sum(w * (attributes.get(a, 5.0) - 5.0) for a, w in priorities.items()) / total
    return round(max(0.0, min(10.0, 5.0 + raw)), 2)


def _drivers(attributes: dict[str, float], priorities: dict[str, float]) -> tuple[str, str]:
    contributions = {a: w * (attributes.get(a, 5.0) - 5.0) for a, w in priorities.items()}
    best = max(contributions, key=lambda a: (contributions[a], a))
    worst = min(contributions, key=lambda a: (contributions[a], a))
    return best, worst


def _describe(attr: str, value: float) -> str:
    level = "high" if value >= 7 else "low" if value <= 3 else "moderate"
    return f"{level} {ATTRIBUTE_LABELS[attr]} ({value:g}/10)"


class MockProvider(LLMProvider):
    name = "mock"

    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> Completion:
        brief = self._brief(messages)
        reply = self._opening(brief) if brief["task"] == "opening" else self._critique(brief)
        content = json.dumps(reply, sort_keys=True)
        prompt_chars = sum(len(m.content) for m in messages)
        return Completion(
            content=content,
            model="mock-boardroom-1",
            usage=Usage(prompt_tokens=prompt_chars // 4, completion_tokens=len(content) // 4),
        )

    @staticmethod
    def _brief(messages: list[Message]) -> dict[str, Any]:
        for message in reversed(messages):
            if message.role != "user":
                continue
            idx = message.content.rfind(BRIEF_MARKER)
            if idx != -1:
                try:
                    data = json.loads(message.content[idx + len(BRIEF_MARKER) :].strip())
                except json.JSONDecodeError as exc:
                    raise LLMError("mock provider could not parse the brief") from exc
                if isinstance(data, dict) and data.get("task") in {"opening", "critique"}:
                    return data
        raise LLMError("mock provider needs a BRIEF_JSON block in the user message")

    def _opening(self, brief: dict[str, Any]) -> dict[str, Any]:
        role = brief["role"]
        priorities: dict[str, float] = role["priorities"]
        options: dict[str, dict[str, float]] = brief["options"]
        scores = {oid: utility(attrs, priorities) for oid, attrs in options.items()}
        rationale: dict[str, str] = {}
        for oid, attrs in options.items():
            best, worst = _drivers(attrs, priorities)
            rationale[oid] = (
                f"Strongest point is {_describe(best, attrs[best])}; "
                f"main drawback is {_describe(worst, attrs[worst])}."
            )
        preferred = max(scores, key=lambda o: (scores[o], o))
        blockers = self._blockers(role, options)
        concerns = []
        for oid, attrs in options.items():
            if scores[oid] < 5:
                worst = _drivers(attrs, priorities)[1]
                concerns.append(f"{oid}: {_describe(worst, attrs[worst])}")
        return {
            "scores": scores,
            "rationale": rationale,
            "preferred": preferred,
            "concerns": concerns,
            "blockers": blockers,
            "critiques": [],
        }

    @staticmethod
    def _blockers(role: dict[str, Any], options: dict[str, dict[str, float]]) -> list[str]:
        if not role.get("can_block"):
            return []
        lines: dict[str, float] = role.get("red_lines", {})
        return sorted(
            oid
            for oid, attrs in options.items()
            if any(attrs.get(a, 0.0) >= limit for a, limit in lines.items())
        )

    def _critique(self, brief: dict[str, Any]) -> dict[str, Any]:
        role = brief["role"]
        priorities: dict[str, float] = role["priorities"]
        options: dict[str, dict[str, float]] = brief["options"]
        own: dict[str, float] = brief["own_scores"]
        peers: dict[str, dict[str, Any]] = brief["peers"]
        scores: dict[str, float] = {}
        rationale: dict[str, str] = {}
        for oid in options:
            peer_scores = [float(p["scores"].get(oid, own[oid])) for p in peers.values()]
            mean = sum(peer_scores) / len(peer_scores) if peer_scores else own[oid]
            new = own[oid] + PERSUASION * (mean - own[oid])
            scores[oid] = round(max(0.0, min(10.0, new)), 2)
            moved = scores[oid] - own[oid]
            if abs(moved) >= 0.25:
                direction = "raised" if moved > 0 else "lowered"
                rationale[oid] = (
                    f"{direction.capitalize()} from {own[oid]:.1f} to {scores[oid]:.1f} after the "
                    f"panel's arguments (panel mean {mean:.1f})."
                )
            else:
                rationale[oid] = f"Holding at {scores[oid]:.1f}; the debate did not change my view."
        critiques = []
        for peer_id, peer in sorted(peers.items()):
            choice = str(peer["preferred"])
            if choice not in options or own[choice] >= max(own.values()) - 0.5:
                continue
            _, worst = _drivers(options[choice], priorities)
            critiques.append(
                {
                    "target_role": peer_id,
                    "option_id": choice,
                    "point": (
                        f"{choice} carries {_describe(worst, options[choice][worst])}, "
                        "which the case for it understates."
                    ),
                }
            )
        preferred = max(scores, key=lambda o: (scores[o], o))
        return {
            "scores": scores,
            "rationale": rationale,
            "preferred": preferred,
            "concerns": [],
            "blockers": self._blockers(role, options),
            "critiques": critiques[:2],
        }
