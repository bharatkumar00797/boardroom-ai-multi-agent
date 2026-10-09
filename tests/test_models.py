from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from boardroom.models import ATTRIBUTES, Scenario


def _option(oid: str, **over: float) -> dict[str, Any]:
    attrs = dict.fromkeys(ATTRIBUTES, 5.0) | over
    return {"id": oid, "title": oid.upper(), "attributes": attrs}


def _scenario(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "s",
        "title": "T",
        "question": "Which option is best for us?",
        "options": [_option("a"), _option("b")],
    }
    return base | over


def test_valid_scenario() -> None:
    s = Scenario.model_validate(_scenario())
    assert [o.id for o in s.options] == ["a", "b"]


@pytest.mark.parametrize(
    "over",
    [
        {"options": [_option("a")]},
        {"options": [_option("a"), _option("a")]},
        {"options": [_option("a"), _option("b", cost=11)]},
        {"options": [_option("a"), _option("Bad Id")]},
        {"question": "short"},
        {"unexpected": 1},
        {"vote_weights": {"cfo": 9}},
        {"context": "x" * 6001},
        {"constraints": [" "]},
    ],
)
def test_invalid_scenarios_rejected(over: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Scenario.model_validate(_scenario(**over))


def test_missing_and_unknown_attributes_rejected() -> None:
    opt = _option("b")
    del opt["attributes"]["cost"]
    with pytest.raises(ValidationError, match="missing"):
        Scenario.model_validate(_scenario(options=[_option("a"), opt]))
    opt = _option("b", vibes=3)
    with pytest.raises(ValidationError, match="unknown"):
        Scenario.model_validate(_scenario(options=[_option("a"), opt]))
