"""Prompt-injection guarding for user-supplied scenario text and model replies.

Scenario text is untrusted: it is scanned for instruction-like patterns, flagged in the
memo, and always wrapped in delimiters that the agents are told to treat as data only.
"""

from __future__ import annotations

import re

from boardroom.models import Scenario

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override-instructions",
        re.compile(
            r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|all)\b.{0,30}\b(instructions?|rules|prompts?)",
            re.I | re.S,
        ),
    ),
    (
        "role-hijack",
        re.compile(
            r"\byou are now\b|\bact as (the )?(system|admin|developer)\b|\bnew instructions\b", re.I
        ),
    ),
    (
        "vote-manipulation",
        re.compile(
            r"\b(always|must|only)\b.{0,30}\b(vote|recommend|score|choose)\b.{0,40}\b(for|option|10)\b",
            re.I | re.S,
        ),
    ),
    (
        "prompt-exfiltration",
        re.compile(
            r"\b(reveal|print|show|repeat)\b.{0,30}\b(system prompt|instructions|api key|secret)",
            re.I | re.S,
        ),
    ),
    ("fake-delimiter", re.compile(r"</?\s*(untrusted|system|assistant)[^>]*>", re.I)),
)

OPEN_TAG = "<untrusted_scenario>"
CLOSE_TAG = "</untrusted_scenario>"


def scan_text(text: str) -> list[str]:
    """Return the names of injection patterns found in ``text``."""
    return [name for name, pattern in _PATTERNS if pattern.search(text)]


def scan_scenario(scenario: Scenario) -> list[str]:
    """Return human-readable findings for every suspicious field in the scenario."""
    fields: list[tuple[str, str]] = [
        ("title", scenario.title),
        ("question", scenario.question),
        ("context", scenario.context),
    ]
    fields += [(f"constraints[{i}]", c) for i, c in enumerate(scenario.constraints)]
    for option in scenario.options:
        fields.append((f"option {option.id} title", option.title))
        fields.append((f"option {option.id} description", option.description))
    findings: list[str] = []
    for where, text in fields:
        for name in scan_text(text):
            findings.append(f"{name} pattern in {where} (treated as data, not instructions)")
    return findings


def neutralize(text: str) -> str:
    """Defang delimiter look-alikes so scenario text cannot close the data block."""
    return re.sub(r"<(/?)\s*(untrusted|system|assistant)", r"[\1\2", text, flags=re.I)


def wrap_untrusted(text: str) -> str:
    return f"{OPEN_TAG}\n{neutralize(text)}\n{CLOSE_TAG}"


def clean_model_text(text: str, limit: int = 600) -> str:
    """Normalise free text coming back from a model before it reaches the memo."""
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]
