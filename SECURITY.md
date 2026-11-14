# Security Policy

## Supported versions

The project is at `0.x`; only the latest release / `main` receives fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

- Preferred: GitHub private vulnerability reporting —
  <https://github.com/avert/sweb-mcp/security/advisories/new>
  (Security → Advisories → "Report a vulnerability").
- Alternative: contact the maintainer [@avert](https://github.com/avert) privately.

Include: affected version/commit, steps to reproduce, what an attacker gains, and any
suggested fix. If credentials are involved, **rotate them first** and send only redacted
values.

## What counts as a vulnerability

- Leakage of credentials, tokens or account data into logs, error messages, MCP tool
  output, tracebacks or crash dumps.
- Bypass of the safety model: a non-read method executed without
  `SWEB_READONLY=0` / `SWEB_ALLOW_DESTRUCTIVE=1` / `confirm=true`, or a method
  misclassified into a less restrictive class in a way that allows an unintended write.
- Credential or token exfiltration to a host other than the configured `SWEB_API_URL`.
- Injection through tool arguments that reaches the HTTP layer (header/URL injection,
  SSRF through `SWEB_API_URL`).
- Supply-chain issues in the build or release artifacts.

Not vulnerabilities (by design, but still worth an issue if they surprise you):

- The server refuses operations because of the default hardening (`SWEB_READONLY=1`) —
  that is intended behaviour.
- Rate limiting / API `429` responses — tuning advice belongs in a normal issue.
- The spec snapshot being out of date with the live API docs.

## Response

- Acknowledgement within ~3 business days.
- Triage and a plan (or a request for more information) within ~10 business days.
- A fix released as soon as practical; the advisory is published together with the fix,
  with credit to the reporter unless you prefer to stay anonymous.

## Scope of this project

This project is an unofficial client. Problems inside SpaceWeb's own service (server-side
bugs, account compromise, billing) must be reported to SpaceWeb, not here.
