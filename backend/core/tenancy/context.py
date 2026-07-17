# -*- coding: utf-8 -*-
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from flask import has_request_context, session

TENANT_SESSION_ID_KEY = "_auth_tenant_id"
TENANT_SESSION_SLUG_KEY = "_auth_tenant_slug"
TENANT_SESSION_NAME_KEY = "_auth_tenant_name"

_TENANT_ID = ContextVar("tenant_id", default="")
_TENANT_SLUG = ContextVar("tenant_slug", default="")
_TENANT_NAME = ContextVar("tenant_name", default="")


def _session_value(key: str) -> str:
    if not has_request_context():
        return ""
    return str(session.get(key) or "").strip()


def bind_current_tenant(tenant_id: str, tenant_slug: str, tenant_name: str = "") -> None:
    _TENANT_ID.set(str(tenant_id or "").strip())
    _TENANT_SLUG.set(str(tenant_slug or "").strip().lower())
    _TENANT_NAME.set(str(tenant_name or "").strip())


def clear_current_tenant() -> None:
    bind_current_tenant("", "", "")


def get_current_tenant_id(*, default: str = "") -> str:
    return _session_value(TENANT_SESSION_ID_KEY) or str(_TENANT_ID.get() or "").strip() or default


def get_current_tenant_slug(*, default: str = "") -> str:
    return _session_value(TENANT_SESSION_SLUG_KEY) or str(_TENANT_SLUG.get() or "").strip().lower() or default


def get_current_tenant_name(*, default: str = "") -> str:
    return _session_value(TENANT_SESSION_NAME_KEY) or str(_TENANT_NAME.get() or "").strip() or default


@contextmanager
def tenant_scope(tenant_id: str, tenant_slug: str, tenant_name: str = ""):
    token_id = _TENANT_ID.set(str(tenant_id or "").strip())
    token_slug = _TENANT_SLUG.set(str(tenant_slug or "").strip().lower())
    token_name = _TENANT_NAME.set(str(tenant_name or "").strip())
    try:
        yield
    finally:
        _TENANT_ID.reset(token_id)
        _TENANT_SLUG.reset(token_slug)
        _TENANT_NAME.reset(token_name)

