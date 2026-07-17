# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import math
import re
import secrets
import time
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from backend.core.auth.service import authenticate_user, can_manage_users, create_user, has_users, registration_enabled
from backend.core.ai.chat_service import append_session_messages, ensure_session, get_session, list_sessions, send_chat_message, update_session_data
from backend.core.common.config import openfinance_api_log_jsonl
from backend.core.common.dates import normalize_date_str, parse_date
from backend.core.common.utils import digits_only, format_currency, money_to_float, now_str
from backend.core.customer.profile_store import load_customer_profile, save_customer_profile
from backend.core.finance.analytics import backfill_statement_import_categories, build_dashboard_summary, filter_transactions, list_transactions
from backend.core.onboarding.state_store import load_onboarding_state, save_onboarding_state
from backend.core.openfinance.accounts_store import load_accounts, save_accounts
from backend.core.openfinance.banks import BANK_MAP, BANK_OPTIONS, resolve_bank_code
from backend.core.openfinance.client import openfinance_request
from backend.core.openfinance.config_store import load_openfinance_config
from backend.core.openfinance.helpers import build_account_label, normalize_card_number, normalize_credit_cards
from backend.core.openfinance.payers_store import load_openfinance_payers, save_openfinance_payers
from backend.core.openfinance.service import (
    create_remote_account,
    create_statement_protocol,
    refresh_remote_account,
    refresh_statement_protocol,
    run_automatic_statement_updates,
    validate_openfinance_account,
)
from backend.core.openfinance.statements_store import load_statement_imports, save_statement_imports
from backend.core.tenancy.context import TENANT_SESSION_ID_KEY, TENANT_SESSION_NAME_KEY, TENANT_SESSION_SLUG_KEY, tenant_scope
from backend.core.tenancy.service import get_claimable_tenant

main_bp = Blueprint("main", __name__)

HIDDEN_PAYER_ID = "payer_customer_default"
DASHBOARD_TX_PAGE_SIZE = 10
AUTH_USER_SESSION_KEY = "_auth_user"
AUTH_USER_ID_SESSION_KEY = "_auth_user_id"
AUTH_USER_ROLE_SESSION_KEY = "_auth_user_role"

DASHBOARD_PERIOD_OPTIONS = [
    ("all", "Todo periodo"),
    ("this_month", "Este mes"),
    ("30d", "Ultimos 30 dias"),
    ("90d", "Ultimos 90 dias"),
    ("6m", "Ultimos 6 meses"),
    ("this_year", "Este ano"),
]

PROFILE_FIELD_LABELS = {
    "nome": "Nome completo ou razao social",
    "cpf": "CPF ou CNPJ",
    "email": "E-mail",
    "telefone": "Telefone",
    "logradouro": "Logradouro",
    "numero": "Numero",
    "bairro": "Bairro",
    "complemento": "Complemento",
    "cidade": "Cidade",
    "estado": "UF",
    "cep": "CEP",
}

ACCOUNT_FIELD_LABELS = {
    "apelido": "Apelido da conta",
    "banco": "Banco",
    "agencia": "Agencia",
    "conta": "Conta",
    "saldo_inicial": "Saldo inicial",
}

CARD_FIELD_LABELS = {
    "label": "Nome do cartao",
    "card_number": "Ultimos 4 digitos",
}

PROFILE_FIELDS = [
    {
        "key": "nome",
        "question": "Vamos comecar. Qual e o nome completo ou a razao social do cliente?",
        "input_type": "text",
        "placeholder": "Nome completo ou razao social",
        "required": True,
    },
    {
        "key": "cpf",
        "question": "Agora me diga o CPF ou CNPJ do cliente.",
        "input_type": "text",
        "placeholder": "CPF ou CNPJ, somente numeros",
        "required": True,
    },
    {
        "key": "email",
        "question": "Qual e o melhor e-mail para avisos e relatorios? Se preferir, voce pode pular.",
        "input_type": "email",
        "placeholder": "cliente@exemplo.com",
        "required": False,
    },
    {
        "key": "telefone",
        "question": "Quer deixar um telefone para contato? Tambem pode pular.",
        "input_type": "text",
        "placeholder": "(00) 00000-0000",
        "required": False,
    },
    {
        "key": "logradouro",
        "question": "Qual e o logradouro do cliente?",
        "input_type": "text",
        "placeholder": "Rua, avenida, travessa...",
        "required": True,
    },
    {
        "key": "numero",
        "question": "E o numero do endereco?",
        "input_type": "text",
        "placeholder": "Numero",
        "required": True,
    },
    {
        "key": "bairro",
        "question": "Qual e o bairro?",
        "input_type": "text",
        "placeholder": "Bairro",
        "required": True,
    },
    {
        "key": "complemento",
        "question": "Tem complemento? Se nao tiver, pode pular.",
        "input_type": "text",
        "placeholder": "Apto, bloco, casa...",
        "required": False,
    },
    {
        "key": "cidade",
        "question": "Qual e a cidade?",
        "input_type": "text",
        "placeholder": "Cidade",
        "required": True,
    },
    {
        "key": "estado",
        "question": "E a UF do endereco?",
        "input_type": "text",
        "placeholder": "Ex.: SP",
        "required": True,
    },
    {
        "key": "cep",
        "question": "Por fim, qual e o CEP?",
        "input_type": "text",
        "placeholder": "Somente numeros",
        "required": True,
    },
]

ACCOUNT_FIELDS = [
    {
        "key": "apelido",
        "question": "Vamos cadastrar uma conta. Como voce quer chamar essa conta?",
        "input_type": "text",
        "placeholder": "Ex.: Itau principal",
        "required": True,
    },
    {
        "key": "banco",
        "question": "Em qual banco essa conta esta?",
        "input_type": "select",
        "placeholder": "",
        "required": True,
    },
    {
        "key": "agencia",
        "question": "Qual e a agencia dessa conta?",
        "input_type": "text",
        "placeholder": "Numero da agencia",
        "required": True,
    },
    {
        "key": "conta",
        "question": "Agora me diga o numero da conta.",
        "input_type": "text",
        "placeholder": "Numero da conta",
        "required": True,
    },
    {
        "key": "saldo_inicial",
        "question": "Se quiser, informe o saldo inicial dessa conta. Se nao quiser, pode pular.",
        "input_type": "text",
        "placeholder": "0,00",
        "required": False,
    },
]

CARD_FIELDS = [
    {
        "key": "label",
        "question_template": "Qual e o nome do cartao vinculado a conta \"{account_label}\"?",
        "input_type": "text",
        "placeholder": "Ex.: Visa Black",
        "required": True,
    },
    {
        "key": "card_number",
        "question_template": "Quais sao os 4 ultimos digitos desse cartao?",
        "input_type": "text",
        "placeholder": "1234",
        "required": True,
    },
]


def _is_authenticated() -> bool:
    return bool(str(session.get(AUTH_USER_SESSION_KEY) or "").strip())


def _public_registration_enabled() -> bool:
    return registration_enabled(bool(current_app.config.get("ALLOW_SELF_REGISTRATION")))


def _current_user_role() -> str:
    return str(session.get(AUTH_USER_ROLE_SESSION_KEY) or "operator").strip() or "operator"


def _can_manage_users() -> bool:
    return _is_authenticated() and can_manage_users(_current_user_role())


def _safe_redirect_target(candidate: str) -> str:
    target = str(candidate or "").strip()
    if not target:
        return url_for("main.dashboard")
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return url_for("main.dashboard")
    if not target.startswith("/") or target.startswith("//"):
        return url_for("main.dashboard")
    return target


def _start_authenticated_session(user: dict) -> None:
    session.clear()
    session[AUTH_USER_SESSION_KEY] = str(user.get("username") or "").strip()
    session[AUTH_USER_ID_SESSION_KEY] = str(user.get("id") or "").strip()
    session[AUTH_USER_ROLE_SESSION_KEY] = str(user.get("role") or "operator").strip() or "operator"
    session[TENANT_SESSION_ID_KEY] = str(user.get("tenant_id") or "").strip()
    session[TENANT_SESSION_SLUG_KEY] = str(user.get("tenant_slug") or "").strip().lower()
    session[TENANT_SESSION_NAME_KEY] = str(user.get("tenant_name") or "").strip()
    session["_csrf_token"] = secrets.token_urlsafe(32)
    session["authenticated_at"] = now_str()
    session.permanent = True


def _load_openfinance_logs(limit: int = 40) -> list[dict]:
    path = Path(openfinance_api_log_jsonl())
    if not path.exists():
        return []
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as file:
            for line in file:
                text = line.strip()
                if not text:
                    continue
                try:
                    row = json.loads(text)
                    for key in ("headers", "payload", "response"):
                        if isinstance(row.get(key), (dict, list)):
                            row[key] = json.dumps(row[key], ensure_ascii=False, indent=2)
                    rows.append(row)
                except Exception:
                    continue
    except Exception:
        return []
    rows.reverse()
    return rows[:limit]


def _pending_authorization_count(accounts: list[dict]) -> int:
    total = 0
    for account in accounts:
        if not account.get("ativo", True):
            continue
        validation_note = validate_openfinance_account(account)
        if validation_note:
            total += 1
            continue
        if not str(account.get("openfinance_account_hash") or "").strip():
            total += 1
            continue
        remote_status = str(account.get("openfinance_remote_status") or "").strip().upper()
        if remote_status not in {"ATIVO", "ACTIVE"}:
            total += 1
    return total


def _build_primary_chat_activity(accounts: list[dict] | None = None) -> dict | None:
    accounts = accounts if accounts is not None else load_accounts()
    for account in accounts:
        if not account.get("ativo", True):
            continue
        account_id = str(account.get("id") or "").strip()
        account_label = build_account_label(account)
        validation_note = validate_openfinance_account(account)
        if validation_note:
            lowered_note = validation_note.casefold()
            if "infraestrutura" in lowered_note:
                actions = [
                    {
                        "kind": "link",
                        "label": "Abrir configuracao",
                        "href": url_for("main.connections"),
                    },
                ]
            elif "dados do titular" in lowered_note:
                actions = [
                    {
                        "kind": "api",
                        "action": "restart_onboarding_chat",
                        "label": "Corrigir cadastro",
                    },
                ]
            else:
                actions = [
                    {
                        "kind": "api",
                        "action": "retry_payer_activation",
                        "label": "Tentar novamente",
                        "account_id": account_id,
                    },
                ]
            return {
                "title": f'Preciso validar o titular da conta "{account_label}".',
                "content": validation_note,
                "actions": actions,
            }

        if not str(account.get("openfinance_account_hash") or "").strip():
            return {
                "title": f'Posso preparar a conta "{account_label}" agora.',
                "content": "Isso cria a conexao segura e gera o link de autorizacao do banco.",
                "actions": [
                    {
                        "kind": "api",
                        "action": "prepare_account_connection",
                        "label": "Preparar conta",
                        "account_id": account_id,
                    },
                ],
            }

        remote_status = str(account.get("openfinance_remote_status") or "").strip().upper()
        if remote_status not in {"ATIVO", "ACTIVE"}:
            actions = []
            if str(account.get("openfinance_link") or "").strip():
                actions.append({
                    "kind": "link",
                    "label": "Abrir banco",
                    "href": str(account.get("openfinance_link") or "").strip(),
                })
            actions.append({
                "kind": "api",
                "action": "check_account_authorization",
                "label": "Ja autorizei",
                "account_id": account_id,
            })
            return {
                "title": f'Agora autorize a conta "{account_label}" no banco.',
                "content": "Abra o banco, conclua o consentimento e depois volte aqui para eu verificar o status.",
                "actions": actions,
            }

    profile = load_customer_profile()
    if not _setup_complete(profile, accounts):
        return {
            "title": "Antes das autorizacoes, preciso concluir o cadastro inicial.",
            "content": "Complete cliente, conta e cartao aqui no proprio chat para eu seguir com as autorizacoes.",
            "actions": [
                {
                    "kind": "api",
                    "action": "restart_onboarding_chat",
                    "label": "Continuar cadastro",
                },
            ],
        }
    return None


def _pending_edit(session: dict | None) -> dict:
    pending = (session or {}).get("pending_edit")
    return dict(pending) if isinstance(pending, dict) else {}


def _pending_setup(session: dict | None) -> dict:
    pending = (session or {}).get("pending_setup")
    return dict(pending) if isinstance(pending, dict) else {}


def _state_message_entries(state: dict, start_index: int) -> list[dict]:
    entries = []
    for item in (state.get("messages") or [])[start_index:]:
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if not role or not content:
            continue
        entries.append({
            "role": role,
            "content": content,
        })
    return entries


def _latest_state_assistant_message(state: dict) -> str:
    for item in reversed(state.get("messages") or []):
        if str(item.get("role") or "").strip() == "assistant":
            return str(item.get("content") or "").strip()
    return ""


def _current_onboarding_field_key(state: dict) -> str:
    stage = str(state.get("stage") or "").strip()
    cursor = int(state.get("cursor") or 0)
    if stage == "profile" and 0 <= cursor < len(PROFILE_FIELDS):
        return PROFILE_FIELDS[cursor]["key"]
    if stage == "accounts" and 0 <= cursor < len(ACCOUNT_FIELDS):
        return ACCOUNT_FIELDS[cursor]["key"]
    if stage == "cards" and 0 <= cursor < len(CARD_FIELDS):
        return CARD_FIELDS[cursor]["key"]
    return ""


def _editable_cards_for_chat(accounts: list[dict]) -> list[dict]:
    items = []
    for account in accounts:
        account_id = str(account.get("id") or "").strip()
        for card in account.get("openfinance_credit_cards") or []:
            number = normalize_card_number(card.get("card_number"))
            if len(number) != 4:
                continue
            items.append({
                "account_id": account_id,
                "card_number": number,
                "label": f'{build_account_label(account)} - {card.get("label") or "Cartao"} final {number}',
            })
    return items


