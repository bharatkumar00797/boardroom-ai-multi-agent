# Contributing to BoardRoom AI

Thanks for your interest in improving BoardRoom AI. Bug reports, documentation fixes and
pull requests are all welcome.

## Development setup

Requirements: Python 3.11 to 3.13, `git`. Docker is optional (only for the container checks).

```bash
git clone https://github.com/bharatkumar00797/boardroom-ai-multi-agent.git
cd boardroom-ai-multi-agent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Everything runs offline with the default `mock` provider, so no API key is needed for
development or tests. To try a real model, copy `.env.example` to `.env` and set the
`BOARDROOM_PROVIDER` / `BOARDROOM_BASE_URL` / `BOARDROOM_API_KEY` / `BOARDROOM_MODEL` variables. Never commit `.env` or
any key.

## Checks

Run these before opening a pull request; CI runs the same commands on Python 3.11, 3.12 and 3.13.

```bash
ruff check .            # lint
ruff format .           # format (CI uses: ruff format --check .)
mypy                    # strict type checking of src/boardroom
pytest                  # full test suite, offline
```

Optional end-to-end checks:

```bash
boardroom run market-expansion --rounds 2
boardroom serve --dev                                # dashboard on http://127.0.0.1:8000
python scripts/smoke_test.py http://127.0.0.1:8000   # health + every scenario through the API
docker compose up --build                            # hardened container
```

## Guidelines

- Keep the mock provider the default: every feature must work without network access or keys.
- New code is fully typed (`mypy --strict` must pass) and comes with tests.
- The model supplies scores and arguments only; ranking, vetoes and confidence stay in code.
- Scenario text is untrusted: it must stay inside the `<untrusted_scenario>` fence and never be
  treated as instructions. New injection patterns go in `guard.py` with a test.
- Anything that touches auth, access modes, rate limiting or the body cap needs a test that
  proves the guard holds (see `tests/test_api.py`).
- Adding a scenario: put a JSON file under `src/boardroom/scenarios/<name>.json` and update
  `scripts/smoke_test.py` (`EXPECTED`) and the tests that keep it in sync.

## Commit style

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(engine): add a corrective retry for invalid replies
fix(voting): sink vetoed options below unblocked ones
docs: explain the untrusted scenario fence
test: cover the events polling cursor
ci: build and smoke-test the Docker image
chore: bump version to 1.0.0
```

Keep commits small and focused, write the subject in the imperative mood, and explain the
"why" in the body when it is not obvious. Update `CHANGELOG.md` under **Unreleased** for
user-visible changes.

## Reporting security issues

Please do not open public issues for vulnerabilities; see [SECURITY.md](SECURITY.md).
