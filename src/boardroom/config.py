"""Runtime configuration loaded from environment variables (secrets only ever come from env)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean (true/false), got {raw!r}")


@dataclass(frozen=True)
class Settings:
    provider: str = "mock"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    rounds: int = 2

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            provider=os.getenv("BOARDROOM_PROVIDER", "mock").strip().lower(),
            base_url=os.getenv("BOARDROOM_BASE_URL", cls.base_url),
            api_key=os.getenv("BOARDROOM_API_KEY", ""),
            model=os.getenv("BOARDROOM_MODEL", cls.model),
            rounds=env_int("BOARDROOM_ROUNDS", cls.rounds),
        )
