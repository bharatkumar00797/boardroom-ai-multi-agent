from __future__ import annotations

import pytest

from boardroom.models import Scenario
from boardroom.scenario import load_packaged


@pytest.fixture
def scenario() -> Scenario:
    return load_packaged("cloud-migration")
