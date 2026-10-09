"""Moderator synthesis: turns the final round into a structured decision memo."""

from __future__ import annotations

from boardroom.agents.roles import Role
from boardroom.models import ATTRIBUTE_LABELS, DecisionMemo, Position, Scenario
from boardroom.voting import confidence, tally

_RISK_ATTRS = ("technical_risk", "regulatory_risk", "cost")


def build_memo(
    scenario: Scenario,
    roles: list[Role],
    rounds: list[list[Position]],
    security_flags: list[str],
    provider: str,
) -> DecisionMemo:
    final = rounds[-1]
    ranking = tally(scenario, roles, final)
    winner = ranking[0]
    option = scenario.option(winner.option_id)
    names = {r.id: r.title for r in roles}
    conf = confidence(ranking)

    dissent = [
        f"{names[p.role_id]} prefers {p.preferred} "
        f"({p.scores[p.preferred]:.1f} vs {p.scores[winner.option_id]:.1f} "
        f"for {winner.option_id}): "
        f"{p.rationale.get(p.preferred) or 'no rationale given'}"
        for p in final
        if not p.fallback and p.preferred != winner.option_id
    ]
    risks = [
        f"{ATTRIBUTE_LABELS[a].capitalize()} is rated {option.attributes[a]:g}/10."
        for a in _RISK_ATTRS
        if option.attributes[a] >= 6
    ]
    for p in final:
        risks += [f"{names[p.role_id]}: {c}" for c in p.concerns if c.startswith(winner.option_id)]
    for r in ranking:
        if r.blocked_by:
            risks.append(
                f"{r.option_id} was blocked by {', '.join(names[b] for b in r.blocked_by)}."
            )
    conditions = [f"Respect constraint: {c}" for c in scenario.constraints]
    if option.attributes["technical_risk"] >= 6:
        conditions.append("Run a time-boxed technical pilot with clear exit criteria first.")
    if option.attributes["regulatory_risk"] >= 6:
        conditions.append("Obtain written legal / compliance sign-off before launch.")
    if option.attributes["cost"] >= 7:
        conditions.append("Release budget in stages tied to measured milestones.")
    if conf == "low":
        conditions.append("Low panel confidence: revisit with more data before committing.")
    runner_up = ranking[1] if len(ranking) > 1 else None
    next_steps = [
        f"Assign an owner for '{option.title}' and agree success metrics within one week.",
        "Share this memo with the panel and record any objections.",
    ]
    if runner_up and not runner_up.blocked_by:
        next_steps.append(f"Keep '{runner_up.title}' as the fallback if checkpoints are missed.")
    abstained = [names[p.role_id] for p in final if p.fallback]
    if abstained:
        risks.append(f"Abstained (no valid reply): {', '.join(abstained)}.")
    if winner.blocked_by:
        recommendation_note = "Every option crosses a red line; no option can be recommended as is."
    else:
        recommendation_note = (
            f"The panel recommends '{option.title}' with a weighted score of "
            f"{winner.weighted_score:.2f}/10 ({winner.votes} of {len(final)} first-choice votes, "
            f"{conf} confidence) after {len(rounds) - 1} debate round(s)."
        )
    return DecisionMemo(
        scenario_id=scenario.id,
        title=scenario.title,
        question=scenario.question,
        recommendation=winner.option_id,
        recommendation_title=option.title,
        confidence=conf,
        summary=recommendation_note,
        ranking=ranking,
        rounds=rounds,
        dissent=dissent,
        risks=risks,
        conditions=conditions,
        next_steps=next_steps,
        security_flags=security_flags,
        provider=provider,
    )


def render_markdown(memo: DecisionMemo) -> str:
    lines = [
        f"# Decision memo: {memo.title}",
        "",
        f"**Question:** {memo.question}",
        "",
        f"**Recommendation:** {memo.recommendation_title} (`{memo.recommendation}`) - "
        f"confidence **{memo.confidence}**",
        "",
        memo.summary,
        "",
        "## Ranking",
        "",
        "| Rank | Option | Weighted score | First-choice votes | Spread | Blocked by |",
        "|---:|---|---:|---:|---:|---|",
    ]
    for i, r in enumerate(memo.ranking, 1):
        blocked = ", ".join(r.blocked_by) or "-"
        lines.append(
            f"| {i} | {r.title} | {r.weighted_score:.2f} | {r.votes} | {r.spread:.2f} | {blocked} |"
        )
    lines += ["", "## Debate", ""]
    for round_positions in memo.rounds:
        label = (
            "Opening statements"
            if round_positions[0].round == 0
            else f"Round {round_positions[0].round}"
        )
        lines += [f"### {label}", ""]
        for p in round_positions:
            text = p.rationale.get(p.preferred, "")
            lines.append(
                f"- **{p.role_id}** prefers `{p.preferred}` ({p.scores[p.preferred]:.1f}). {text}"
            )
            for c in p.critiques:
                lines.append(f"  - challenges **{c.target_role}** on `{c.option_id}`: {c.point}")
            for b in p.blockers:
                lines.append(f"  - raises a blocker on `{b}`")
        lines.append("")
    for heading, items in (
        ("Dissent", memo.dissent),
        ("Risks", memo.risks),
        ("Conditions", memo.conditions),
        ("Next steps", memo.next_steps),
        ("Security flags", memo.security_flags),
    ):
        if items:
            lines += [f"## {heading}", "", *(f"- {i}" for i in items), ""]
    lines.append(f"_Generated with provider `{memo.provider}`._")
    return "\n".join(lines) + "\n"
