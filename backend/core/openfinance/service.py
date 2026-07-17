# -*- coding: utf-8 -*-
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta

from backend.core.common.dates import parse_date
from backend.core.common.utils import now_str
from backend.core.openfinance.accounts_store import load_accounts, save_accounts
from backend.core.openfinance.client import openfinance_request
from backend.core.openfinance.config_store import load_openfinance_config
from backend.core.openfinance.helpers import (
    build_account_scope_label,
    format_import_name,
    normalize_card_number,
    normalize_statement_type,
    parse_openfinance_transactions,
)
from backend.core.openfinance.payers_store import load_openfinance_payers
from backend.core.openfinance.statements_store import load_statement_imports, save_statement_imports

SYNC_SUCCESS_STATUSES = {"SUCCESS", "COMPLETED", "DONE"}
SYNC_FINAL_ERROR_STATUSES = {"FAILED", "ERROR", "CANCELLED"}
SYNC_FINAL_STATUSES = SYNC_SUCCESS_STATUSES | SYNC_FINAL_ERROR_STATUSES
DEFAULT_SYNC_HISTORY_MONTHS = 6
PENDING_AUTH_REFRESH_INTERVAL_SECONDS = 300


def _active_payer_map() -> dict[str, dict]:
    return {
        item.get("cpf_cnpj"): item
        for item in load_openfinance_payers()
        if isinstance(item, dict) and item.get("cpf_cnpj")
    }


def _error_detail(data, err) -> str:
    if isinstance(data, dict):
        message = str(data.get("message") or data.get("error") or data.get("raw") or "").strip()
        if message:
            return message
    if data:
        return str(data).strip()
    return str(err or "").strip()


def _set_account_last_error(account: dict, message: str) -> None:
    account["openfinance_last_error"] = str(message or "").strip()
    account["updated_at"] = now_str()


def _shift_months(base_date: date, months: int) -> date:
    month_index = (base_date.year * 12 + (base_date.month - 1)) + months
    year = month_index // 12
    month = (month_index % 12) + 1
    day = min(base_date.day, monthrange(year, month)[1])
    return date(year, month, day)


def _initial_sync_start(end_date: date) -> date:
    return _shift_months(end_date, -DEFAULT_SYNC_HISTORY_MONTHS) + timedelta(days=1)


def _status_upper(row: dict) -> str:
    return str(row.get("status") or "").strip().upper()


def _is_pending_status(status: str) -> bool:
    return bool(status) and status not in SYNC_FINAL_STATUSES


def _scope_imports(
    imports: list[dict],
    account_id: str,
    *,
    statement_type: str = "ACCOUNT",
    card_number: str = "",
) -> list[dict]:
    statement_type = normalize_statement_type(statement_type)
    card_number = normalize_card_number(card_number)
    rows = [
        item for item in imports
        if str(item.get("account_id") or "").strip() == account_id
        and normalize_statement_type(item.get("statement_type")) == statement_type
        and normalize_card_number(item.get("card_number")) == card_number
    ]
    rows.sort(key=lambda row: row.get("updated_at") or row.get("created_at") or "", reverse=True)
    return rows


def _scope_is_syncable(account: dict) -> bool:
    if not account.get("ativo", True):
        return False
    if not str(account.get("openfinance_account_hash") or "").strip():
        return False
    remote_status = str(account.get("openfinance_remote_status") or "").strip().upper()
    if remote_status and remote_status not in {"ATIVO", "ACTIVE"}:
        return False
    return not validate_openfinance_account(account)


def _metadata_check_age_seconds(account: dict) -> float | None:
    checked_at = str(account.get("openfinance_last_metadata_check_at") or "").strip()
    if not checked_at:
        return None
    try:
        return (datetime.now() - datetime.strptime(checked_at, "%Y-%m-%d %H:%M:%S")).total_seconds()
    except Exception:
        return None


def _should_refresh_pending_authorization(account: dict) -> bool:
    if not account.get("ativo", True):
        return False
    if not str(account.get("openfinance_account_hash") or "").strip():
        return False
    if validate_openfinance_account(account):
        return False
    remote_status = str(account.get("openfinance_remote_status") or "").strip().upper()
    if remote_status in {"ATIVO", "ACTIVE"}:
        return False
    age_seconds = _metadata_check_age_seconds(account)
    return age_seconds is None or age_seconds >= PENDING_AUTH_REFRESH_INTERVAL_SECONDS


