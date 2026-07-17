# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.core.common.config import accounts_json
from backend.core.common.json_store import read_json, write_json
from backend.core.openfinance.helpers import normalize_credit_cards


def _normalize(data) -> list[dict]:
    if not isinstance(data, list):
        data = []
    items = []
    for item in data:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row.setdefault("id", "")
        row.setdefault("apelido", "")
        row.setdefault("titular", "")
        row.setdefault("banco", "")
        row.setdefault("agencia", "")
        row.setdefault("conta", "")
        row.setdefault("saldo_inicial", 0.0)
        row.setdefault("openfinance_payer_cpf_cnpj", "")
        row.setdefault("openfinance_account_hash", "")
        row.setdefault("openfinance_id", "")
        row.setdefault("openfinance_link", "")
        row.setdefault("openfinance_remote_status", "")
        row.setdefault("openfinance_last_status", "")
        row.setdefault("openfinance_last_error", "")
        row.setdefault("openfinance_agencia_dig", "")
        row.setdefault("openfinance_conta_dig", "")
        row.setdefault("openfinance_account_type", "")
        row.setdefault("openfinance_account_payment", False)
        row.setdefault("openfinance_webservice", False)
        row.setdefault("openfinance_recipient_notification", False)
        row.setdefault("ativo", True)
        row["openfinance_credit_cards"] = normalize_credit_cards(row.get("openfinance_credit_cards"))
        items.append(row)
    return items


def load_accounts(*, only_active: bool = False) -> list[dict]:
    items = _normalize(read_json(accounts_json(), []))
    if only_active:
        return [item for item in items if item.get("ativo")]
    return items


def save_accounts(data: list[dict]) -> None:
    write_json(accounts_json(), _normalize(data))