def _build_correction_chat_activity(session: dict | None, accounts: list[dict]) -> dict:
    pending = _pending_edit(session)
    if not pending:
        return {
            "title": "Precisa corrigir algum dado do cadastro?",
            "content": "Voce pode ajustar cliente, conta ou cartao por aqui sem sair do chat.",
            "actions": [
                {"kind": "api", "action": "start_profile_correction", "label": "Corrigir cliente"},
                {"kind": "api", "action": "start_account_correction", "label": "Corrigir conta"},
                {"kind": "api", "action": "start_card_correction", "label": "Corrigir cartao"},
            ],
        }

    mode = str(pending.get("mode") or "").strip()
    step = str(pending.get("step") or "").strip()
    cancel_action = {"kind": "api", "action": "cancel_correction", "label": "Cancelar"}

    if mode == "profile" and step == "choose_field":
        return {
            "title": "Qual dado do cliente voce quer corrigir?",
            "content": "Escolha o campo e depois me envie o novo valor na conversa.",
            "actions": [
                {
                    "kind": "api",
                    "action": "choose_profile_field",
                    "label": label,
                    "field_key": key,
                }
                for key, label in PROFILE_FIELD_LABELS.items()
            ] + [cancel_action],
        }

    if mode == "account" and step == "choose_account":
        active_accounts = [account for account in accounts if account.get("ativo", True)]
        return {
            "title": "Qual conta voce quer corrigir?",
            "content": "Escolha a conta para eu abrir os campos editaveis.",
            "actions": [
                {
                    "kind": "api",
                    "action": "choose_account_for_correction",
                    "label": build_account_label(account),
                    "account_id": str(account.get("id") or "").strip(),
                }
                for account in active_accounts
            ] + [cancel_action],
        }

    if mode == "account" and step == "choose_field":
        account_id = str(pending.get("account_id") or "").strip()
        account = next((item for item in accounts if str(item.get("id") or "").strip() == account_id), None)
        account_label = build_account_label(account or {})
        return {
            "title": f'Qual campo da conta "{account_label}" voce quer corrigir?',
            "content": "Depois da escolha, me diga o novo valor aqui no chat.",
            "actions": [
                {
                    "kind": "api",
                    "action": "choose_account_field",
                    "label": label,
                    "account_id": account_id,
                    "field_key": key,
                }
                for key, label in ACCOUNT_FIELD_LABELS.items()
            ] + [cancel_action],
        }

    if mode == "card" and step == "choose_card":
        cards = _editable_cards_for_chat(accounts)
        return {
            "title": "Qual cartao voce quer corrigir?",
            "content": "Escolha o cartao para eu abrir os campos editaveis.",
            "actions": [
                {
                    "kind": "api",
                    "action": "choose_card_for_correction",
                    "label": item["label"],
                    "account_id": item["account_id"],
                    "card_number": item["card_number"],
                }
                for item in cards
            ] + [cancel_action],
        }

    if mode == "card" and step == "choose_field":
        account_id = str(pending.get("account_id") or "").strip()
        card_number = normalize_card_number(pending.get("card_number"))
        account = next((item for item in accounts if str(item.get("id") or "").strip() == account_id), None)
        return {
            "title": f'Qual dado do cartao final {card_number} voce quer corrigir?',
            "content": f'Conta vinculada: {build_account_label(account or {})}. Depois da escolha, me envie o novo valor no chat.',
            "actions": [
                {
                    "kind": "api",
                    "action": "choose_card_field",
                    "label": label,
                    "account_id": account_id,
                    "card_number": card_number,
                    "field_key": key,
                }
                for key, label in CARD_FIELD_LABELS.items()
            ] + [cancel_action],
        }

    if step == "await_value":
        field_key = str(pending.get("field_key") or "").strip()
        label = (
            PROFILE_FIELD_LABELS.get(field_key)
            or ACCOUNT_FIELD_LABELS.get(field_key)
            or CARD_FIELD_LABELS.get(field_key)
            or field_key
        )
        return {
            "title": f"Envie o novo valor para {label}.",
            "content": "Responda na caixa de mensagem abaixo. Quando eu salvar, a atividade volta ao estado normal.",
            "actions": [cancel_action],
        }

    return {
        "title": "Correcao em andamento",
        "content": "Use os botoes abaixo para concluir ou cancelar essa edicao.",
        "actions": [cancel_action],
    }


def _build_onboarding_chat_activity(session: dict | None, accounts: list[dict]) -> dict | None:
    profile = load_customer_profile()
    state = _ensure_onboarding_state(profile, accounts)
    prompt = _current_onboarding_prompt(state, accounts)
    pending_setup = _pending_setup(session)
    active_accounts = [account for account in accounts if account.get("ativo", True)]

    if pending_setup.get("mode") == "choose_card_account":
        return {
            "title": "Em qual conta voce quer adicionar um novo cartao?",
            "content": "Escolha a conta abaixo e eu sigo com o cadastro conversacional do cartao.",
            "actions": [
                {
                    "kind": "api",
                    "action": "choose_card_account_for_add",
                    "label": build_account_label(account),
                    "account_id": str(account.get("id") or "").strip(),
                }
                for account in active_accounts
            ] + [
                {
                    "kind": "api",
                    "action": "cancel_setup_pending",
                    "label": "Cancelar",
                }
            ],
            "focus": True,
        }

    stage = str(state.get("stage") or "").strip()
    if prompt and stage in {"profile", "accounts", "cards"}:
        question = _latest_state_assistant_message(state) or "Vamos continuar a configuracao."
        content_lines = [question]
        actions = []
        if prompt.get("kind") == "field":
            field_key = _current_onboarding_field_key(state)
            if field_key == "banco":
                content_lines.append("Digite o codigo ou o nome da instituicao. Ex.: 102 - SC XP Investimentos ou 348 - Banco XP.")
            elif prompt.get("allow_skip"):
                content_lines.append("Se preferir, voce pode usar o botao de pular.")
            else:
                content_lines.append("Responda na caixa de mensagem abaixo para eu seguir.")
            if prompt.get("allow_skip"):
                actions.append({
                    "kind": "api",
                    "action": "onboarding_skip",
                    "label": "Pular",
                })
        elif prompt.get("kind") == "choice":
            content_lines.append("Escolha uma das proximas acoes para continuar.")
            actions = [
                {
                    "kind": "api",
                    "action": "onboarding_choice",
                    "label": choice["label"],
                    "value": choice["value"],
                }
                for choice in prompt.get("choices") or []
            ]
        return {
            "title": "Configuracao guiada no chat",
            "content": "\n".join(content_lines),
            "actions": actions,
            "focus": True,
        }

    if _setup_complete(profile, accounts):
        actions = [
            {
                "kind": "api",
                "action": "start_add_account",
                "label": "Adicionar conta",
            },
            {
                "kind": "api",
                "action": "start_add_card",
                "label": "Adicionar cartao",
            },
        ]
        return {
            "title": "Cadastro e ajustes no proprio chat",
            "content": "Posso reabrir o onboarding para adicionar conta, vincular cartao ou continuar ajustando o cadastro sem sair daqui.",
            "actions": actions,
            "focus": False,
        }

    return None


def _build_restart_onboarding_chat_activity(accounts: list[dict]) -> dict | None:
    profile = load_customer_profile()
    if not _setup_complete(profile, accounts):
        return None
    if not (_required_profile_complete(profile) or any(account.get("ativo", True) for account in accounts)):
        return None
    return {
        "title": "Reiniciar fluxo",
        "content": "Mantem os dados salvos e reabre o onboarding no chat.",
        "actions": [
            {
                "kind": "api",
                "action": "restart_onboarding_chat",
                "label": "Reabrir onboarding no chat",
            },
        ],
    }


def _build_chat_activities(session: dict | None, accounts: list[dict] | None = None) -> list[dict]:
    accounts = accounts if accounts is not None else load_accounts()
    pending = _pending_edit(session)
    if pending:
        return [_build_correction_chat_activity(session, accounts)]

    activities = []
    onboarding = _build_onboarding_chat_activity(session, accounts)
    if onboarding and onboarding.get("focus"):
        return [onboarding]
    if onboarding:
        activities.append(onboarding)
    primary = _build_primary_chat_activity(accounts)
    if primary:
        activities.append(primary)
    activities.append(_build_correction_chat_activity(session, accounts))
    restart = _build_restart_onboarding_chat_activity(accounts)
    if restart:
        activities.append(restart)
    return activities


def _cards_text(cards: list[dict]) -> str:
    lines = []
    for card in cards or []:
        label = str(card.get("label") or "Cartao").strip()
        number = normalize_card_number(card.get("card_number"))
        if len(number) == 4:
            lines.append(f"{label}:{number}")
    return "\n".join(lines)


def _mask_document(value: str) -> str:
    digits = digits_only(value)
    if len(digits) == 11:
        return f"***.***.***-{digits[-2:]}"
    if len(digits) == 14:
        return f"**.***.***/****-{digits[-2:]}"
    return value


def _mask_cpf(value: str) -> str:
    # Mantido por compatibilidade com o resto da aplicacao.
    digits = digits_only(value)
    if len(digits) not in {11, 14}:
        return value
    return _mask_document(value)


def _display_profile_answer(field_key: str, value: str) -> str:
    if field_key == "cpf":
        return _mask_document(value)
    if field_key == "estado":
        return str(value or "").upper()
    return str(value or "").strip() or "Pulado"


def _display_account_answer(field_key: str, value: str) -> str:
    if field_key == "banco":
        return BANK_MAP.get(str(value or "").strip(), str(value or "").strip())
    if field_key == "saldo_inicial":
        return format_currency(money_to_float(value))
    return str(value or "").strip() or "Pulado"


def _display_card_answer(field_key: str, value: str) -> str:
    if field_key == "card_number":
        return normalize_card_number(value)
    return str(value or "").strip()


def _dashboard_money(value) -> str:
    amount = int(round(float(value or 0.0)))
    sign = "-" if amount < 0 else ""
    formatted = f"{abs(amount):,}".replace(",", ".")
    return f"{sign}R$ {formatted}"


def _dashboard_pct(value) -> str:
    return f"{int(round(float(value or 0.0)))}%"


def _profile_field(field_key: str) -> dict | None:
    return next((field for field in PROFILE_FIELDS if field["key"] == field_key), None)


def _account_field(field_key: str) -> dict | None:
    return next((field for field in ACCOUNT_FIELDS if field["key"] == field_key), None)


def _card_field(field_key: str) -> dict | None:
    return next((field for field in CARD_FIELDS if field["key"] == field_key), None)


def _append_message(state: dict, role: str, content: str) -> None:
    content = str(content or "").strip()
    if not content:
        return
    messages = state.setdefault("messages", [])
    if messages and messages[-1].get("role") == role and messages[-1].get("content") == content:
        return
    messages.append({
        "role": role,
        "content": content,
        "created_at": now_str(),
    })


def _openfinance_base_url(cfg: dict) -> str:
    base_url = str(cfg.get("base_url") or "").strip()
    if base_url:
        return base_url.rstrip("/")
    if str(cfg.get("environment") or "").strip().lower() == "production":
        return "https://api.pagamentobancario.com.br/api/v1"
    return "https://staging.pagamentobancario.com.br/api/v1"


def _openfinance_error_detail(data, err) -> str:
    if isinstance(data, dict):
        if isinstance(data.get("errors"), list) and data.get("errors"):
            first_error = data["errors"][0]
            if isinstance(first_error, dict):
                message = str(first_error.get("message") or first_error.get("internalCode") or "").strip()
                if message:
                    return message
        message = str(data.get("message") or data.get("error") or data.get("raw") or "").strip()
        if message:
            return message
    if data:
        return str(data).strip()
    return str(err or "").strip()


def _humanize_openfinance_error(status: int, data, err, cfg: dict) -> str:
    detail = _openfinance_error_detail(data, err)
    base_url = _openfinance_base_url(cfg)
    lowered = detail.lower()
    if status == 403 and "api.pagamentobancario.com.br" in base_url:
        return (
            "A API Open Finance respondeu 403 para este servidor. A credencial esta valida, "
            "mas a VPS precisa ser liberada na TecnoSpeed/Open Finance antes de gerar o link de autorizacao."
        )
    if status == 0 and "name or service not known" in lowered and "staging.pagamentobancario.com.br" in base_url:
        return (
            "O host de staging da TecnoSpeed nao resolve mais. O sistema precisa usar a base de producao "
            "ou uma nova URL oficial de homologacao."
        )
    if detail:
        return f"Falha ao ativar o titular no Open Finance: {detail}"
    return "Falha ao ativar o titular no Open Finance."


def _required_profile_complete(profile: dict) -> bool:
    for field in PROFILE_FIELDS:
        if field["required"] and not str(profile.get(field["key"]) or "").strip():
            return False
    return True


def _next_profile_cursor(profile: dict, accounts: list[dict]) -> int | None:
    required_complete = _required_profile_complete(profile)
    for idx, field in enumerate(PROFILE_FIELDS):
        if str(profile.get(field["key"]) or "").strip():
            continue
        if not accounts or field["required"] or not required_complete:
            return idx
    return None


def _setup_complete(profile: dict, accounts: list[dict]) -> bool:
    return _required_profile_complete(profile) and any(
        account.get("ativo", True)
        for account in accounts
    )


def _stage_number(stage: str) -> int:
    if stage == "profile":
        return 1
    if stage == "accounts":
        return 2
    if stage == "cards":
        return 3
    return 4


def _next_account_without_cards(accounts: list[dict], *, exclude_id: str = "") -> dict | None:
    for account in accounts:
        if not account.get("ativo", True):
            continue
        if exclude_id and str(account.get("id") or "").strip() == exclude_id:
            continue
        if not (account.get("openfinance_credit_cards") or []):
            return account
    return None


def _mark_onboarding_completed_if_ready() -> None:
    profile = load_customer_profile()
    accounts = load_accounts()
    if _setup_complete(profile, accounts) and not str(profile.get("onboarding_completed_at") or "").strip():
        profile["onboarding_completed_at"] = now_str()
        save_customer_profile(profile)


def _set_onboarding_connect_stage(state: dict) -> None:
    state["stage"] = "connect"
    state["mode"] = "ready"
    state["cursor"] = 0
    _mark_onboarding_completed_if_ready()


def _reset_onboarding_state_from_data(message: str = "") -> None:
    profile = load_customer_profile()
    accounts = load_accounts()
    state = _build_initial_onboarding_state(profile, accounts)
    if message:
        state["messages"] = [{
            "role": "assistant",
            "content": str(message).strip(),
            "created_at": now_str(),
        }] + list(state.get("messages") or [])
    save_onboarding_state(state)


def _empty_account_draft() -> dict:
    return {
        "apelido": "",
        "banco": "",
        "agencia": "",
        "conta": "",
        "saldo_inicial": "",
    }


def _empty_card_draft() -> dict:
    return {
        "label": "",
        "card_number": "",
    }


def _build_initial_onboarding_state(profile: dict, accounts: list[dict]) -> dict:
    state = {
        "stage": "profile",
        "mode": "field",
        "cursor": 0,
        "messages": [],
        "current_account_draft": _empty_account_draft(),
        "current_card_draft": _empty_card_draft(),
        "current_card_account_id": "",
        "last_account_id": "",
    }
    if _setup_complete(profile, accounts):
        state["stage"] = "connect"
        _append_message(state, "assistant", "Cadastro concluido. Agora e so autorizar e sincronizar as contas abaixo.")
        return state
    next_profile_cursor = _next_profile_cursor(profile, accounts)
    if next_profile_cursor is not None:
        state["cursor"] = next_profile_cursor
        _append_message(state, "assistant", PROFILE_FIELDS[next_profile_cursor]["question"])
        return state
    if not accounts:
        state["stage"] = "accounts"
        _append_message(state, "assistant", ACCOUNT_FIELDS[0]["question"])
        return state
    state["stage"] = "connect"
    _append_message(state, "assistant", "Cadastro concluido. Agora e so autorizar e sincronizar as contas abaixo.")
    return state


def _ensure_onboarding_state(profile: dict, accounts: list[dict]) -> dict:
    state = load_onboarding_state()
    if not state.get("stage"):
        state = _build_initial_onboarding_state(profile, accounts)
        save_onboarding_state(state)
        return state
    if state.get("stage") == "cards":
        target_id = str(state.get("current_card_account_id") or "").strip()
        if target_id and not any(str(account.get("id") or "").strip() == target_id for account in accounts):
            state = _build_initial_onboarding_state(profile, accounts)
            save_onboarding_state(state)
            return state
    if state.get("stage") == "connect" and not state.get("messages"):
        _append_message(state, "assistant", "Cadastro concluido. Agora e so autorizar e sincronizar as contas abaixo.")
        save_onboarding_state(state)
    return state


def _upsert_hidden_payer(profile: dict) -> dict:
    payers = load_openfinance_payers()
    target = next((item for item in payers if item.get("id") == HIDDEN_PAYER_ID), None)
    payload = {
        "id": HIDDEN_PAYER_ID,
        "cpf_cnpj": digits_only(profile.get("cpf")),
        "nome": str(profile.get("nome") or "").strip(),
        "email": str(profile.get("email") or "").strip(),
        "telefone": str(profile.get("telefone") or "").strip(),
        "logradouro": str(profile.get("logradouro") or "").strip(),
        "numero": str(profile.get("numero") or "").strip(),
        "bairro": str(profile.get("bairro") or "").strip(),
        "complemento": str(profile.get("complemento") or "").strip(),
        "cidade": str(profile.get("cidade") or "").strip(),
        "estado": str(profile.get("estado") or "").strip().upper(),
        "cep": str(profile.get("cep") or "").strip(),
        "updated_at": now_str(),
    }
    if target:
        target.update(payload)
    else:
        target = {
            "statement_actived": False,
            "tecnospeed_status": "",
            "created_at": now_str(),
            **payload,
        }
        payers.append(target)
    save_openfinance_payers(payers)
    return target