def _extract_remote_account(data_info: dict) -> dict:
    if not isinstance(data_info, dict):
        return {}
    accounts = data_info.get("accounts")
    if isinstance(accounts, dict):
        return accounts
    if isinstance(accounts, list) and accounts:
        return accounts[0] if isinstance(accounts[0], dict) else {}
    return data_info


def _sync_remote_account_metadata(account: dict, cfg: dict) -> tuple[bool, str]:
    account_hash = str(account.get("openfinance_account_hash") or "").strip()
    if not account_hash:
        return False, "Informe o accountHash para atualizar a conta Open Finance."

    ok, status, data, err = openfinance_request(cfg, "GET", f"account/{account_hash}")
    if not ok or not isinstance(data, dict):
        return False, f"Erro ao atualizar conta Open Finance ({status}): {_error_detail(data, err) or 'falha na requisicao'}"

    remote = _extract_remote_account(data)
    openfinance_link = str(remote.get("openfinanceLink") or "").strip()
    openfinance_id = str(remote.get("openfinanceId") or "").strip()
    status_of = str(remote.get("statusOpenfinance") or remote.get("status") or "").strip()

    if openfinance_link:
        account["openfinance_link"] = openfinance_link
    if openfinance_id:
        account["openfinance_id"] = openfinance_id
    if status_of:
        account["openfinance_remote_status"] = status_of
    account["updated_at"] = now_str()
    return True, ""


def refresh_remote_account(account_id: str) -> tuple[bool, str]:
    accounts = load_accounts()
    account = next((item for item in accounts if item.get("id") == account_id), None)
    if not account:
        return False, "Conta nao encontrada."

    validation_error = validate_openfinance_account(account)
    if validation_error:
        account["openfinance_last_metadata_check_at"] = now_str()
        _set_account_last_error(account, validation_error)
        save_accounts(accounts)
        return False, validation_error

    cfg = load_openfinance_config()
    cfg["payer_cpf_cnpj"] = account.get("openfinance_payer_cpf_cnpj") or ""
    ok, message = _sync_remote_account_metadata(account, cfg)
    account["openfinance_last_metadata_check_at"] = now_str()
    if not ok:
        _set_account_last_error(account, message)
        save_accounts(accounts)
        return False, message

    account["openfinance_last_error"] = ""
    save_accounts(accounts)
    return True, "Conta Open Finance atualizada."


def validate_openfinance_account(account: dict) -> str:
    cfg = load_openfinance_config()
    if not str(cfg.get("cnpjsh") or "").strip() or not str(cfg.get("tokensh") or "").strip():
        return "A infraestrutura de conexao segura ainda nao foi configurada no sistema."
    payer = str(account.get("openfinance_payer_cpf_cnpj") or "").strip()
    if not payer:
        return "Finalize os dados do titular antes de conectar a conta."
    payer_map = _active_payer_map()
    if payer in payer_map:
        active = payer_map[payer].get("statement_actived") or payer_map[payer].get("tecnospeed_status") == "ACTIVE"
        if not active:
            last_error = str(payer_map[payer].get("last_error") or "").strip()
            if last_error:
                return last_error
            return "O perfil bancario do titular ainda nao foi validado para Open Finance."
    return ""


