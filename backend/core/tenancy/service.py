# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import secrets
import shutil
import unicodedata

from backend.core.common.config import (
    LEGACY_TENANT_FILE_MAP,
    TENANT_FILE_NAMES,
    tenant_data_file,
    tenant_data_dir,
)
from backend.core.common.json_store import read_json
from backend.core.common.utils import now_str
from backend.core.tenancy.store import load_tenants, save_tenants

DEFAULT_TENANT_ID = "tenant_default"
DEFAULT_TENANT_SLUG = "default"
DEFAULT_TENANT_NAME = "Ambiente principal"
TENANT_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])?$")


def _public_tenant(tenant: dict | None) -> dict | None:
    if not isinstance(tenant, dict):
        return None
    return {
        "id": str(tenant.get("id") or "").strip(),
        "name": str(tenant.get("name") or "").strip(),
        "slug": str(tenant.get("slug") or "").strip().lower(),
        "owner_user_id": str(tenant.get("owner_user_id") or "").strip(),
        "active": bool(tenant.get("active", True)),
        "created_at": str(tenant.get("created_at") or "").strip(),
        "updated_at": str(tenant.get("updated_at") or "").strip(),
        "created_by": str(tenant.get("created_by") or "").strip(),
    }


def list_tenants() -> list[dict]:
    tenants = [_public_tenant(item) for item in load_tenants()]
    tenants = [item for item in tenants if item]
    tenants.sort(key=lambda item: item.get("created_at") or item.get("name") or "")
    return tenants


def has_tenants() -> bool:
    return any(isinstance(item, dict) for item in load_tenants())


def find_tenant_by_id(tenant_id: str) -> dict | None:
    tenant_id = str(tenant_id or "").strip()
    if not tenant_id:
        return None
    return next(
        (_public_tenant(item) for item in load_tenants() if str(item.get("id") or "").strip() == tenant_id),
        None,
    )


def find_tenant_by_slug(slug: str) -> dict | None:
    slug = str(slug or "").strip().lower()
    if not slug:
        return None
    return next(
        (_public_tenant(item) for item in load_tenants() if str(item.get("slug") or "").strip().lower() == slug),
        None,
    )


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip())
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:40].strip("-")


def build_tenant_record(name: str, slug: str = "", *, created_by: str = "self-service") -> tuple[bool, dict | None, str]:
    display_name = str(name or "").strip()
    if len(display_name) < 2:
        return False, None, "Informe o nome da empresa ou licenca."

    explicit_slug = str(slug or "").strip().lower()
    base_slug = explicit_slug or _slugify(display_name) or "tenant"
    if explicit_slug and not TENANT_SLUG_RE.fullmatch(base_slug):
        return False, None, "Use apenas letras minusculas, numeros e hifen no identificador da licenca."

    existing_slugs = {
        str(item.get("slug") or "").strip().lower()
        for item in load_tenants()
        if isinstance(item, dict)
    }

    resolved_slug = base_slug
    if explicit_slug:
        if resolved_slug in existing_slugs:
            return False, None, "Esse identificador de licenca ja esta em uso."
    else:
        suffix = 2
        while resolved_slug in existing_slugs:
            short_base = base_slug[: max(3, 40 - len(str(suffix)) - 1)].rstrip("-") or "tenant"
            resolved_slug = f"{short_base}-{suffix}"
            suffix += 1

    if not TENANT_SLUG_RE.fullmatch(resolved_slug):
        return False, None, "Nao consegui gerar um identificador valido para a licenca."

    timestamp = now_str()
    tenant = {
        "id": f"tenant_{secrets.token_urlsafe(10)}",
        "name": display_name,
        "slug": resolved_slug,
        "owner_user_id": "",
        "active": True,
        "created_at": timestamp,
        "updated_at": timestamp,
        "created_by": str(created_by or "").strip() or "self-service",
    }
    return True, tenant, ""


def save_tenant_record(tenant: dict) -> dict:
    tenants = load_tenants()
    saved = dict(tenant or {})
    saved["slug"] = str(saved.get("slug") or "").strip().lower()
    saved["updated_at"] = now_str()
    for index, current in enumerate(tenants):
        if str(current.get("id") or "").strip() == str(saved.get("id") or "").strip():
            tenants[index] = saved
            break
    else:
        tenants.append(saved)
    save_tenants(tenants)
    tenant_data_dir(saved["slug"])
    return _public_tenant(saved)


