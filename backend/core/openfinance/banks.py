# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import unicodedata


BANK_OPTIONS = [
    ("001", "Banco do Brasil"),
    ("003", "Banco da Amazonia"),
    ("004", "Banco do Nordeste"),
    ("021", "Banestes"),
    ("033", "Santander"),
    ("041", "Banrisul"),
    ("047", "Banese"),
    ("070", "BRB"),
    ("077", "Inter"),
    ("085", "Ailos"),
    ("102", "SC XP Investimentos"),
    ("104", "Caixa"),
    ("121", "Agibank"),
    ("133", "Cresol"),
    ("136", "Unicred"),
    ("197", "Stone"),
    ("208", "BTG Pactual"),
    ("212", "Banco Original"),
    ("218", "BS2"),
    ("237", "Bradesco"),
    ("246", "Banco ABC Brasil"),
    ("260", "Nubank"),
    ("290", "PagBank"),
    ("318", "BMG"),
    ("323", "Mercado Pago"),
    ("336", "C6 Bank"),
    ("341", "Itau"),
    ("348", "Banco XP"),
    ("380", "PicPay"),
    ("389", "Banco Mercantil do Brasil"),
    ("422", "Safra"),
    ("623", "Pan"),
    ("633", "Rendimento"),
    ("637", "Sofisa"),
    ("655", "Banco BV"),
    ("707", "Daycoval"),
    ("745", "Citibank"),
    ("748", "Sicredi"),
    ("756", "Sicoob"),
]

BANK_MAP = {code: label for code, label in BANK_OPTIONS}

_BASE_ALIASES = {
    "bb": "001",
    "caixa": "104",
    "caixa economica": "104",
    "caixa economica federal": "104",
    "itau": "341",
    "itau unibanco": "341",
    "nubank": "260",
    "nu": "260",
    "pagbank": "290",
    "pag seguro": "290",
    "pagseguro": "290",
    "mercado pago": "323",
    "c6": "336",
    "c6 bank": "336",
    "btg": "208",
    "btg pactual": "208",
    "xp banco": "348",
    "xp banking": "348",
    "xp bank": "348",
    "banco xp": "348",
    "xp investimentos": "102",
    "xp investimento": "102",
    "sc xp investimentos": "102",
    "xp corretora": "102",
    "xp invest": "102",
    "picpay": "380",
    "bv": "655",
    "banco bv": "655",
    "pan": "623",
    "banco pan": "623",
    "original": "212",
    "stone": "197",
}


def _normalize_bank_lookup(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


BANK_ALIASES = {key: value for key, value in _BASE_ALIASES.items()}
for bank_code, bank_label in BANK_OPTIONS:
    normalized_label = _normalize_bank_lookup(bank_label)
    if normalized_label:
        BANK_ALIASES.setdefault(normalized_label, bank_code)
        if normalized_label.startswith("banco "):
            BANK_ALIASES.setdefault(normalized_label.removeprefix("banco ").strip(), bank_code)


def resolve_bank_code(value: str) -> str:
    raw = str(value or "").strip()
    digits = "".join(char for char in raw if char.isdigit())
    if len(digits) == 3:
        return digits

    normalized = _normalize_bank_lookup(raw)
    if normalized == "xp":
        return ""
    if normalized in BANK_ALIASES:
        return BANK_ALIASES[normalized]
    if normalized.startswith("banco "):
        return BANK_ALIASES.get(normalized.removeprefix("banco ").strip(), "")
    return ""
