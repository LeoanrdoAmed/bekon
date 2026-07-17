# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import secrets
from datetime import timedelta

from flask import Flask, flash, jsonify, redirect, request, session, url_for
from markupsafe import Markup, escape
from werkzeug.middleware.proxy_fix import ProxyFix

from backend.core.auth.service import bootstrap_configured_user, can_manage_users, has_users, registration_enabled
from backend.core.common.config import PROJECT_ROOT, ensure_project_root_cwd
from backend.core.openfinance.client import sanitize_all_openfinance_logs
from backend.core.tenancy.context import (
    TENANT_SESSION_ID_KEY,
    TENANT_SESSION_NAME_KEY,
    TENANT_SESSION_SLUG_KEY,
    bind_current_tenant,
    clear_current_tenant,
)
from backend.core.tenancy.service import DEFAULT_TENANT_SLUG, bootstrap_tenant_storage

TRUTHY_VALUES = {"1", "true", "on", "yes"}
CSRF_SESSION_KEY = "_csrf_token"
AUTH_SESSION_KEY = "_auth_user"
AUTH_ROLE_SESSION_KEY = "_auth_user_role"


def _flag_from_env(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in TRUTHY_VALUES


def _csrf_token() -> str:
    token = str(session.get(CSRF_SESSION_KEY) or "").strip()
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def _csrf_input() -> Markup:
    return Markup(
        f'<input type="hidden" name="csrf_token" value="{escape(_csrf_token())}">'
    )


def _invalid_csrf_response():
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "CSRF token invalido."}), 400
    flash("Sua sessao expirou ou a requisicao nao e confiavel. Tente novamente.", "danger")
    if request.endpoint in {"main.login", "main.register"}:
        return redirect(url_for("main.login"))
    return redirect(request.referrer or url_for("main.dashboard"))


