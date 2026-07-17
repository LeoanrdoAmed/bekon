# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.core.common.config import statement_imports_json
from backend.core.common.json_store import read_json, write_json
from backend.core.openfinance.helpers import normalize_card_number, normalize_statement_type


def _normalize_tx_list(data) -> list[dict]:
    if not isinstance(data, list):
        data = []
    items = []
    for item in data:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row.setdefault("id", "")
        row.setdefault("external_id", "")
        row.setdefault("data", "")
        row.setdefault("valor", 0.0)
        row.setdefault("tipo", "")
        row.setdefault("descricao", "")
        row.setdefault("categoria", "")
        row.setdefault("subcategoria", "")
        items.append(row)
    return items


def _normalize(data) -> list[dict]:
    if not isinstance(data, list):
        data = []
    items = []
    for item in data:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row.setdefault("id", "")
        row.setdefault("account_id", "")
        row.setdefault("account_label", "")
        row.setdefault("created_at", "")
        row.setdefault("updated_at", "")
        row.setdefault("period_start", "")
        row.setdefault("period_end", "")
        row.setdefault("unique_id", "")
        row.setdefault("status", "")
        row.setdefault("reason", "")
        row.setdefault("origin", "openfinance")
        row["statement_type"] = normalize_statement_type(row.get("statement_type"))
        row["card_number"] = normalize_card_number(row.get("card_number"))
        row["transactions"] = _normalize_tx_list(row.get("transactions"))
        items.append(row)
    return items


def load_statement_imports() -> list[dict]:
    return _normalize(read_json(statement_imports_json(), []))


def save_statement_imports(data: list[dict]) -> None:
    write_json(statement_imports_json(), _normalize(data))