def ensure_default_tenant(*, created_by: str = "system") -> dict:
    existing = find_tenant_by_id(DEFAULT_TENANT_ID) or find_tenant_by_slug(DEFAULT_TENANT_SLUG)
    if existing:
        tenant_data_dir(existing["slug"])
        return existing

    tenant = {
        "id": DEFAULT_TENANT_ID,
        "name": DEFAULT_TENANT_NAME,
        "slug": DEFAULT_TENANT_SLUG,
        "owner_user_id": "",
        "active": True,
        "created_at": now_str(),
        "updated_at": now_str(),
        "created_by": str(created_by or "").strip() or "system",
    }
    return save_tenant_record(tenant)


def bootstrap_tenant_storage(*, ensure_default_if_empty: bool = False) -> dict | None:
    default_tenant = None
    if ensure_default_if_empty and not has_tenants():
        default_tenant = ensure_default_tenant(created_by="bootstrap")

    from backend.core.auth.user_store import load_users, save_users

    users = load_users()
    missing_tenant = any(not str(user.get("tenant_id") or "").strip() for user in users)
    orphan_tenant = any(
        str(user.get("tenant_id") or "").strip()
        and not find_tenant_by_id(str(user.get("tenant_id") or "").strip())
        for user in users
    )
    legacy_data_exists = any(path.exists() and path.stat().st_size > 0 for path in LEGACY_TENANT_FILE_MAP.values())
    if default_tenant is None and (legacy_data_exists or users or missing_tenant or orphan_tenant):
        default_tenant = ensure_default_tenant(created_by="legacy-migration")

    if default_tenant:
        for filename, source_path in LEGACY_TENANT_FILE_MAP.items():
            target_path = tenant_data_file(filename, tenant_slug=default_tenant["slug"])
            if source_path.exists() and not target_path.exists():
                shutil.copy2(source_path, target_path)

        changed = False
        for user in users:
            tenant_id = str(user.get("tenant_id") or "").strip()
            tenant = find_tenant_by_id(tenant_id) if tenant_id else None
            if not tenant:
                tenant = default_tenant
                user["tenant_id"] = tenant["id"]
                changed = True
            tenant_slug = str(user.get("tenant_slug") or "").strip().lower()
            if tenant_slug != tenant["slug"]:
                user["tenant_slug"] = tenant["slug"]
                changed = True
            if not str(user.get("updated_at") or "").strip():
                user["updated_at"] = now_str()
                changed = True
        if changed:
            save_users(users)

    return default_tenant


def assign_tenant_owner(tenant_id: str, user_id: str) -> dict | None:
    tenant = find_tenant_by_id(tenant_id)
    if not tenant:
        return None
    tenant["owner_user_id"] = str(user_id or "").strip()
    return save_tenant_record(tenant)


def _tenant_has_meaningful_data(tenant: dict) -> bool:
    tenant_slug = str((tenant or {}).get("slug") or "").strip().lower()
    if not tenant_slug:
        return False

    profile = read_json(tenant_data_file(TENANT_FILE_NAMES["customer_profile"], tenant_slug=tenant_slug), {})
    if isinstance(profile, dict):
        for key in ("nome", "cpf", "email", "telefone", "logradouro", "numero", "bairro", "cidade", "estado", "cep"):
            if str(profile.get(key) or "").strip():
                return True

    for data_key in ("accounts", "statement_imports", "openfinance_payers"):
        payload = read_json(tenant_data_file(TENANT_FILE_NAMES[data_key], tenant_slug=tenant_slug), [])
        if isinstance(payload, list) and payload:
            return True

    return False


def list_claimable_tenants() -> list[dict]:
    from backend.core.auth.user_store import load_users

    users_by_tenant = {
        str(user.get("tenant_id") or "").strip()
        for user in load_users()
        if isinstance(user, dict) and str(user.get("tenant_id") or "").strip()
    }

    claimable = []
    for tenant in list_tenants():
        tenant_id = str(tenant.get("id") or "").strip()
        if not tenant_id or tenant_id in users_by_tenant:
            continue
        if not tenant.get("active", True):
            continue
        if not _tenant_has_meaningful_data(tenant):
            continue
        claimable.append(tenant)
    return claimable


def get_claimable_tenant() -> dict | None:
    tenants = list_claimable_tenants()
    if len(tenants) != 1:
        return None
    return tenants[0]
