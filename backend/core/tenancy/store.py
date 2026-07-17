# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.core.common.config import TENANTS_JSON
from backend.core.common.json_store import read_json, write_json


def _normalize(data) -> list[dict]:
    if not isinstance(data, list):
        data = []
    tenants = []
    for item in data:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row.setdefault("id", "")
        row.setdefault("name", "")
        row.setdefault("slug", "")
        row.setdefault("owner_user_id", "")
        row.setdefault("active", True)
        row.setdefault("created_at", "")
        row.setdefault("updated_at", "")
        row.setdefault("created_by", "")
        tenants.append(row)
    return tenants


def load_tenants() -> list[dict]:
    return _normalize(read_json(TENANTS_JSON, []))


def save_tenants(data: list[dict]) -> None:
    write_json(TENANTS_JSON, _normalize(data))

