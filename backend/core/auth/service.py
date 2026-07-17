# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import secrets

from werkzeug.security import check_password_hash, generate_password_hash

from backend.core.auth.user_store import load_users, save_users
from backend.core.common.utils import now_str
from backend.core.tenancy.service import (
    assign_tenant_owner,
    build_tenant_record,
    ensure_default_tenant,
    find_tenant_by_id,
    save_tenant_record,
)

USERNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{1,30}[a-z0-9])?$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_username(value: str) -> str:
    return str(value or "").strip().casefold()


def _normalize_email(value: str) -> str:
    return str(value or "").strip().casefold()


def _public_user(user: dict | None) -> dict | None:
    if not isinstance(user, dict):
        return None
    payload = dict(user)
    payload.pop("password_hash", None)
    payload.pop("username_key", None)
    payload.pop("email_key", None)
    return payload


def has_users() -> bool:
    return any(isinstance(user, dict) for user in load_users())


def registration_enabled(allow_self_registration: bool) -> bool:
    return bool(allow_self_registration) or not has_users()


def can_manage_users(user_role: str) -> bool:
    return str(user_role or "").strip().lower() == "admin"


def find_user_by_id(user_id: str) -> dict | None:
    target_id = str(user_id or "").strip()
    if not target_id:
        return None
    return next((user for user in load_users() if str(user.get("id") or "").strip() == target_id), None)


def find_user_by_login(login_value: str) -> dict | None:
    login = str(login_value or "").strip()
    if not login:
        return None
    username_key = _normalize_username(login)
    email_key = _normalize_email(login)
    return next(
        (
            user
            for user in load_users()
            if user.get("username_key") == username_key or (email_key and user.get("email_key") == email_key)
        ),
        None,
    )


def _resolve_user_tenant(user: dict | None) -> dict | None:
    if not isinstance(user, dict):
        return None
    tenant_id = str(user.get("tenant_id") or "").strip()
    tenant = find_tenant_by_id(tenant_id) if tenant_id else None
    if tenant:
        return tenant
    return ensure_default_tenant(created_by="auth-fallback")


def authenticate_user(login_value: str, password: str) -> tuple[bool, dict | None, str]:
    user = find_user_by_login(login_value)
    if not user or not user.get("active", True):
        return False, None, "Credenciais invalidas."

    tenant = _resolve_user_tenant(user)
    if not tenant or not tenant.get("active", True):
        return False, None, "A licenca vinculada a esse usuario esta inativa."

    password_hash = str(user.get("password_hash") or "").strip()
    if not password_hash:
        return False, None, "Essa conta nao possui senha configurada."
    try:
        if not check_password_hash(password_hash, str(password or "")):
            return False, None, "Credenciais invalidas."
    except Exception:
        return False, None, "Credenciais invalidas."

    user_payload = dict(user)
    user_payload["tenant_id"] = tenant["id"]
    user_payload["tenant_slug"] = tenant["slug"]
    user_payload["tenant_name"] = tenant["name"]
    return True, _public_user(user_payload), ""


def _validate_user_payload(
    users: list[dict],
    username: str,
    email: str,
    password: str,
    password_confirm: str,
) -> tuple[bool, str, str, str]:
    display_username = str(username or "").strip()
    username_key = _normalize_username(username)
    email_value = str(email or "").strip()
    email_key = _normalize_email(email)

    if len(display_username) < 3:
        return False, "", "", "O usuario precisa ter pelo menos 3 caracteres."
    if not USERNAME_RE.fullmatch(username_key):
        return False, "", "", "Use apenas letras, numeros, ponto, hifen ou underscore no usuario."
    if any(user.get("username_key") == username_key for user in users):
        return False, "", "", "Esse usuario ja esta em uso."

    if email_value:
        if not EMAIL_RE.fullmatch(email_value):
            return False, "", "", "Informe um e-mail valido."
        if any(user.get("email_key") == email_key for user in users if user.get("email_key")):
            return False, "", "", "Esse e-mail ja esta vinculado a outro usuario."

    if len(password) < 8:
        return False, "", "", "A senha precisa ter pelo menos 8 caracteres."
    if password != password_confirm:
        return False, "", "", "A confirmacao da senha nao confere."

    return True, display_username, username_key, ""


