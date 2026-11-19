# Бэклог

Идеи и отложенные работы. Порядок не гарантирован; попадание в релиз решает владелец.

## Ближайшие

- [ ] **S3 API для EC2-ключа** — ключ уже валиден по FTP (`ftp.<pool>.storage.selcloud.ru`,
  ru-1/ru-7), но S3-гейты (`s3.<pool>.storage.selcloud.ru`) пока отвечают
  `InvalidAccessKeyId`. Периодически прогонять `python scripts/selectel_auth.py --check`;
  когда синкнётся — убрать FTP-фолбэк из проверки в чистую SigV4-пробу и добавить тест.
- [ ] **Миграция на mcp 2.x** — тесты сидят на `mcp.shared.memory.create_connected_server_and_client_session`,
  который удалён в 2.x, поэтому зависимость запинена `mcp>=1.2,<2` (Dependabot-PR #3 закрыт).
  Перевести тесты на новый API сессий, поднять потолок зависимости.

## По решению владельца

- [ ] **PyPI** — trusted publishing (OIDC) + pending publisher на PyPI; до решения релизы
  только через git/теги.
- [ ] **Docker/GHCR-образ** — multi-arch по тегу `v*` (как в sweb-mcp); для stdio-сервера
  не обязателен.
- [ ] **Анонс** — r/mcp, awesome-mcp-servers, Хабр.

## Опциональная гигиена

- [ ] `pre-commit` (ruff, ruff-format, end-of-file-fixer, detect-private-key, gitleaks).
- [ ] `mypy`/`pyright` базовый режим.
- [ ] `CODEOWNERS` / `FUNDING.yml` / `CITATION.cff`.