def _find_payer_by_account(account: dict) -> dict | None:
    payer_cpf = digits_only(account.get("openfinance_payer_cpf_cnpj"))
    if not payer_cpf:
        return None
    return next(
        (
            item for item in load_openfinance_payers()
            if digits_only(item.get("cpf_cnpj")) == payer_cpf
        ),
        None,
    )


def _normalize_profile_value(field: dict, answer: str) -> tuple[bool, str, str]:
    normalized = str(answer or "").strip()
    if field["key"] == "cpf":
        normalized = digits_only(normalized)
        if len(normalized) not in {11, 14}:
            return False, "", "Documento invalido. Informe um CPF com 11 numeros ou um CNPJ com 14 numeros."
    elif field["key"] == "estado":
        normalized = normalized.upper()[:2]
        if len(normalized) != 2:
            return False, "", "Informe a UF com 2 letras."
    elif field["key"] == "cep":
        normalized = digits_only(normalized)
        if len(normalized) < 8:
            return False, "", "Informe um CEP valido."
    if field["required"] and not normalized:
        return False, "", "Essa resposta e obrigatoria para continuar."
    return True, normalized, ""


def _registration_profile_defaults(claimable_tenant: dict | None) -> dict:
    defaults = {field["key"]: "" for field in PROFILE_FIELDS}
    if not claimable_tenant:
        return defaults
    with tenant_scope(
        str(claimable_tenant.get("id") or "").strip(),
        str(claimable_tenant.get("slug") or "").strip(),
        str(claimable_tenant.get("name") or "").strip(),
    ):
        profile = load_customer_profile()
    for field in PROFILE_FIELDS:
        defaults[field["key"]] = str(profile.get(field["key"]) or "").strip()
    return defaults


def _normalize_registration_profile(form_data: dict) -> tuple[bool, dict, str]:
    payload = {}
    for field in PROFILE_FIELDS:
        raw_value = form_data.get(field["key"], "")
        ok, normalized, message = _normalize_profile_value(field, raw_value)
        if not ok:
            label = PROFILE_FIELD_LABELS.get(field["key"], field["key"])
            return False, {}, f"{label}: {message}"
        payload[field["key"]] = normalized
    return True, payload, ""


def _registration_profile_fields() -> list[dict]:
    return [
        {
            "key": field["key"],
            "label": PROFILE_FIELD_LABELS.get(field["key"], field["key"]),
            "question": field["question"],
            "input_type": field["input_type"],
            "placeholder": field["placeholder"],
            "required": field["required"],
            "input_mode": (
                "numeric"
                if field["key"] in {"cpf", "cep", "numero"}
                else "tel" if field["key"] == "telefone" else ""
            ),
        }
        for field in PROFILE_FIELDS
    ]


def _onboarding_state_after_profile_registration(profile: dict, accounts: list[dict]) -> dict:
    state = {
        "stage": "accounts",
        "mode": "field",
        "cursor": 0,
        "messages": [],
        "current_account_draft": _empty_account_draft(),
        "current_card_draft": _empty_card_draft(),
        "current_card_account_id": "",
        "last_account_id": "",
    }
    if accounts:
        state = _build_initial_onboarding_state(profile, accounts)
        if str(state.get("stage") or "").strip() == "profile" and _required_profile_complete(profile):
            state["stage"] = "connect"
            state["mode"] = "ready"
            state["cursor"] = 0
            state["messages"] = []
            _append_message(state, "assistant", "Perfil do cliente confirmado no cadastro. Agora acompanhe as contas, cartoes e autorizacoes abaixo.")
        return state
    _append_message(state, "assistant", "Perfil do cliente salvo no cadastro.")
    _append_message(state, "assistant", ACCOUNT_FIELDS[0]["question"])
    return state


def _save_registered_profile(profile_payload: dict) -> tuple[bool, str]:
    profile = load_customer_profile()
    for field in PROFILE_FIELDS:
        field_key = field["key"]
        profile[field_key] = str(profile_payload.get(field_key) or "").strip()
    if not profile.get("created_at"):
        profile["created_at"] = now_str()
    profile["updated_at"] = now_str()
    save_customer_profile(profile)

    payer = _upsert_hidden_payer(profile)
    ok, message = _activate_payer(payer.get("id") or HIDDEN_PAYER_ID)

    accounts = load_accounts()
    state = _onboarding_state_after_profile_registration(profile, accounts)
    if _setup_complete(profile, accounts) and not str(profile.get("onboarding_completed_at") or "").strip():
        profile["onboarding_completed_at"] = now_str()
        save_customer_profile(profile)
    save_onboarding_state(state)
    return ok, message


def _normalize_account_value(field: dict, answer: str) -> tuple[bool, str, str]:
    raw_answer = str(answer or "").strip()
    normalized = raw_answer
    if field["key"] == "banco":
        normalized = resolve_bank_code(normalized)
        if len(normalized) != 3:
            if raw_answer.casefold().strip() == "xp":
                return False, "", "Para XP, escolha explicitamente 102 - SC XP Investimentos ou 348 - Banco XP."
            return False, "", "Selecione um banco valido."
    elif field["key"] == "saldo_inicial":
        normalized = str(money_to_float(normalized))
    if field["required"] and not normalized:
        return False, "", "Essa resposta e obrigatoria para continuar."
    return True, normalized, ""


def _normalize_card_value(field: dict, answer: str) -> tuple[bool, str, str]:
    normalized = str(answer or "").strip()
    if field["key"] == "card_number":
        normalized = normalize_card_number(normalized)
        if len(normalized) != 4:
            return False, "", "Informe exatamente os 4 ultimos digitos do cartao."
    if field["required"] and not normalized:
        return False, "", "Essa resposta e obrigatoria para continuar."
    return True, normalized, ""


def _activate_payer(payer_id: str) -> tuple[bool, str]:
    payers = load_openfinance_payers()
    payer = next((item for item in payers if item.get("id") == payer_id), None)
    if not payer:
        return False, "Nao consegui localizar o perfil bancario do cliente."

    cfg_req = load_openfinance_config()
    cfg_req["payer_cpf_cnpj"] = payer.get("cpf_cnpj") or ""
    payload = {
        "name": payer.get("nome"),
        "email": payer.get("email"),
        "cpfCnpj": payer.get("cpf_cnpj"),
        "accounts": [],
        "ddaActived": False,
        "statementActived": True,
        "street": payer.get("logradouro"),
        "neighborhood": payer.get("bairro"),
        "addressNumber": payer.get("numero"),
        "addressComplement": payer.get("complemento"),
        "city": payer.get("cidade"),
        "state": payer.get("estado"),
        "zipcode": digits_only(payer.get("cep")),
    }
    ok, status, data, err = openfinance_request(cfg_req, "POST", "payer", payload=payload, include_payer_header=False)
    if not ok:
        ok, status, data, err = openfinance_request(cfg_req, "PUT", "payer", payload={"statementActived": True})
    if not ok:
        payer["statement_actived"] = False
        payer["tecnospeed_status"] = "ERROR"
        payer["last_api_at"] = now_str()
        payer["last_error"] = _humanize_openfinance_error(status, data, err, cfg_req)
        save_openfinance_payers(payers)
        return False, payer["last_error"]
    payer["statement_actived"] = True
    payer["tecnospeed_status"] = "ACTIVE"
    payer["last_api_at"] = now_str()
    payer["last_error"] = ""
    save_openfinance_payers(payers)
    return True, "Perfil bancario ativado com sucesso."


def _save_profile_answer(state: dict, field: dict, answer: str) -> tuple[bool, str]:
    profile = load_customer_profile()
    ok, normalized, message = _normalize_profile_value(field, answer)
    if not ok:
        return False, message

    profile[field["key"]] = normalized
    if not profile.get("created_at"):
        profile["created_at"] = now_str()
    profile["updated_at"] = now_str()
    save_customer_profile(profile)
    _append_message(state, "user", _display_profile_answer(field["key"], normalized))

    if state["cursor"] + 1 < len(PROFILE_FIELDS):
        state["cursor"] += 1
        next_field = PROFILE_FIELDS[state["cursor"]]
        _append_message(state, "assistant", next_field["question"])
    else:
        payer = _upsert_hidden_payer(profile)
        ok, message = _activate_payer(payer.get("id") or HIDDEN_PAYER_ID)
        _append_message(state, "assistant", "Perfil do cliente salvo.")
        _append_message(state, "assistant", message)
        state["stage"] = "accounts"
        state["mode"] = "field"
        state["cursor"] = 0
        state["current_account_draft"] = _empty_account_draft()
        _append_message(state, "assistant", ACCOUNT_FIELDS[0]["question"])
    save_onboarding_state(state)
    return True, ""


def _save_account_answer(state: dict, field: dict, answer: str) -> tuple[bool, str]:
    ok, normalized, message = _normalize_account_value(field, answer)
    if not ok:
        return False, message

    draft = dict(state.get("current_account_draft") or _empty_account_draft())
    draft[field["key"]] = normalized
    state["current_account_draft"] = draft
    _append_message(state, "user", _display_account_answer(field["key"], normalized))

    if state["cursor"] + 1 < len(ACCOUNT_FIELDS):
        state["cursor"] += 1
        next_field = ACCOUNT_FIELDS[state["cursor"]]
        _append_message(state, "assistant", next_field["question"])
        save_onboarding_state(state)
        return True, ""

    profile = load_customer_profile()
    accounts = load_accounts()
    account_id = f"acct_{int(time.time() * 1000)}"
    accounts.append({
        "id": account_id,
        "ativo": True,
        "created_at": now_str(),
        "updated_at": now_str(),
        "apelido": draft.get("apelido") or "",
        "titular": str(profile.get("nome") or "").strip(),
        "banco": draft.get("banco") or "",
        "agencia": draft.get("agencia") or "",
        "conta": draft.get("conta") or "",
        "saldo_inicial": money_to_float(draft.get("saldo_inicial")),
        "openfinance_payer_cpf_cnpj": digits_only(profile.get("cpf")),
        "openfinance_account_hash": "",
        "openfinance_id": "",
        "openfinance_link": "",
        "openfinance_agencia_dig": "",
        "openfinance_conta_dig": "",
        "openfinance_account_type": "",
        "openfinance_account_payment": False,
        "openfinance_webservice": False,
        "openfinance_recipient_notification": False,
        "openfinance_credit_cards": [],
    })
    save_accounts(accounts)

    state["last_account_id"] = account_id
    state["mode"] = "decision"
    state["cursor"] = 0
    state["current_account_draft"] = _empty_account_draft()
    _append_message(
        state,
        "assistant",
        f'Conta "{draft.get("apelido") or build_account_label(accounts[-1])}" adicionada. Voce pode cadastrar outra conta, vincular um cartao ou habilitar esta conta agora e concluir.',
    )
    save_onboarding_state(state)
    return True, ""


def _save_card_answer(state: dict, field: dict, answer: str) -> tuple[bool, str]:
    account_id = str(state.get("current_card_account_id") or "").strip()
    accounts = load_accounts()
    account = next((item for item in accounts if str(item.get("id") or "").strip() == account_id), None)
    if not account:
        return False, "Nao encontrei a conta atual para vincular o cartao."

    ok, normalized, message = _normalize_card_value(field, answer)
    if not ok:
        return False, message

    draft = dict(state.get("current_card_draft") or _empty_card_draft())
    draft[field["key"]] = normalized
    state["current_card_draft"] = draft
    _append_message(state, "user", _display_card_answer(field["key"], normalized))

    if state["cursor"] + 1 < len(CARD_FIELDS):
        state["cursor"] += 1
        next_question = CARD_FIELDS[state["cursor"]]["question_template"].format(account_label=build_account_label(account))
        _append_message(state, "assistant", next_question)
        save_onboarding_state(state)
        return True, ""

    cards = normalize_credit_cards((account.get("openfinance_credit_cards") or []) + [draft])
    account["openfinance_credit_cards"] = cards
    account["updated_at"] = now_str()
    save_accounts(accounts)

    state["mode"] = "decision"
    state["cursor"] = 0
    state["current_card_draft"] = _empty_card_draft()
    _append_message(
        state,
        "assistant",
        f'Cartao "{draft.get("label")}" final {draft.get("card_number")} vinculado a conta "{build_account_label(account)}". Quer adicionar outro cartao nessa conta ou seguir?',
    )
    _mark_onboarding_completed_if_ready()
    save_onboarding_state(state)
    return True, ""


def _process_onboarding_choice(state: dict, choice: str) -> None:
    choice = str(choice or "").strip()
    if state.get("stage") == "accounts" and state.get("mode") == "decision":
        if choice == "add_account":
            state["stage"] = "accounts"
            state["mode"] = "field"
            state["cursor"] = 0
            state["current_account_draft"] = _empty_account_draft()
            _append_message(state, "assistant", ACCOUNT_FIELDS[0]["question"])
        elif choice == "enable_account_now":
            accounts = load_accounts()
            target_id = str(state.get("last_account_id") or "").strip()
            target = next((item for item in accounts if str(item.get("id") or "").strip() == target_id), None)
            if not target and accounts:
                target = accounts[-1]
            if not target:
                state["stage"] = "accounts"
                state["mode"] = "field"
                state["cursor"] = 0
                _append_message(state, "assistant", "Nao encontrei a conta recem-criada. Vamos cadastrar novamente.")
                _append_message(state, "assistant", ACCOUNT_FIELDS[0]["question"])
            else:
                payer = _find_payer_by_account(target)
                if payer and not (payer.get("statement_actived") or payer.get("tecnospeed_status") == "ACTIVE"):
                    ok, message = _activate_payer(str(payer.get("id") or "").strip())
                    _append_message(state, "assistant", message)
                    if not ok:
                        _set_onboarding_connect_stage(state)
                        save_onboarding_state(state)
                        return
                ok, message = create_remote_account(str(target.get("id") or "").strip())
                _append_message(state, "assistant", message)
                target_after = next(
                    (item for item in load_accounts() if str(item.get("id") or "").strip() == str(target.get("id") or "").strip()),
                    target,
                )
                if ok:
                    if str(target_after.get("openfinance_link") or "").strip():
                        _append_message(
                            state,
                            "assistant",
                            f'Conta "{build_account_label(target_after)}" habilitada. O link do banco ja esta pronto para autorizacao.',
                        )
                    else:
                        _append_message(
                            state,
                            "assistant",
                            f'Conta "{build_account_label(target_after)}" habilitada. Voce pode seguir com a autorizacao quando quiser.',
                        )
                    _set_onboarding_connect_stage(state)
                else:
                    _append_message(
                        state,
                        "assistant",
                        "Nao consegui habilitar essa conta agora. Posso tentar novamente ou voce pode seguir com outra opcao.",
                    )
                    _set_onboarding_connect_stage(state)
        elif choice == "go_cards":
            accounts = load_accounts()
            if not accounts:
                state["stage"] = "accounts"
                state["mode"] = "field"
                state["cursor"] = 0
                _append_message(state, "assistant", ACCOUNT_FIELDS[0]["question"])
            else:
                target = _next_account_without_cards(accounts) or accounts[0]
                state["stage"] = "cards"
                state["mode"] = "field"
                state["cursor"] = 0
                state["current_card_account_id"] = str(target.get("id") or "").strip()
                state["current_card_draft"] = _empty_card_draft()
                _append_message(state, "assistant", f'Agora vamos vincular os cartoes da conta "{build_account_label(target)}".')
                _append_message(
                    state,
                    "assistant",
                    CARD_FIELDS[0]["question_template"].format(account_label=build_account_label(target)),
                )
        save_onboarding_state(state)
        return

    if state.get("stage") == "cards" and state.get("mode") == "decision":
        accounts = load_accounts()
        current_account_id = str(state.get("current_card_account_id") or "").strip()
        current_account = next((item for item in accounts if str(item.get("id") or "").strip() == current_account_id), None)
        if choice == "add_card_same" and current_account:
            state["mode"] = "field"
            state["cursor"] = 0
            state["current_card_draft"] = _empty_card_draft()
            _append_message(
                state,
                "assistant",
                CARD_FIELDS[0]["question_template"].format(account_label=build_account_label(current_account)),
            )
        else:
            next_account = _next_account_without_cards(accounts, exclude_id=current_account_id)
            if next_account:
                state["mode"] = "field"
                state["cursor"] = 0
                state["current_card_account_id"] = str(next_account.get("id") or "").strip()
                state["current_card_draft"] = _empty_card_draft()
                _append_message(state, "assistant", f'Agora vamos vincular os cartoes da conta "{build_account_label(next_account)}".')
                _append_message(
                    state,
                    "assistant",
                    CARD_FIELDS[0]["question_template"].format(account_label=build_account_label(next_account)),
                )
            else:
                _set_onboarding_connect_stage(state)
                _append_message(state, "assistant", "Perfeito. O cadastro inicial foi concluido. Agora voce pode autorizar e sincronizar as contas.")
        save_onboarding_state(state)


