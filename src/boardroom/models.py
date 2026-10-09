"""Validated domain models: scenarios in, positions/votes/memo out."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ATTRIBUTES: tuple[str, ...] = (
    "cost",
    "revenue_upside",
    "strategic_fit",
    "time_to_value",
    "technical_risk",
    "regulatory_risk",
    "customer_value",
)
"""Option attributes, each rated 0-10 (higher = more of that quality, e.g. higher cost)."""

ATTRIBUTE_LABELS: dict[str, str] = {
    "cost": "cost",
    "revenue_upside": "revenue upside",
    "strategic_fit": "strategic fit",
    "time_to_value": "speed to value",
    "technical_risk": "technical risk",
    "regulatory_risk": "regulatory / legal risk",
    "customer_value": "customer value",
}

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Option(_Strict):
    id: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    attributes: dict[str, float]

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not _ID.match(value):
            raise ValueError("option id must be lowercase letters, digits and dashes")
        return value

    @field_validator("attributes")
    @classmethod
    def _check_attributes(cls, value: dict[str, float]) -> dict[str, float]:
        unknown = set(value) - set(ATTRIBUTES)
        if unknown:
            raise ValueError(f"unknown attributes: {sorted(unknown)}")
        missing = set(ATTRIBUTES) - set(value)
        if missing:
            raise ValueError(f"missing attributes: {sorted(missing)}")
        for name, rating in value.items():
            if not 0 <= rating <= 10:
                raise ValueError(f"attribute {name} must be between 0 and 10")
        return {name: float(value[name]) for name in ATTRIBUTES}


class Scenario(_Strict):
    id: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=160)
    question: str = Field(min_length=10, max_length=1000)
    context: str = Field(default="", max_length=6000)
    constraints: list[str] = Field(default_factory=list, max_length=12)
    options: list[Option] = Field(min_length=2, max_length=6)
    vote_weights: dict[str, float] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not _ID.match(value):
            raise ValueError("scenario id must be lowercase letters, digits and dashes")
        return value

    @field_validator("constraints")
    @classmethod
    def _check_constraints(cls, value: list[str]) -> list[str]:
        for item in value:
            if not item.strip() or len(item) > 400:
                raise ValueError("constraints must be non-empty and at most 400 characters")
        return value

    @field_validator("vote_weights")
    @classmethod
    def _check_weights(cls, value: dict[str, float]) -> dict[str, float]:
        for role, weight in value.items():
            if not 0 <= weight <= 5:
                raise ValueError(f"vote weight for {role} must be between 0 and 5")
        return value

    @model_validator(mode="after")
    def _unique_options(self) -> Scenario:
        ids = [o.id for o in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError("option ids must be unique")
        return self

    def option(self, option_id: str) -> Option:
        for option in self.options:
            if option.id == option_id:
                return option
        raise KeyError(option_id)


class Critique(BaseModel):
    target_role: str
    option_id: str
    point: str


class Position(BaseModel):
    """One agent's stance on every option in a given round."""

    role_id: str
    round: int
    scores: dict[str, float]
    rationale: dict[str, str]
    preferred: str
    concerns: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    critiques: list[Critique] = Field(default_factory=list)
    fallback: bool = False


class OptionResult(BaseModel):
    option_id: str
    title: str
    weighted_score: float
    votes: int
    spread: float
    blocked_by: list[str] = Field(default_factory=list)


Confidence = Literal["high", "medium", "low"]


class DecisionMemo(BaseModel):
    scenario_id: str
    title: str
    question: str
    recommendation: str
    recommendation_title: str
    confidence: Confidence
    summary: str
    ranking: list[OptionResult]
    rounds: list[list[Position]]
    dissent: list[str]
    risks: list[str]
    conditions: list[str]
    next_steps: list[str]
    security_flags: list[str] = Field(default_factory=list)
    provider: str = "mock"
