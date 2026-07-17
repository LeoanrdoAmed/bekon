# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.core.common.config import openfinance_payers_json
from backend.core.common.json_store import read_json, write_json


def _normalize(data) -> list[dict]:
    if not isinstance(data, list):
        data = []
    result = []
    for item in data:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row.setdefault("id", "")
        row.setdefault("cpf_cnpj", "")
        row.setdefault("nome", "")
        row.setdefault("email", "")
        row.setdefault("telefone", "")
        row.setdefault("logradouro", "")
        row.setdefault("numero", "")
        row.setdefault("bairro", "")
        row.setdefault("complemento", "")
        row.setdefault("cidade", "")
        row.setdefault("estado", "")
        row.setdefault("cep", "")
        row.setdefault("statement_actived", False)
        row.setdefault("tecnospeed_status", "")
        row.setdefault("last_error", "")
        row.setdefault("last_api_at", "")
        result.append(row)
    return result


def load_openfinance_payers() -> list[dict]:
    return _normalize(read_json(openfinance_payers_json(), []))


def save_openfinance_payers(data: list[dict]) -> None:
    write_json(openfinance_payers_json(), _normalize(data))
