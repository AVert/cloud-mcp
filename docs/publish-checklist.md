# Чеклист публикации sweb-mcp в GitHub (open source)

Статус на 14.11.2026: **опубликовано** — https://github.com/AVert/sweb-mcp (public, MIT,
релиз v0.1.0, GHCR-образ, branch protection, secret scanning). Чеклист относится только к **собственным**
opensource-репозиториям владельца; пуши/PR в чужие проекты — по правилам этих проектов, не по этому файлу.
Легенда: `[x]` готово · `[ ]` нужно сделать · `[?]` решение владельца.

## 0. Блокеры (без них не публиковать)

- [x] **LICENSE** — MIT, `Copyright (c) 2026 Alexey Vertinsky (@avert)`.
- [x] **Правовая чистота `specs/`** — вариант (б): публикуется с атрибуцией в `NOTICE`
      (происхождение: снапшот документации apidoc.sweb.ru, извлечение `scripts/sync_specs.py`,
      логика портирована из `sanchpet/sweb-go-sdk`, MIT) и разделом Disclaimer в README.
- [x] **`.claude/settings.local.json`** — `.claude/` в `.gitignore`, в индекс не попадает.
- [x] **Абсолютные личные пути в README** — заменены на `$PWD`/`/path/to/sweb-mcp`.
- [x] **Нет git-репозитория** — `git init -b main`, baseline-коммит.
- [x] **CHANGELOG.md** — удалён; содержимое перенесено в `.github/release-notes/v0.1.0.md`,
      ссылки в CLAUDE.md/README убраны (история — GitHub Releases).
- [x] **Имя и владелец репо** — `github.com/avert/sweb-mcp` (плейсхолдеры `OWNER` заменены).
- [x] **Лицензия** — MIT + расширенный NOTICE.
- [-] **Публиковать ли в PyPI** — отложено (владелец, 14.11.2026): релиз только git/GHCR.
      `pyproject.toml` к публикации готов (`build` + `twine check` проходят).

## 1. Юридические файлы

- [x] `LICENSE` — полный текст MIT, `Copyright (c) 2026 Alexey Vertinsky (@avert)`.
- [x] `NOTICE` — источник и правовой статус спек, sanchpet/sweb-go-sdk (MIT), runtime- и
      dev-зависимости с лицензиями, заявление о неаффилированности и товарных знаках.
- [x] README: раздел «Лицензия и disclaimer», отсутствие гарантий, соблюдение ToS и лимитов.
- [ ] (опц.) SPDX-заголовок `# SPDX-License-Identifier: MIT` в каждом `.py` — не обязателен
      для MIT, не делали.
- [x] Проверено: нигде не заявлено партнёрство/поддержка со стороны SpaceWeb.

## 2. Git-гигиена

- [x] `git init -b main`.
- [x] `.gitignore` дополнен: `.claude/`, `dist/`, `build/`, `*.egg-info/`, `.ruff_cache/`,
      `.mypy_cache/`, `.coverage`, `htmlcov/`, `.DS_Store`, `.idea/`, `.vscode/`, `*.pyc`,
      `accounts*.json`, `.specs-cache/`.
- [x] `.gitattributes`: `* text=auto eol=lf`, `*.json text`, `uv.lock linguist-generated`.
- [x] Мусор в индекс не попал: `.venv/`, `__pycache__/`, `.pytest_cache/` игнорируются.
- [x] `.env` не в индексе, `.env.example` — с пустыми значениями.
- [x] Имя клиентского аккаунта из `.env` не встречается в индексе/документации.
- [x] Коммиты — с GitHub noreply-почтой, без `Co-Authored-By` трейлеров.
- [ ] Скан секретов до первого push: хук `gitleaks` в `.pre-commit-config.yaml` настроен;
      отдельный прогон `gitleaks detect`/`trufflehog` — перед публикацией.
- [x] `git status --ignored` и `git ls-files` проверены глазами.
- [x] Размер допустимый: `specs/` 828 КБ, `uv.lock` ~180 КБ, бинарников нет.

## 3. README и публичная документация

