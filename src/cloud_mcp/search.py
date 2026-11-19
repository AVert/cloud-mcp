"""Lexical tool search across every provider: rank operations, return the top-N.

No embeddings and no index: ~1.2k operations with Russian and English summaries are covered by a
token-overlap ranker with RU->EN aliases, light stemming, a best-field-per-token score and a
method gate for explicit actions. The benchmark lives in tests/test_search.py.
"""

from __future__ import annotations

import re

from .core.normalize import Operation

CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
HOMOGLYPHS = str.maketrans("aceopxykmt", "асеорхукмт")
SPLIT = re.compile(r"[^a-z0-9а-яё]+")
STEM = 5
MIN_ALIAS = 4
MAX_STEM_GAP = 3

WEIGHT_TOOL = 9.0
WEIGHT_PATH = 4.0
WEIGHT_PRODUCT = 2.5
WEIGHT_SUMMARY = 1.5
WEIGHT_KIND = 2.0
BONUS_PROVIDER_NAMED = 10.0
COLLECTION_WORDS = frozenset({"list", "all", "список"})


WEIGHT_INTENT = 5.0
BONUS_FULL_COVERAGE = 6.0
BONUS_COLLECTION = 1.0
BONUS_ROOT = 2.0
BONUS_RESOURCE_ROOT = 2.5
PENALTY_EXTRA_TOKEN = 1.5
PENALTY_ITEM = 3.0
PENALTY_WRONG_METHOD = 5.0
MAX_EXTRA = 4

ALIASES = {
    "баланс": ("balance", "finances", "payment", "account", "cost"),
    "деньги": ("balance", "finances", "payment"),
    "финансы": ("finance", "finances", "cost", "balance"),
    "финанс": ("finance", "finances", "cost", "balance"),
    "стоимость": ("price", "cost", "preset"),
    "счёт": ("account", "finance", "bill"),
    "счет": ("account", "finance", "bill"),
    "тариф": ("preset", "price", "plan", "tariff"),
    "тарифы": ("preset", "price", "plan", "tariff"),
    "доступность": ("available", "availability", "zone", "location"),
    "балансировщик": ("balancer",),
    "балансировщики": ("balancer",),
    "балансировщика": ("balancer",),
    "локация": ("location",),
    "локации": ("location",),
    "нода": ("node",),
    "ноды": ("node",),
    "узел": ("node",),
    "с3": ("s3", "storage"),
    "s3": ("storage", "bucket"),
    "хранилище": ("storage", "bucket"),
    "бакет": ("bucket", "storage"),
    "бакеты": ("bucket", "storage"),
    "бакетов": ("bucket", "storage"),
    "объект": ("object",),
    "объекты": ("object",),
    "объектов": ("object",),
    "ключи": ("ssh", "key"),
    "ключ": ("ssh", "key"),
    "бэкап": ("backup",),
    "бэкапы": ("backup",),
    "бэкапов": ("backup",),
    "резерв": ("backup",),
    "перезагрузить": ("reboot",),
    "перезагрузка": ("reboot",),
    "перезагрузку": ("reboot",),
    "перезапуск": ("reboot", "restart"),
    "перезапустить": ("reboot", "restart"),
    "удалить": ("delete", "remove"),
    "создать": ("create", "add"),
    "список": ("list",),
    "настройки": ("settings", "config"),
    "сервер": ("server",),
    "серверы": ("server",),
    "серверов": ("server",),
    "сервере": ("server",),
    "база": ("database", "db"),
    "баз": ("database", "db"),
    "базы": ("database", "db"),
    "базу": ("database", "db"),
    "бд": ("database", "db"),
    "домен": ("domain",),
    "домена": ("domain",),
    "кластер": ("cluster",),
    "кластера": ("cluster",),
    "диск": ("disk",),
    "диски": ("disk",),
    "дисков": ("disk",),
    "снапшот": ("snapshot", "backup"),
    "образ": ("image",),
    "образы": ("image",),
    "проект": ("project",),
    "проекты": ("project",),
    "аккаунт": ("account",),
    "ящик": ("mailbox",),
    "почта": ("mail",),
    "почтовый": ("mail", "mailbox"),
    "правило": ("rule",),
    "правила": ("rule",),
    "группа": ("group",),
    "сеть": ("network",),
    "сети": ("network",),
    "адрес": ("ip",),
    "адреса": ("ip",),
    "сертификат": ("certificate",),
    "шаблон": ("preset", "template"),
    "зона": ("zone", "availability"),
    "зоны": ("zone", "availability"),
    "зон": ("zone", "availability"),
    "версия": ("version",),
    "версии": ("version",),
    "скачать": ("download",),
    "скачивание": ("download",),
    "выключить": ("shutdown", "stop", "poweroff"),
    "выключение": ("shutdown", "stop"),
    "включить": ("start", "enable"),
    "запустить": ("start",),
    "остановить": ("stop", "shutdown"),
    "пользователь": ("admin", "user"),
    "пользователи": ("admin", "user"),
    "пользователей": ("admin", "user"),
    "привязать": ("bind", "attach"),
    "привязан": ("bind", "attach"),
    "отвязать": ("unbind", "detach"),
    "тикет": ("ticket",),
    "тикеты": ("ticket",),
    "тикетов": ("ticket",),
    "обращение": ("ticket",),
    "квота": ("quota", "limit"),
    "квоты": ("quota", "limit"),
    "лимит": ("limit", "quota"),
    "лимиты": ("limit", "quota"),
    "транзакция": ("transaction",),
    "транзакции": ("transaction",),
    "платежи": ("payment", "transaction"),
    "реестр": ("registry",),
    "реестры": ("registry",),
    "образов": ("image",),
    "секрет": ("secret",),
    "секреты": ("secret",),
    "секретов": ("secret",),
    "сайт": ("project", "site"),
    "сайты": ("project", "site"),
    "сайтов": ("project", "site"),
    "страница": ("page",),
    "страницы": ("page",),
    "страниц": ("page",),
    "выгрузка": ("export",),
    "выгрузить": ("export",),
    "экспорт": ("export",),
    "том": ("volume",),
    "тома": ("volume",),
    "томов": ("volume",),
}

