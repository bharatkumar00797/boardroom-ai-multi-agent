# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-10-09

First stable release.

### Added

- Multi-agent decision engine: five AI executive agents (CFO, CTO, CMO, General Counsel & CRO,
  Head of Customer Success) with signed priorities and vote weights debate a decision in an
  opening round plus 0-5 critique rounds.
- Moderator with tolerant JSON reply parsing, validation and clamping, one corrective retry,
  then abstention (excluded from the vote and reported as a risk).
- Deterministic voting: vote-weighted averages, first-choice votes, panel spread, legal vetoes
  that sink blocked options, and high / medium / low confidence.
- Decision memo (recommendation, ranking, transcript, dissent, risks, conditions, next steps,
  security flags) as Markdown or JSON.
- Prompt-injection guard: pattern scan surfaced as `security_flags`, `<untrusted_scenario>`
  fencing with delimiter look-alikes defanged, model output cleaning.
- LLM providers: deterministic offline `mock` (default) and an OpenAI-compatible client
  (OpenAI, Groq, Ollama) with retries.
- Three packaged scenarios: `cloud-migration`, `market-expansion`, `ai-support-build-vs-buy`.
- `boardroom scenarios | run | serve` CLI.
- FastAPI service: sync or background debates, event polling cursor, Markdown memo download,
  scenarios / roles / config endpoints, OpenAPI docs and `/healthz`.
- Access modes `api-key`, `dev` and `public-demo`; constant-time API-key checks, per-client
  ownership, sliding-window rate limits, bounded queue, 64 KB body cap, strict CSP and security
  headers, opt-in CORS, right-most `X-Forwarded-For` behind a trusted proxy.
- Static web dashboard: scenario picker and custom JSON, live debate transcript, ranking chart,
  memo view with copy/download, history and `#decision=` deep links.
- Multi-stage non-root Dockerfile, hardened docker compose, Render, Fly.io, Railway and Vercel
  configs, stdlib smoke-test script and Docker CI job.
- Full README, screenshots, CONTRIBUTING and SECURITY policy.

[Unreleased]: https://github.com/bharatkumar00797/boardroom-ai-multi-agent/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/bharatkumar00797/boardroom-ai-multi-agent/releases/tag/v1.0.0