def create_user(
    username: str,
    email: str,
    password: str,
    password_confirm: str,
    *,
    tenant_id: str = "",
    tenant_name: str = "",
    tenant_slug: str = "",
    role: str = "operator",
    created_by: str = "self-service",
    promote_first_user_to_admin: bool = True,
) -> tuple[bool, dict | None, str]:
    users = load_users()
    password = str(password or "")
    password_confirm = str(password_confirm or "")

    valid, display_username, username_key, message = _validate_user_payload(
        users,
        username,
        email,
        password,
        password_confirm,
    )
    if not valid:
        return False, None, message

    email_value = str(email or "").strip()
    email_key = _normalize_email(email)
    tenant = None
    is_new_tenant = False
    resolved_role = str(role or "operator").strip() or "operator"
    first_user_for_tenant = False

    resolved_tenant_id = str(tenant_id or "").strip()
    if resolved_tenant_id:
        tenant = find_tenant_by_id(resolved_tenant_id)
        if not tenant:
            return False, None, "Nao encontrei a licenca vinculada a este usuario."
        if not tenant.get("active", True):
            return False, None, "A licenca selecionada esta inativa."
        first_user_for_tenant = not any(
            str(user.get("tenant_id") or "").strip() == resolved_tenant_id
            for user in users
        )
        if first_user_for_tenant and promote_first_user_to_admin:
            resolved_role = "admin"
    else:
        ok, tenant, tenant_message = build_tenant_record(
            tenant_name,
            tenant_slug,
            created_by=created_by,
        )
        if not ok or not tenant:
            return False, None, tenant_message or "Nao foi possivel criar a licenca."
        is_new_tenant = True
        first_user_for_tenant = True
        resolved_role = "admin"

    timestamp = now_str()
    user = {
        "id": f"user_{secrets.token_urlsafe(10)}",
        "username": display_username,
        "username_key": username_key,
        "email": email_value,
        "email_key": email_key,
        "password_hash": generate_password_hash(password),
        "tenant_id": tenant["id"],
        "tenant_slug": tenant["slug"],
        "role": resolved_role,
        "active": True,
        "created_at": timestamp,
        "updated_at": timestamp,
        "created_by": str(created_by or "").strip(),
    }

    if is_new_tenant:
        tenant["owner_user_id"] = user["id"]
        save_tenant_record(tenant)

    users.append(user)
    save_users(users)

    if first_user_for_tenant:
        assign_tenant_owner(tenant["id"], user["id"])

    payload = dict(user)
    payload["tenant_name"] = tenant["name"]
    return True, _public_user(payload), ""


def bootstrap_configured_user(
    username: str,
    *,
    password: str = "",
    password_hash: str = "",
    role: str = "admin",
) -> dict | None:
    display_username = str(username or "").strip()
    username_key = _normalize_username(display_username)
    password = str(password or "")
    password_hash = str(password_hash or "").strip()
    if not display_username or not username_key or not (password or password_hash):
        return None

    users = load_users()
    existing = next((user for user in users if user.get("username_key") == username_key), None)
    if existing:
        tenant = _resolve_user_tenant(existing)
        payload = dict(existing)
        if tenant:
            payload["tenant_name"] = tenant["name"]
            payload["tenant_slug"] = tenant["slug"]
            payload["tenant_id"] = tenant["id"]
        return _public_user(payload)

    tenant = ensure_default_tenant(created_by="env-bootstrap")
    created_password_hash = password_hash or generate_password_hash(password)
    timestamp = now_str()
    user = {
        "id": f"user_{secrets.token_urlsafe(10)}",
        "username": display_username,
        "username_key": username_key,
        "email": "",
        "email_key": "",
        "password_hash": created_password_hash,
        "tenant_id": tenant["id"],
        "tenant_slug": tenant["slug"],
        "role": str(role or "admin").strip() or "admin",
        "active": True,
        "created_at": timestamp,
        "updated_at": timestamp,
        "created_by": "env-bootstrap",
    }
    users.append(user)
    save_users(users)
    assign_tenant_owner(tenant["id"], user["id"])

    payload = dict(user)
    payload["tenant_name"] = tenant["name"]
    return _public_user(payload)
