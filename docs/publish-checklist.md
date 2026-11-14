# Чеклист публикации sweb-mcp в GitHub (open source)

Статус на 14.11.2026. Чеклист относится только к **собственным** opensource-репозиториям владельца; пуши/PR в чужие проекты — по правилам этих проектов, не по этому файлу.
Легенда: `[x]` готово · `[ ]` нужно сделать · `[?]` решение владельца.

## 0. Блокеры (без них не публиковать)

- [ ] **LICENSE** — файла нет вообще. Выбрать и положить в корень.
- [?] **Правовая чистота `specs/`** — 828 КБ снапшота JS-бандла apidoc.sweb.ru (чужой сайт).
      Варианты: (а) не публиковать `specs/`, тянуть `scripts/sync_specs.py` при первом запуске
      (чисто, но MCP не работает «из коробки»); (б) публиковать с явной атрибуцией в NOTICE и
      немедленным удалением по требованию; (в) публиковать только генерируемый минимум.
      Рекомендация: (б) + раздел «Disclaimer» в README, т.к. это описание API, а не код SpaceWeb.
- [ ] **`.claude/settings.local.json`** — содержит `"defaultMode": "bypassPermissions"`.
      Не публиковать: добавить в `.gitignore` (сейчас `.claude/` не игнорируется).
- [ ] **Абсолютные личные пути в README** — `claude mcp add ... <absolute-repo-path>/...` (2 места).
      Заменить на переменную/относительный путь.
- [ ] **Нет git-репозитория** — `git init` ещё не делали (`.git` отсутствует).
- [?] **CHANGELOG.md** — по правилу проекта локального CHANGELOG не держим (история из git/Releases).
      Решить: удалить файл + ссылки на него (CLAUDE.md) или оставить как историю версий.
- [?] **Имя и владелец репо** — `github.com/<owner>/sweb-mcp`? Нужен GitHub-аккаунт/организация.
- [?] **Лицензия** — MIT (просто, совместимо с MIT-кодом sanchpet) или Apache-2.0 (патентная оговорка,
      сложнее с attribution). Рекомендация: **MIT** + расширенный NOTICE.
- [?] **Публиковать ли в PyPI** (`sweb-mcp`) — если да, нужен trusted publishing, иначе только git/GHCR.

## 1. Юридические файлы

- [ ] `LICENSE` — полный текст MIT, `Copyright (c) 2026 <владелец>`.
- [ ] `NOTICE` — сейчас 2 строки, расширить:
      - спеки: источник — документация SpaceWeb (apidoc.sweb.ru), сниппет сгенерирован нашим кодом;
      - логика извлечения спек: sanchpet/sweb-go-sdk, MIT, copyright авторов;
      - перечень runtime-зависимостей с лицензиями (mcp, httpx — MIT/BSD) и dev-зависимостей;
      - явно: «проект не аффилирован со SpaceWeb, товарные знаки принадлежат правообладателям».
- [ ] README: раздел «Disclaimer / не официальный клиент», отсутствие гарантий, соблюдение ToS и лимитов.
- [ ] (опц.) SPDX-заголовок `# SPDX-License-Identifier: MIT` в каждом `.py` — не обязателен для MIT,
      но снимает вопросы при копировании файлов по одному.
- [ ] Проверить, что нигде не заявлено партнёрство/поддержка со стороны SpaceWeb.

## 2. Git-гигиена

- [ ] `git init -b main`.
- [ ] `.gitignore` дополнить: `.claude/`, `dist/`, `build/`, `*.egg-info/`, `.ruff_cache/`,
      `.mypy_cache/`, `.coverage`, `htmlcov/`, `.DS_Store`, `.idea/`, `.vscode/`, `*.pyc`.
- [ ] `.gitattributes`: `* text=auto eol=lf`, `*.json text`, `uv.lock linguist-generated`.
- [ ] Перед первым коммитом убрать мусор: `__pycache__/`, `.pytest_cache/`, `.venv/` (сейчас в дереве есть).
- [ ] `.env` не в индексе, `.env.example` — с пустыми значениями и без реальных имён аккаунтов.
- [ ] `.env` содержит `SWEB_ACCOUNT=<account-name>` (имя клиентского аккаунта) — в репо не попадёт, но
      проверить, что имя клиента нет в документации/тестах/коммитах.
- [ ] Коммиты — с GitHub noreply-почтой (не светить личный email), без `Co-Authored-By` трейлеров.
- [ ] Скан секретов до первого push: `gitleaks detect --no-git=false` / `trufflehog filesystem .`.
- [ ] `git ls-files -s | wc -l` и `git status --ignored` — глазами проверить индекс.
- [ ] Проверить размер: `specs/` 828 КБ, `uv.lock` 157 КБ — допустимо, бинарников нет.

## 3. README и публичная документация

