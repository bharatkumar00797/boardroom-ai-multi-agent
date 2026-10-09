"""Weighted scoring, plurality votes, blockers and confidence."""

from __future__ import annotations

from statistics import pstdev

from boardroom.agents.roles import Role
from boardroom.models import Confidence, OptionResult, Position, Scenario


def tally(scenario: Scenario, roles: list[Role], positions: list[Position]) -> list[OptionResult]:
    """Rank options by vote-weighted average score; blocked options sink to the bottom."""
    weight = {r.id: scenario.vote_weights.get(r.id, r.vote_weight) for r in roles}
    blockers = {r.id for r in roles if r.can_block}
    voting = [p for p in positions if not p.fallback and weight.get(p.role_id, 0) > 0]
    results: list[OptionResult] = []
    for option in scenario.options:
        scores = [(p.scores[option.id], weight[p.role_id]) for p in voting]
        total = sum(w for _, w in scores)
        avg = sum(s * w for s, w in scores) / total if total else 0.0
        results.append(
            OptionResult(
                option_id=option.id,
                title=option.title,
                weighted_score=round(avg, 2),
                votes=sum(1 for p in voting if p.preferred == option.id),
                spread=round(pstdev([s for s, _ in scores]), 2) if len(scores) > 1 else 0.0,
                blocked_by=sorted(
                    p.role_id for p in voting if p.role_id in blockers and option.id in p.blockers
                ),
            )
        )
    return sorted(
        results, key=lambda r: (bool(r.blocked_by), -r.weighted_score, -r.votes, r.option_id)
    )


def confidence(ranking: list[OptionResult]) -> Confidence:
    """High when the winner leads clearly and the panel broadly agrees on it."""
    if not ranking or ranking[0].blocked_by:
        return "low"
    margin = ranking[0].weighted_score - (ranking[1].weighted_score if len(ranking) > 1 else 0)
    spread = ranking[0].spread
    if margin >= 1.0 and spread <= 1.0:
        return "high"
    if margin >= 0.4 and spread <= 2.0:
        return "medium"
    return "low"
