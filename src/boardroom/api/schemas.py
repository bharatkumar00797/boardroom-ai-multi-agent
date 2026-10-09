"""Request and response schemas for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from boardroom.api.jobs import JobState
from boardroom.engine import MAX_ROUNDS
from boardroom.models import DecisionMemo, Scenario


class DecisionCreate(BaseModel):
    """Either a packaged ``scenario_id`` or a full custom ``scenario`` (exactly one)."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str | None = Field(
        default=None, min_length=1, max_length=40, pattern=r"^[a-z0-9-]+$"
    )
    scenario: Scenario | None = None
    rounds: int | None = Field(default=None, ge=0, le=MAX_ROUNDS)
    roles: list[str] | None = Field(default=None, min_length=1, max_length=8)
    provider: Literal["mock", "configured"] | None = None


class EventOut(BaseModel):
    seq: int
    stage: str
    position: dict[str, Any]


class DecisionSummaryOut(BaseModel):
    id: str
    state: JobState
    scenario_id: str
    title: str
    provider: str
    rounds: int
    recommendation: str | None = None
    confidence: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class DecisionDetailOut(DecisionSummaryOut):
    started_at: datetime | None = None
    error: str | None = None
    event_count: int = 0
    memo: DecisionMemo | None = None


class DecisionCreatedOut(DecisionDetailOut):
    events: list[EventOut] = Field(default_factory=list)


class DecisionListOut(BaseModel):
    decisions: list[DecisionSummaryOut]


class EventsOut(BaseModel):
    id: str
    state: JobState
    done: bool
    next_cursor: int
    events: list[EventOut]


class ScenarioOut(BaseModel):
    id: str
    title: str
    question: str
    options: list[dict[str, str]]


class ScenarioListOut(BaseModel):
    scenarios: list[ScenarioOut]


class RoleOut(BaseModel):
    id: str
    name: str
    title: str
    mandate: str
    vote_weight: float
    can_block: bool
    priorities: dict[str, float]


class RoleListOut(BaseModel):
    roles: list[RoleOut]


class ConfigOut(BaseModel):
    version: str
    auth_required: bool
    access_mode: str
    authenticated: bool
    custom_scenarios_allowed: bool
    providers: list[str]
    default_provider: str
    default_rounds: int
    max_rounds: int
    sync_runs: bool
    scenarios: list[str]


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    active_debates: int