def create_remote_account(account_id: str) -> tuple[bool, str]:
    accounts = load_accounts()
    account = next((item for item in accounts if item.get("id") == account_id), None)
    if not account:
        return False, "Conta nao encontrada."
    validation_error = validate_openfinance_account(account)
    if validation_error:
        _set_account_last_error(account, validation_error)
        save_accounts(accounts)
        return False, validation_error

    bank_code = str(account.get("banco") or "").strip()
    agency = str(account.get("agencia") or "").strip()
    number = str(account.get("conta") or "").strip()
    if not bank_code or not agency or not number:
        _set_account_last_error(account, "Informe banco, agencia e conta antes de criar a conta Open Finance.")
        save_accounts(accounts)
        return False, "Informe banco, agencia e conta antes de criar a conta Open Finance."

    cfg = load_openfinance_config()
    cfg["payer_cpf_cnpj"] = account.get("openfinance_payer_cpf_cnpj") or ""
    payload = [{
        "bankCode": bank_code,
        "agency": agency,
        "agencyDigit": str(account.get("openfinance_agencia_dig") or "").strip(),
        "accountNumber": number,
        "accountNumberDigit": str(account.get("openfinance_conta_dig") or "").strip(),
        "accountDac": str(account.get("openfinance_conta_dig") or "").strip(),
        "convenioAgency": None,
        "convenioNumber": "",
        "remessaSequential": 0,
        "accountPayment": bool(account.get("openfinance_account_payment")),
        "webservice": bool(account.get("openfinance_webservice")),
        "recipientNotification": bool(account.get("openfinance_recipient_notification")),
        "statementActived": True,
    }]
    account_type = str(account.get("openfinance_account_type") or "").strip()
    if bank_code == "104" and account_type:
        try:
            payload[0]["accountType"] = int(account_type)
        except Exception:
            pass

    ok, status, data, err = openfinance_request(cfg, "POST", "account", payload=payload)
    if not ok:
        message = f"Erro ao criar conta Open Finance ({status}): {_error_detail(data, err) or 'falha na requisicao'}"
        _set_account_last_error(account, message)
        save_accounts(accounts)
        return False, message

    account_hash = ""
    remote_link = ""
    remote_id = ""
    if isinstance(data, dict):
        accounts_payload = data.get("accounts") if isinstance(data.get("accounts"), list) else None
        if accounts_payload:
            account_hash = accounts_payload[0].get("accountHash") or accounts_payload[0].get("hash") or ""
            remote_link = accounts_payload[0].get("openfinanceLink") or ""
            remote_id = accounts_payload[0].get("openfinanceId") or ""
        else:
            account_hash = data.get("accountHash") or data.get("hash") or ""
    elif isinstance(data, list) and data:
        first = data[0] if isinstance(data[0], dict) else {}
        account_hash = first.get("accountHash") or first.get("hash") or ""
        remote_link = first.get("openfinanceLink") or ""
        remote_id = first.get("openfinanceId") or ""

    if not account_hash:
        _set_account_last_error(account, "A API nao retornou accountHash.")
        save_accounts(accounts)
        return False, "A API nao retornou accountHash."

    account["openfinance_account_hash"] = account_hash
    account["openfinance_last_error"] = ""
    if remote_link:
        account["openfinance_link"] = remote_link
    if remote_id:
        account["openfinance_id"] = remote_id
    if not remote_link or not remote_id:
        _sync_remote_account_metadata(account, cfg)
    account["updated_at"] = now_str()
    save_accounts(accounts)
    return True, "Conta Open Finance criada ou atualizada."


