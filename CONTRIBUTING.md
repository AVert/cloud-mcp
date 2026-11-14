# Contributing to sweb-mcp

Thanks for taking the time to contribute. This project is an unofficial MCP server for
the SpaceWeb (sweb.ru) API; issues and pull requests are welcome.

## Development environment

```bash
git clone https://github.com/avert/sweb-mcp && cd sweb-mcp
uv sync --extra dev
uv run pre-commit install        # optional but recommended
```

Python 3.11–3.13 are supported; CI runs the full test suite on all three.

## Tests

```bash
uv run python -m pytest -q                 # full suite
uv run python -m pytest -q tests/test_spec_safety.py
```

Notes:

- Tests must not touch the network. HTTP is mocked with
  [respx](https://lundberg.github.io/respx/) and the MCP server is exercised through an
  in-memory session (`mcp.shared.memory`).
- Never add real logins, passwords or account JSON. Use the dummy values already used in
  the tests (`"u"`, `"p"`, `"a"`, `"b"`).
- Live write/destructive calls against a real account are not part of the test suite.

## Style

- [ruff](https://docs.astral.sh/ruff/) for linting and formatting, configured in
  `pyproject.toml` (line length 100, `py311` target, rules `E,F,I,UP,B`).
- ```bash
  uv run ruff check . && uv run ruff format --check .
  ```
- Keep changes focused; do not mix formatting-only churn with behaviour changes.
- Behaviour changes need a test that fails before the change and passes after it.
- Keep the safety model intact: a method's class (`read`/`write`/`destructive`/`paid`)
  must never become *less* restrictive without a note in the PR description.

## Updating the API specs

`specs/*.json` is a snapshot of the OpenRPC documents embedded in the documentation site
`https://apidoc.sweb.ru`. It is **generated** — do not hand-edit those files.

```bash
uv run python scripts/sync_specs.py --check   # report drift, write nothing
uv run python scripts/sync_specs.py           # refresh specs/
```

After a refresh:

1. Review the printed `+ method` / `- method` / `changed files` summary.
2. Check the safety classification of every new method
   (`uv run python -m pytest -q tests/test_spec_safety.py`); add manual overrides via
   `SWEB_OVERRIDES` only when the heuristics are clearly wrong.
3. Update the counts in `README.md` if the number of methods changed.
4. Commit the regenerated specs together with the code that depends on them.

If the docs site changes its bundle layout, `sync_specs.py` prints
"no OpenRPC documents found" and exits non-zero — the extractor needs an update, not a
manual spec edit.

## Commit messages and sign-off

- Write commit messages in English, imperative mood, one logical change per commit.
- Small PRs are easier to review; keep unrelated refactors out.
- This project uses the [Developer Certificate of Origin](https://developercertificate.org/)
  instead of a CLA. Sign off your commits with `git commit -s`; the `Signed-off-by`
  trailer certifies that you have the right to submit the change under the project's
  MIT license.

## Reporting bugs and security issues

- Bugs and feature requests: [issues](https://github.com/avert/sweb-mcp/issues)
  (see the templates).
- Security problems: **do not open a public issue** — follow [SECURITY.md](SECURITY.md).

By contributing you agree that your contribution is licensed under the MIT License
(see [LICENSE](LICENSE)) and that you have read the [Code of Conduct](CODE_OF_CONDUCT.md).
