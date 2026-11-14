# sweb-mcp

MCP (stdio, Python, low-level `mcp.server.Server`, mcp<2) для API SpaceWeb. Без package.json.

## Архитектура (`src/sweb_mcp/`)
- `config.py` — Settings из env (`SWEB_*`, см. `.env.example`). Никаких хардкодов кроме публичного API URL по умолчанию. Единственный источник учёток — `SWEB_ACCOUNTS_FILE` (JSON), аккаунт по умолчанию — `SWEB_ACCOUNT`; `Settings.account(name)`.
- `client.py` — JSON-RPC клиент: `getToken` на `/notAuthorized/`, Bearer, перелогин при коде `-32603`, `extendedResult.code==0` → ошибка; троттлинг (semaphore + min interval) и повторы (429 всегда, 502/503/504/сеть только для read) → README#FAQ. `trust_env=False` (мимо прокси).
- `spec.py` — читает `specs/*.json` (OpenRPC), резолвит `$ref`, строит inputSchema; дубли (path, method) отбрасываются (276 уникальных из 279).
- `safety.py` — классы read/write/destructive/paid + `authorize()`. Параметр `confirm` добавляется в схему всех не-read tools.
- `server.py` — tools `<path_с_подчёркиваниями>_<method>` + `sweb_list_methods/describe/call`.

## Грабли
- Спеки — снапшот JS-бандла apidoc.sweb.ru, не официальный артефакт; обновлять `scripts/sync_specs.py`, после — пересмотреть классификацию новых методов.
- В спеках нет read/write флагов — классификация эвристическая (тест `test_classify`).
- Живые write/destructive вызовы без явного разрешения владельца не гонять.

Тесты: `uv run --extra dev python -m pytest -q`. История → GitHub Releases (`.github/release-notes/`).
Пакет: `specs/` входит в wheel (`force-include`), `DEFAULT_SPECS_DIR` — package-relative при установке.
Публичный репозиторий: https://github.com/avert/sweb-mcp, ветка `main`, лицензия MIT.
Публикация в GitHub/OSS — только для собственных opensource-репозиториев (не для пушей в чужие проекты) → `docs/publish-checklist.md`.
Репозиторий: https://github.com/AVert/sweb-mcp (public, MIT, ветка `main`). Релиз: `git tag -a vX.Y.Z -m ...` + `git push origin vX.Y.Z` → `gh release create vX.Y.Z --notes-file .github/release-notes/vX.Y.Z.md`; тег `v*` собирает GHCR-образ `ghcr.io/avert/sweb-mcp`. Ветка защищена (require PR + CI-чеки), владелец пушит напрямую через `enforce_admins=false`.
