"""Background debates with bounded concurrency and an in-memory decision store."""

from __future__ import annotations

import secrets
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from boardroom.config import Settings
from boardroom.engine import Boardroom, DebateConfig, ProgressHook
from boardroom.llm import build_provider
from boardroom.models import DecisionMemo, Position, Scenario

JobState = Literal["queued", "running", "finished", "error"]
RunFn = Callable[[Scenario, Settings, DebateConfig, ProgressHook], DecisionMemo]


def default_run(
    scenario: Scenario, settings: Settings, config: DebateConfig, on_progress: ProgressHook
) -> DecisionMemo:
    return Boardroom(build_provider(settings), config, on_progress=on_progress).run(scenario)


def _now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return "dec_" + secrets.token_hex(6)


class QueueFull(RuntimeError):
    """Too many debates are queued or running."""


@dataclass
class DecisionRecord:
    """One decision tracked by the service; events are append-only so polling is cheap."""

    id: str
    owner: str
    scenario: Scenario
    provider: str
    rounds: int
    roles: list[str]
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    state: JobState = "queued"
    memo: DecisionMemo | None = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def done(self) -> bool:
        return self.state in ("finished", "error")

    def record_event(self, stage: str, position: Position) -> None:
        with self.lock:
            self.events.append(
                {"seq": len(self.events), "stage": stage, "position": position.model_dump()}
            )

    def events_since(self, since: int) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.events[since:])


class DecisionManager:
    """Owns the worker pool and the decision records.

    ``max_active`` bounds queued + running debates (callers get :class:`QueueFull` -> 503);
    the oldest finished decisions are evicted beyond ``max_kept``. With ``inline=True`` the
    debate runs inside :meth:`submit` (serverless mode).
    """

    def __init__(
        self,
        *,
        max_workers: int = 2,
        max_active: int = 8,
        max_kept: int = 200,
        run_fn: RunFn = default_run,
        inline: bool = False,
    ) -> None:
        self.inline = inline
        self._executor = (
            None
            if inline
            else ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="debate")
        )
        self._max_active = max_active
        self._max_kept = max_kept
        self._run_fn = run_fn
        self._records: OrderedDict[str, DecisionRecord] = OrderedDict()
        self._lock = threading.Lock()

    def submit(
        self, *, owner: str, scenario: Scenario, settings: Settings, config: DebateConfig
    ) -> DecisionRecord:
        record = DecisionRecord(
            id=new_id(),
            owner=owner,
            scenario=scenario,
            provider=settings.provider,
            rounds=config.rounds,
            roles=list(config.roles or []),
        )
        with self._lock:
            if sum(1 for r in self._records.values() if not r.done) >= self._max_active:
                raise QueueFull("Too many debates in progress; try again shortly")
            self._records[record.id] = record
            self._evict_unlocked()
        if self._executor is None:
            self._execute(record, settings, config)
        else:
            self._executor.submit(self._execute, record, settings, config)
        return record

    def get(self, decision_id: str, owner: str | None) -> DecisionRecord | None:
        """Look up a decision; ``owner=None`` means the caller may see every decision."""
        with self._lock:
            record = self._records.get(decision_id)
        if record is None or (owner is not None and record.owner != owner):
            return None
        return record

    def list(self, owner: str | None, limit: int = 50) -> list[DecisionRecord]:
        with self._lock:
            records = [
                r for r in reversed(self._records.values()) if owner is None or r.owner == owner
            ]
        return records[:limit]

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for r in self._records.values() if not r.done)

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _evict_unlocked(self) -> None:
        overflow = len(self._records) - self._max_kept
        if overflow <= 0:
            return
        for rid in [rid for rid, r in self._records.items() if r.done][:overflow]:
            del self._records[rid]

    def _execute(self, record: DecisionRecord, settings: Settings, config: DebateConfig) -> None:
        with record.lock:
            record.state = "running"
            record.started_at = _now()
        try:
            memo = self._run_fn(record.scenario, settings, config, record.record_event)
        except Exception as exc:  # a crashed debate must never take down the worker
            with record.lock:
                record.state = "error"
                record.error = f"{type(exc).__name__}: {exc}"[:500]
                record.finished_at = _now()
            return
        with record.lock:
            record.memo = memo
            record.state = "finished"
            record.finished_at = _now()