def create_statement_protocol(
    account_id: str,
    *,
    date_start: str = "",
    date_end: str = "",
    statement_type: str = "ACCOUNT",
    card_number: str = "",
    automatic: bool = False,
) -> tuple[bool, str]:
    accounts = load_accounts()
    imports = load_statement_imports()
    account = next((item for item in accounts if item.get("id") == account_id), None)
    if not account:
        return False, "Conta nao encontrada."
    validation_error = validate_openfinance_account(account)
    if validation_error:
        return False, validation_error
    account_hash = str(account.get("openfinance_account_hash") or "").strip()
    if not account_hash:
        return False, "Finalize a preparacao da conta antes de iniciar a sincronizacao."

    statement_type = normalize_statement_type(statement_type)
    card_number = normalize_card_number(card_number)
    plan = None
    if not str(date_start or "").strip() or not str(date_end or "").strip():
        plan = get_statement_sync_plan(
            account_id,
            statement_type=statement_type,
            card_number=card_number,
        )
        if not plan.get("available"):
            return True, str(plan.get("message") or "Nenhuma nova movimentacao encontrada para sincronizar.")
        date_start = str(plan.get("period_start") or "").strip()
        date_end = str(plan.get("period_end") or "").strip()

    cfg = load_openfinance_config()
    cfg["payer_cpf_cnpj"] = account.get("openfinance_payer_cpf_cnpj") or ""
    if not str(account.get("openfinance_remote_status") or "").strip():
        ok_sync, sync_message = _sync_remote_account_metadata(account, cfg)
        if not ok_sync:
            _set_account_last_error(account, sync_message)
            save_accounts(accounts)
            return False, sync_message
        save_accounts(accounts)

    status_of = str(account.get("openfinance_remote_status") or "").strip().upper()
    if status_of and status_of not in {"ATIVO", "ACTIVE"}:
        return False, "Finalize a autorizacao do banco antes de sincronizar essa conta."

    if statement_type == "CREDIT_CARD" and len(card_number) != 4:
        return False, "Informe os 4 ultimos digitos do cartao."

    existing_scope_imports = _scope_imports(
        imports,
        account_id,
        statement_type=statement_type,
        card_number=card_number,
    )
    existing_period = next(
        (
            item for item in existing_scope_imports
            if str(item.get("period_start") or "").strip() == date_start
            and str(item.get("period_end") or "").strip() == date_end
        ),
        None,
    )
    if existing_period:
        existing_status = _status_upper(existing_period)
        if existing_status in SYNC_SUCCESS_STATUSES:
            return True, "Esse periodo ja foi sincronizado."
        if _is_pending_status(existing_status):
            return True, "Ja existe uma sincronizacao em andamento para esse periodo."
        if automatic:
            return True, "A ultima tentativa automatica para esse periodo ainda nao concluiu com sucesso."

    payload = {
        "accountHash": account_hash,
        "dateStart": date_start,
        "dateEnd": date_end,
        "today": False,
    }
    if statement_type == "CREDIT_CARD":
        payload["statementType"] = "CREDIT_CARD"
        payload["cardNumber"] = card_number

    ok, status, data, err = openfinance_request(cfg, "POST", "statement/openfinance", payload=payload)
    if not ok:
        _set_account_last_error(account, f"Erro ao gerar protocolo ({status}): {_error_detail(data, err) or 'falha na requisicao'}")
        save_accounts(accounts)
        return False, f"Erro ao gerar protocolo ({status}): {_error_detail(data, err) or 'falha na requisicao'}"
    if not isinstance(data, dict):
        return False, "Resposta invalida da API Open Finance."

    unique_id = str(data.get("uniqueId") or data.get("uniqueID") or data.get("protocol") or data.get("id") or "").strip()
    current_status = str(data.get("status") or data.get("state") or data.get("processingStatus") or "").strip()
    if not unique_id:
        return False, "A API nao retornou o protocolo de sincronizacao."
    if any(item.get("unique_id") == unique_id for item in imports):
        return False, "Ja existe uma sincronizacao igual registrada para esta conta."

    timestamp = str(int(__import__("time").time() * 1000))
    imports.append({
        "id": f"imp_{timestamp}",
        "account_id": account_id,
        "account_label": build_account_scope_label(account, statement_type, card_number),
        "created_at": now_str(),
        "updated_at": now_str(),
        "period_start": date_start,
        "period_end": date_end,
        "unique_id": unique_id,
        "status": current_status or "PROCESSING",
        "reason": "",
        "origin": "openfinance",
        "statement_type": statement_type,
        "card_number": card_number,
        "import_name": format_import_name(unique_id, statement_type, card_number),
        "transactions": [],
    })
    account["openfinance_last_sync_at"] = now_str()
    account["openfinance_last_unique_id"] = unique_id
    account["openfinance_last_status"] = current_status or "PROCESSING"
    account["openfinance_last_error"] = ""
    save_accounts(accounts)
    save_statement_imports(imports)
    if plan and plan.get("mode") == "initial":
        return True, "Sincronizacao inicial dos ultimos 6 meses iniciada."
    if plan and plan.get("mode") == "backfill":
        return True, "Backfill dos ultimos 6 meses iniciado."
    if automatic:
        return True, "Atualizacao automatica iniciada."
    return True, "Sincronizacao iniciada."


