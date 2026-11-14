import pytest

from sweb_mcp.config import DEFAULT_SPECS_DIR, Account, Settings


@pytest.fixture
def settings():
    return Settings(accounts=(Account("default", "u", "p"),), default_account="default",
                    readonly=False, allow_destructive=True)


@pytest.fixture
def specs_dir():
    return DEFAULT_SPECS_DIR