INTENT_METHOD = {
    "delete": "delete",
    "remove": "delete",
    "destroy": "delete",
    "удалить": "delete",
    "create": "post",
    "add": "post",
    "new": "post",
    "создать": "post",
    "update": "patch",
    "edit": "patch",
    "обновить": "patch",
    "изменить": "patch",
    "list": "get",
    "all": "get",
    "get": "get",
    "info": "get",
    "список": "get",
    "получить": "get",
}

INTENT_ALIASES = frozenset(INTENT_METHOD.values())

REST_VERBS = frozenset(
    {
        "list",
        "get",
        "create",
        "add",
        "update",
        "patch",
        "put",
        "delete",
        "remove",
        "reset",
        "set",
        "unset",
        "start",
        "stop",
        "shutdown",
        "reboot",
        "restart",
        "order",
        "clone",
        "upgrade",
        "install",
        "uninstall",
        "mount",
        "unmount",
        "bind",
        "unbind",
        "attach",
        "detach",
        "enable",
        "disable",
        "copy",
        "move",
        "list_2",
    }
)


def tokens(text: str) -> list[tuple[str, float]]:
    """Query tokens with weights: the words as typed weigh 1, aliases weigh 0.5."""
    weights: dict[str, float] = {}
    for raw in SPLIT.split(text.lower()):
        if len(raw) < 2:
            continue
        weights[raw] = 1.0
        expanded = list(ALIASES.get(raw, ()))
        for alias, extra in [] if raw in ALIASES else ALIASES.items():
            if alias == raw or len(alias) < MIN_ALIAS:
                continue
            shortest = min(len(raw), len(alias))
            if abs(len(alias) - len(raw)) > MAX_STEM_GAP:
                continue
            head = min(STEM, shortest - 1) if shortest <= STEM else STEM
            if head < 3 or raw[:head] != alias[:head]:
                continue
            expanded.extend(extra)
        for word in expanded:
            weights.setdefault(word, 0.5)
    return sorted(weights.items(), key=lambda pair: (-pair[1], pair[0]))


def _cyrillic(text: str) -> bool:
    return any("\u0400" <= char <= "\u04ff" for char in text)


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def stem_match(a: str, b: str) -> bool:
    """Russian words match on a 5-letter stem, Latin words only as whole words or plurals.

    Truncation is right for Russian inflection (``правило``/``правила``) but wrong for English,
    where it would equate unrelated words that share a prefix (``balancer`` / ``balances``).
    """
    if a == b:
        return True
    if _cyrillic(a) or _cyrillic(b):
        width = min(STEM, len(a), len(b))
        return width >= 3 and a[:width] == b[:width]
    return _singular(a) == _singular(b)