def refresh_statement_protocol(import_id: str) -> tuple[bool, str]:
    accounts = load_accounts()
    imports = load_statement_imports()
    target = next((item for item in imports if item.get("id") == import_id), None)
    if not target:
        return False, "Importacao nao encontrada."
    account = next((item for item in accounts if item.get("id") == target.get("account_id")), None)
    if not account:
        return False, "Conta vinculada a importacao nao encontrada."
    validation_error = validate_openfinance_account(account)
    if validation_error:
        return False, validation_error

    cfg = load_openfinance_config()
    cfg["payer_cpf_cnpj"] = account.get("openfinance_payer_cpf_cnpj") or ""
    unique_id = str(target.get("unique_id") or "").strip()
    if not unique_id:
        return False, "Registro de sincronizacao invalido."

    ok, status, data, err = openfinance_request(cfg, "GET", f"statement/openfinance/{unique_id}")
    if not ok:
        return False, f"Erro ao buscar protocolo ({status}): {_error_detail(data, err) or 'falha na requisicao'}"
    if not isinstance(data, dict):
        return False, "Resposta invalida da API Open Finance."

    transactions = parse_openfinance_transactions(data)
    current_status = str(
        data.get("status")
        or data.get("state")
        or data.get("processingStatus")
        or ((data.get("statement") or {}).get("status") if isinstance(data.get("statement"), dict) else "")
        or ((data.get("statement") or {}).get("state") if isinstance(data.get("statement"), dict) else "")
        or ""
    ).strip()
    current_reason = str(
        data.get("reason")
        or ((data.get("statement") or {}).get("reason") if isinstance(data.get("statement"), dict) else "")
        or ""
    ).strip()

    target["transactions"] = transactions
    target["status"] = current_status or ("COMPLETED" if transactions else "PROCESSING")
    target["reason"] = current_reason
    target["updated_at"] = now_str()
    account["openfinance_last_sync_at"] = now_str()
    account["openfinance_last_unique_id"] = unique_id
    account["openfinance_last_status"] = target["status"]
    account["openfinance_last_error"] = ""
    save_accounts(accounts)
    save_statement_imports(imports)
    return True, "Protocolo atualizado."


def get_statement_sync_plan(
    account_id: str,
    *,
    statement_type: str = "ACCOUNT",
    card_number: str = "",
    today_value: date | None = None,
) -> dict:
    statement_type = normalize_statement_type(statement_type)
    card_number = normalize_card_number(card_number)
    today_value = today_value or date.today()
    yesterday = today_value - timedelta(days=1)

    account = next((item for item in load_accounts() if item.get("id") == account_id), None)
    if not account:
        return {
            "available": False,
            "mode": "initial",
            "period_start": "",
            "period_end": "",
            "has_success": False,
            "message": "Conta nao encontrada.",
        }

    if yesterday < date(2000, 1, 1):
        return {
            "available": False,
            "mode": "initial",
            "period_start": "",
            "period_end": "",
            "has_success": False,
            "message": "Ainda nao existe uma janela valida para sincronizacao.",
        }

    imports = load_statement_imports()
    scope_rows = _scope_imports(
        imports,
        account_id,
        statement_type=statement_type,
        card_number=card_number,
    )
    successful_rows = [
        item for item in scope_rows
        if _status_upper(item) in SYNC_SUCCESS_STATUSES
    ]
    latest_success = max(
        (
            item for item in successful_rows
            if parse_date(item.get("period_end"))
        ),
        key=lambda item: parse_date(item.get("period_end")) or yesterday,
        default=None,
    )
    earliest_success = min(
        successful_rows,
        key=lambda item: parse_date(item.get("period_start")) or yesterday,
        default=None,
    )

    def build_plan(mode: str, start_date: date, end_date: date, *, has_success: bool, last_success_end: str = "") -> dict:
        pending_same_window = next(
            (
                item for item in scope_rows
                if str(item.get("period_start") or "").strip() == start_date.isoformat()
                and str(item.get("period_end") or "").strip() == end_date.isoformat()
                and _is_pending_status(_status_upper(item))
            ),
            None,
        )
        if pending_same_window:
            return {
                "available": False,
                "mode": mode,
                "period_start": start_date.isoformat(),
                "period_end": end_date.isoformat(),
                "has_success": has_success,
                "last_success_end": last_success_end,
                "message": "Sincronizacao em andamento para essa janela.",
            }
        return {
            "available": start_date <= end_date,
            "mode": mode,
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "has_success": has_success,
            "last_success_end": last_success_end,
            "message": "",
        }

    desired_initial_start = _initial_sync_start(yesterday)

    if latest_success:
        earliest_start = parse_date(earliest_success.get("period_start")) if earliest_success else None
        if earliest_start and desired_initial_start < earliest_start:
            backfill_end = earliest_start - timedelta(days=1)
            if desired_initial_start <= backfill_end:
                return build_plan(
                    "backfill",
                    desired_initial_start,
                    backfill_end,
                    has_success=True,
                    last_success_end=latest_success.get("period_end") or "",
                )
        last_end = parse_date(latest_success.get("period_end"))
        start_date = last_end + timedelta(days=1) if last_end else yesterday
        if start_date > yesterday:
            return {
                "available": False,
                "mode": "incremental",
                "period_start": "",
                "period_end": "",
                "has_success": True,
                "last_success_end": latest_success.get("period_end") or "",
                "message": "Ja sincronizado ate ontem.",
            }
        return build_plan(
            "incremental",
            start_date,
            yesterday,
            has_success=True,
            last_success_end=latest_success.get("period_end") or "",
        )

    start_date = desired_initial_start
    return build_plan(
        "initial",
        start_date,
        yesterday,
        has_success=False,
    )


