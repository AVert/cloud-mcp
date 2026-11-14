# sweb-mcp

MCP-сервер (stdio) для клиентского API SpaceWeb (sweb.ru): JSON-RPC 2.0, 29 объектов, **276 уникальных методов** — все доступны как tools `<объект>_<метод>` (`vps_index`, `domains_dns_editTxt`, `vh_mail_createMbox`, …) + 3 meta-tools: `sweb_list_methods`, `sweb_describe`, `sweb_call`.

## Быстрый старт
```
SpaceWeb (sweb.ru) API. Tools: <object>_<method> — sites_index, vps_index, domains_dns_info…
1) Explore: sweb_list_methods(group=/search=) → sweb_describe(path, method) → call the tool.
2) Accounts: sweb_accounts (list + current) → sweb_use_account(name) for this session, or pass account="name" on a single call.
3) Safety: read runs freely; write needs confirm=true; destructive/paid need SWEB_READONLY=0 + SWEB_ALLOW_DESTRUCTIVE=1.
4) Errors: "[code] message"; -32603 = token expired (auto re-login), 429 = rate limit (auto retry).
```
`sweb_use_account` действует до перезапуска процесса; после старта умолчание снова берётся из `SWEB_ACCOUNT`.

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

## Безопасность
Метод классифицируется как `read` / `write` / `destructive` / `paid` (`src/sweb_mcp/safety.py`; в спеках флагов нет, это эвристика + таблица платных).
Write требует `SWEB_READONLY=0` и `confirm=true`; destructive/paid — ещё `SWEB_ALLOW_DESTRUCTIVE=1`.

## Несколько аккаунтов
Единственный источник учёток — JSON-файл из `SWEB_ACCOUNTS_FILE`; `SWEB_ACCOUNT` задаёт аккаунт по умолчанию. В рантайме: `sweb_accounts` показывает список и текущий, `sweb_use_account` переключает умолчание, а любой tool принимает `account="имя"` для разового вызова. Клиент и токен кешируются на аккаунт.

## Подключение к Claude Code
```bash
claude mcp add sweb -- docker compose -f $PWD/docker-compose.yml run --rm -T sweb-mcp
# или без docker:
claude mcp add sweb -- uv run --directory $PWD --env-file .env sweb-mcp
```

## Разработка
```bash
uv sync --extra dev && .venv/bin/python -m pytest -q
.venv/bin/python scripts/sync_specs.py --check   # дрейф спек относительно apidoc.sweb.ru
.venv/bin/python scripts/sync_specs.py           # обновить specs/
```
Спеки — OpenRPC, извлечённые из JS-бандла apidoc.sweb.ru (официальной машиночитаемой спеки нет); логика извлечения портирована из [sanchpet/sweb-go-sdk](https://github.com/sanchpet/sweb-go-sdk) (MIT).