def _parts(text: str) -> list[str]:
    """Split ids into searchable words: ``vps_addLocal`` → vps / add / local."""
    spaced = CAMEL.sub(" ", text)
    seen: dict[str, None] = {}
    for token in SPLIT.split(spaced.lower()):
        if not token:
            continue
        if _cyrillic(token):
            token = token.translate(HOMOGLYPHS)
        seen.setdefault(token, None)
    return list(seen)


def _evaluate(
    op: Operation,
    q: list[tuple[str, float]],
    provider_hint: str = "",
) -> tuple[float, int, int]:
    tool_tokens = _parts(op.tool)
    path_tokens = _parts(op.path)
    product_tokens = _parts(op.product)
    summary_tokens = _parts(op.summary)
    matched_tool: set[str] = set()
    points = 0.0
    for token, weight in q:
        if token in INTENT_METHOD or (weight < 1.0 and token in INTENT_ALIASES):
            continue
        best = 0.0
        for candidate in tool_tokens:
            if stem_match(token, candidate):
                best = max(best, WEIGHT_TOOL * weight)
                matched_tool.add(candidate)
        if any(stem_match(token, t) for t in path_tokens):
            best = max(best, WEIGHT_PATH * weight)
        if weight == 1.0 and any(stem_match(token, t) for t in product_tokens):
            best = max(best, WEIGHT_PRODUCT)
        if any(stem_match(token, t) for t in summary_tokens):
            best = max(best, WEIGHT_SUMMARY * weight)
        if token == op.kind:
            best = max(best, WEIGHT_KIND * weight)
        points += best
    if provider_hint and op.provider == provider_hint:
        points += BONUS_PROVIDER_NAMED
    if points <= 0:
        return 0.0, 0, 0
    intents = {INTENT_METHOD[t] for t, w in q if w == 1.0 and t in INTENT_METHOD}
    collection_intent = bool(intents & {"get"}) and any(
        t in COLLECTION_WORDS for t, w in q if w == 1.0
    )
    if intents:
        points += WEIGHT_INTENT if op.method in intents else -PENALTY_WRONG_METHOD
    elif op.tool.endswith("_list"):
        points += BONUS_COLLECTION
    if collection_intent and op.tool.endswith("_list"):
        points += BONUS_COLLECTION
    tail = op.path.rstrip("/").rsplit("/", 1)[-1]
    if tail.startswith("{"):
        if not intents or collection_intent:
            points -= PENALTY_ITEM
    else:
        root = max((weight for token, weight in q if stem_match(token, tail)), default=0.0)
        points += BONUS_ROOT * root
        if any(weight == 1.0 and stem_match(token, op.product) for token, weight in q):
            points += BONUS_RESOURCE_ROOT
    extra = [t for t in tool_tokens if t not in matched_tool and t not in REST_VERBS]
    points -= PENALTY_EXTRA_TOKEN * min(len(extra), MAX_EXTRA)
    primary = [
        token
        for token, weight in q
        if weight == 1.0 and len(token) > 3 and token not in INTENT_METHOD
    ]
    if len(primary) > 1 and all(any(stem_match(t, c) for c in tool_tokens) for t in primary):
        points += BONUS_FULL_COVERAGE
    return points, len(matched_tool), len(extra)


def score(op: Operation, query: str) -> float:
    return _evaluate(op, tokens(query))[0]


def search(
    ops: list[Operation],
    query: str,
    limit: int,
    *,
    provider: str = "",
    product: str = "",
    kind: str = "",
) -> list[Operation]:
    q = tokens(query)
    if not q:
        return []
    named = next(
        (
            name
            for name in (provider, "timeweb", "selectel", "tilda")
            if f" {name} " in f" {query.lower()} "
        ),
        "",
    )
    scope = [
        op
        for op in ops
        if (not provider or op.provider == provider)
        and (not product or op.product == product)
        and (not kind or op.kind == kind)
    ]
    ranked = []
    for op in scope:
        points, hits, extra = _evaluate(op, q, provider_hint=named)
        if points > 0:
            ranked.append((points, hits, extra, len(op.tool), op.tool, op))
    ranked.sort(key=lambda row: (-row[0], -row[1], row[2], row[3], row[4]))
    return [row[5] for row in ranked[: max(1, limit)]]