def _apply_profile_field_edit(field_key: str, answer: str) -> tuple[bool, str]:
    field = _profile_field(field_key)
    if not field:
        return False, "Campo do cliente invalido."
    ok, normalized, message = _normalize_profile_value(field, answer)
    if not ok:
        return False, message

    profile = load_customer_profile()
    profile[field_key] = normalized
    profile["updated_at"] = now_str()
    save_customer_profile(profile)
    payer = _upsert_hidden_payer(profile)
    _activate_payer(payer.get("id") or HIDDEN_PAYER_ID)
    return True, f'Dado do cliente atualizado: {PROFILE_FIELD_LABELS.get(field_key, field_key)}.'


def _edit_profile_field(state: dict, field_key: str, answer: str) -> tuple[bool, str]:
    ok, message = _apply_profile_field_edit(field_key, answer)
    if ok:
        _append_message(state, "assistant", message)
        save_onboarding_state(state)
        return True, ""
    return False, message


def _apply_account_field_edit(account_id: str, field_key: str, answer: str) -> tuple[bool, str]:
    field = _account_field(field_key)
    if not field:
        return False, "Campo da conta invalido."
    ok, normalized, message = _normalize_account_value(field, answer)
    if not ok:
        return False, message

    accounts = load_accounts()
    account = next((item for item in accounts if str(item.get("id") or "").strip() == account_id), None)
    if not account:
        return False, "Conta nao encontrada."

    if field_key == "saldo_inicial":
        account[field_key] = money_to_float(normalized)
    else:
        account[field_key] = normalized

    if field_key in {"banco", "agencia", "conta"}:
        account["openfinance_account_hash"] = ""
        account["openfinance_id"] = ""
        account["openfinance_link"] = ""
        account["openfinance_last_error"] = ""

    account["updated_at"] = now_str()
    save_accounts(accounts)
    return True, f'Conta "{build_account_label(account)}" atualizada em {ACCOUNT_FIELD_LABELS.get(field_key, field_key)}.'


def _edit_account_field(state: dict, account_id: str, field_key: str, answer: str) -> tuple[bool, str]:
    ok, message = _apply_account_field_edit(account_id, field_key, answer)
    if ok:
        _append_message(state, "assistant", message)
        save_onboarding_state(state)
        return True, ""
    return False, message


def _apply_card_field_edit(account_id: str, card_number: str, field_key: str, answer: str) -> tuple[bool, str]:
    field = _card_field(field_key)
    if not field:
        return False, "Campo do cartao invalido."
    ok, normalized, message = _normalize_card_value(field, answer)
    if not ok:
        return False, message

    target_card_number = normalize_card_number(card_number)
    accounts = load_accounts()
    account = next((item for item in accounts if str(item.get("id") or "").strip() == account_id), None)
    if not account:
        return False, "Conta do cartao nao encontrada."

    cards = list(account.get("openfinance_credit_cards") or [])
    target = next((card for card in cards if normalize_card_number(card.get("card_number")) == target_card_number), None)
    if not target:
        return False, "Cartao nao encontrado."

    target[field_key] = normalized
    account["openfinance_credit_cards"] = normalize_credit_cards(cards)
    account["updated_at"] = now_str()
    save_accounts(accounts)
    return True, f'Cartao da conta "{build_account_label(account)}" atualizado em {CARD_FIELD_LABELS.get(field_key, field_key)}.'


def _edit_card_field(state: dict, account_id: str, card_number: str, field_key: str, answer: str) -> tuple[bool, str]:
    ok, message = _apply_card_field_edit(account_id, card_number, field_key, answer)
    if ok:
        _append_message(state, "assistant", message)
        save_onboarding_state(state)
        return True, ""
    return False, message


def _delete_account(account_id: str) -> tuple[bool, str]:
    accounts = load_accounts()
    target = next((item for item in accounts if str(item.get("id") or "").strip() == account_id), None)
    if not target:
        return False, "Conta nao encontrada."

    account_label = build_account_label(target)
    remaining_accounts = [
        item for item in accounts
        if str(item.get("id") or "").strip() != account_id
    ]
    save_accounts(remaining_accounts)

    imports = load_statement_imports()
    remaining_imports = [
        item for item in imports
        if str(item.get("account_id") or "").strip() != account_id
    ]
    save_statement_imports(remaining_imports)
    _reset_onboarding_state_from_data(f'Conta "{account_label}" excluida. As movimentacoes vinculadas tambem foram removidas.')
    return True, f'Conta "{account_label}" excluida com sucesso.'


def _delete_card(account_id: str, card_number: str) -> tuple[bool, str]:
    target_card_number = normalize_card_number(card_number)
    accounts = load_accounts()
    account = next((item for item in accounts if str(item.get("id") or "").strip() == account_id), None)
    if not account:
        return False, "Conta do cartao nao encontrada."

    cards = list(account.get("openfinance_credit_cards") or [])
    target = next((card for card in cards if normalize_card_number(card.get("card_number")) == target_card_number), None)
    if not target:
        return False, "Cartao nao encontrado."

    card_label = str(target.get("label") or "Cartao").strip() or "Cartao"
    account["openfinance_credit_cards"] = [
        card for card in cards
        if normalize_card_number(card.get("card_number")) != target_card_number
    ]
    account["updated_at"] = now_str()
    save_accounts(accounts)

    imports = load_statement_imports()
    remaining_imports = [
        item for item in imports
        if not (
            str(item.get("account_id") or "").strip() == account_id
            and str(item.get("statement_type") or "").strip().upper() == "CREDIT_CARD"
            and normalize_card_number(item.get("card_number")) == target_card_number
        )
    ]
    save_statement_imports(remaining_imports)
    return True, f'{card_label} final {target_card_number} excluido com sucesso.'


def _current_onboarding_prompt(state: dict, accounts: list[dict]) -> dict | None:
    stage = str(state.get("stage") or "").strip()
    mode = str(state.get("mode") or "field").strip()
    cursor = int(state.get("cursor") or 0)

    if stage == "profile":
        field = PROFILE_FIELDS[cursor]
        inputmode = "text"
        if field["key"] in {"cpf", "cep"}:
            inputmode = "numeric"
        elif field["key"] == "telefone":
            inputmode = "tel"
        return {
            "kind": "field",
            "input_type": field["input_type"],
            "inputmode": inputmode,
            "placeholder": field["placeholder"],
            "required": field["required"],
            "allow_skip": not field["required"],
            "options": [],
        }

    if stage == "accounts":
        if mode == "decision":
            return {
                "kind": "choice",
                "choices": [
                    {"value": "enable_account_now", "label": "Habilitar esta conta e concluir"},
                    {"value": "add_account", "label": "Adicionar outra conta"},
                    {"value": "go_cards", "label": "Seguir para os cartoes"},
                ],
            }
        field = ACCOUNT_FIELDS[cursor]
        inputmode = "text"
        if field["key"] in {"agencia", "conta"}:
            inputmode = "numeric"
        elif field["key"] == "saldo_inicial":
            inputmode = "decimal"
        return {
            "kind": "field",
            "input_type": field["input_type"],
            "inputmode": inputmode,
            "placeholder": field["placeholder"],
            "required": field["required"],
            "allow_skip": not field["required"],
            "options": [
                {"value": code, "label": f"{code} - {label}"}
                for code, label in BANK_OPTIONS
            ] if field["input_type"] == "select" else [],
        }

    if stage == "cards":
        if mode == "decision":
            current_account_id = str(state.get("current_card_account_id") or "").strip()
            next_account = _next_account_without_cards(accounts, exclude_id=current_account_id)
            next_label = "Ir para a proxima conta" if next_account else "Concluir cadastro"
            return {
                "kind": "choice",
                "choices": [
                    {"value": "add_card_same", "label": "Adicionar outro cartao"},
                    {"value": "next_cards", "label": next_label},
                ],
            }
        field = CARD_FIELDS[cursor]
        return {
            "kind": "field",
            "input_type": field["input_type"],
            "inputmode": "numeric" if field["key"] == "card_number" else "text",
            "placeholder": field["placeholder"],
            "required": field["required"],
            "allow_skip": False,
            "options": [],
        }

    return None


def _resume_account_onboarding(state: dict) -> None:
    state["stage"] = "accounts"
    state["mode"] = "field"
    state["cursor"] = 0
    state["current_account_draft"] = _empty_account_draft()
    state["current_card_draft"] = _empty_card_draft()
    state["current_card_account_id"] = ""
    _append_message(state, "assistant", "Vamos adicionar mais uma conta ao cliente.")
    _append_message(state, "assistant", ACCOUNT_FIELDS[0]["question"])
    save_onboarding_state(state)


def _resume_card_onboarding(state: dict, account_id: str) -> tuple[bool, str]:
    accounts = load_accounts()
    account = next((item for item in accounts if str(item.get("id") or "").strip() == account_id), None)
    if not account:
        return False, "Conta nao encontrada para incluir um novo cartao."
    state["stage"] = "cards"
    state["mode"] = "field"
    state["cursor"] = 0
    state["current_card_account_id"] = account_id
    state["current_card_draft"] = _empty_card_draft()
    _append_message(state, "assistant", f'Vamos adicionar mais um cartao para a conta "{build_account_label(account)}".')
    _append_message(
        state,
        "assistant",
        CARD_FIELDS[0]["question_template"].format(account_label=build_account_label(account)),
    )
    save_onboarding_state(state)
    return True, ""


def _chat_composer_meta(session: dict | None, accounts: list[dict]) -> dict:
    pending = _pending_edit(session)
    if pending.get("step") == "await_value":
        field_key = str(pending.get("field_key") or "").strip()
        label = (
            PROFILE_FIELD_LABELS.get(field_key)
            or ACCOUNT_FIELD_LABELS.get(field_key)
            or CARD_FIELD_LABELS.get(field_key)
            or "o dado escolhido"
        )
        placeholder = "Digite o novo valor..."
        if field_key == "banco":
            placeholder = "Ex.: 102 - SC XP Investimentos"
        elif field_key == "card_number":
            placeholder = "Digite os 4 ultimos digitos"
        return {
            "placeholder": placeholder,
            "hint": f"Correcao em andamento: envie o novo valor para {label}.",
        }

    profile = load_customer_profile()
    state = _ensure_onboarding_state(profile, accounts)
    prompt = _current_onboarding_prompt(state, accounts)
    if prompt and str(state.get("stage") or "").strip() in {"profile", "accounts", "cards"}:
        field_key = _current_onboarding_field_key(state)
        placeholder = str(prompt.get("placeholder") or "Digite sua resposta...").strip() or "Digite sua resposta..."
        if field_key == "banco":
            placeholder = "Ex.: 102 - SC XP Investimentos ou 348 - Banco XP"
        elif field_key == "saldo_inicial":
            placeholder = "Ex.: 0,00"
        elif field_key == "card_number":
            placeholder = "Ex.: 1234"
        hint = "Configuracao guiada ativa neste chat."
        if prompt.get("kind") == "choice":
            placeholder = "Use um dos botoes acima para continuar."
            hint = "Esta etapa do cadastro usa os botoes da conversa."
        return {
            "placeholder": placeholder,
            "hint": hint,
        }

    return {
        "placeholder": "Pergunte sobre contas, cartoes, gastos, relatorios ou tendencias...",
        "hint": "Autorizacoes, cadastro e ajustes tambem podem acontecer por aqui. Logs e fila tecnica ficam em Operacoes.",
    }


def _run_automatic_sync_cycle() -> None:
    backfill_statement_import_categories()
    if not load_accounts():
        return
    run_automatic_statement_updates()


def _handle_chat_onboarding_message(session_id: str | None, message: str) -> dict | None:
    profile = load_customer_profile()
    accounts = load_accounts()
    state = _ensure_onboarding_state(profile, accounts)
    prompt = _current_onboarding_prompt(state, accounts)
    stage = str(state.get("stage") or "").strip()
    if not prompt or stage not in {"profile", "accounts", "cards"}:
        return None

    session = get_session(str(session_id or "").strip()) or ensure_session(session_id)
    if prompt.get("kind") != "field":
        return append_session_messages(session.get("id"), [
            {"role": "user", "content": message},
            {"role": "assistant", "content": "Use os botoes acima para continuar nessa etapa do cadastro guiado."},
        ])

    before_count = len(state.get("messages") or [])
    cursor = int(state.get("cursor") or 0)
    if stage == "profile":
        ok, reply = _save_profile_answer(state, PROFILE_FIELDS[cursor], message)
    elif stage == "accounts":
        ok, reply = _save_account_answer(state, ACCOUNT_FIELDS[cursor], message)
    elif stage == "cards":
        ok, reply = _save_card_answer(state, CARD_FIELDS[cursor], message)
    else:
        ok, reply = False, "Nao ha etapa de onboarding aguardando resposta agora."

    if not ok:
        return append_session_messages(session.get("id"), [
            {"role": "user", "content": message},
            {"role": "assistant", "content": reply},
        ])

    entries = _state_message_entries(state, before_count)
    if not entries:
        entries = [{"role": "assistant", "content": "Resposta registrada. Vamos seguir."}]
    session = append_session_messages(session.get("id"), entries)
    session = update_session_data(session.get("id"), pending_setup=None)
    return session


def _handle_chat_correction_message(session_id: str | None, message: str) -> dict | None:
    session = get_session(str(session_id or "").strip()) or ensure_session(session_id)
    pending = _pending_edit(session)
    if not pending:
        return None

    step = str(pending.get("step") or "").strip()
    if step != "await_value":
        session = append_session_messages(session.get("id"), [
            {"role": "user", "content": message},
            {"role": "assistant", "content": "Use os botoes acima para escolher o dado que deseja corrigir, ou cancele a edicao atual."},
        ])
        return session

    mode = str(pending.get("mode") or "").strip()
    field_key = str(pending.get("field_key") or "").strip()
    if mode == "profile":
        ok, reply = _apply_profile_field_edit(field_key, message)
    elif mode == "account":
        ok, reply = _apply_account_field_edit(str(pending.get("account_id") or "").strip(), field_key, message)
    elif mode == "card":
        ok, reply = _apply_card_field_edit(
            str(pending.get("account_id") or "").strip(),
            str(pending.get("card_number") or "").strip(),
            field_key,
            message,
        )
    else:
        ok, reply = False, "Nao consegui identificar que tipo de correcao estava em andamento."

    session = append_session_messages(session.get("id"), [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ])
    if ok:
        session = update_session_data(session.get("id"), pending_edit=None)
    return session


