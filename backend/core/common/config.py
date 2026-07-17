# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "dados"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TENANTS_DIR = DATA_DIR / "tenants"
TENANTS_DIR.mkdir(parents=True, exist_ok=True)

TENANTS_JSON = DATA_DIR / "tenants.json"
USERS_JSON = DATA_DIR / "users.json"

TENANT_FILE_NAMES = {
    "openfinance_config": "openfinance_config.json",
    "openfinance_payers": "openfinance_payers.json",
    "openfinance_api_log": "openfinance_api_log.jsonl",
    "accounts": "accounts.json",
    "statement_imports": "statement_imports.json",
    "chat_sessions": "chat_sessions.json",
    "customer_profile": "customer_profile.json",
    "onboarding_state": "onboarding_state.json",
}

LEGACY_OPENFINANCE_CONFIG_JSON = DATA_DIR / TENANT_FILE_NAMES["openfinance_config"]
LEGACY_OPENFINANCE_PAYERS_JSON = DATA_DIR / TENANT_FILE_NAMES["openfinance_payers"]
LEGACY_OPENFINANCE_API_LOG_JSONL = DATA_DIR / TENANT_FILE_NAMES["openfinance_api_log"]
LEGACY_ACCOUNTS_JSON = DATA_DIR / TENANT_FILE_NAMES["accounts"]
LEGACY_STATEMENT_IMPORTS_JSON = DATA_DIR / TENANT_FILE_NAMES["statement_imports"]
LEGACY_CHAT_SESSIONS_JSON = DATA_DIR / TENANT_FILE_NAMES["chat_sessions"]
LEGACY_CUSTOMER_PROFILE_JSON = DATA_DIR / TENANT_FILE_NAMES["customer_profile"]
LEGACY_ONBOARDING_STATE_JSON = DATA_DIR / TENANT_FILE_NAMES["onboarding_state"]

LEGACY_TENANT_FILE_MAP = {
    TENANT_FILE_NAMES["openfinance_config"]: LEGACY_OPENFINANCE_CONFIG_JSON,
    TENANT_FILE_NAMES["openfinance_payers"]: LEGACY_OPENFINANCE_PAYERS_JSON,
    TENANT_FILE_NAMES["openfinance_api_log"]: LEGACY_OPENFINANCE_API_LOG_JSONL,
    TENANT_FILE_NAMES["accounts"]: LEGACY_ACCOUNTS_JSON,
    TENANT_FILE_NAMES["statement_imports"]: LEGACY_STATEMENT_IMPORTS_JSON,
    TENANT_FILE_NAMES["chat_sessions"]: LEGACY_CHAT_SESSIONS_JSON,
    TENANT_FILE_NAMES["customer_profile"]: LEGACY_CUSTOMER_PROFILE_JSON,
    TENANT_FILE_NAMES["onboarding_state"]: LEGACY_ONBOARDING_STATE_JSON,
}


def _current_tenant_slug(default: str = "default") -> str:
    from backend.core.tenancy.context import get_current_tenant_slug

    return get_current_tenant_slug(default=default)


def tenant_data_dir(tenant_slug: str) -> Path:
    path = TENANTS_DIR / (str(tenant_slug or "").strip().lower() or "default")
    path.mkdir(parents=True, exist_ok=True)
    return path


def tenant_data_file(filename: str, *, tenant_slug: str | None = None) -> Path:
    return tenant_data_dir(tenant_slug or _current_tenant_slug()) / str(filename or "").strip()


def openfinance_config_json(*, tenant_slug: str | None = None) -> Path:
    return tenant_data_file(TENANT_FILE_NAMES["openfinance_config"], tenant_slug=tenant_slug)


def openfinance_payers_json(*, tenant_slug: str | None = None) -> Path:
    return tenant_data_file(TENANT_FILE_NAMES["openfinance_payers"], tenant_slug=tenant_slug)


def openfinance_api_log_jsonl(*, tenant_slug: str | None = None) -> Path:
    return tenant_data_file(TENANT_FILE_NAMES["openfinance_api_log"], tenant_slug=tenant_slug)


def accounts_json(*, tenant_slug: str | None = None) -> Path:
    return tenant_data_file(TENANT_FILE_NAMES["accounts"], tenant_slug=tenant_slug)


def statement_imports_json(*, tenant_slug: str | None = None) -> Path:
    return tenant_data_file(TENANT_FILE_NAMES["statement_imports"], tenant_slug=tenant_slug)


def chat_sessions_json(*, tenant_slug: str | None = None) -> Path:
    return tenant_data_file(TENANT_FILE_NAMES["chat_sessions"], tenant_slug=tenant_slug)


def customer_profile_json(*, tenant_slug: str | None = None) -> Path:
    return tenant_data_file(TENANT_FILE_NAMES["customer_profile"], tenant_slug=tenant_slug)


def onboarding_state_json(*, tenant_slug: str | None = None) -> Path:
    return tenant_data_file(TENANT_FILE_NAMES["onboarding_state"], tenant_slug=tenant_slug)


def ensure_project_root_cwd() -> None:
    os.chdir(PROJECT_ROOT)