- [ ] Первый экран: что это, для кого, одно предложение + пример вызова (до/после).
- [ ] Бейджи: CI, license, python 3.11–3.13, (опц.) PyPI версия.
- [ ] Установка: `uvx` / `pip install` / Docker — три пути, каждый проверен на чистой машине.
- [ ] Quick start (уже добавлен) + 3–5 примеров реальных read-вызовов с ответом.
- [ ] Полная таблица env-переменных (есть) + `.env.example` (есть).
- [ ] Безопасность: read/write/destructive/paid, `confirm=true`, `SWEB_ALLOW_DESTRUCTIVE` (есть).
- [ ] Мультиаккаунт: `sweb_accounts`, `sweb_use_account`, `account="имя"` (есть).
- [ ] Подключение к клиентам: Claude Code, OpenCode, Cursor, Docker — **без абсолютных личных путей**.
- [ ] Ограничения честно: спеки — снапшот, классификация эвристическая, лимиты API не документированы.
- [ ] Troubleshooting/FAQ: `-32603`, 429, «no accounts», прокси (`trust_env=False`).
- [ ] `CONTRIBUTING.md`: как поднять dev-окружение, стиль, тесты, DCO/CLA (решить), как обновлять спеки.
- [ ] `CODE_OF_CONDUCT.md` — Contributor Covenant 2.1.
- [ ] `SECURITY.md`: куда сообщать об уязвимостях (приватно), SLA ответа, что считать уязвимостью
      (утечка кредов в логи — да).
- [ ] Ссылки на LICENSE и NOTICE из README.
- [ ] (опц.) `docs/` с архитектурой; CLAUDE.md — решить, публиковать ли внутреннюю память (переписать нейтрально).

## 4. Код и метаданные пакета

- [ ] `pyproject.toml`: добавить `license = "MIT"`, `license-files = ["LICENSE"]`, `readme = "README.md"`,
      `authors`, `keywords`, `classifiers` (Python 3.11–3.13, MCP, hosting API), `[project.urls]`
      (Homepage/Repository/Issues/Changelog).
- [ ] Проверить доступность имени `sweb-mcp` в PyPI (если публикуем).
- [ ] `ruff` (lint+format) в dev-зависимостях + конфиг в `pyproject.toml`; прогнать и починить.
- [ ] (опц.) `mypy`/`pyright` базовый режим; `py.typed` — если позиционируем как библиотеку.
- [ ] pre-commit: ruff, ruff-format, end-of-file-fixer, check-yaml/toml, detect-private-key,
      gitleaks — чтобы секреты не долетели до истории.
- [ ] `python -m build` + `twine check dist/*` — sdist/wheel ставятся и запускаются в чистом venv.
- [ ] Убедиться, что `python -m sweb_mcp` работает без `SWEB_ACCOUNTS_FILE` (понятная ошибка, не трейсбек).
- [ ] Тесты зелёные (31 passed) + покрытие ключевых модулей (config/safety/spec).
- [ ] Убрать/обезличить ссылки на внутренние правила (CLAUDE.md → CHANGELOG.md и т.п.).

## 5. GitHub-репозиторий

- [ ] Создать public-репо: `gh repo create <owner>/sweb-mcp --public --source=. --push`.
- [ ] About: описание ≤ 120 симв., topics (`mcp`, `model-context-protocol`, `spaceweb`, `sweb`, `hosting`,
      `python`, `api-client`, `claude`), homepage (если будет).
- [ ] Default branch `main`; branch protection: require PR + require CI, запрет force-push.
- [ ] `.github/workflows/ci.yml`: matrix 3.11/3.12/3.13, `pytest -q`, `ruff check`, `ruff format --check`,
      `python -m build`. Триггеры: push в main, все PR.
- [ ] `.github/workflows/codeql.yml` (Python) — еженедельно + на PR.
- [ ] `.github/dependabot.yml`: `pip` (uv.lock) и `github-actions`, weekly.
- [ ] `.github/workflows/release.yml`: по тегу `v*` — build sdist/wheel, GitHub Release, аттач артефактов.
- [ ] Шаблоны: `.github/ISSUE_TEMPLATE/bug_report.yml`, `feature_request.yml`, `PULL_REQUEST_TEMPLATE.md`.
- [ ] (опц.) `CODEOWNERS`, `FUNDING.yml`, `CITATION.cff`.
- [ ] Настройки безопасности: secret scanning + push protection, Dependabot alerts,
      private vulnerability reporting (вкл. — связка с SECURITY.md).
- [ ] Релиз `v0.1.0`: тег, release notes (перенос фактов из CHANGELOG, если его удаляем).
- [ ] (опц.) PyPI trusted publishing (OIDC, без токенов в секретах) + бейдж версии.
- [ ] (опц.) GHCR-образ `ghcr.io/<owner>/sweb-mcp`, multi-arch amd64/arm64.

## 6. Проверка «с нуля» перед публикацией

- [ ] `git clone` в `/tmp` → следовать README буквально → сервер стартует, read-вызов проходит.
- [ ] `pip install .` в чистый venv (Python 3.11 и 3.13) → `sweb-mcp` в PATH.
- [ ] `docker build .` из клона → `docker compose run --rm -T sweb-mcp` работает.
- [ ] `grep -rn -E "password\s*=\s*['\"][^'\"]{4,}"` по дереву — чисто; личные имена/пути/почты не встречаются.
- [ ] `git log --stat` — нет случайных файлов, нет `.env`, нет `accounts.json`.
- [ ] Ссылки в README резолвятся, LICENSE рендерится GitHub'ом, бейджи зелёные.
- [ ] (важно) креды, которые когда-либо попадали в локальные логи opencode, в репо не попали;
      при сомнении — сменить пароль клиентского аккаунта у SpaceWeb.

## 7. После публикации

- [ ] Включить watch на issues/security, ответить на первый фидбек.
- [ ] Зафиксировать в CLAUDE.md: репо, ветка, как выпускать релиз.
- [ ] (опц.) анонс: r/mcp, awesome-mcp-servers, Хабр.
