# Security Policy

BoardRoom AI is an AI multi-agent system that reads untrusted business scenarios and asks LLM
agents to score options, so we take prompt-injection hardening, vote integrity and API security
seriously. The design is described in the [security model](README.md#security-model) section
of the README.

## Supported versions

| Version | Supported |
| --- | --- |
| 1.0.x | yes |
| < 1.0 | no |

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

- Use GitHub's private vulnerability reporting:
  **Security → Report a vulnerability** on
  <https://github.com/bharatkumar00797/boardroom-ai-multi-agent/security>.
- Include the affected version or commit, a description of the impact, and steps or a proof of
  concept to reproduce it.

You can expect an acknowledgement within 3 working days and a status update within 10 working
days. Once a fix is released we are happy to credit you in the changelog unless you prefer to
stay anonymous.

## Scope

In scope:

- Scenario text that escapes the `<untrusted_scenario>` fence or is treated as instructions.
- Influencing the outcome beyond one agent's clamped scores: forging vetoes from a non-blocking
  role, injecting unknown options, bypassing validation, or altering the vote arithmetic.
- Authentication or authorization bypass in the REST API: reading another caller's decisions,
  using custom scenarios or a real provider in public-demo mode.
- Bypassing rate limits, the request body cap or the debate queue bounds.
- Cross-site scripting or CSP bypass in the dashboard.
- Secrets exposed in API responses, logs or the published Docker image.

Out of scope:

- Poor or biased recommendations from a real LLM provider; the memo is decision support.
- Injection phrasings the regex tripwire does not flag, as long as validation and voting still
  bound their effect (reports with a concrete outcome change are welcome).
- Denial of service that requires more traffic than the configured rate limits allow.
- Shared public-demo ownership when `BOARDROOM_TRUST_PROXY` is unset behind a reverse proxy.
- In-memory decision loss across restarts or serverless instances (documented caveat).
- Vulnerabilities in third-party platforms (Render, Fly.io, Railway, Vercel) or dependencies
  without a demonstrated impact on BoardRoom AI.
