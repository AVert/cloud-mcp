# cloud-mcp

[![CI](https://github.com/AVert/cloud-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/AVert/cloud-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)

Один MCP-сервер (stdio) сразу для нескольких облачных провайдеров: **SpaceWeb** (276 методов
JSON-RPC), **Timeweb Cloud** (515 операций), **Selectel** (31 продукт, 746 операций), **Tilda
Publishing** (10). Провайдер — **аргумент вызова**, а не переменная окружения: переключение без
рестарта и без обхода кэша `tools/list` у клиента.

Ищете **SpaceWeb MCP / sweb mcp** — это он же: SpaceWeb живёт здесь как провайдер `sweb`
(раньше — отдельный репозиторий sweb-mcp, см. «Переход с sweb-mcp 0.1»).

Вместо сотен tool-схем в промпте — discovery-интерфейс из 5 инструментов:

```
cloud_search(query="перезагрузить сервер")       → топ операций с именами/методами/параметрами
cloud_describe(provider="timeweb", tool="servers_reboot") → полная схема
cloud_call(provider="timeweb", tool="servers_reboot", args={"server_id": 1}) → вызов
cloud_providers()  → провайдеры, продукты, счётчики, состояние кредов
cloud_catalog(provider="selectel") → grep-файл «читай тут» с правилами и индексом операций
```

## Поиск

Лексический ранкер без эмбеддингов и без индекса: RU→EN алиасы, стемминг (кириллица — 5-символьный
стем, латиница — слово/множественное число), вес 1.0 у набранного слова и 0.5 у алиаса, на токен
берётся лучшее поле (tool 9 / path 4 / продукт 2.5 / summary 1.5), бонус корневой коллекции
ресурса, гейт по HTTP-методу при явном действии («удалить» → DELETE), бонус провайдеру, если его
имя упомянуто в запросе. Бенчмарк — 51 запрос RU/EN против 1271 операции: top-1 ≥ 90%,
top-3 = 100% (`tests/test_search.py::BENCHMARK`, регрессия ловится тестом).

## Установка

```bash
# из git, без клонирования (обе точки входа: cloud-mcp и прежняя sweb-mcp)
uvx --from git+https://github.com/AVert/cloud-mcp cloud-mcp
uvx --from git+https://github.com/AVert/cloud-mcp sweb-mcp     # то же самое, старое имя

# разработка
git clone https://github.com/AVert/cloud-mcp && cd cloud-mcp
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python scripts/sync_specs.py   # обновить снапшоты API из документации провайдеров

# контейнер
docker run -i --rm -e CLOUD_ACCOUNTS_FILE=/accounts.json \
  -v "$HOME/.config/cloud-mcp:/cfg:ro" ghcr.io/avert/cloud-mcp
```

## Учётные данные

Один файл на все провайдеры — `CLOUD_ACCOUNTS_FILE` (по умолчанию
`~/.config/cloud-mcp/accounts.json`, `chmod 600`, в git не попадает):

```json
{
  "timeweb":  {"token": "eyJ..."},
  "selectel": {"iam_token": "...", "static_token": "...", "login": "svc_user", "password": "...", "account_id": "12345"},
  "tilda":    {"public_key": "...", "private_key": "..."}
}
```

- **timeweb** — `Authorization: Bearer <token>`. Совместимость: читается старый
  `TIMEWEB_ACCOUNTS_FILE` / `TIMEWEB_TOKEN`, если cloud-файла нет.
- **selectel** — три вида доступа, и продукт сам решает, какой ему нужен:
  - **account-scoped IAM-токен** (`X-Auth-Token`): баланс, тикеты, пользователи и роли, аудит,
    глобальный роутер, проекты, федерации;
  - **project-scoped IAM-токен** + заголовок `X-Project-Id`: CDN, DNS, приватный DNS,
    Managed Kubernetes, Managed Databases, бэкапы по расписанию, публичные порты, 1С-облако,
    object storage, почтовый сервис, сертификаты Let's Encrypt;
  - **статический токен** (`X-Token`): legacy API без IAM (часть биллинга, ipam).
  С `login`/`password` сервисного пользователя (+ `account_id`, `project_id`) оба IAM-токена
  выпускаются автоматически через Keystone и кэшируются; готовые токены тоже принимаются.
  Какой именно вид нужен конкретному вызову, снапшот хранит на **каждую операцию** (`security`
  из спеки; описание схемы приоритетнее имени — документация Selectel ошибается: secrets-manager
  зовёт схему account-scoped, а принимает project).
- **sweb** — JSON-RPC 2.0: `Authorization: Bearer <token>`, токен берётся через
  `POST /notAuthorized/` `getToken` (логин/пароль) и переиспользуется до `-32603` (тогда
  автоматический re-login). Пейсинг 5 rps и 4 параллельных запроса по умолчанию.
- **tilda** — `publickey`/`privatekey` в query каждого запроса.

Файл читается лениво: дописать токен можно в уже запущенный сервер (правки кода — только рестарт).

## Первичная настройка Selectel

Рабочий вариант — сервисный пользователь (токены без срока 24 ч): скрипт сам создаёт его,
выдаёт роли, выпускает пароль и проверяет оба токена живым read-запросом.

```bash
python scripts/selectel_service_user.py                  # reader на аккаунт + на проект
python scripts/selectel_service_user.py --write          # member (полный доступ), не reader
python scripts/selectel_service_user.py --s3             # плюс access key/secret для S3
python scripts/selectel_service_user.py --list           # кем уже владеет аккаунт
python scripts/selectel_service_user.py --delete svc-cloud-mcp --yes
```

По умолчанию — минимальные права (`reader`): просмотр всех проектов, квот и биллинга. Пароль
генерируется локально, не печатается и пишется в файл учёток (0600); панельные токены (24 ч)
после успешной проверки убираются, чтобы клиент не ходил ими до истечения. Действия с
пользователями требуют админского токена — `--token <панельный IAM-токен>`, у `reader` его нет
(ответ будет 403 с подсказкой).

Разово проверить готовые токены или дописать их вручную:

```bash
python scripts/selectel_auth.py --login svc-cloud --account-id 123456   # пароль спросим
python scripts/selectel_auth.py --login svc-cloud --account-id 123456 --project-id 7f1c…
python scripts/selectel_auth.py --iam-token <панельный токен>            # быстрая проверка, 24 ч
python scripts/selectel_auth.py --project-token <токен> --project-id 7f1c…
python scripts/selectel_auth.py --static-token <API-ключ>                # legacy X-Token
python scripts/selectel_auth.py --check                                  # что реально работает
```

Оба скрипта ничего не печатают из секретов, проверяют каждый токен живым read-запросом и **мержат**
запись `selectel` в файл учёток (остальные провайдеры не затираются), права 0600.

## Регионы Selectel

Базовые URL каждого продукта берутся из таблицы «URL для обращения к API» документации Selectel
и хранятся в снапшоте по-регионально (`base_urls`: ru-2, ru-3, ru-8, kz-1, uz-1…). Регион
выбирается переменной `SELECTEL_REGION` (по умолчанию `ru-2`); точечный оверрайд —
`SELECTEL_BASE_<SLUG>` (пример: `SELECTEL_BASE_MANAGED_DATABASES=https://ru-3.dbaas.selcloud.ru/v1`).
Региональные продукты: 1c-cloud, cloud-public-network, managed-databases, managed-kubernetes,
managed-kubernetes-legacy, object-storage, private-dns, quota-management, scheduled-backups.
Дубли версий в URL разруливаются при сборке снапшота: `/v2/clusters` в путях спецификации и
`…/v2` в URL документации не задваиваются.

## Безопасность

Класс операции определяется при сборке снапшота и хранится в нём: `read` / `write` /
`destructive` / `paid` (`src/cloud_mcp/core/safety.py`). `read` — свободно; `write` — требует
`confirm: true`; `destructive`/`paid` — только при `CLOUD_READONLY=0` и
`CLOUD_ALLOW_DESTRUCTIVE=1`. Удаления Selectel могут отвечать 403 с запросом кода подтверждения —
повторить вызов с `hash`.

## Env

| Переменная | По умолчанию | Что делает |
|---|---|---|
| `CLOUD_ACCOUNTS_FILE` | `~/.config/cloud-mcp/accounts.json` | учётки всех провайдеров |
| `CLOUD_CACHE_DIR` | `~/.cache/cloud-mcp` | куда `cloud_catalog` пишет файлы |
| `CLOUD_PROVIDERS` | все | включить подмножество: `timeweb,selectel` |
| `CLOUD_READONLY` | `0` | запретить всё, кроме read |
| `CLOUD_ALLOW_DESTRUCTIVE` | `0` | разрешить destructive/paid |
| `CLOUD_TIMEOUT` | `60` | таймаут HTTP, сек |
| `CLOUD_SPECS_DIR` | пакетные `specs/` | свой каталог снапшотов |
| `SELECTEL_REGION` | `ru-2` | регион для региональных продуктов selectel |
| `SELECTEL_BASE_<SLUG>` | — | точечный оверрайд базового URL продукта |
| `TIMEWEB_TOKEN` / `TIMEWEB_ACCOUNTS_FILE` | — | совместимость со старым timeweb-mcp |

## Подключение в OpenCode

```json
"cloud": {
  "type": "local",
  "command": ["/path/to/cloud-mcp/.venv/bin/cloud-mcp"],
  "environment": {
    "CLOUD_ACCOUNTS_FILE": "/home/<user>/.config/cloud-mcp/accounts.json"
  }
}
```

## Снапшоты и их обновление

`specs/` — нормализованные снапшоты документации (Timeweb OpenAPI 3.0, Selectel — Swagger 2.0 /
OpenAPI 3.x по продуктам, Tilda — hand-written: официального OpenAPI у Tilda нет). Источник истины
— документация провайдеров; обновление: `python scripts/sync_specs.py`, проверка дрейфа:
`--check`. Ошибка классификации операции правится в `core/safety.py`, а не в снапшоте руками.

## Провайдер-специфика

- **timeweb**: списки пагинируются `limit`/`offset`; удаление может требовать `hash`
  (код из Telegram); ошибки приходят как `[code] message`.
- **selectel**: пагинация `per-page`/`page` (или `size`/`page`); IAM-токен живёт час;
  у части продуктов только статический токен.
- **tilda**: все операции read-only (экспорт сайтов/страниц); `getfullexport` возвращает
  `exportid`, статус — `getexport`, ссылка — `getexportlink`.

## Tilda: что доступно без тарифа Business

Экспортное API Tilda (`publickey`/`secretkey`, Настройки сайта → Экспорт → API) и её родные
«Ключи MCP» открываются только на тарифе **Business**; сторонние MCP-серверы для Tilda
(`theYahia/tilda-mcp` и подобные) ходят в то же API, поэтому без Business бесполезны. Провайдер
`tilda` в этом сервере остаётся в снапшотах (10 read-операций), но по умолчанию выключен:
`CLOUD_PROVIDERS=timeweb,selectel`.

Опубликованные страницы читаются без всякого API — для бэкапа и инвентаризации есть офлайн-скрипт:

```bash
python scripts/tilda_backup.py --site https://example.com --out ~/tilda/example           # весь сайт по sitemap
python scripts/tilda_backup.py --site https://example.com --out ~/tilda/example --diff     # что изменилось
python scripts/tilda_backup.py --url https://example.com/page.html --out ~/tilda/one       # одна страница
```

Пишет `<out>/pages/*.html` (сырой HTML) и `<out>/index.json`: title, description, og, число
блоков и их record-type, изображения, внутренние/внешние ссылки, формы, css/js. Ноль токенов на
прогон: модель читает индекс с диска, а не браузерные снапшоты. Правки и настройки (то, чего в
публичных страницах нет) — только через браузерный MCP, по требованию.

## SpaceWeb (sweb.ru)

276 уникальных методов 29 объектов превращаются в операции с **прежними** именами
`<объект>_<метод>` (`vps_reboot`, `domains_dns_editTxt`, `vh_mail_createMbox`, …) — тем же
именам, что были в per-op сервере, только доступны они через `cloud_call(provider="sweb",
tool="vps_reboot", ...)`.

Учётные записи: entry `sweb` в общем файле учёток — `{"login": "…", "password": "…"}`.
Несколько аккаунтов — блоком `accounts` и `default_account`, переключение на один вызов —
аргументом `account="имя"`:

```json
{"sweb": {"login": "main-login", "password": "…",
          "accounts": {"work": {"login": "…", "password": "…"},
                       "home": "login:password"},
          "default_account": "work"}}
```

Старые переменные окружения продолжают работать: `SWEB_ACCOUNTS_FILE` (формат прежний:
`{"имя": {"login","password"}}` или `{"имя": "login:password"}`), `SWEB_ACCOUNT`, `SWEB_TOKEN`,
плюс `SWEB_MIN_INTERVAL` / `SWEB_MAX_CONCURRENCY`. Права: read свободно, write — `confirm=true`,
destructive/paid — `CLOUD_READONLY=0` + `CLOUD_ALLOW_DESTRUCTIVE=1` (старые `SWEB_READONLY` /
`SWEB_ALLOW_DESTRUCTIVE` тоже читаются).

Ошибки: `[rpc] <код>: <сообщение>`, `-32603` лечится автоматическим re-login, 429 — ретраем.

## Переход с sweb-mcp 0.1

Версия 0.2.0 — breaking change: 276 per-op тулов заменены пятью discovery-тулами. Те же методы
вызываются через `cloud_call`, имена операций не изменились.

| Было (sweb-mcp 0.1) | Стало (cloud-mcp 0.2) |
|---|---|
| `sweb_list_methods(group=/search=)` | `cloud_search(query, provider="sweb", product=…)` |
| `sweb_describe(path, method)` | `cloud_describe(provider="sweb", tool="<объект>_<метод>")` |
| `sweb_call(path, method, params)` | `cloud_call(provider="sweb", tool="<объект>_<метод>", …)` |
| `sweb_accounts`, `sweb_use_account` | `account="имя"` в `cloud_call`; список — `cloud_providers` |
| `SWEB_READONLY` / `SWEB_ALLOW_DESTRUCTIVE` | `CLOUD_READONLY` / `CLOUD_ALLOW_DESTRUCTIVE` (старые имена читаются) |
| `ghcr.io/avert/sweb-mcp` | `ghcr.io/avert/cloud-mcp` (образ sweb-mcp заморожен на 0.1.x) |

## Семейство

- **cloud-mcp** — этот сервер: SpaceWeb, Timeweb, Selectel, Tilda за discovery-интерфейсом
  (сюда переехал [sweb-mcp](https://github.com/AVert/cloud-mcp) вместе с историей и issues);
- timeweb-mcp — Timeweb (per-op tools + профили, предок движка).

## Лицензия и disclaimer

MIT — см. `LICENSE`. Не аффилирован с Timeweb, Selectel, SpaceWeb и Tilda; товарные знаки
принадлежат владельцам. Снапшоты — переработанные фрагменты публичной документации провайдеров
(см. `NOTICE`).
