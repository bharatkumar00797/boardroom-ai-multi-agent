from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from boardroom.cli import main
from boardroom.config import Settings
from boardroom.engine import Boardroom
from boardroom.llm import MockProvider, OpenAICompatibleProvider, build_provider
from boardroom.llm.base import LLMError, Message
from boardroom.memo import render_markdown
from boardroom.scenario import load_packaged


def test_cli_scenarios(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scenarios"]) == 0
    assert "cloud-migration" in capsys.readouterr().out


def test_cli_run_markdown_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "market-expansion", "--quiet"]) == 0
    assert "# Decision memo" in capsys.readouterr().out
    out = tmp_path / "memo.json"
    assert main(["run", "cloud-migration", "--format", "json", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["recommendation"] == "phased-replatform"


def test_cli_run_from_file(tmp_path: Path) -> None:
    data = load_packaged("cloud-migration").model_dump()
    data["id"] = "custom"
    path = tmp_path / "custom.json"
    path.write_text(json.dumps(data))
    assert main(["run", str(path), "--quiet", "--rounds", "1"]) == 0


def test_cli_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "nope", "--quiet"]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text('{"id": "x"}')
    assert main(["run", str(bad), "--quiet"]) == 2
    assert main(["run", "cloud-migration", "--rounds", "9"]) == 2
    assert "error:" in capsys.readouterr().err


def test_markdown_memo_sections() -> None:
    memo = Boardroom(MockProvider()).run(load_packaged("ai-support-build-vs-buy"))
    text = render_markdown(memo)
    for heading in ("## Ranking", "## Debate", "## Conditions", "## Security flags"):
        assert heading in text


def test_build_provider() -> None:
    assert isinstance(build_provider(Settings()), MockProvider)
    assert isinstance(build_provider(Settings(provider="groq")), OpenAICompatibleProvider)
    with pytest.raises(ValueError):
        build_provider(Settings(provider="other"))


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOARDROOM_PROVIDER", " OpenAI ")
    monkeypatch.setenv("BOARDROOM_ROUNDS", "3")
    s = Settings.from_env()
    assert (s.provider, s.rounds) == ("openai", 3)
    monkeypatch.setenv("BOARDROOM_ROUNDS", "x")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_mock_requires_brief() -> None:
    with pytest.raises(LLMError):
        MockProvider().complete([Message("user", "hello")])


def test_openai_compatible_provider() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(base_url="https://x/v1", model="m", client=client)
    assert provider.complete([Message("user", "hi")]).content == "{}"
    assert seen[0].url.path == "/v1/chat/completions"

    failing = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    provider = OpenAICompatibleProvider(base_url="https://x/v1", model="m", client=failing)
    with pytest.raises(LLMError):
        provider.complete([Message("user", "hi")])
    with pytest.raises(ValueError):
        OpenAICompatibleProvider(base_url="ftp://x", model="m")