def run_automatic_statement_updates() -> dict:
    results = {
        "refreshed": [],
        "refreshed_accounts": [],
        "created": [],
        "errors": [],
    }

    pending_rows = load_statement_imports()
    refreshed_scopes = set()
    for item in sorted(pending_rows, key=lambda row: row.get("updated_at") or row.get("created_at") or "", reverse=True):
        status = _status_upper(item)
        if not _is_pending_status(status):
            continue
        scope_key = (
            str(item.get("account_id") or "").strip(),
            normalize_statement_type(item.get("statement_type")),
            normalize_card_number(item.get("card_number")),
        )
        if scope_key in refreshed_scopes:
            continue
        refreshed_scopes.add(scope_key)
        ok, message = refresh_statement_protocol(str(item.get("id") or "").strip())
        if ok:
            results["refreshed"].append({
                "import_id": item.get("id"),
                "message": message,
            })
        else:
            results["errors"].append({
                "scope": scope_key,
                "message": message,
            })

    for account in load_accounts():
        account_id = str(account.get("id") or "").strip()
        if account_id and _should_refresh_pending_authorization(account):
            ok, message = refresh_remote_account(account_id)
            if ok:
                results["refreshed_accounts"].append({
                    "account_id": account_id,
                    "message": message,
                })
            else:
                results["errors"].append({
                    "scope": (account_id, "ACCOUNT_METADATA", ""),
                    "message": message,
                })
            account = next(
                (item for item in load_accounts() if str(item.get("id") or "").strip() == account_id),
                account,
            )
        if not account_id or not _scope_is_syncable(account):
            continue

        for statement_type, card_number in [("ACCOUNT", "")] + [
            ("CREDIT_CARD", normalize_card_number(card.get("card_number")))
            for card in account.get("openfinance_credit_cards") or []
            if len(normalize_card_number(card.get("card_number"))) == 4
        ]:
            plan = get_statement_sync_plan(
                account_id,
                statement_type=statement_type,
                card_number=card_number,
            )
            if not plan.get("available"):
                continue
            ok, message = create_statement_protocol(
                account_id,
                statement_type=statement_type,
                card_number=card_number,
                automatic=True,
            )
            if ok and "iniciada" in message.lower():
                results["created"].append({
                    "account_id": account_id,
                    "statement_type": statement_type,
                    "card_number": card_number,
                    "period_start": plan.get("period_start"),
                    "period_end": plan.get("period_end"),
                })
            elif not ok:
                results["errors"].append({
                    "scope": (account_id, statement_type, card_number),
                    "message": message,
                })

    return results
