# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import getpass
import os
import secrets
import sys
from pathlib import Path

from werkzeug.security import generate_password_hash

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.auth.service import bootstrap_configured_user  # noqa: E402
from backend.core.auth.user_store import load_users, save_users  # noqa: E402
from backend.core.common.utils import now_str  # noqa: E402


def _normalize_username(value: str) -> str:
    return str(value or "").strip().casefold()


def _password_from_args(args: argparse.Namespace) -> tuple[str, bool]:
    env_password = str(os.getenv(args.password_env) or "")
    if env_password:
        return env_password, False

    if args.generate:
        return secrets.token_urlsafe(24), True

    password = getpass.getpass("Nova senha local: ")
    password_confirm = getpass.getpass("Confirme a senha local: ")
    if password != password_confirm:
        raise ValueError("A confirmacao da senha nao confere.")
    return password, False


def _write_password_file(path_value: str, password: str) -> Path:
    target = (PROJECT_ROOT / path_value).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(password + "\n", encoding="utf-8")
    return target


def reset_local_password(username: str, password: str, *, create: bool, role: str) -> str:
    users = load_users()
    username_key = _normalize_username(username)
    user = next((item for item in users if item.get("username_key") == username_key), None)

    if user:
        user["password_hash"] = generate_password_hash(password)
        user["updated_at"] = now_str()
        save_users(users)
        return "reset"

    if not create:
        raise LookupError(f"Usuario local '{username}' nao encontrado em dados/users.json.")

    created = bootstrap_configured_user(username, password=password, role=role)
    if not created:
        raise RuntimeError(f"Nao foi possivel criar o usuario local '{username}'.")
    return "created"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reseta a senha de um usuario local sem versionar o segredo.",
    )
    parser.add_argument("username", help="Usuario local a atualizar, por exemplo: fontenelle")
    parser.add_argument(
        "--password-env",
        default="APP_AUTH_PASSWORD",
        help="Variavel de ambiente com a nova senha. Padrao: APP_AUTH_PASSWORD.",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Gera uma senha forte localmente quando a variavel de ambiente nao estiver definida.",
    )
    parser.add_argument(
        "--password-file",
        default="",
        help="Arquivo local para gravar a senha gerada. Use apenas com --generate.",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        help="Cria o usuario local se ele ainda nao existir.",
    )
    parser.add_argument(
        "--role",
        default="admin",
        help="Perfil usado quando --create cria um usuario. Padrao: admin.",
    )
    args = parser.parse_args()

    try:
        password, generated = _password_from_args(args)
        if len(password) < 8:
            raise ValueError("A senha precisa ter pelo menos 8 caracteres.")
        if args.password_file and not generated:
            raise ValueError("Use --password-file apenas junto com --generate.")

        action = reset_local_password(
            args.username,
            password,
            create=args.create,
            role=str(args.role or "admin").strip() or "admin",
        )

        if generated and args.password_file:
            path = _write_password_file(args.password_file, password)
            print(f"Senha gerada gravada localmente em: {path}")
        elif generated:
            print(f"Senha gerada: {password}")

        print(f"Usuario {action}: {args.username}")
        return 0
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
