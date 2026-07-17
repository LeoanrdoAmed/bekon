# -*- coding: utf-8 -*-
from __future__ import annotations

import os

from backend.core.common.config import LEGACY_OPENFINANCE_CONFIG_JSON, openfinance_config_json
from backend.core.common.json_store import read_json, write_json

DEFAULT_STAGING_BASE_URL = "https://staging.pagamentobancario.com.br/api/v1"
DEFAULT_PRODUCTION_BASE_URL = "https://api.pagamentobancario.com.br/api/v1"


def _normalize(data) -> dict:
    if not isinstance(data, dict):
        data = {}
    payload = dict(data)
    payload.setdefault("environment", "production")
    payload.setdefault("base_url", DEFAULT_PRODUCTION_BASE_URL)
    payload.setdefault("cnpjsh", "")
    payload.setdefault("tokensh", "")
    if (
        str(payload.get("environment") or "").strip().lower() == "staging"
        and str(payload.get("base_url") or "").strip() in {"", DEFAULT_STAGING_BASE_URL}
    ):
        payload["environment"] = "production"
        payload["base_url"] = DEFAULT_PRODUCTION_BASE_URL
    return payload


def _persistable(payload: dict) -> dict:
    stored = _normalize(payload)
    if str(os.getenv("OPENFINANCE_CNPJSH", "")).strip():
        stored["cnpjsh"] = ""
    if str(os.getenv("OPENFINANCE_TOKENSH", "")).strip():
        stored["tokensh"] = ""
    return stored


def _has_credentials(payload: dict) -> bool:
    return bool(str(payload.get("cnpjsh") or "").strip() and str(payload.get("tokensh") or "").strip())


def _apply_global_fallback(payload: dict) -> tuple[dict, bool]:
    if _has_credentials(payload):
        return payload, False

    legacy_payload = _normalize(read_json(LEGACY_OPENFINANCE_CONFIG_JSON, {}))
    if not _has_credentials(legacy_payload):
        return payload, False

    resolved = dict(payload)
    if not str(resolved.get("cnpjsh") or "").strip():
        resolved["cnpjsh"] = legacy_payload.get("cnpjsh") or ""
    if not str(resolved.get("tokensh") or "").strip():
        resolved["tokensh"] = legacy_payload.get("tokensh") or ""
    if not str(resolved.get("environment") or "").strip():
        resolved["environment"] = legacy_payload.get("environment") or "production"
    if not str(resolved.get("base_url") or "").strip():
        resolved["base_url"] = legacy_payload.get("base_url") or DEFAULT_PRODUCTION_BASE_URL
    return _normalize(resolved), True


def load_openfinance_config() -> dict:
    path = openfinance_config_json()
    stored_payload = _normalize(read_json(path, {}))
    payload, used_global_fallback = _apply_global_fallback(stored_payload)
    env_environment = str(os.getenv("OPENFINANCE_ENVIRONMENT", "")).strip().lower()
    env_base_url = str(os.getenv("OPENFINANCE_BASE_URL", "")).strip()
    env_cnpjsh = str(os.getenv("OPENFINANCE_CNPJSH", "")).strip()
    env_tokensh = str(os.getenv("OPENFINANCE_TOKENSH", "")).strip()
    if env_environment in {"staging", "production"}:
        payload["environment"] = env_environment
    if env_base_url:
        payload["base_url"] = env_base_url
    if env_cnpjsh:
        payload["cnpjsh"] = env_cnpjsh
    if env_tokensh:
        payload["tokensh"] = env_tokensh

    persist_payload = dict(payload)
    if used_global_fallback:
        if not str(stored_payload.get("cnpjsh") or "").strip():
            persist_payload["cnpjsh"] = ""
        if not str(stored_payload.get("tokensh") or "").strip():
            persist_payload["tokensh"] = ""
    sanitized = _persistable(persist_payload)
    if sanitized != stored_payload:
        write_json(path, sanitized)
    return payload


def save_openfinance_config(data: dict) -> None:
    write_json(openfinance_config_json(), _persistable(data))