- [x] Первый экран: что это, для кого, пример вызова (до/после).
- [x] Бейджи: CI, license, python 3.11–3.13.
- [x] Установка: `uvx` из git / `pip install .` / Docker — все три проверены на чистой копии.
- [x] Quick start (инструкция для модели) + 6 примеров read-вызовов.
- [x] Полная таблица env-переменных + `.env.example`.
- [x] Безопасность: read/write/destructive/paid, `confirm=true`, `SWEB_ALLOW_DESTRUCTIVE`.
- [x] Мультиаккаунт: `sweb_accounts`, `sweb_use_account`, `account="имя"`.
- [x] Подключение к клиентам: Claude Code, OpenCode, Cursor, Docker — без абсолютных личных путей.
- [x] Ограничения честно: спеки — снапшот, классификация эвристическая, лимиты API не документированы.
- [x] Troubleshooting/FAQ: `-32603`, 429, «no accounts», прокси (`trust_env=False`).
- [x] `CONTRIBUTING.md`: dev-окружение, стиль, тесты, DCO (без CLA), обновление спек.
- [x] `CODE_OF_CONDUCT.md` — Contributor Covenant 2.1.
- [x] `SECURITY.md`: приватный reporting, SLA, что считать уязвимостью (утечка кредов в логи — да).
- [x] Ссылки на LICENSE и NOTICE из README.
- [x] `docs/` + CLAUDE.md: внутренняя память переписана нейтрально и публикуется.

## 4. Код и метаданные пакета

- [x] `pyproject.toml`: `license`, `license-files`, `readme`, `authors`, `keywords`,
      `classifiers` (Python 3.11–3.13, MCP, hosting API), `[project.urls]`
      (Homepage/Repository/Issues/Changelog→Releases).
- [ ] Проверить доступность имени `sweb-mcp` в PyPI — только если решим публиковать.
- [x] `ruff` (lint+format) в dev-зависимостях + конфиг в `pyproject.toml`; прогон чистый.
- [ ] (опц.) `mypy`/`pyright` базовый режим — не делали.
- [x] pre-commit: ruff, ruff-format, end-of-file-fixer, trailing-whitespace, check-yaml,
      check-toml, detect-private-key, gitleaks.
- [x] `python -m build` + `twine check dist/*` — проходят; sdist/wheel ставятся и запускаются
      в чистом venv (37 файлов, спеки входят в wheel).
- [x] `python -m sweb_mcp` без `SWEB_ACCOUNTS_FILE` — понятное сообщение в stderr, не трейсбек.
- [x] Тесты зелёные (31 passed).
- [x] Ссылки на внутренние правила обезличены (CLAUDE.md → README/Releases).

## 5. GitHub-репозиторий — сделано 14.11.2026

- [x] Public-репо: https://github.com/AVert/sweb-mcp (ветка `main`).
- [x] About: описание 97 симв., topics (`mcp`, `model-context-protocol`, `spaceweb`, `sweb`,
      `hosting`, `api-client`, `python`, `claude`).
- [x] Branch protection `main`: require PR (0 approvals — self-merge не блокируется) + required checks
      `test (py3.11|3.12|3.13)`, `build sdist + wheel`, strict; запрет force-push/удаления,
      required conversation resolution; `enforce_admins=false` — владелец может пушить напрямую.
- [x] `.github/workflows/ci.yml` — matrix 3.11/3.12/3.13, `pytest -q`, `ruff check`,
      `ruff format --check`, `python -m build` + `twine check`. Триггеры: push в main, все PR.
- [x] `.github/workflows/codeql.yml` (Python) — еженедельно + на PR.
- [x] `.github/dependabot.yml`: `pip` (uv.lock) и `github-actions`, weekly.
- [~] `.github/workflows/release.yml` — не делали: релиз собирается вручную (`git tag` + `gh release`),
      исходники wheel/sdist GitHub отдаёт из тега. Добавить, если понадобится автосборка.
- [x] Шаблоны: `.github/ISSUE_TEMPLATE/bug_report.yml`, `feature_request.yml`,
      `PULL_REQUEST_TEMPLATE.md`.
- [ ] (опц.) `CODEOWNERS`, `FUNDING.yml`, `CITATION.cff`.
- [x] Настройки безопасности: secret scanning + push protection, Dependabot alerts/security updates,
      private vulnerability reporting.
- [x] Релиз `v0.1.0`: тег + GitHub Release из `.github/release-notes/v0.1.0.md`.
- [-] (опц.) PyPI — решение владельца 14.11.2026: **отложено**, релиз только через git/GHCR.
      `pyproject.toml` к публикации готов; при возврате к вопросу нужен trusted publishing (OIDC)
      + pending publisher на PyPI.
- [x] GHCR-образ `ghcr.io/avert/sweb-mcp`, multi-arch amd64/arm64 (`.github/workflows/docker.yml`,
      по тегу `v*` и вручную); проверено — тянется анонимно (`:latest`, `:0.1`, `:0.1.0`).
- [x] `delete_branch_on_merge` включён.

## 6. Проверка «с нуля» перед публикацией

- [x] Копия дерева без `.venv`/`.env`/`.git` в `/tmp` → `uv sync` → `pytest` 31 passed →
      сервер стартует.
