# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.core.common.config import LEGACY_OPENFINANCE_API_LOG_JSONL, TENANTS_DIR, openfinance_api_log_jsonl
from backend.core.common.utils import digits_only, now_str

REDACTED_TEXT = "[redacted]"
REDACTED_LINK = "[redacted-link]"
FULL_REDACT_KEYS = {
    "authorization",
    "password",
    "secret",
    "token",
    "tokensh",
    "x-api-key",
}
MASK_KEYS = {
    "accountdac",
    "accounthash",
    "accountnumber",
    "accountnumberdigit",
    "agency",
    "agencydigit",
    "cardnumber",
    "cnpjsh",
    "cpf",
    "cpfcnpj",
    "cpf_cnpj",
    "openfinanceid",
    "payercpfcnpj",
    "zipcode",
}
PII_REDACT_KEYS = {
    "addresscomplement",
    "addressnumber",
    "bairro",
    "city",
    "complemento",
    "email",
    "logradouro",
    "name",
    "neighborhood",
    "nome",
    "numero",
    "state",
    "street",
    "telefone",
    "titular",
}


def _mask_value(value: str, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return "*" * (len(value) - keep) + value[-keep:]


def _base_url(cfg: dict) -> str:
    env_url = os.getenv("OPENFINANCE_BASE_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")
    custom = str(cfg.get("base_url") or "").strip()
    if custom:
        return custom.rstrip("/")
    if str(cfg.get("environment") or "").strip().lower() == "production":
        return "https://api.pagamentobancario.com.br/api/v1"
    return "https://staging.pagamentobancario.com.br/api/v1"


def _truncate_text(text: str, limit: int = 2000) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[:limit] + "...(truncado)"


def _mask_email(value: str) -> str:
    text = str(value or "").strip()
    if not text or "@" not in text:
        return REDACTED_TEXT if text else ""
    local_part, _, domain = text.partition("@")
    if len(local_part) <= 2:
        masked_local = "*" * len(local_part)
    else:
        masked_local = local_part[:1] + ("*" * (len(local_part) - 2)) + local_part[-1:]
    return f"{masked_local}@{domain}"


def _key_name(key) -> str:
    return "".join(ch for ch in str(key or "").strip().lower() if ch.isalnum() or ch == "_")


def _sanitize_scalar(value, *, key: str = ""):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value

    text = str(value or "").strip()
    normalized_key = _key_name(key)
    if not text:
        return text
    if normalized_key in FULL_REDACT_KEYS:
        return REDACTED_TEXT
    if normalized_key in PII_REDACT_KEYS:
        return _mask_email(text) if normalized_key == "email" else REDACTED_TEXT
    if normalized_key.endswith("link"):
        return REDACTED_LINK
    if normalized_key in MASK_KEYS:
        digits = digits_only(text)
        return _mask_value(digits or text)
    return _truncate_text(text)


def _maybe_parse_json_text(value):
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "{[":
        return value
    try:
        return json.loads(text)
    except Exception:
        return value


def _sanitize_for_log(value, *, key: str = ""):
    if isinstance(value, str) and _key_name(key) in {"headers", "payload", "response"}:
        parsed = _maybe_parse_json_text(value)
        if parsed is not value:
            return _sanitize_for_log(parsed, key=key)
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_for_log(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_for_log(item, key=key) for item in value]
    return _sanitize_scalar(value, key=key)


def _sanitize_log_entry(entry: dict) -> dict:
    sanitized = {}
    for key, value in dict(entry or {}).items():
        if key == "url":
            sanitized[key] = _truncate_text(str(value or ""))
            continue
        sanitized[key] = _sanitize_for_log(value, key=key)
    return sanitized


def sanitize_existing_openfinance_logs(path: Path | None = None) -> None:
    path = Path(path or openfinance_api_log_jsonl())
    if not path.exists():
        return

    sanitized_lines = []
    changed = False
    try:
        with open(path, "r", encoding="utf-8") as file:
            for raw_line in file:
                text = raw_line.strip()
                if not text:
                    continue
                try:
                    entry = json.loads(text)
                except Exception:
                    continue
                sanitized = _sanitize_log_entry(entry)
                if sanitized != entry:
                    changed = True
                sanitized_lines.append(json.dumps(sanitized, ensure_ascii=False))
        if not changed:
            return
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=f".{path.stem}_",
            suffix=path.suffix or ".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write("\n".join(sanitized_lines))
                if sanitized_lines:
                    file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
    except Exception:
        return


def sanitize_all_openfinance_logs() -> None:
    sanitize_existing_openfinance_logs(LEGACY_OPENFINANCE_API_LOG_JSONL)
    if not TENANTS_DIR.exists():
        return
    for tenant_dir in TENANTS_DIR.iterdir():
        if not tenant_dir.is_dir():
            continue
        sanitize_existing_openfinance_logs(tenant_dir / "openfinance_api_log.jsonl")


def _log_openfinance_call(entry: dict) -> None:
    try:
        path = Path(openfinance_api_log_jsonl())
        path.parent.mkdir(parents=True, exist_ok=True)
        entry["at"] = now_str()
        entry = _sanitize_log_entry(entry)
        with open(path, "a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _headers(cfg: dict, payer_cpf_cnpj: str | None = None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "fin-na-mao/1.0",
    }
    cnpjsh = str(cfg.get("cnpjsh") or "").strip()
    tokensh = str(cfg.get("tokensh") or "").strip()
    payer = str(payer_cpf_cnpj or cfg.get("payer_cpf_cnpj") or "").strip()
    if cnpjsh:
        headers["cnpjsh"] = cnpjsh
    if tokensh:
        headers["tokensh"] = tokensh
    if payer:
        headers["payercpfcnpj"] = payer
    return headers


def openfinance_request(
    cfg: dict,
    method: str,
    path: str,
    *,
    payload: dict | list | None = None,
    params: dict | None = None,
    timeout: int = 30,
    include_payer_header: bool = True,
):
    url = f"{_base_url(cfg)}/{path.lstrip('/')}"
    if params:
        url += "?" + urlencode({key: value for key, value in params.items() if value is not None})
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    if include_payer_header:
        headers = _headers(cfg)
    else:
        headers = _headers({"cnpjsh": cfg.get("cnpjsh"), "tokensh": cfg.get("tokensh")})
    req = Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read()
            status = getattr(response, "status", 200)
            try:
                data = json.loads(raw.decode("utf-8"))
                _log_openfinance_call({
                    "ok": True,
                    "status": status,
                    "method": method.upper(),
                    "path": path,
                    "url": url,
                    "headers": {
                        "cnpjsh": cfg.get("cnpjsh") or "",
                        "tokensh": _mask_value(cfg.get("tokensh") or ""),
                        "payercpfcnpj": _mask_value(headers.get("payercpfcnpj") or ""),
                    },
                    "payload": payload,
                    "response": data,
                })
                return True, status, data, None
            except Exception:
                text = raw.decode("utf-8", errors="ignore")
                _log_openfinance_call({
                    "ok": True,
                    "status": status,
                    "method": method.upper(),
                    "path": path,
                    "url": url,
                    "headers": {
                        "cnpjsh": cfg.get("cnpjsh") or "",
                        "tokensh": _mask_value(cfg.get("tokensh") or ""),
                        "payercpfcnpj": _mask_value(headers.get("payercpfcnpj") or ""),
                    },
                    "payload": payload,
                    "response": text,
                })
                return True, status, text, None
    except HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", errors="ignore")
            try:
                data = json.loads(raw)
            except Exception:
                data = {"raw": raw} if raw else None
        except Exception:
            data = None
        _log_openfinance_call({
            "ok": False,
            "status": getattr(exc, "code", 0),
            "method": method.upper(),
            "path": path,
            "url": url,
            "headers": {
                "cnpjsh": cfg.get("cnpjsh") or "",
                "tokensh": _mask_value(cfg.get("tokensh") or ""),
                "payercpfcnpj": _mask_value(headers.get("payercpfcnpj") or ""),
            },
            "payload": payload,
            "response": data if isinstance(data, (dict, list)) else str(data or ""),
            "error": str(exc),
        })
        return False, getattr(exc, "code", 0), data, str(exc)
    except Exception as exc:
        _log_openfinance_call({
            "ok": False,
            "status": 0,
            "method": method.upper(),
            "path": path,
            "url": url,
            "headers": {
                "cnpjsh": cfg.get("cnpjsh") or "",
                "tokensh": _mask_value(cfg.get("tokensh") or ""),
                "payercpfcnpj": _mask_value(headers.get("payercpfcnpj") or ""),
            },
            "payload": payload,
            "response": "",
            "error": str(exc),
        })
        return False, 0, None, f"{exc} @ {now_str()}"
