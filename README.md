# sweb-mcp

[![CI](https://github.com/avert/sweb-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/avert/sweb-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](pyproject.toml)
[![MCP](https://img.shields.io/badge/MCP-server-6f42c1.svg)](https://modelcontextprotocol.io)

MCP-сервер (stdio) для клиентского API SpaceWeb (sweb.ru): JSON-RPC 2.0, 29 объектов,
**276 уникальных методов** — все доступны как tools `<объект>_<метод>` (`vps_index`,
`domains_dns_editTxt`, `vh_mail_createMbox`, …) + 5 meta-tools: `sweb_list_methods`,
`sweb_describe`, `sweb_call`, `sweb_accounts`, `sweb_use_account`.

Вместо «прочитай документацию и напиши curl» — модель видит методы как инструменты:

```
> сколько сейчас сайтов на аккаунте и которые из них без SSL?
  sites_index                       → 7 сайтов
  sites_getSiteInfo(siteId=...)     → ...
```

## Быстрый старт
```
SpaceWeb (sweb.ru) API. Tools: <object>_<method> — sites_index, vps_index, domains_dns_info…
1) Explore: sweb_list_methods(group=/search=) → sweb_describe(path, method) → call the tool.
2) Accounts: sweb_accounts (list + current) → sweb_use_account(name) for this session, or pass account="name" on a single call.
3) Safety: read runs freely; write needs confirm=true; destructive/paid need SWEB_READONLY=0 + SWEB_ALLOW_DESTRUCTIVE=1.
4) Errors: "[code] message"; -32603 = token expired (auto re-login), 429 = rate limit (auto retry).
```
`sweb_use_account` действует до перезапуска процесса; после старта умолчание снова берётся из `SWEB_ACCOUNT`.

## Установка

Нужен Python 3.11–3.13 и файл с учётками (см. «Настройка»).

**uv (из git, без клонирования)**
```bash
uvx --from git+https://github.com/avert/sweb-mcp sweb-mcp
```

**uv / pip из клона**
```bash
git clone https://github.com/avert/sweb-mcp && cd sweb-mcp
uv sync                       # или: python -m venv .venv && .venv/bin/pip install .
cp .env.example .env          # указать SWEB_ACCOUNTS_FILE
uv run --env-file .env sweb-mcp
```

**Docker**
```bash
# готовый образ (multi-arch, теги vX.Y.Z / latest)
docker run -i --rm --env-file .env ghcr.io/avert/sweb-mcp:latest

# или собрать из клона
docker build -t sweb-mcp .
docker run -i --rm --env-file .env sweb-mcp
# или в репозитории:
docker compose run --rm -T sweb-mcp
```

Пакет в PyPI пока не публикуется; устанавливайте из git, из локального клона или из образа GHCR.

## Примеры read-вызовов

Все примеры — это имена tools, которые модель вызывает сама; параметры описаны в
`sweb_describe(path="/vps", method="index")`.

| Запрос | Вызов | Ответ (сокращённо) |
|---|---|---|
| Список сайтов | `sites_index` | `[{"siteId": 123, "domain": "example.ru", ...}]` |
| Баланс и платежи | `pay_index` / `pay_getBalance` | `{"balance": 1234.5, "currency": "RUB"}` |
| DNS-записи домена | `domains_dns_info(domain="example.ru")` | `{"records": [{"type": "A", "value": "1.2.3.4"}]}` |
| VPS-серверы | `vps_index` | `[{"billingId": "srv123", "alias": "web", "state": "running"}]` |
| Почтовые ящики | `vh_mail_getMailboxesList(domain="example.ru")` | `[{"mbox": "info", "size": "…"}]` |
| Тариф | `tariff_index` | `{"plan": "…", "resources": {…}}` |

Любой метод можно вызвать и напрямую через meta-tool:
`sweb_call(path="/domains/dns", method="info", params={"domain": "example.ru"})`.

## Настройка
```bash
cp .env.example .env   # указать SWEB_ACCOUNTS_FILE
```
| Переменная | Назначение | По умолчанию |
|---|---|---|
| `SWEB_ACCOUNTS_FILE` | **единственный** источник учёток: JSON `{"имя": {"login": "...", "password": "..."}}` или `{"имя": "login:password"}` | — |
| `SWEB_ACCOUNT` | аккаунт по умолчанию (имя из файла); пусто = первый | — |
| `SWEB_READONLY` | `1` — доступны только read-методы | `1` |
| `SWEB_ALLOW_DESTRUCTIVE` | разрешить destructive/paid методы | `0` |
| `SWEB_GROUPS` | фильтр, напр. `vps,domains,vh/mail` (пусто = всё) | все |
| `SWEB_OVERRIDES` | JSON `{"/vps:reboot":"write"}` — ручная правка классов | — |
| `SWEB_API_URL`, `SWEB_TIMEOUT` | адрес API, таймаут (с) | api.sweb.ru, 30 |
| `SWEB_MAX_CONCURRENCY`, `SWEB_MIN_INTERVAL` | одновременных запросов / пауза между стартами запросов (с) — защита от rate limit | 4, 0.2 |
| `SWEB_MAX_RETRIES`, `SWEB_BACKOFF_BASE` | повторы (HTTP 429 — всегда; 502/503/504 и сеть — только read) и база экспоненциальной паузы (с), `Retry-After` учитывается | 3, 0.5 |
| `SWEB_SPECS_DIR` | каталог спек (вне Docker; в образе задан через ENV — не класть в `.env`) | `specs/` |

Файл учёток — обычный JSON, права `chmod 600`, он не должен попадать в git
(`.gitignore` уже исключает `accounts*.json` и `.env`).

## Безопасность
Метод классифицируется как `read` / `write` / `destructive` / `paid` (`src/sweb_mcp/safety.py`; в спеках флагов нет, это эвристика + таблица платных).
Write требует `SWEB_READONLY=0` и `confirm=true`; destructive/paid — ещё `SWEB_ALLOW_DESTRUCTIVE=1`.

Read-вызовы выполняются свободно, записи — только с явным `confirm=true` в аргументах
tool-а. Повторы после 502/503/504 и сетевых ошибок делаются только для read-методов:
исход write/destructive-вызова неизвестен, повтор мог бы задвоить заказ или удаление.

## Несколько аккаунтов
Единственный источник учёток — JSON-файл из `SWEB_ACCOUNTS_FILE`; `SWEB_ACCOUNT` задаёт аккаунт по умолчанию. В рантайме: `sweb_accounts` показывает список и текущий, `sweb_use_account` переключает умолчание, а любой tool принимает `account="имя"` для разового вызова. Клиент и токен кешируются на аккаунт.

## Подключение к клиентам

**Claude Code** (из каталога с клоном):
```bash
claude mcp add sweb -- uv run --directory "$PWD" --env-file .env sweb-mcp
# Docker-вариант:
claude mcp add sweb -- docker compose -f "$PWD/docker-compose.yml" run --rm -T sweb-mcp
```

**OpenCode** (`opencode.json`):
```json
{
  "mcp": {
    "sweb": {
      "type": "local",
      "command": ["uv", "run", "--directory", "/path/to/sweb-mcp", "--env-file", ".env", "sweb-mcp"]
    }
  }
}
```

**Cursor** (`.cursor/mcp.json`), установка из git без клонирования:
```json
{
  "mcpServers": {
    "sweb": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/avert/sweb-mcp", "sweb-mcp"],
      "env": { "SWEB_ACCOUNTS_FILE": "/path/to/accounts.json", "SWEB_ACCOUNT": "main" }
    }
  }
}
```

**Docker**, если клиенту нужен явный контейнер:
```bash
docker run -i --rm --env-file .env sweb-mcp
```
stdio-сервер запускается клиентом по требованию, отдельным сервисом его держать не нужно.

## Ограничения
- **Спеки — снапшот.** `specs/*.json` сняты с apidoc.sweb.ru на момент синхронизации; новых
  методов в них нет. Обновление — `scripts/sync_specs.py` (см. CONTRIBUTING.md).
- **Классификация эвристическая.** В спеках нет флагов read/write: класс выводится из имени
  метода, таблицы платных операций и `SWEB_OVERRIDES`. Ошибка классификации возможна —
  проверяйте `[WRITE]`/`[DESTRUCTIVE]`/`[PAID]` в описании tool-а.
- **Лимиты API не документированы.** `SWEB_MAX_CONCURRENCY`/`SWEB_MIN_INTERVAL`/`SWEB_MAX_RETRIES`
  подобраны консервативно; при 429 увеличьте паузу.
- Ответы API отдаются как есть (JSON), без нормализации и без кеширования.

## FAQ / troubleshooting

| Симптом | Причина и что делать |
|---|---|
| `[-32603] ...` | Сессия API истекла; клиент перелогинивается автоматически. Если ошибка повторяется — проверьте логин/пароль в файле учёток. |
| `[429] ...` | Rate limit. Уменьшите `SWEB_MAX_CONCURRENCY`, увеличьте `SWEB_MIN_INTERVAL`; повторы уже включены. |
| `[config] no accounts: set SWEB_ACCOUNTS_FILE ...` | Не задан `SWEB_ACCOUNTS_FILE` или файл пустой. Укажите путь в `.env`/окружении клиента. |
| `[refused] ... SWEB_READONLY` / `... requires confirm=true` | Сработала защита: включите `SWEB_READONLY=0` и передайте `confirm=true` (для destructive/paid — ещё `SWEB_ALLOW_DESTRUCTIVE=1`). |
| `[network] ...` / таймауты за прокси | Клиент ходит напрямую (`trust_env=False`) и игнорирует `HTTP(S)_PROXY`. Нужен прокси — используйте сетевой уровень (VPN, `HTTPS_PROXY`-aware обёртка), а не переменные окружения. |
| Сервер «молчит» в клиенте | Это stdio-сервер: он пишет только в stderr. Запустите вручную `uv run --env-file .env sweb-mcp` — при старте печатается строка `[sweb-mcp] readonly=… creds=set/MISSING`. |
| `unknown account '...'` | Имя не совпадает с ключом в JSON-файле; список — tool `sweb_accounts`. |

## Разработка
```bash
uv sync --extra dev && uv run python -m pytest -q
uv run python scripts/sync_specs.py --check   # дрейф спек относительно apidoc.sweb.ru
uv run python scripts/sync_specs.py           # обновить specs/
uv run ruff check . && uv run ruff format --check .
```
Спеки — OpenRPC, извлечённые из JS-бандла apidoc.sweb.ru (официальной машиночитаемой спеки нет); логика извлечения портирована из [sanchpet/sweb-go-sdk](https://github.com/sanchpet/sweb-go-sdk) (MIT). Подробности — [CONTRIBUTING.md](CONTRIBUTING.md).

## Лицензия и disclaimer
Проект распространяется по [MIT License](LICENSE). Сторонние компоненты и происхождение
спек — в [NOTICE](NOTICE).

**Неофициальный клиент.** Проект не аффилирован со SpaceWeb (sweb.ru), не поддерживается и
не одобрен правообладателем; товарные знаки принадлежат их владельцам. Используя сервер, вы
соблюдаете условия обслуживания SpaceWeb и лимиты API; автор не несёт ответственности за
последствия вызовов, выполненных с вашими учётными данными. Никаких гарантий не даётся.

История изменений — в [GitHub Releases](https://github.com/avert/sweb-mcp/releases).
