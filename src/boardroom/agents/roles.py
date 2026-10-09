"""The boardroom panel: each role has a mandate, priorities and a vote weight."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Role:
    id: str
    name: str
    title: str
    mandate: str
    priorities: dict[str, float]
    """Attribute weights; negative means the role dislikes more of that attribute."""
    vote_weight: float = 1.0
    can_block: bool = False
    """Whether this role may raise blockers that disqualify an option."""
    red_lines: dict[str, float] = field(default_factory=dict)
    """Attribute thresholds at or above which this role raises a blocker."""


DEFAULT_ROLES: tuple[Role, ...] = (
    Role(
        id="cfo",
        name="Priya Raman",
        title="Chief Financial Officer",
        mandate="Protect cash, margins and return on investment; insist on payback discipline.",
        priorities={
            "cost": -1.0,
            "revenue_upside": 0.9,
            "time_to_value": 0.5,
            "technical_risk": -0.3,
        },
        vote_weight=1.2,
    ),
    Role(
        id="cto",
        name="Arjun Mehta",
        title="Chief Technology Officer",
        mandate="Keep the platform reliable, scalable and maintainable; avoid technical dead ends.",
        priorities={
            "technical_risk": -1.0,
            "strategic_fit": 0.8,
            "time_to_value": 0.4,
            "cost": -0.3,
        },
        vote_weight=1.1,
    ),
    Role(
        id="cmo",
        name="Sara Kapoor",
        title="Chief Marketing Officer",
        mandate="Grow the market, the brand and revenue; move before competitors do.",
        priorities={
            "revenue_upside": 1.0,
            "time_to_value": 0.8,
            "customer_value": 0.6,
            "strategic_fit": 0.3,
        },
        vote_weight=1.0,
    ),
    Role(
        id="legal",
        name="Vikram Iyer",
        title="General Counsel & Chief Risk Officer",
        mandate=(
            "Keep the company compliant and its downside bounded; "
            "flag anything that crosses a legal red line."
        ),
        priorities={"regulatory_risk": -1.0, "technical_risk": -0.4, "customer_value": 0.3},
        vote_weight=1.0,
        can_block=True,
        red_lines={"regulatory_risk": 8.0},
    ),
    Role(
        id="customer",
        name="Neha Joshi",
        title="Head of Customer Success",
        mandate="Represent the customer: value delivered, trust, and disruption to existing users.",
        priorities={
            "customer_value": 1.0,
            "technical_risk": -0.5,
            "regulatory_risk": -0.3,
            "time_to_value": 0.3,
        },
        vote_weight=1.0,
    ),
)


def get_roles(ids: list[str] | None = None) -> list[Role]:
    """Return the panel, optionally restricted to ``ids`` (order preserved)."""
    if not ids:
        return list(DEFAULT_ROLES)
    by_id = {r.id: r for r in DEFAULT_ROLES}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise ValueError(f"unknown roles: {unknown} (available: {sorted(by_id)})")
    if len(set(ids)) < 2:
        raise ValueError("a debate needs at least two distinct roles")
    return [by_id[i] for i in dict.fromkeys(ids)]