- [x] `pip install .` в чистый venv → `sweb-mcp` в PATH, спеки резолвятся из wheel (276 методов).
- [x] `docker build .` → `docker run -i --rm sweb-mcp` работает.
- [x] `grep -rn -E "password\s*=\s*['\"][^'\"]{4,}"` по дереву — чисто; личные имена/пути/почты
      в индексе отсутствуют.
- [x] `git log --stat` — нет случайных файлов, нет `.env`, нет `accounts.json`.
- [x] Ссылки в README резолвятся, LICENSE рендерится как MIT, CI-бейдж зелёный.
- [ ] (важно) креды, которые когда-либо попадали в локальные логи opencode, в репо не попали;
      при сомнении — сменить пароль клиентского аккаунта у SpaceWeb.

## 7. После публикации

- [ ] Включить watch на issues/security, ответить на первый фидбек.
- [x] Зафиксировать в CLAUDE.md: репо, ветка, как выпускать релиз.
- [ ] (опц.) анонс: r/mcp, awesome-mcp-servers, Хабр.

## 8. Поисковая оптимизация (GitHub SEO) — делать при публикации на GitHub и аналоги

Цель: репо находится по всем фразам, которыми его будут искать («spaceweb mcp», «sweb mcp»,
«selectel mcp», «timeweb mcp» и т.п.). Проверять результат реальным поиском в incognito-браузере,
а не «на глаз». Правки делаются сразу через `gh repo edit`, не через веб-UI.

- [ ] **Имя репо** — самый сильный сигнал: ключ в имени (`sweb-mcp`), если имя не содержит ключ —
      компенсировать описанием и topics.
- [x] **Description (About)** — собрана в одну строку все варианты, которыми ищут: продукт
      полностью и сокращённо + слова «MCP server». Формула: `<Продукт> (<вторая орфография>)
      MCP server — <что делает> · <Полный Продукт> MCP / <сокращение> mcp`.
      Пример (sweb): «MCP server for SpaceWeb (sweb.ru, SpaceWeb hosting) JSON-RPC API —
      SpaceWeb MCP / sweb mcp: 276 API methods as tools for Claude, OpenCode and any MCP client».
- [x] **Topics (до 20)** — главный фильтр поиска и topic-страницы. Обязательные группы:
      экосистема: `mcp`, `model-context-protocol`, `mcp-server`;
      продукт: полная и краткая орфография (`spaceweb`, `sweb`, `selectel`, `timeweb`, `tilda`);
      домен: `hosting`, `cloud`, `dns`, `cdn`, `storage` — что реально есть;
      стек: язык (`python`), `api`, `api-client`;
      клиенты: `claude`, `claude-code`, `opencode`, `openai`, `llm-tools`, `ai-tools`.
- [ ] **README первый экран** — GitHub code search и Google индексируют README: в H1/первом
      абзаце полное имя продукта (не только аббревиатура) и строка «searchable as» со всеми
      вариантами («SpaceWeb MCP · sweb mcp · MCP-сервер хостинга SpaceWeb»). RU-аудитория ищет
      и по-русски — одна строка по-русски не помешает.
- [ ] **`pyproject.toml`** — `keywords` и `classifiers` с теми же словами (PyPI/GitHub packages
      поиск), `[project.urls]` заполнены.
- [ ] **Releases** — текст релиза индексируется: в заголовке/первых строках имя продукта и
      «MCP server».
- [ ] **Кросс-ссылки** — README каждого сервера семейства ссылается на остальные
      (`sweb-mcp` ↔ `cloud-mcp` ↔ `timeweb-mcp`): GitHub поднимает связанные репо, поисковый
      вес суммарный.
- [ ] **Профиль владельца** — закрепить репо, в profile README держать список MCP-серверов
      одной таблицей (Google индексирует профиль).
- [ ] **Честность вместо спама** — ключи только там, где они описывают реальное содержимое;
      скрытый текст и повторения не делать — до флага/пометки спама недалеко, и модель-агенту
      это тоже читается хуже.
- [ ] **Проверка** — поиск GitHub по каждой целевой фразе (web + repos), репо в первой пятёрке;
      поиск Google/Bing «<продукт> mcp github» — репо присутствует. После правки метаданных
      переиндексация может занять до нескольких дней — дату проверки зафиксировать здесь же.

Сделано для sweb-mcp 18.11.2026: description переписан (содержит «SpaceWeb MCP / sweb mcp»),
topics дополнены `mcp-server`, `llm-tools`, `ai-tools`, `openai`, `claude-code`, `api`.
Осталось: строка «searchable as» в README, кросс-ссылки на cloud-mcp/timeweb-mcp (когда
опубликуются), проверка позиций поиском.
