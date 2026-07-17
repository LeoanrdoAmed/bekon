# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.core.common.config import USERS_JSON
from backend.core.common.json_store import read_json, write_json


def _normalize(data) -> list[dict]:
    if not isinstance(data, list):
        data = []
    users = []
    for item in data:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row.setdefault("id", "")
        row.setdefault("username", "")
        row.setdefault("username_key", "")
        row.setdefault("email", "")
        row.setdefault("email_key", "")
        row.setdefault("password_hash", "")
        row.setdefault("tenant_id", "")
        row.setdefault("tenant_slug", "")
        row.setdefault("role", "operator")
        row.setdefault("active", True)
        row.setdefault("created_at", "")
        row.setdefault("updated_at", "")
        row.setdefault("created_by", "")
        users.append(row)
    return users


def load_users() -> list[dict]:
    return _normalize(read_json(USERS_JSON, []))


def save_users(data: list[dict]) -> None:
    write_json(USERS_JSON, _normalize(data))