def create_app() -> Flask:
    ensure_project_root_cwd()

    debug_enabled = _flag_from_env("APP_DEBUG", True)
    secret_key = str(os.getenv("APP_SECRET_KEY", "")).strip()
    if not secret_key:
        if debug_enabled:
            secret_key = "fin-na-mao-local-dev"
        else:
            raise RuntimeError("APP_SECRET_KEY precisa estar configurada quando APP_DEBUG=0.")

    auth_enabled = _flag_from_env("APP_AUTH_ENABLED", True)
    auth_username = str(os.getenv("APP_AUTH_USERNAME", "admin")).strip() or "admin"
    auth_password = str(os.getenv("APP_AUTH_PASSWORD", ""))
    auth_password_hash = str(os.getenv("APP_AUTH_PASSWORD_HASH", "")).strip()
    allow_self_registration = _flag_from_env("APP_ALLOW_SELF_REGISTRATION", debug_enabled)

    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "templates"),
        static_folder=str(PROJECT_ROOT / "static"),
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1, x_proto=1)
    app.config["SECRET_KEY"] = secret_key
    app.config["DEBUG"] = debug_enabled
    app.config["HOST"] = os.getenv("HOST", "127.0.0.1")
    app.config["PORT"] = os.getenv("PORT", "8000")
    app.config["JSON_AS_ASCII"] = False
    app.config["AUTH_ENABLED"] = auth_enabled
    app.config["AUTH_USERNAME"] = auth_username
    app.config["AUTH_PASSWORD"] = auth_password
    app.config["AUTH_PASSWORD_HASH"] = auth_password_hash
    app.config["ALLOW_SELF_REGISTRATION"] = allow_self_registration
    app.config["SESSION_COOKIE_NAME"] = "fin_na_mao_session"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = _flag_from_env(
        "APP_SESSION_COOKIE_SECURE",
        not debug_enabled,
    )
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)
    default_tenant = bootstrap_tenant_storage(ensure_default_if_empty=not auth_enabled)
    if default_tenant:
        app.config["DEFAULT_TENANT_ID"] = default_tenant["id"]
        app.config["DEFAULT_TENANT_NAME"] = default_tenant["name"]
        app.config["DEFAULT_TENANT_SLUG"] = default_tenant["slug"]
    else:
        app.config["DEFAULT_TENANT_ID"] = ""
        app.config["DEFAULT_TENANT_NAME"] = ""
        app.config["DEFAULT_TENANT_SLUG"] = DEFAULT_TENANT_SLUG

    bootstrap_configured_user(
        auth_username,
        password=auth_password,
        password_hash=auth_password_hash,
        role="admin",
    )
    if not app.config.get("DEFAULT_TENANT_ID"):
        default_tenant = bootstrap_tenant_storage()
        if default_tenant:
            app.config["DEFAULT_TENANT_ID"] = default_tenant["id"]
            app.config["DEFAULT_TENANT_NAME"] = default_tenant["name"]
            app.config["DEFAULT_TENANT_SLUG"] = default_tenant["slug"]
    if auth_enabled and not registration_enabled(allow_self_registration) and not has_users():
        raise RuntimeError(
            "Autenticacao habilitada sem usuarios locais. Defina credenciais bootstrap ou libere auto cadastro."
        )

    @app.context_processor
    def inject_security_helpers():
        return {
            "auth_enabled": bool(app.config.get("AUTH_ENABLED")),
            "authenticated_user": str(session.get(AUTH_SESSION_KEY) or "").strip(),
            "authenticated_user_role": str(session.get(AUTH_ROLE_SESSION_KEY) or "operator").strip() or "operator",
            "current_tenant_name": (
                str(session.get(TENANT_SESSION_NAME_KEY) or "").strip()
                or str(app.config.get("DEFAULT_TENANT_NAME") or "").strip()
            ),
            "current_tenant_slug": (
                str(session.get(TENANT_SESSION_SLUG_KEY) or "").strip()
                or str(app.config.get("DEFAULT_TENANT_SLUG") or DEFAULT_TENANT_SLUG).strip()
            ),
            "csrf_input": _csrf_input,
            "csrf_token": _csrf_token,
            "registration_enabled": registration_enabled(bool(app.config.get("ALLOW_SELF_REGISTRATION"))),
            "can_manage_users": can_manage_users(str(session.get(AUTH_ROLE_SESSION_KEY) or "").strip()),
        }

    @app.template_filter("nl2br")
    def nl2br(value):
        return Markup("<br>\n").join(escape(str(value or "")).splitlines())

    @app.before_request
    def enforce_security():
        clear_current_tenant()
        if request.method in {"GET", "HEAD", "OPTIONS"} and not session.get(CSRF_SESSION_KEY):
            session[CSRF_SESSION_KEY] = secrets.token_urlsafe(32)

        if request.endpoint == "static" or request.path.startswith("/static/"):
            return None

        if request.endpoint == "main.healthz":
            return None

        authenticated_user = str(session.get(AUTH_SESSION_KEY) or "").strip()
        tenant_id = str(session.get(TENANT_SESSION_ID_KEY) or "").strip()
        tenant_slug = str(session.get(TENANT_SESSION_SLUG_KEY) or "").strip().lower()
        tenant_name = str(session.get(TENANT_SESSION_NAME_KEY) or "").strip()

        if authenticated_user and not tenant_slug:
            tenant_id = str(app.config.get("DEFAULT_TENANT_ID") or "").strip()
            tenant_slug = str(app.config.get("DEFAULT_TENANT_SLUG") or DEFAULT_TENANT_SLUG).strip().lower()
            tenant_name = str(app.config.get("DEFAULT_TENANT_NAME") or "").strip()
            if tenant_id:
                session.setdefault(TENANT_SESSION_ID_KEY, tenant_id)
            if tenant_slug:
                session.setdefault(TENANT_SESSION_SLUG_KEY, tenant_slug)
            if tenant_name:
                session.setdefault(TENANT_SESSION_NAME_KEY, tenant_name)
        elif not authenticated_user and not app.config.get("AUTH_ENABLED"):
            tenant_id = str(app.config.get("DEFAULT_TENANT_ID") or "").strip()
            tenant_slug = str(app.config.get("DEFAULT_TENANT_SLUG") or DEFAULT_TENANT_SLUG).strip().lower()
            tenant_name = str(app.config.get("DEFAULT_TENANT_NAME") or "").strip()

        if tenant_slug:
            bind_current_tenant(tenant_id, tenant_slug, tenant_name)

        if app.config.get("AUTH_ENABLED") and request.endpoint not in {"main.login", "main.register"} and not authenticated_user:
            next_url = request.full_path.rstrip("?") or request.path
            login_url = url_for("main.login", next=next_url)
            if request.path.startswith("/api/"):
                return jsonify({
                    "ok": False,
                    "error": "Autenticacao necessaria.",
                    "login_url": login_url,
                }), 401
            return redirect(login_url)

        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None

        expected_token = str(session.get(CSRF_SESSION_KEY) or "").strip()
        received_token = str(request.headers.get("X-CSRF-Token") or "").strip()
        if not received_token:
            received_token = str(request.form.get("csrf_token") or "").strip()
        if not received_token:
            payload = request.get_json(silent=True)
            if isinstance(payload, dict):
                received_token = str(payload.get("csrf_token") or "").strip()
        if not expected_token or not received_token or not secrets.compare_digest(expected_token, received_token):
            return _invalid_csrf_response()
        return None

    @app.teardown_request
    def clear_tenant_scope(_error):
        clear_current_tenant()

    @app.after_request
    def apply_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
        )
        return response

    sanitize_all_openfinance_logs()

    from backend.routes import main_bp

    app.register_blueprint(main_bp)
    return app
