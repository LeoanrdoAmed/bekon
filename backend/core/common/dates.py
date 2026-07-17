# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache


def parse_date(value: str | None):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    return _parse_date_cached(text)


@lru_cache(maxsize=8192)
def _parse_date_cached(text: str):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except Exception:
            continue
    digits = re.sub(r"[^\d]", "", text)
    if len(digits) >= 8:
        for fmt in ("%Y%m%d", "%d%m%Y"):
            try:
                return datetime.strptime(digits[:8], fmt).date()
            except Exception:
                continue
    return None


def normalize_date_str(value: str | None) -> str:
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else ""
