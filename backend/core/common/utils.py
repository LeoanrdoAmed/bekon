# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
from datetime import datetime


def digits_only(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def sha1_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def sha1_bytes(value: bytes) -> str:
    return hashlib.sha1(value).hexdigest()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def money_to_float(value) -> float:
    if value is None:
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    text = text.replace("R$", "").replace(".", "").replace(",", ".")
    try:
        return float(text)
    except Exception:
        return 0.0


def format_currency(value) -> str:
    number = round(float(value or 0.0), 2)
    return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
