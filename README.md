# BoardRoom AI — Multi-Agent Business Decision Engine

An AI multi-agent system in which LLM-powered executive role agents (CFO, CTO, CMO,
Legal & Risk, Customer Advocate) debate a business decision in moderated rounds,
critique each other, vote with weighted scoring and produce a structured decision memo.

Runs fully offline by default with a deterministic mock model; switch to any
OpenAI-compatible endpoint (OpenAI, Groq, Ollama) with environment variables.

> Work in progress — full documentation coming with v1.0.0.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
boardroom scenarios
boardroom run cloud-migration            # Markdown decision memo, live debate on stderr
boardroom run market-expansion --format json --out memo.json
boardroom run my-decision.json --rounds 3 --roles cfo,cto,legal
```

## How it works (short version)

1. **Validate** the scenario (strict schema: 2-6 options, each rated 0-10 on cost,
   revenue upside, strategic fit, speed to value, technical risk, regulatory risk and
   customer value) and **scan** its free text for prompt-injection patterns.
2. **Opening round:** every executive agent independently scores each option from its
   own mandate and priorities.
3. **Debate rounds:** each agent reads its colleagues' positions, critiques the weakest
   argument and revises its scores (persuasion, not majority-following).
4. **Vote:** vote-weighted average score per option; the General Counsel can block
   options that cross a legal red line; confidence comes from the winning margin and
   panel agreement.
5. **Memo:** recommendation, ranking table, full debate transcript, dissent, risks,
   conditions, next steps and security flags.

## Development

```bash
ruff check . && ruff format --check . && mypy && pytest
```
