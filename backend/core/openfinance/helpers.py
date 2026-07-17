# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime

from backend.core.common.dates import normalize_date_str
from backend.core.common.utils import digits_only, sha1_text
from backend.core.finance.categorizer import categorize_transaction_details
from backend.core.openfinance.banks import BANK_MAP


def normalize_statement_type(value) -> str:
    return "CREDIT_CARD" if str(value or "").strip().upper() == "CREDIT_CARD" else "ACCOUNT"


def normalize_card_number(value) -> str:
    digits = digits_only(value)
    return digits[-4:] if len(digits) >= 4 else digits


def normalize_credit_cards(raw_cards) -> list[dict]:
    if isinstance(raw_cards, dict):
        raw_cards = [raw_cards]
    if not isinstance(raw_cards, list):
        raw_cards = []
    cards = []
    seen = set()
    for idx, item in enumerate(raw_cards):
        label = ""
        number = ""
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("nome") or "").strip()
            number = str(item.get("card_number") or item.get("final") or item.get("last4") or "")
        else:
            number = str(item or "")
        number = normalize_card_number(number)
        if len(number) != 4:
            continue
        key = (label.lower(), number)
        if key in seen:
            continue
        seen.add(key)
        cards.append({
            "id": f"card_{idx}_{number}",
            "label": label or "Cartao",
            "card_number": number,
        })
    return cards


def format_scope_label(statement_type, card_number: str = "") -> str:
    statement_type = normalize_statement_type(statement_type)
    card_number = normalize_card_number(card_number)
    if statement_type == "CREDIT_CARD":
        return f"Cartao final {card_number}" if len(card_number) == 4 else "Cartao de credito"
    return "Conta bancaria"


def format_import_name(unique_id: str = "", statement_type="ACCOUNT", card_number: str = "") -> str:
    scope = format_scope_label(statement_type, card_number)
    return f"Open Finance {scope} ({unique_id})" if unique_id else f"Open Finance {scope}"


def build_account_label(account: dict) -> str:
    bank_code = str(account.get("banco") or "").strip()
    bank_label = BANK_MAP.get(bank_code) or bank_code or "Conta"
    agency = str(account.get("agencia") or "").strip()
    number = str(account.get("conta") or "").strip()
    alias = str(account.get("apelido") or "").strip()
    base = " / ".join(part for part in [bank_label, f"Ag {agency}" if agency else "", f"Conta {number}" if number else ""] if part)
    return f"{alias} - {base}" if alias and base else alias or base or "Conta"


def build_account_scope_label(account: dict, statement_type="ACCOUNT", card_number: str = "") -> str:
    account_label = build_account_label(account)
    scope = format_scope_label(statement_type, card_number)
    if statement_type != "CREDIT_CARD":
        return account_label
    return f"{account_label} | {scope}"


def _category_text(value) -> str:
    if isinstance(value, dict):
        value = (
            value.get("description")
            or value.get("label")
            or value.get("name")
            or value.get("category")
            or value.get("code")
            or ""
        )
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("_", " ").replace("-", " ")
    return " ".join(part.capitalize() for part in text.split())


def parse_openfinance_transactions(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        return []

    tx_section = None
    for key in ("transaction", "transactions"):
        if isinstance(payload.get(key), dict):
            tx_section = payload.get(key)
            break
    if tx_section is None and isinstance(payload.get("statement"), dict):
        statement = payload.get("statement") or {}
        if isinstance(statement.get("transaction"), dict):
            tx_section = statement.get("transaction")

    transactions = []
    base_ts = int(datetime.now().timestamp() * 1000)

    def pick(source: dict, keys: list[str], default=None):
        for key in keys:
            if key in source and source.get(key) not in (None, ""):
                return source.get(key)
        return default

    def add_items(items, direction: str):
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_value = pick(item, ["amount", "value", "valor", "transactionAmount", "amountTotal"], 0)
            try:
                value = float(str(raw_value).replace(",", "."))
            except Exception:
                value = 0.0
            if direction == "DEBIT" and value > 0:
                value = -value
            if direction == "CREDIT" and value < 0:
                value = abs(value)
            raw_id = str(pick(item, ["id", "transactionId", "idTransaction", "uniqueId", "fitid", "hash"], "")).strip()
            if not raw_id:
                raw_id = sha1_text(json.dumps(item, ensure_ascii=False, sort_keys=True))
            raw_desc = str(pick(item, ["description", "historic", "narrative", "memo", "title", "history"], "")).strip()
            raw_category = _category_text(pick(item, ["transaction_category", "transactionCategory", "category", "categoria"], ""))
            raw_subcategory = _category_text(pick(item, ["transaction_subcategory", "transactionSubcategory", "subcategory", "subcategoria"], ""))
            category, subcategory = categorize_transaction_details(
                raw_desc or direction,
                value,
                api_category=raw_category,
                api_subcategory=raw_subcategory,
            )
            transactions.append({
                "id": f"tx_{base_ts}_{len(transactions)}",
                "external_id": raw_id,
                "data": normalize_date_str(str(pick(item, ["date", "transactionDate", "dateTime", "movementDate", "postedDate", "bookingDate"], ""))),
                "valor": round(value, 2),
                "tipo": direction,
                "descricao": raw_desc or direction,
                "categoria": category,
                "subcategoria": subcategory,
            })

    credit = None
    debit = None
    if tx_section and isinstance(tx_section.get("credit"), (dict, list)):
        credit = tx_section.get("credit")
    if tx_section and isinstance(tx_section.get("debit"), (dict, list)):
        debit = tx_section.get("debit")
    if tx_section is None and isinstance(payload.get("credit"), dict):
        credit = payload.get("credit")
    if tx_section is None and isinstance(payload.get("debit"), dict):
        debit = payload.get("debit")

    if isinstance(credit, list):
        add_items(credit, "CREDIT")
    else:
        add_items((credit or {}).get("transaction") or [], "CREDIT")
    if isinstance(debit, list):
        add_items(debit, "DEBIT")
    else:
        add_items((debit or {}).get("transaction") or [], "DEBIT")

    return transactions