def _handle_chat_activity_action(
    session_id: str | None,
    action: str,
    account_id: str = "",
    action_label: str = "",
    card_number: str = "",
    field_key: str = "",
    value: str = "",
) -> tuple[dict, bool]:
    action = str(action or "").strip()
    account_id = str(account_id or "").strip()
    action_label = str(action_label or "").strip()
    card_number = normalize_card_number(card_number)
    field_key = str(field_key or "").strip()
    value = str(value or "").strip()
    session = get_session(str(session_id or "").strip()) or ensure_session(session_id)
    accounts = load_accounts()

    if action == "cancel_setup_pending":
        session = append_session_messages(session.get("id"), [
            {"role": "user", "content": action_label or "Cancelar"},
            {"role": "assistant", "content": "Tudo certo. Voltei o chat para o modo normal de assistente."},
        ])
        session = update_session_data(session.get("id"), pending_setup=None)
        return session, True

    if action == "onboarding_choice":
        profile = load_customer_profile()
        state = _ensure_onboarding_state(profile, load_accounts())
        prompt = _current_onboarding_prompt(state, load_accounts())
        if not prompt or prompt.get("kind") != "choice":
            session = append_session_messages(session.get("id"), [{"role": "assistant", "content": "Nao ha uma escolha pendente no onboarding agora."}])
            return session, False
        before_count = len(state.get("messages") or [])
        choice_labels = {
            str(choice.get("value") or "").strip(): str(choice.get("label") or "").strip()
            for choice in prompt.get("choices") or []
        }
        selected_value = value or field_key
        _append_message(state, "user", action_label or choice_labels.get(selected_value, selected_value))
        _process_onboarding_choice(state, selected_value)
        session = append_session_messages(session.get("id"), _state_message_entries(state, before_count))
        session = update_session_data(session.get("id"), pending_setup=None)
        return session, True

    if action == "onboarding_skip":
        profile = load_customer_profile()
        accounts = load_accounts()
        state = _ensure_onboarding_state(profile, accounts)
        prompt = _current_onboarding_prompt(state, accounts)
        stage = str(state.get("stage") or "").strip()
        if not prompt or prompt.get("kind") != "field" or not prompt.get("allow_skip"):
            session = append_session_messages(session.get("id"), [{"role": "assistant", "content": "Essa etapa nao pode ser pulada."}])
            return session, False
        before_count = len(state.get("messages") or [])
        cursor = int(state.get("cursor") or 0)
        if stage == "profile":
            ok, reply = _save_profile_answer(state, PROFILE_FIELDS[cursor], "")
        elif stage == "accounts":
            ok, reply = _save_account_answer(state, ACCOUNT_FIELDS[cursor], "")
        elif stage == "cards":
            ok, reply = _save_card_answer(state, CARD_FIELDS[cursor], "")
        else:
            ok, reply = False, "Nao ha etapa pulavel agora."
        if not ok:
            session = append_session_messages(session.get("id"), [{"role": "assistant", "content": reply}])
            return session, False
        session = append_session_messages(session.get("id"), _state_message_entries(state, before_count))
        return session, True

    if action == "start_add_account":
        profile = load_customer_profile()
        state = _ensure_onboarding_state(profile, load_accounts())
        before_count = len(state.get("messages") or [])
        _resume_account_onboarding(state)
        entries = []
        if action_label:
            entries.append({"role": "user", "content": action_label})
        entries.extend(_state_message_entries(state, before_count))
        session = append_session_messages(session.get("id"), entries)
        session = update_session_data(session.get("id"), pending_setup=None)
        return session, True

    if action == "restart_onboarding_chat":
        profile = load_customer_profile()
        accounts = load_accounts()
        message = "Mantive os dados salvos e reabri o fluxo no ponto certo."
        if _setup_complete(profile, accounts):
            message = "Mantive os dados salvos. Posso continuar pelo chat adicionando conta, vinculando cartao ou ajustando o cadastro."
        _reset_onboarding_state_from_data(message)
        state = _ensure_onboarding_state(profile, accounts)
        entries = []
        if action_label:
            entries.append({"role": "user", "content": action_label})
        entries.extend(_state_message_entries(state, 0))
        session = append_session_messages(session.get("id"), entries)
        session = update_session_data(session.get("id"), pending_edit=None, pending_setup=None)
        return session, True

    if action == "start_add_card":
        active_accounts = [item for item in load_accounts() if item.get("ativo", True)]
        if not active_accounts:
            session = append_session_messages(session.get("id"), [{"role": "assistant", "content": "Ainda nao ha contas ativas para vincular um cartao."}])
            return session, False
        if len(active_accounts) == 1:
            profile = load_customer_profile()
            state = _ensure_onboarding_state(profile, active_accounts)
            before_count = len(state.get("messages") or [])
            ok, reply = _resume_card_onboarding(state, str(active_accounts[0].get("id") or "").strip())
            if not ok:
                session = append_session_messages(session.get("id"), [{"role": "assistant", "content": reply}])
                return session, False
            entries = []
            if action_label:
                entries.append({"role": "user", "content": action_label})
            entries.extend(_state_message_entries(state, before_count))
            session = append_session_messages(session.get("id"), entries)
            session = update_session_data(session.get("id"), pending_setup=None)
            return session, True
        session = append_session_messages(session.get("id"), [
            {"role": "user", "content": action_label or "Adicionar cartao"},
            {"role": "assistant", "content": "Escolha primeiro em qual conta voce quer vincular esse novo cartao."},
        ])
        session = update_session_data(session.get("id"), pending_setup={"mode": "choose_card_account"})
        return session, True

    if action == "choose_card_account_for_add":
        profile = load_customer_profile()
        state = _ensure_onboarding_state(profile, load_accounts())
        before_count = len(state.get("messages") or [])
        ok, reply = _resume_card_onboarding(state, account_id)
        if not ok:
            session = append_session_messages(session.get("id"), [{"role": "assistant", "content": reply}])
            return session, False
        entries = []
        if action_label:
            entries.append({"role": "user", "content": action_label})
        entries.extend(_state_message_entries(state, before_count))
        session = append_session_messages(session.get("id"), entries)
        session = update_session_data(session.get("id"), pending_setup=None)
        return session, True

    if action == "cancel_correction":
        session = append_session_messages(session.get("id"), [
            {"role": "user", "content": action_label or "Cancelar"},
            {"role": "assistant", "content": "Edicao cancelada. Se quiser, posso abrir outra correcao por aqui."},
        ])
        session = update_session_data(session.get("id"), pending_edit=None, pending_setup=None)
        return session, True

    if action == "start_profile_correction":
        session = append_session_messages(session.get("id"), [
            {"role": "user", "content": action_label or "Corrigir cliente"},
            {"role": "assistant", "content": "Certo. Vamos corrigir um dado do cliente."},
        ])
        session = update_session_data(session.get("id"), pending_edit={"mode": "profile", "step": "choose_field"}, pending_setup=None)
        return session, True

    if action == "choose_profile_field":
        session = append_session_messages(session.get("id"), [
            {"role": "user", "content": action_label or PROFILE_FIELD_LABELS.get(field_key, field_key)},
            {"role": "assistant", "content": f'Me diga o novo valor para {PROFILE_FIELD_LABELS.get(field_key, field_key)}.'},
        ])
        session = update_session_data(session.get("id"), pending_edit={"mode": "profile", "step": "await_value", "field_key": field_key})
        return session, True

    if action == "start_account_correction":
        active_accounts = [account for account in accounts if account.get("ativo", True)]
        if not active_accounts:
            session = append_session_messages(session.get("id"), [
                {"role": "assistant", "content": "Ainda nao ha contas cadastradas para corrigir."},
            ])
            return session, False
        session = append_session_messages(session.get("id"), [
            {"role": "user", "content": action_label or "Corrigir conta"},
            {"role": "assistant", "content": "Certo. Vamos corrigir uma conta."},
        ])
        pending = {"mode": "account", "step": "choose_account"}
        if len(active_accounts) == 1:
            pending = {
                "mode": "account",
                "step": "choose_field",
                "account_id": str(active_accounts[0].get("id") or "").strip(),
            }
        session = update_session_data(session.get("id"), pending_edit=pending, pending_setup=None)
        return session, True

    if action == "choose_account_for_correction":
        account = next((item for item in accounts if str(item.get("id") or "").strip() == account_id), None)
        if not account:
            session = append_session_messages(session.get("id"), [{"role": "assistant", "content": "Nao encontrei a conta escolhida para correcao."}])
            return session, False
        session = append_session_messages(session.get("id"), [
            {"role": "user", "content": action_label or build_account_label(account)},
            {"role": "assistant", "content": f'Perfeito. Agora escolha o campo da conta "{build_account_label(account)}".'},
        ])
        session = update_session_data(session.get("id"), pending_edit={"mode": "account", "step": "choose_field", "account_id": account_id})
        return session, True

    if action == "choose_account_field":
        session = append_session_messages(session.get("id"), [
            {"role": "user", "content": action_label or ACCOUNT_FIELD_LABELS.get(field_key, field_key)},
            {"role": "assistant", "content": f'Me diga o novo valor para {ACCOUNT_FIELD_LABELS.get(field_key, field_key)}.'},
        ])
        session = update_session_data(
            session.get("id"),
            pending_edit={"mode": "account", "step": "await_value", "account_id": account_id, "field_key": field_key},
        )
        return session, True

    if action == "start_card_correction":
        cards = _editable_cards_for_chat(accounts)
        if not cards:
            session = append_session_messages(session.get("id"), [{"role": "assistant", "content": "Ainda nao ha cartoes cadastrados para corrigir."}])
            return session, False
        session = append_session_messages(session.get("id"), [
            {"role": "user", "content": action_label or "Corrigir cartao"},
            {"role": "assistant", "content": "Certo. Vamos corrigir um cartao."},
        ])
        pending = {"mode": "card", "step": "choose_card"}
        if len(cards) == 1:
            pending = {
                "mode": "card",
                "step": "choose_field",
                "account_id": cards[0]["account_id"],
                "card_number": cards[0]["card_number"],
            }
        session = update_session_data(session.get("id"), pending_edit=pending, pending_setup=None)
        return session, True

    if action == "choose_card_for_correction":
        card = next(
            (
                item for item in _editable_cards_for_chat(accounts)
                if item["account_id"] == account_id and item["card_number"] == card_number
            ),
            None,
        )
        if not card:
            session = append_session_messages(session.get("id"), [{"role": "assistant", "content": "Nao encontrei o cartao escolhido para correcao."}])
            return session, False
        session = append_session_messages(session.get("id"), [
            {"role": "user", "content": action_label or card["label"]},
            {"role": "assistant", "content": f'Perfeito. Agora escolha o campo do cartao "{card["label"]}".'},
        ])
        session = update_session_data(
            session.get("id"),
            pending_edit={"mode": "card", "step": "choose_field", "account_id": account_id, "card_number": card_number},
        )
        return session, True

    if action == "choose_card_field":
        session = append_session_messages(session.get("id"), [
            {"role": "user", "content": action_label or CARD_FIELD_LABELS.get(field_key, field_key)},
            {"role": "assistant", "content": f'Me diga o novo valor para {CARD_FIELD_LABELS.get(field_key, field_key)}.'},
        ])
        session = update_session_data(
            session.get("id"),
            pending_edit={
                "mode": "card",
                "step": "await_value",
                "account_id": account_id,
                "card_number": card_number,
                "field_key": field_key,
            },
        )
        return session, True

    accounts = load_accounts()
    account = next((item for item in accounts if str(item.get("id") or "").strip() == account_id), None)
    if not account:
        session = append_session_messages(session.get("id"), [{
            "role": "assistant",
            "content": "Nao encontrei a conta vinculada a essa atividade.",
        }])
        return session, False

    user_entries = []
    if action_label:
        user_entries.append({
            "role": "user",
            "content": action_label,
        })

    assistant_reply = "Nao consegui concluir essa etapa."
    success = False

    if action == "retry_payer_activation":
        payer = _find_payer_by_account(account)
        if payer:
            success, message = _activate_payer(str(payer.get("id") or "").strip())
            assistant_reply = message
        else:
            assistant_reply = "Nao encontrei o titular vinculado a essa conta."

    elif action == "prepare_account_connection":
        payer = _find_payer_by_account(account)
        if payer and not (payer.get("statement_actived") or payer.get("tecnospeed_status") == "ACTIVE"):
            ok_payer, payer_message = _activate_payer(str(payer.get("id") or "").strip())
            if not ok_payer:
                session = append_session_messages(session.get("id"), user_entries + [{
                    "role": "assistant",
                    "content": payer_message,
                }])
                return session, False
        success, message = create_remote_account(account_id)
        account_after = next((item for item in load_accounts() if str(item.get("id") or "").strip() == account_id), None) or account
        if success and str(account_after.get("openfinance_link") or "").strip():
            assistant_reply = (
                f'Conta "{build_account_label(account_after)}" preparada. '
                "Agora abra o banco pelo proximo botao para concluir a autorizacao."
            )
        else:
            assistant_reply = message

    elif action == "check_account_authorization":
        success, message = refresh_remote_account(account_id)
        account_after = next((item for item in load_accounts() if str(item.get("id") or "").strip() == account_id), None) or account
        remote_status = str(account_after.get("openfinance_remote_status") or "").strip().upper()
        if success and remote_status in {"ATIVO", "ACTIVE"}:
            sync_result = run_automatic_statement_updates()
            created = [
                item for item in sync_result.get("created", [])
                if str(item.get("account_id") or "").strip() == account_id
            ]
            if created:
                assistant_reply = (
                    f'Autorizacao confirmada para "{build_account_label(account_after)}". '
                    "Ja iniciei a sincronizacao automatica das movimentacoes."
                )
            else:
                assistant_reply = (
                    f'Autorizacao confirmada para "{build_account_label(account_after)}". '
                    "A partir daqui eu sigo atualizando automaticamente ate ontem."
                )
        elif success:
            assistant_reply = (
                f'A conta "{build_account_label(account_after)}" ainda aparece como aguardando o banco. '
                "Se voce ja concluiu o consentimento, tente verificar novamente em alguns segundos."
            )
        else:
            assistant_reply = message

    session = append_session_messages(session.get("id"), user_entries + [{
        "role": "assistant",
        "content": assistant_reply,
    }])
    return session, success


