"""Search quality benchmark across providers, run against the shipped snapshots.

Keep top-1 >= 90% and top-3 == 100%: the discovery interface is the only entry point, a wrong
top-1 costs the model a describe + call round-trip.
"""

from __future__ import annotations

import pytest

from cloud_mcp import registry
from cloud_mcp.search import search

BENCHMARK = [
    ("reboot", "timeweb", {"servers_reboot"}),
    ("перезагрузить сервер", "timeweb", {"servers_reboot"}),
    ("выключить сервер", "timeweb", {"servers_shutdown", "servers_hard_shutdown"}),
    ("delete server", "timeweb", {"servers_delete"}),
    ("баланс", "timeweb", {"account_finances_list"}),
    ("баланс аккаунта selectel", "selectel", {"balance_balances_list"}),
    ("транзакции", "selectel", {"billing_transactions_billing_transactions_list"}),
    ("статус аккаунта", "timeweb", {"account_status_list"}),
    ("ssh ключи", "timeweb", {"ssh_keys_list", "ssh_keys_get", "ssh_keys_create"}),
    ("создать ssh ключ", "timeweb", {"ssh_keys_create"}),
    ("создать сервер", "timeweb", {"servers_create"}),
    ("список серверов", "timeweb", {"servers_list"}),
    ("снапшот диска", "timeweb", {"servers_disks_backups_list", "servers_disks_backups"}),
    ("список дисков", "timeweb", {"servers_disks_list"}),
    ("правила балансировщика", "timeweb", {"balancers_rules", "balancers_rules_list"}),
    ("балансировщик", "timeweb", {"balancers_list"}),
    ("dns записи домена", "timeweb", {"domains_dns_records", "domains_dns_records_list"}),
    ("удалить домен", "timeweb", {"domains_delete"}),
    ("dns зоны selectel", "selectel", {"dns_actual_zones_list"}),
    ("почтовый ящик", "timeweb", {"mail_list", "mail_domains_mailboxes_get"}),
    ("bucket s3", "timeweb", {"storages_buckets_list", "storages_buckets"}),
    ("список бакетов", "timeweb", {"storages_buckets_list"}),
    ("правило firewall", "timeweb", {"firewall_groups_rules", "firewall_groups_rules_list"}),
    ("обновить правило firewall", "timeweb", {"firewall_groups_rules_patch"}),
    ("стоимость сервисов", "timeweb", {"account_services_cost_list"}),
    ("резервная копия базы", "timeweb", {"databases_backups_list", "dbs_backups_list"}),
    ("удалить бэкап", "timeweb", {"dbs_backups_delete", "databases_backups_delete"}),
    ("список баз данных", "timeweb", {"databases_list"}),
    ("создать базу данных", "timeweb", {"databases_create"}),
    ("пользователи базы", "timeweb", {"databases_admins_list"}),
    ("container registry", "timeweb", {"container_registry", "container_registry_list"}),
    ("сертификат cdn", "selectel", {"cdn_certificate_list"}),
    ("привязать floating ip", "timeweb", {"floating_ips_bind"}),
    ("образы", "timeweb", {"images_list"}),
    ("скачать образ", "timeweb", {"images_download_url_list"}),
    ("список проектов", "timeweb", {"projects_list"}),
    ("тарифы серверов", "timeweb", {"presets_servers_list"}),
    ("k8s кластер", "timeweb", {"k8s_clusters", "k8s_clusters_list"}),
    ("ноды кластера", "timeweb", {"k8s_clusters_nodes_list"}),
    ("версии k8s", "timeweb", {"k8s_k8s_versions_list"}),
    ("зоны доступности", "timeweb", {"locations_list"}),
    ("настройки уведомлений", "timeweb", {"account_notification_settings_list"}),
    ("тикеты", "selectel", {"tickets_tickets_list"}),
    ("удалить тикет", "selectel", {"tickets_tickets_list", "tickets_tickets_create"}),
    ("перезагрузить vps", "sweb", {"vps_reboot"}),
    ("создать балансировщик", "sweb", {"balancer_create"}),
    ("add ip vps", "sweb", {"vps_ip_add"}),
    (
        "квоты проекта",
        "selectel",
        {"quota_management_projects_quotas_list", "quota_management_projects_limits_list"},
    ),
    ("создать кластер kubernetes selectel", "selectel", {"managed_kubernetes_clusters_create"}),
    (
        "кластеры баз данных selectel",
        "selectel",
        {"managed_databases_databases_list", "managed_databases_datastores_list"},
    ),
    ("список сайтов tilda", "tilda", {"tilda_projects_list"}),
    ("tilda список проектов", "tilda", {"tilda_projects_list"}),
    ("страницы сайта tilda", "tilda", {"tilda_pages_list"}),
    ("выгрузка проекта tilda", "tilda", {"tilda_project_export_get"}),
]


@pytest.fixture(scope="module")
def operations():
    providers = registry.load()
    return [op for provider in providers.values() for op in provider.operations]


@pytest.mark.parametrize("query,provider,tools", BENCHMARK)
def test_top1(operations, query, provider, tools):
    hits = search(operations, query, 3)
    assert (
        hits
        and (hits[0].provider, hits[0].tool) == (provider, hits[0].tool)
        and hits[0].tool in tools
    ), (
        query,
        [(h.provider, h.tool) for h in hits],
    )


def test_provider_and_product_filters(operations):
    hits = search(operations, "баланс", 10, provider="selectel")
    assert hits and all(op.provider == "selectel" for op in hits)
    hits = search(operations, "zones", 5, product="dns-actual")
    assert hits and all(op.product == "dns-actual" for op in hits)


def test_kind_filter(operations):
    assert search(operations, "перезагрузить", 5, kind="read") == []
    hits = search(operations, "delete server", 5, kind="destructive")
    assert hits and hits[0].tool == "servers_delete"


def test_junk_query_returns_nothing(operations):
    assert search(operations, "zzzz-nothing-matches", 5) == []
