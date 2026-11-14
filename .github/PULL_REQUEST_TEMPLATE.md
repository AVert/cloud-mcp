## What and why

<!-- Describe the change and the problem it solves. -->

## Checklist

- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] `uv run python -m pytest -q` passes (all tests)
- [ ] Behaviour change is covered by a test (or the PR explains why no test is needed)
- [ ] No credentials, account files, tokens or personal data in the diff or logs
- [ ] `specs/*.json` only changed via `scripts/sync_specs.py` (never hand-edited)
- [ ] Documentation updated (README / CONTRIBUTING / docstrings) when behaviour or config changed

## Notes for reviewers

<!-- Anything non-obvious: safety classification changes, API quirks, retries. -->