def _dashboard_context() -> dict:
    profile = load_customer_profile()
    accounts = load_accounts()
    imports = load_statement_imports()
    summary = build_dashboard_summary()
    imports_sorted = sorted(imports, key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
    processing = sum(1 for item in imports if str(item.get("status") or "").strip().upper() not in {"SUCCESS", "COMPLETED", "DONE"})
    chat_activities = _build_chat_activities(None, accounts)
    primary_chat_activity = _build_primary_chat_activity(accounts)
    return {
        "profile": profile,
        "accounts": accounts,
        "imports": imports_sorted,
        "summary": summary,
        "imports_processing": processing,
        "imports_completed": len(imports) - processing,
        "setup_complete": _setup_complete(profile, accounts),
        "total_cards": sum(len(account.get("openfinance_credit_cards") or []) for account in accounts),
        "chat_activities": chat_activities,
        "chat_activity": primary_chat_activity or (chat_activities[0] if chat_activities else None),
        "pending_authorizations": _pending_authorization_count(accounts),
    }


def _dashboard_period_dates(period_key: str) -> tuple[str, str]:
    today_ref = date.today()
    start = None
    end = today_ref

    if period_key == "this_month":
        start = today_ref.replace(day=1)
    elif period_key == "30d":
        start = today_ref - timedelta(days=29)
    elif period_key == "90d":
        start = today_ref - timedelta(days=89)
    elif period_key == "6m":
        start = today_ref - timedelta(days=179)
    elif period_key == "this_year":
        start = today_ref.replace(month=1, day=1)

    return normalize_date_str(start), normalize_date_str(end)


def _dashboard_scope_label(filters: dict, total: int) -> str:
    start = str(filters.get("date_start_effective") or "").strip()
    end = str(filters.get("date_end_effective") or "").strip()
    if start and end:
        range_label = f"{start} ate {end}"
    elif start:
        range_label = f"A partir de {start}"
    elif end:
        range_label = f"Ate {end}"
    else:
        range_label = dict(DASHBOARD_PERIOD_OPTIONS).get(str(filters.get("period") or "all"), "Todo periodo")
    tx_label = "transacao" if total == 1 else "transacoes"
    return f"{range_label} - {total} {tx_label} no recorte"


def _dashboard_filter_tags(filters: dict, accounts: list[dict]) -> list[str]:
    tags: list[str] = []
    account_id = str(filters.get("account_id") or "").strip()
    card_number = normalize_card_number(filters.get("card_number"))
    category = str(filters.get("category") or "").strip()
    direction = str(filters.get("direction") or "").strip()
    start = str(filters.get("date_start_effective") or "").strip()
    end = str(filters.get("date_end_effective") or "").strip()
    period = str(filters.get("period") or "all").strip()

    if start or end:
        if start and end:
            tags.append(f"Periodo: {start} ate {end}")
        elif start:
            tags.append(f"Periodo: a partir de {start}")
        else:
            tags.append(f"Periodo: ate {end}")
    elif period and period != "all":
        tags.append(dict(DASHBOARD_PERIOD_OPTIONS).get(period, period))

    if account_id:
        account = next((item for item in accounts if str(item.get("id") or "").strip() == account_id), None)
        tags.append(f"Conta: {build_account_label(account or {})}")
    if card_number:
        tags.append(f"Cartao final {card_number}")
    if category:
        tags.append(f"Categoria: {category}")
    if direction == "entrada":
        tags.append("Somente entradas")
    elif direction == "saida":
        tags.append("Somente saidas")
    return tags


def _dashboard_card_options(accounts: list[dict]) -> list[dict]:
    options: list[dict] = []
    seen: set[str] = set()
    for account in accounts:
        for card in account.get("openfinance_credit_cards") or []:
            number = normalize_card_number(card.get("card_number"))
            if len(number) != 4 or number in seen:
                continue
            seen.add(number)
            options.append({
                "value": number,
                "label": f"{card.get('label') or 'Cartao'} - final {number}",
            })
    options.sort(key=lambda item: item["label"])
    return options


def _dashboard_query_params(filters: dict, *, page: int | None = None) -> dict:
    params: dict[str, str | int] = {}
    period = str(filters.get("period") or "all").strip() or "all"
    if period != "all":
        params["period"] = period
    for key in ("account_id", "card_number", "category", "direction", "date_start", "date_end"):
        value = str(filters.get(key) or "").strip()
        if value:
            params[key] = value
    if page and page > 1:
        params["page"] = page
    return params


def _same_person_transfer_preferences(profile: dict | None = None) -> dict[str, bool]:
    profile = profile or load_customer_profile()
    prefs = profile.get("analysis_preferences") or {}
    entrada = bool(prefs.get("include_same_person_transfer_inflow", True))
    saida = bool(prefs.get("include_same_person_transfer_outflow", True))
    return {
        "entrada": entrada,
        "saida": saida,
        "geral": entrada and saida,
    }


CATEGORY_CHART_PALETTE = [
    "#D7AE17",
    "#35D39A",
    "#8AA8D7",
    "#FF7A68",
    "#F6B560",
    "#C7CDD8",
    "#9C8CFF",
    "#59B9D8",
    "#F28B82",
    "#6ED3B3",
]

CATEGORY_ICON_RULES = [
    (("pix", "transferenc", "mesma titularidade", "same person", "boleto", "ted", "doc"), "&#128176;"),
    (("mercado", "supermercado", "compras", "shopping", "casa e utilidades"), "&#128722;"),
    (("restaurante", "alimentacao", "delivery", "padaria", "cafe", "bar"), "&#127869;&#65039;"),
    (("automot", "combust", "posto", "transporte", "mobilidade", "uber", "estacionamento"), "&#128663;"),
    (("moradia", "aluguel", "condominio", "energia", "agua", "gas", "casa"), "&#127968;"),
    (("invest", "rendimento", "dividend", "fundo", "tesouro", "cdb", "corretora"), "&#128200;"),
    (("salario", "renda", "entrada", "entradas"), "&#128184;"),
    (("saude", "farmacia", "hospital", "clinica"), "&#128138;"),
    (("lazer", "entretenimento", "cinema", "show", "evento"), "&#127916;"),
    (("assinatura", "streaming", "app"), "&#128250;"),
    (("cartao", "credito"), "&#128179;"),
]
DEFAULT_CATEGORY_ICON = "&#128202;"


def _normalize_icon_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _resolve_category_icon(*labels: str) -> str:
    haystack = " ".join(_normalize_icon_key(label) for label in labels if str(label or "").strip())
    for keywords, icon in CATEGORY_ICON_RULES:
        if any(keyword in haystack for keyword in keywords):
            return icon
    return DEFAULT_CATEGORY_ICON


def _category_chart_color(index: int) -> str:
    return CATEGORY_CHART_PALETTE[index % len(CATEGORY_CHART_PALETTE)]


def _build_category_donut_chart(items: list[dict]) -> dict:
    if not items:
        return {}
    entries = [item for item in items if float(item.get("valor") or 0.0) > 0]
    if not entries:
        return {}

    size = 240.0
    center = size / 2.0
    radius = 76.0
    stroke = 24.0
    circumference = 2.0 * math.pi * radius
    progress = 0.0
    slices: list[dict] = []

    total = sum(float(item.get("valor") or 0.0) for item in entries) or 1.0
    dominant = entries[0]

    for index, item in enumerate(entries):
        value = round(float(item.get("valor") or 0.0), 2)
        share_precise = max(0.0, value / total)
        dash = circumference * share_precise
        slices.append({
            "categoria": item.get("categoria") or "Outros",
            "valor": value,
            "share": round(share_precise * 100, 1),
            "stroke": _category_chart_color(index),
            "dasharray": f"{dash:.2f} {max(circumference - dash, 0.0):.2f}",
            "dashoffset": f"{-progress:.2f}",
        })
        progress += dash

    return {
        "size": round(size, 2),
        "center": round(center, 2),
        "radius": round(radius, 2),
        "stroke": round(stroke, 2),
        "circumference": round(circumference, 2),
        "total": round(total, 2),
        "dominant_label": str(dominant.get("categoria") or "Categorias"),
        "dominant_icon": _resolve_category_icon(str(dominant.get("categoria") or "")),
        "dominant_share": round(float(dominant.get("share") or 0.0), 1),
        "slices": slices,
    }


def _build_category_details(items: list[dict], transactions: list[dict], *, per_category_limit: int = 12) -> list[dict]:
    if not items:
        return []

    grouped: dict[str, list[dict]] = {}
    for tx in transactions:
        categoria = str(tx.get("categoria") or "Outros").strip() or "Outros"
        grouped.setdefault(categoria, []).append(tx)

    details: list[dict] = []
    for index, item in enumerate(items):
        categoria = str(item.get("categoria") or "Outros").strip() or "Outros"
        category_transactions = sorted(
            grouped.get(categoria, []),
            key=lambda row: (row.get("data") or "", row.get("id") or ""),
            reverse=True,
        )
        visible_transactions = []
        for tx in category_transactions[:per_category_limit]:
            card_number = normalize_card_number(tx.get("card_number"))
            scope_label = str(tx.get("account_short_label") or tx.get("account_label") or "Conta").strip() or "Conta"
            if card_number:
                scope_label = f"{scope_label} • Cartao {card_number}"
            visible_transactions.append({
                "data": str(tx.get("data") or "").strip(),
                "descricao": str(tx.get("descricao") or "").strip() or "Sem descricao",
                "scope_label": scope_label,
                "valor": round(float(tx.get("valor") or 0.0), 2),
            })

        details.append({
            "categoria": categoria,
            "icon": _resolve_category_icon(categoria),
            "valor": round(float(item.get("valor") or 0.0), 2),
            "share": round(float(item.get("share") or 0.0), 1),
            "stroke": _category_chart_color(index),
            "transaction_count": len(category_transactions),
            "transactions": visible_transactions,
            "has_more_transactions": len(category_transactions) > len(visible_transactions),
        })
    return details


def _build_subcategory_details(items: list[dict], transactions: list[dict], *, per_subcategory_limit: int = 12) -> list[dict]:
    if not items:
        return []

    grouped: dict[str, list[dict]] = {}
    for tx in transactions:
        subcategoria = str(tx.get("subcategoria") or tx.get("categoria") or "Outros").strip() or "Outros"
        grouped.setdefault(subcategoria, []).append(tx)

    max_value = max([float(item.get("valor") or 0.0) for item in items] or [0.0]) or 1.0
    details: list[dict] = []
    for index, item in enumerate(items):
        subcategoria = str(item.get("subcategoria") or "Outros").strip() or "Outros"
        subcategory_transactions = sorted(
            grouped.get(subcategoria, []),
            key=lambda row: (row.get("data") or "", row.get("id") or ""),
            reverse=True,
        )
        category_hint = ""
        if subcategory_transactions:
            category_hint = str(subcategory_transactions[0].get("categoria") or "").strip()
        visible_transactions = []
        for tx in subcategory_transactions[:per_subcategory_limit]:
            card_number = normalize_card_number(tx.get("card_number"))
            scope_label = str(tx.get("account_short_label") or tx.get("account_label") or "Conta").strip() or "Conta"
            if card_number:
                scope_label = f"{scope_label} • Cartao {card_number}"
            visible_transactions.append({
                "data": str(tx.get("data") or "").strip(),
                "descricao": str(tx.get("descricao") or "").strip() or "Sem descricao",
                "scope_label": scope_label,
                "categoria": str(tx.get("categoria") or "Outros").strip() or "Outros",
                "valor": round(float(tx.get("valor") or 0.0), 2),
            })

        valor = round(float(item.get("valor") or 0.0), 2)
        details.append({
            "subcategoria": subcategoria,
            "icon": _resolve_category_icon(subcategoria, category_hint),
            "valor": valor,
            "share": round(float(item.get("share") or 0.0), 1),
            "width_pct": round((valor / max_value) * 100, 1) if max_value else 0.0,
            "stroke": _category_chart_color(index),
            "transaction_count": len(subcategory_transactions),
            "transactions": visible_transactions,
            "has_more_transactions": len(subcategory_transactions) > len(visible_transactions),
        })
    return details


def _build_monthly_combo_chart(monthly: list[dict]) -> dict:
    if not monthly:
        return {}

    view_width = 960.0
    view_height = 376.0
    plot_left = 28.0
    plot_right = 24.0
    plot_top = 44.0
    plot_bottom = 302.0
    plot_width = view_width - plot_left - plot_right
    plot_height = plot_bottom - plot_top
    count = max(len(monthly), 1)
    group_step = plot_width / count
    bar_width = min(36.0, max(22.0, group_step * 0.2))
    bar_gap = min(20.0, max(12.0, group_step * 0.12))
    max_bar_value = max(
        [max(float(item.get("entradas", 0.0)), float(item.get("saidas", 0.0))) for item in monthly] or [0.0]
    ) or 1.0

    grid_lines = []
    for step in range(5):
        y = plot_top + (plot_height * (step / 4.0))
        grid_lines.append(round(y, 2))

    bars: list[dict] = []
    bar_labels: list[dict] = []
    labels: list[dict] = []
    for index, item in enumerate(monthly):
        center_x = plot_left + (group_step * (index + 0.5))
        income_value = round(float(item.get("entradas", 0.0)), 2)
        expense_value = round(float(item.get("saidas", 0.0)), 2)

        income_height = max(8.0, (income_value / max_bar_value) * plot_height) if income_value > 0 else 0.0
        expense_height = max(8.0, (expense_value / max_bar_value) * plot_height) if expense_value > 0 else 0.0
        income_x = center_x - bar_gap / 2.0 - bar_width
        expense_x = center_x + bar_gap / 2.0

        if income_height:
            income_y = round(plot_bottom - income_height, 2)
            bars.append({
                "kind": "income",
                "x": round(income_x, 2),
                "y": income_y,
                "width": round(bar_width, 2),
                "height": round(income_height, 2),
            })
            bar_labels.append({
                "kind": "income",
                "x": round(income_x + (bar_width / 2.0), 2),
                "y": round(max(plot_top + 16.0, income_y - 12.0), 2),
                "text": _dashboard_money(income_value),
            })
        if expense_height:
            expense_y = round(plot_bottom - expense_height, 2)
            bars.append({
                "kind": "expense",
                "x": round(expense_x, 2),
                "y": expense_y,
                "width": round(bar_width, 2),
                "height": round(expense_height, 2),
            })
            bar_labels.append({
                "kind": "expense",
                "x": round(expense_x + (bar_width / 2.0), 2),
                "y": round(max(plot_top + 16.0, expense_y - 12.0), 2),
                "text": _dashboard_money(expense_value),
            })
        labels.append({
            "x": round(center_x, 2),
            "y": round(plot_bottom + 28.0, 2),
            "text": str(item.get("label") or ""),
        })

    return {
        "view_width": round(view_width, 2),
        "view_height": round(view_height, 2),
        "plot_left": round(plot_left, 2),
        "plot_right": round(plot_right, 2),
        "plot_top": round(plot_top, 2),
        "plot_bottom": round(plot_bottom, 2),
        "plot_width": round(plot_width, 2),
        "plot_height": round(plot_height, 2),
        "grid_lines": grid_lines,
        "bars": bars,
        "bar_labels": bar_labels,
        "labels": labels,
    }


def _build_monthly_flow_rows(monthly: list[dict]) -> list[dict]:
    if not monthly:
        return []

    max_value = max(
        [
            max(float(item.get("entradas") or 0.0), float(item.get("saidas") or 0.0))
            for item in monthly
        ] or [0.0]
    ) or 1.0

    rows: list[dict] = []
    for item in monthly:
        entradas = round(float(item.get("entradas") or 0.0), 2)
        saidas = round(float(item.get("saidas") or 0.0), 2)
        saldo_final = round(float(item.get("saldo_final") or 0.0), 2)
        geracao_caixa = round(float(item.get("geracao_caixa") or 0.0), 2)
        rows.append({
            "label": str(item.get("label") or "").strip(),
            "saldo_final": saldo_final,
            "saldo_final_label": _dashboard_money(saldo_final),
            "geracao_caixa": geracao_caixa,
            "geracao_caixa_label": _dashboard_money(geracao_caixa),
            "entradas": entradas,
            "entradas_label": _dashboard_money(entradas),
            "entradas_width_pct": round((entradas / max_value) * 100, 1) if entradas > 0 else 0.0,
            "saidas": saidas,
            "saidas_label": _dashboard_money(saidas),
            "saidas_width_pct": round((saidas / max_value) * 100, 1) if saidas > 0 else 0.0,
        })
    return rows


def _build_monthly_balance_line_chart(monthly: list[dict]) -> dict:
    if not monthly:
        return {}

    view_width = 520.0
    view_height = 300.0
    plot_left = 18.0
    plot_right = 18.0
    plot_top = 28.0
    plot_bottom = 226.0
    plot_width = view_width - plot_left - plot_right
    plot_height = plot_bottom - plot_top

    balances = [
        round(float(item.get("saldo_final", 0.0)), 2)
        for item in monthly
    ]
    min_balance = min(balances or [0.0])
    max_balance = max(balances or [0.0])
    if min_balance == max_balance:
        pad = max(abs(min_balance) * 0.25, 1.0)
        min_balance -= pad
        max_balance += pad
    else:
        pad = max((max_balance - min_balance) * 0.14, 1.0)
        min_balance -= pad
        max_balance += pad

    step_count = max(len(monthly) - 1, 1)
    x_step = plot_width / step_count

    grid_lines = []
    for step in range(5):
        y = plot_top + (plot_height * (step / 4.0))
        grid_lines.append(round(y, 2))

    points: list[dict] = []
    labels: list[dict] = []
    value_labels: list[dict] = []
    for index, item in enumerate(monthly):
        balance_value = round(float(item.get("saldo_final", 0.0)), 2)
        x = plot_left + (x_step * index if len(monthly) > 1 else plot_width / 2.0)
        ratio = (max_balance - balance_value) / (max_balance - min_balance) if max_balance != min_balance else 0.5
        y = plot_top + (ratio * plot_height)
        points.append({
            "x": round(x, 2),
            "y": round(y, 2),
            "value": balance_value,
        })
        labels.append({
            "x": round(x, 2),
            "y": round(plot_bottom + 26.0, 2),
            "text": str(item.get("label") or ""),
        })
        value_labels.append({
            "x": round(x, 2),
            "y": round(max(plot_top + 14.0, y - 12.0), 2),
            "text": _dashboard_money(balance_value),
            "tone": "positive" if balance_value >= 0 else "negative",
        })

    line_points = " ".join(f'{point["x"]},{point["y"]}' for point in points)
    area_points = ""
    if points:
        area_points = " ".join(
            [f'{points[0]["x"]},{plot_bottom}']
            + [f'{point["x"]},{point["y"]}' for point in points]
            + [f'{points[-1]["x"]},{plot_bottom}']
        )

    zero_line_y = None
    if min_balance < 0 < max_balance:
        zero_ratio = (max_balance - 0.0) / (max_balance - min_balance)
        zero_line_y = round(plot_top + (zero_ratio * plot_height), 2)

    latest_value = balances[-1] if balances else 0.0

    return {
        "view_width": round(view_width, 2),
        "view_height": round(view_height, 2),
        "plot_left": round(plot_left, 2),
        "plot_right": round(plot_right, 2),
        "plot_top": round(plot_top, 2),
        "plot_bottom": round(plot_bottom, 2),
        "plot_width": round(plot_width, 2),
        "plot_height": round(plot_height, 2),
        "grid_lines": grid_lines,
        "points": points,
        "line_points": line_points,
        "area_points": area_points,
        "labels": labels,
        "value_labels": value_labels,
        "zero_line_y": zero_line_y,
        "latest_value": round(latest_value, 2),
    }


def _build_monthly_balance_trend(monthly: list[dict]) -> list[dict]:
    """Compat shim for older dashboard code paths.

    The dashboard now renders the monthly chart from `_build_monthly_combo_chart`,
    but a stale reload can still reference the old helper name. Returning the
    combo-chart points keeps those paths safe until the server reloads cleanly.
    """
    chart = _build_monthly_combo_chart(monthly)
    return list(chart.get("points") or [])


def _resolve_chat_session(sessions: list[dict], session_id: str = "") -> dict | None:
    session_id = str(session_id or "").strip()
    if session_id:
        session = next((item for item in sessions if item.get("id") == session_id), None)
        if session:
            return session
    return sessions[0] if sessions else None


def _chat_widget_payload(
    session: dict | None = None,
    *,
    session_id: str = "",
    create_if_missing: bool = False,
) -> dict:
    accounts = load_accounts()
    sessions = list_sessions()
    current_session = session or _resolve_chat_session(sessions, session_id or str(request.args.get("session_id") or "").strip())

    if current_session is None and create_if_missing:
        current_session = ensure_session(None)
        sessions = list_sessions()

    current_session = current_session or {
        "id": "",
        "title": "Nova conversa",
        "messages": [],
    }

    summary = build_dashboard_summary(list_transactions())
    profile = load_customer_profile()
    composer = _chat_composer_meta(current_session if current_session.get("id") else None, accounts)
    auto_open = str(request.args.get("open_chat") or "").strip().lower() in {"1", "true", "yes"}
    if request.endpoint == "main.dashboard" and not _setup_complete(profile, accounts):
        auto_open = True

    return {
        "sessions": sessions,
        "current_session": current_session,
        "summary": summary,
        "summary_balance": format_currency(summary.get("total_entradas", 0.0) - summary.get("total_saidas", 0.0)),
        "chat_activities": _build_chat_activities(current_session if current_session.get("id") else None, accounts),
        "pending_authorizations": _pending_authorization_count(accounts),
        "composer": composer,
        "auto_open": auto_open,
    }


@main_bp.context_processor
def inject_helpers():
    if request.endpoint in {"main.login", "main.register"}:
        return {}
    profile = load_customer_profile()
    accounts = load_accounts()
    return {
        "money": format_currency,
        "dash_money": _dashboard_money,
        "dash_pct": _dashboard_pct,
        "mask_cpf": _mask_cpf,
        "cards_text": _cards_text,
        "bank_map": BANK_MAP,
        "build_account_label": build_account_label,
        "customer_profile": profile,
        "same_person_preferences": _same_person_transfer_preferences(profile),
        "dashboard_current_url": request.full_path.rstrip("?"),
        "setup_complete_global": _setup_complete(profile, accounts),
        "chat_widget": _chat_widget_payload(session_id=str(request.args.get("session_id") or "").strip()),
    }


@main_bp.post("/dashboard/preferences/same-person-transfer")
def toggle_same_person_transfer_preference():
    profile = load_customer_profile()
    direction = str(request.form.get("direction") or "geral").strip()
    enabled = str(request.form.get("enabled") or "").strip().lower() in {"1", "true", "on", "yes"}
    next_url = str(request.form.get("next_url") or request.referrer or url_for("main.dashboard")).strip()
    if not next_url.startswith("/"):
        next_url = url_for("main.dashboard")

    if direction not in {"entrada", "saida", "geral"}:
        flash("Preferencia invalida para mesma titularidade.", "danger")
        return redirect(next_url)

    prefs = profile.setdefault("analysis_preferences", {})
    if direction == "geral":
        prefs["include_same_person_transfer_inflow"] = enabled
        prefs["include_same_person_transfer_outflow"] = enabled
    else:
        key = "include_same_person_transfer_inflow" if direction == "entrada" else "include_same_person_transfer_outflow"
        prefs[key] = enabled
    profile["updated_at"] = now_str()
    save_customer_profile(profile)

    if direction == "geral":
        message = (
            "Transacoes de mesma titularidade agora entram no recorte."
            if enabled
            else "Transacoes de mesma titularidade agora ficam fora do recorte."
        )
    else:
        message = (
            f"Transacoes de mesma titularidade de {'entrada' if direction == 'entrada' else 'saida'} "
            f"agora {'entram' if enabled else 'ficam fora'} do recorte."
        )
    flash(message, "success")
    return redirect(next_url)


@main_bp.route("/login", methods=["GET", "POST"])
def login():
    if not current_app.config.get("AUTH_ENABLED"):
        return redirect(url_for("main.dashboard"))

    next_url = _safe_redirect_target(request.args.get("next") or request.form.get("next") or "")
    if _is_authenticated():
        return redirect(next_url)

    login_value = str(request.form.get("login") or "").strip()
    if request.method == "POST":
        password = str(request.form.get("password") or "")
        ok, user, message = authenticate_user(login_value, password)
        if ok and user:
            _start_authenticated_session(user)
            flash("Sessao iniciada com sucesso.", "success")
            return redirect(next_url)
        flash(message or "Credenciais invalidas.", "danger")

    return render_template(
        "login.html",
        page_key="login",
        next_url=next_url,
        login_value=login_value,
        public_registration_enabled=_public_registration_enabled(),
        has_local_users=has_users(),
    )


@main_bp.route("/register", methods=["GET", "POST"])
def register():
    if not current_app.config.get("AUTH_ENABLED"):
        return redirect(url_for("main.dashboard"))

    next_url = _safe_redirect_target(request.args.get("next") or request.form.get("next") or "")
    authenticated = _is_authenticated()
    public_registration_enabled = _public_registration_enabled()
    can_manage_current_tenant = _can_manage_users()
    claimable_tenant = None if authenticated or has_users() else get_claimable_tenant()

    if authenticated and not can_manage_current_tenant:
        flash("Somente administradores podem cadastrar novos usuarios.", "warning")
        return redirect(url_for("main.dashboard"))
    if not authenticated and not public_registration_enabled:
        flash("O cadastro publico de novas licencas esta desabilitado neste ambiente.", "warning")
        return redirect(url_for("main.login"))
    if authenticated and not next_url:
        next_url = url_for("main.dashboard")

    profile_defaults = _registration_profile_defaults(claimable_tenant) if not authenticated else {}
    form_data = {
        "username": str(request.form.get("username") or "").strip(),
        "email": str(request.form.get("email") or "").strip(),
    }
    if not authenticated:
        for field in PROFILE_FIELDS:
            field_key = field["key"]
            default_value = str(profile_defaults.get(field_key) or "").strip()
            form_data[field_key] = str(request.form.get(field_key) or default_value).strip()
    if request.method == "POST":
        profile_payload = {}
        if not authenticated:
            ok, profile_payload, message = _normalize_registration_profile(form_data)
            if not ok:
                flash(message, "danger")
                return render_template(
                    "register.html",
                    page_key="register",
                    next_url=next_url,
                    form_data=form_data,
                    authenticated=authenticated,
                    public_registration_enabled=public_registration_enabled,
                    current_tenant_name=str(session.get(TENANT_SESSION_NAME_KEY) or "").strip(),
                    claimable_tenant=claimable_tenant,
                    register_profile_fields=_registration_profile_fields(),
                )
        target_tenant_id = str(session.get(TENANT_SESSION_ID_KEY) or "").strip()
        if not authenticated and claimable_tenant:
            target_tenant_id = str(claimable_tenant.get("id") or "").strip()
        ok, user, message = create_user(
            form_data["username"],
            profile_payload.get("email") if not authenticated else form_data["email"],
            str(request.form.get("password") or ""),
            str(request.form.get("password_confirm") or ""),
            tenant_id=target_tenant_id,
            tenant_name="" if authenticated else profile_payload.get("nome", ""),
            tenant_slug="",
            role="operator",
            created_by=str(session.get(AUTH_USER_SESSION_KEY) or "self-service").strip() or "self-service",
            promote_first_user_to_admin=not bool(claimable_tenant),
        )
        if ok and user:
            if not authenticated:
                _start_authenticated_session(user)
                payer_ok, payer_message = _save_registered_profile(profile_payload)
                flash(
                    "Acesso principal criado e sessao iniciada com sucesso."
                    if claimable_tenant
                    else "Licenca criada e sessao iniciada com sucesso.",
                    "success",
                )
                if not payer_ok and payer_message:
                    flash(payer_message, "warning")
                return redirect(next_url or url_for("main.dashboard"))
            flash("Usuario criado com sucesso.", "success")
            return redirect(url_for("main.register"))
        flash(message or "Nao foi possivel criar o usuario.", "danger")

    return render_template(
        "register.html",
        page_key="register",
        next_url=next_url,
        form_data=form_data,
        authenticated=authenticated,
        public_registration_enabled=public_registration_enabled,
        current_tenant_name=str(session.get(TENANT_SESSION_NAME_KEY) or "").strip(),
        claimable_tenant=claimable_tenant,
        register_profile_fields=_registration_profile_fields(),
    )


@main_bp.post("/logout")
def logout():
    session.clear()
    flash("Sessao encerrada.", "success")
    if current_app.config.get("AUTH_ENABLED"):
        return redirect(url_for("main.login"))
    return redirect(url_for("main.dashboard"))


@main_bp.get("/")
def dashboard():
    _run_automatic_sync_cycle()
    context = _dashboard_context()
    accounts = context["accounts"]
    profile = load_customer_profile()
    all_transactions = list_transactions()
    period = str(request.args.get("period") or "all").strip() or "all"
    account_id = str(request.args.get("account_id") or "").strip()
    card_number = str(request.args.get("card_number") or "").strip()
    category = str(request.args.get("category") or "").strip()
    direction = str(request.args.get("direction") or "").strip()
    raw_date_start = str(request.args.get("date_start") or "").strip()
    raw_date_end = str(request.args.get("date_end") or "").strip()
    try:
        page = max(1, int(str(request.args.get("page") or "1").strip() or "1"))
    except ValueError:
        page = 1
    if raw_date_start or raw_date_end:
        date_start = raw_date_start
        date_end = raw_date_end
    else:
        date_start, date_end = _dashboard_period_dates(period)

    parsed_start = parse_date(date_start)
    parsed_end = parse_date(date_end)
    if parsed_start and parsed_end and parsed_start > parsed_end:
        parsed_start, parsed_end = parsed_end, parsed_start
        date_start = normalize_date_str(parsed_start)
        date_end = normalize_date_str(parsed_end)

    filtered_transactions = filter_transactions(
        transactions=all_transactions,
        account_id=account_id,
        card_number=card_number,
        category=category,
        direction=direction,
        date_start=date_start,
        date_end=date_end,
    )
    summary = build_dashboard_summary(filtered_transactions)
    context["summary"] = summary
    categories = sorted({str(tx.get("categoria") or "").strip() for tx in all_transactions if str(tx.get("categoria") or "").strip()})
    filters = {
        "period": period,
        "account_id": account_id,
        "card_number": card_number,
        "category": category,
        "direction": direction,
        "date_start": raw_date_start,
        "date_end": raw_date_end,
        "date_start_effective": date_start,
        "date_end_effective": date_end,
    }
    total_filtered_transactions = len(filtered_transactions)
    total_pages = max(1, (total_filtered_transactions + DASHBOARD_TX_PAGE_SIZE - 1) // DASHBOARD_TX_PAGE_SIZE) if total_filtered_transactions else 1
    page = min(page, total_pages)
    page_start = (page - 1) * DASHBOARD_TX_PAGE_SIZE
    page_end = page_start + DASHBOARD_TX_PAGE_SIZE
    paged_transactions = filtered_transactions[page_start:page_end]
    visible_page_numbers = sorted(
        {
            number
            for number in (
                1,
                total_pages,
                page - 2,
                page - 1,
                page,
                page + 1,
                page + 2,
            )
            if 1 <= number <= total_pages
        }
    )
    pagination_pages: list[dict] = []
    last_number = 0
    for number in visible_page_numbers:
        if last_number and number - last_number > 1:
            pagination_pages.append({"gap": True})
        pagination_pages.append({
            "number": number,
            "current": number == page,
            "url": url_for("main.dashboard", **_dashboard_query_params(filters, page=number)),
        })
        last_number = number
    monthly_flow_rows = _build_monthly_flow_rows(summary.get("monthly") or [])
    monthly_balance_chart = _build_monthly_balance_line_chart(summary.get("monthly") or [])
    category_chart = _build_category_donut_chart(summary.get("top_categories") or [])
    category_details = _build_category_details(summary.get("top_categories") or [], filtered_transactions)
    subcategory_details = _build_subcategory_details(summary.get("top_subcategories") or [], filtered_transactions)
    subcategory_max = max([item.get("valor", 0.0) for item in summary.get("top_subcategories") or []] or [1.0])
    account_max = max([item.get("movimentado", 0.0) for item in summary.get("account_breakdown") or []] or [1.0])
    return render_template(
        "dashboard.html",
        page_key="dashboard",
        dash_money=_dashboard_money,
        dash_pct=_dashboard_pct,
        monthly_flow_rows=monthly_flow_rows,
        monthly_balance_chart=monthly_balance_chart,
        category_chart=category_chart,
        category_details=category_details,
        subcategory_details=subcategory_details,
        subcategory_max=subcategory_max,
        account_max=account_max,
        dashboard_transactions=paged_transactions,
        dashboard_cards=_dashboard_card_options(accounts),
        dashboard_tx_pagination={
            "page": page,
            "page_size": DASHBOARD_TX_PAGE_SIZE,
            "total_items": total_filtered_transactions,
            "total_pages": total_pages,
            "start_item": page_start + 1 if total_filtered_transactions else 0,
            "end_item": min(page_end, total_filtered_transactions),
            "prev_url": url_for("main.dashboard", **_dashboard_query_params(filters, page=page - 1)) if page > 1 else "",
            "next_url": url_for("main.dashboard", **_dashboard_query_params(filters, page=page + 1)) if page < total_pages else "",
            "pages": pagination_pages,
        },
        dashboard_filters=filters,
        dashboard_periods=[{"value": value, "label": label} for value, label in DASHBOARD_PERIOD_OPTIONS],
        dashboard_categories=categories,
        dashboard_scope_label=_dashboard_scope_label(filters, len(filtered_transactions)),
        dashboard_filter_tags=_dashboard_filter_tags(filters, accounts),
        same_person_preferences=_same_person_transfer_preferences(profile),
        dashboard_current_url=request.full_path.rstrip("?"),
        **context,
    )


@main_bp.route("/perfil", methods=["GET", "POST"])
def profile_view():
    profile = load_customer_profile()
    accounts = load_accounts()
    state = _ensure_onboarding_state(profile, accounts)

    if request.method == "POST":
        ok, message = _apply_profile_field_edit(
            str(request.form.get("field_key") or "").strip(),
            str(request.form.get("field_value") or "").strip(),
        )
        flash("Dado do cliente atualizado." if ok else message, "success" if ok else "danger")
        return redirect(url_for("main.profile_view"))

    def profile_item(field_key: str) -> dict:
        field = _profile_field(field_key) or {}
        raw_value = str(profile.get(field_key) or "").strip()
        display_value = raw_value or "Nao informado"
        if field_key == "cpf" and raw_value:
            display_value = _mask_cpf(raw_value)
        input_mode = ""
        if field_key in {"cpf", "cep", "numero"}:
            input_mode = "numeric"
        elif field_key == "telefone":
            input_mode = "tel"
        return {
            "key": field_key,
            "label": PROFILE_FIELD_LABELS.get(field_key, field_key),
            "value": display_value,
            "raw_value": raw_value,
            "placeholder": str(field.get("placeholder") or "").strip(),
            "input_type": str(field.get("input_type") or "text").strip(),
            "input_mode": input_mode,
            "required": bool(field.get("required")),
        }

    profile_sections = [
        {
            "title": "Identificacao",
            "items": [
                profile_item("nome"),
                profile_item("cpf"),
                profile_item("email"),
                profile_item("telefone"),
            ],
        },
        {
            "title": "Endereco",
            "items": [
                profile_item("logradouro"),
                profile_item("numero"),
                profile_item("bairro"),
                profile_item("complemento"),
                profile_item("cidade"),
                profile_item("estado"),
                profile_item("cep"),
            ],
        },
    ]

    return render_template(
        "profile.html",
        page_key="profile",
        profile=profile,
        profile_sections=profile_sections,
        setup_complete=_setup_complete(profile, accounts),
        total_accounts=len(accounts),
        total_cards=sum(len(account.get("openfinance_credit_cards") or []) for account in accounts),
        onboarding_stage_number=_stage_number(str(state.get("stage") or "profile")),
    )


@main_bp.route("/conexoes", methods=["GET", "POST"])
def connections():
    profile = load_customer_profile()
    accounts = load_accounts()
    state = _ensure_onboarding_state(profile, accounts)

    if request.method == "POST":
        action = str(request.form.get("action") or "").strip()

        if action == "reset_onboarding":
            _reset_onboarding_state_from_data("Fluxo reaberto. Vamos continuar pelo chat.")
            return redirect(url_for("main.connections", open_chat=1))

        if action == "onboarding_choice":
            choice = str(request.form.get("choice") or "").strip()
            _append_message(state, "user", dict((item["value"], item["label"]) for item in (_current_onboarding_prompt(state, accounts) or {}).get("choices", [])).get(choice, choice))
            _process_onboarding_choice(state, choice)
            return redirect(url_for("main.connections"))

        if action == "onboarding_answer":
            submit_action = str(request.form.get("submit_action") or "").strip()
            prompt = _current_onboarding_prompt(state, accounts)
            if not prompt or prompt.get("kind") != "field":
                return redirect(url_for("main.connections"))

            answer = str(request.form.get("answer") or "").strip()
            stage = str(state.get("stage") or "").strip()
            cursor = int(state.get("cursor") or 0)
            if stage == "accounts" and ACCOUNT_FIELDS[cursor]["key"] == "banco":
                answer = str(request.form.get("answer_manual") or answer).strip()

            if not answer and submit_action == "skip" and prompt.get("allow_skip"):
                answer = ""
            elif not answer and prompt.get("required"):
                flash("Responda a pergunta atual para continuar.", "danger")
                return redirect(url_for("main.connections"))

            if stage == "profile":
                ok, message = _save_profile_answer(state, PROFILE_FIELDS[cursor], answer)
            elif stage == "accounts":
                ok, message = _save_account_answer(state, ACCOUNT_FIELDS[cursor], answer)
            elif stage == "cards":
                ok, message = _save_card_answer(state, CARD_FIELDS[cursor], answer)
            else:
                ok, message = False, "Nao ha pergunta pendente agora."

            if not ok:
                flash(message, "danger")
            return redirect(url_for("main.connections"))

        if action == "edit_profile_field":
            ok, message = _edit_profile_field(
                state,
                str(request.form.get("field_key") or "").strip(),
                str(request.form.get("field_value") or "").strip(),
            )
            flash("Dado do cliente atualizado." if ok else message, "success" if ok else "danger")
            return redirect(url_for("main.connections"))

        if action == "edit_account_field":
            field_key = str(request.form.get("field_key") or "").strip()
            raw_value = (
                str(request.form.get("field_value_bank_manual") or request.form.get("field_value_bank") or "").strip()
                if field_key == "banco"
                else str(request.form.get("field_value") or "").strip()
            )
            ok, message = _edit_account_field(
                state,
                str(request.form.get("account_id") or "").strip(),
                field_key,
                raw_value,
            )
            flash("Conta atualizada." if ok else message, "success" if ok else "danger")
            return redirect(url_for("main.connections"))

        if action == "edit_card_field":
            card_ref = str(request.form.get("card_ref") or "").strip()
            ref_account_id, _, ref_card_number = card_ref.partition("::")
            ok, message = _edit_card_field(
                state,
                str(request.form.get("account_id") or ref_account_id).strip(),
                str(request.form.get("card_number") or ref_card_number).strip(),
                str(request.form.get("field_key") or "").strip(),
                str(request.form.get("field_value") or "").strip(),
            )
            flash("Cartao atualizado." if ok else message, "success" if ok else "danger")
            return redirect(url_for("main.connections"))

        if action == "delete_account":
            ok, message = _delete_account(str(request.form.get("account_id") or "").strip())
            flash(message, "success" if ok else "danger")
            return redirect(url_for("main.connections"))

        if action == "delete_card":
            card_ref = str(request.form.get("card_ref") or "").strip()
            ref_account_id, _, ref_card_number = card_ref.partition("::")
            ok, message = _delete_card(ref_account_id.strip(), ref_card_number.strip())
            flash(message, "success" if ok else "danger")
            return redirect(url_for("main.connections"))

        if action == "resume_account_onboarding":
            _resume_account_onboarding(state)
            return redirect(url_for("main.connections"))

        if action == "resume_card_onboarding":
            ok, message = _resume_card_onboarding(
                state,
                str(request.form.get("account_id") or "").strip(),
            )
            if not ok:
                flash(message, "danger")
            return redirect(url_for("main.connections"))

        if action == "retry_payer_activation":
            account_id = str(request.form.get("account_id") or "").strip()
            account = next((item for item in accounts if str(item.get("id") or "").strip() == account_id), None)
            payer = _find_payer_by_account(account or {})
            if not payer:
                flash("Nao consegui localizar o titular vinculado a esta conta.", "danger")
                return redirect(url_for("main.connections"))
            ok, message = _activate_payer(str(payer.get("id") or "").strip())
            flash(message, "success" if ok else "danger")
            return redirect(url_for("main.connections"))

        if action == "prepare_account_connection":
            account_id = str(request.form.get("account_id") or "").strip()
            account = next((item for item in accounts if str(item.get("id") or "").strip() == account_id), None)
            payer = _find_payer_by_account(account or {})
            if payer and not (payer.get("statement_actived") or payer.get("tecnospeed_status") == "ACTIVE"):
                ok, message = _activate_payer(str(payer.get("id") or "").strip())
                if not ok:
                    flash(message, "danger")
                    return redirect(url_for("main.connections"))
            ok, message = create_remote_account(account_id)
            flash(message, "success" if ok else "danger")
            return redirect(url_for("main.connections"))

        if action == "create_statement_protocol":
            ok, message = create_statement_protocol(
                str(request.form.get("account_id") or "").strip(),
                statement_type=str(request.form.get("statement_type") or "ACCOUNT").strip().upper(),
                card_number=str(request.form.get("card_number") or "").strip(),
            )
            flash(message, "success" if ok else "danger")
            return redirect(url_for("main.connections"))

        if action == "refresh_statement_protocol":
            ok, message = refresh_statement_protocol(str(request.form.get("import_id") or "").strip())
            flash(message, "success" if ok else "danger")
            return redirect(url_for("main.connections"))

    _run_automatic_sync_cycle()
    profile = load_customer_profile()
    accounts = load_accounts()
    state = _ensure_onboarding_state(profile, accounts)
    prompt = _current_onboarding_prompt(state, accounts)
    account_connection_notes: dict[str, str] = {}
    accounts_view: list[dict] = []

    def build_account_edit_item(account: dict, field: dict) -> dict:
        field_key = str(field.get("key") or "").strip()
        raw_source = account.get(field_key)
        raw_value = str(raw_source or "").strip()
        display_value = raw_value or "Nao informado"
        input_type = "text"
        input_mode = "text"
        placeholder = str(field.get("placeholder") or "").strip()

        if field_key == "banco":
            display_value = BANK_MAP.get(raw_value, raw_value or "Nao informado")
            placeholder = "Ex.: 102 - SC XP Investimentos ou 348 - Banco XP"
        elif field_key in {"agencia", "conta"}:
            input_mode = "numeric"
        elif field_key == "saldo_inicial":
            input_mode = "decimal"
            amount = money_to_float(raw_source)
            raw_value = f"{amount:.2f}".replace(".", ",")
            display_value = format_currency(amount)
            placeholder = "Ex.: 0,00"

        return {
            "key": field_key,
            "label": ACCOUNT_FIELD_LABELS.get(field_key, field_key),
            "value": display_value,
            "raw_value": raw_value,
            "placeholder": placeholder,
            "input_type": input_type,
            "input_mode": input_mode,
            "required": bool(field.get("required")),
            "is_bank": field_key == "banco",
        }

    for account in accounts:
        note = str(account.get("openfinance_last_error") or "").strip()
        if not note:
            note = validate_openfinance_account(account)
        if note:
            account_connection_notes[str(account.get("id") or "").strip()] = note
        account_view = dict(account)
        account_view["edit_items"] = [build_account_edit_item(account_view, field) for field in ACCOUNT_FIELDS]
        accounts_view.append(account_view)

    return render_template(
        "connections.html",
        page_key="setup",
        profile=profile,
        accounts=accounts_view,
        bank_select_options=[{"value": code, "label": f"{code} - {label}"} for code, label in BANK_OPTIONS],
        total_cards=sum(len(account.get("openfinance_credit_cards") or []) for account in accounts),
        card_edit_fields=[{"key": key, "label": label} for key, label in CARD_FIELD_LABELS.items()],
        onboarding_state=state,
        onboarding_prompt=prompt,
        onboarding_stage_number=_stage_number(str(state.get("stage") or "profile")),
        setup_complete=_setup_complete(profile, accounts),
        account_connection_notes=account_connection_notes,
    )


@main_bp.route("/operacoes", methods=["GET", "POST"])
def operations_view():
    if request.method == "POST":
        action = str(request.form.get("action") or "").strip()
        if action == "refresh_statement_protocol":
            ok, message = refresh_statement_protocol(str(request.form.get("import_id") or "").strip())
            flash(message, "success" if ok else "danger")
            return redirect(url_for("main.operations_view"))
        if action == "run_sync_cycle":
            _run_automatic_sync_cycle()
            flash("Fila automatica atualizada.", "success")
            return redirect(url_for("main.operations_view"))

    _run_automatic_sync_cycle()
    accounts = load_accounts()
    imports = sorted(load_statement_imports(), key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
    logs = _load_openfinance_logs()
    processing = sum(1 for item in imports if str(item.get("status") or "").strip().upper() not in {"SUCCESS", "COMPLETED", "DONE"})
    return render_template(
        "operations.html",
        page_key="operations",
        imports=imports,
        logs=logs,
        accounts=accounts,
        imports_processing=processing,
        imports_completed=len(imports) - processing,
        pending_authorizations=_pending_authorization_count(accounts),
    )


@main_bp.get("/transacoes")
def transactions_view():
    return redirect(url_for("main.dashboard", **request.args.to_dict(flat=True)))


@main_bp.get("/chat")
def chat_view():
    params = request.args.to_dict(flat=True)
    params["open_chat"] = "1"
    return redirect(url_for("main.dashboard", **params))


@main_bp.get("/healthz")
def healthz():
    return jsonify({"ok": True})


@main_bp.post("/api/chat/session")
def api_chat_session():
    session = ensure_session(None)
    payload = _chat_widget_payload(session, create_if_missing=True)
    return jsonify({
        "ok": True,
        "session_id": payload["current_session"].get("id"),
        "sessions": payload["sessions"],
        "messages": payload["current_session"].get("messages") or [],
        "activities": payload["chat_activities"],
        "composer": payload["composer"],
        "pending_authorizations": payload["pending_authorizations"],
        "summary_balance": payload["summary_balance"],
    })


@main_bp.get("/api/chat/session/<session_id>")
def api_chat_session_detail(session_id: str):
    session = get_session(str(session_id or "").strip())
    if not session:
        return jsonify({"ok": False, "error": "Conversa nao encontrada."}), 404
    payload = _chat_widget_payload(session, session_id=session_id)
    return jsonify({
        "ok": True,
        "session_id": payload["current_session"].get("id"),
        "sessions": payload["sessions"],
        "messages": payload["current_session"].get("messages") or [],
        "activities": payload["chat_activities"],
        "composer": payload["composer"],
        "pending_authorizations": payload["pending_authorizations"],
        "summary_balance": payload["summary_balance"],
    })


@main_bp.post("/api/chat/message")
def api_chat_message():
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("session_id") or "").strip()
    message = str(payload.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "Mensagem vazia."}), 400
    correction_session = _handle_chat_correction_message(session_id or None, message)
    onboarding_session = None if correction_session else _handle_chat_onboarding_message(session_id or None, message)
    session = correction_session or onboarding_session or send_chat_message(session_id or None, message)
    response_payload = _chat_widget_payload(session, create_if_missing=True)
    return jsonify({
        "ok": True,
        "session_id": response_payload["current_session"].get("id"),
        "title": response_payload["current_session"].get("title"),
        "sessions": response_payload["sessions"],
        "messages": response_payload["current_session"].get("messages") or [],
        "activities": response_payload["chat_activities"],
        "composer": response_payload["composer"],
        "pending_authorizations": response_payload["pending_authorizations"],
        "summary_balance": response_payload["summary_balance"],
    })


@main_bp.post("/api/chat/activity")
def api_chat_activity():
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action") or "").strip()
    account_id = str(payload.get("account_id") or "").strip()
    card_number = str(payload.get("card_number") or "").strip()
    field_key = str(payload.get("field_key") or "").strip()
    value = str(payload.get("value") or "").strip()
    session_id = str(payload.get("session_id") or "").strip() or None
    action_label = str(payload.get("label") or "").strip()
    if not action:
        return jsonify({"ok": False, "error": "Atividade invalida."}), 400
    session, success = _handle_chat_activity_action(session_id, action, account_id, action_label, card_number, field_key, value)
    response_payload = _chat_widget_payload(session, create_if_missing=True)
    return jsonify({
        "ok": True,
        "success": success,
        "session_id": response_payload["current_session"].get("id"),
        "title": response_payload["current_session"].get("title"),
        "sessions": response_payload["sessions"],
        "messages": response_payload["current_session"].get("messages") or [],
        "activities": response_payload["chat_activities"],
        "composer": response_payload["composer"],
        "pending_authorizations": response_payload["pending_authorizations"],
        "summary_balance": response_payload["summary_balance"],
    })
