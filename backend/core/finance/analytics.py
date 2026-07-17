# -*- coding: utf-8 -*-
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from backend.core.common.dates import parse_date
from backend.core.customer.profile_store import load_customer_profile
from backend.core.finance.categorizer import categorize_transaction_details
from backend.core.openfinance.accounts_store import load_accounts
from backend.core.openfinance.helpers import build_account_label, normalize_card_number
from backend.core.openfinance.statements_store import load_statement_imports, save_statement_imports

MONTH_LABELS = {
    1: "Jan",
    2: "Fev",
    3: "Mar",
    4: "Abr",
    5: "Mai",
    6: "Jun",
    7: "Jul",
    8: "Ago",
    9: "Set",
    10: "Out",
    11: "Nov",
    12: "Dez",
}

WEEKDAY_LABELS = {
    0: "Seg",
    1: "Ter",
    2: "Qua",
    3: "Qui",
    4: "Sex",
    5: "Sab",
    6: "Dom",
}


def _same_person_transfer_preferences() -> dict[str, bool]:
    profile = load_customer_profile()
    prefs = profile.get("analysis_preferences") or {}
    return {
        "entrada": bool(prefs.get("include_same_person_transfer_inflow", True)),
        "saida": bool(prefs.get("include_same_person_transfer_outflow", True)),
    }


def _should_keep_transaction(tx: dict, prefs: dict[str, bool]) -> bool:
    subcategoria = str(tx.get("subcategoria") or "").strip()
    if subcategoria != "Mesma titularidade":
        return True
    direction = "entrada" if float(tx.get("valor") or 0.0) > 0 else "saida"
    return bool(prefs.get(direction, True))


def _nice_axis_max(value: float) -> float:
    value = max(round(float(value or 0.0), 2), 0.0)
    if value <= 0:
        return 100.0

    for step in (10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000):
        rounded = ((int(value) + step - 1) // step) * step
        if rounded / value <= 1.6:
            return float(rounded)
    return float(value)


def backfill_statement_import_categories() -> bool:
    imports = load_statement_imports()
    changed = False

    for import_row in imports:
        for tx in import_row.get("transactions") or []:
            amount = round(float(tx.get("valor") or 0.0), 2)
            category, subcategory = categorize_transaction_details(
                tx.get("descricao"),
                amount,
                api_category=tx.get("categoria"),
                api_subcategory=tx.get("subcategoria"),
            )
            if tx.get("categoria") != category or tx.get("subcategoria") != subcategory:
                tx["categoria"] = category
                tx["subcategoria"] = subcategory
                changed = True

    if changed:
        save_statement_imports(imports)
    return changed


def list_transactions() -> list[dict]:
    backfill_statement_import_categories()
    prefs = _same_person_transfer_preferences()
    accounts = {item.get("id"): item for item in load_accounts()}
    items = []
    for import_row in load_statement_imports():
        for tx in import_row.get("transactions") or []:
            item = dict(tx)
            account = accounts.get(import_row.get("account_id")) or {}
            item["account_id"] = import_row.get("account_id")
            item["account_label"] = import_row.get("account_label") or build_account_label(account)
            item["account_short_label"] = str(account.get("apelido") or "").strip() or item["account_label"]
            item["statement_type"] = import_row.get("statement_type") or "ACCOUNT"
            item["card_number"] = normalize_card_number(import_row.get("card_number"))
            item["import_id"] = import_row.get("id")
            item["import_status"] = import_row.get("status")
            item["categoria"], item["subcategoria"] = categorize_transaction_details(
                item.get("descricao"),
                float(item.get("valor") or 0.0),
                api_category=item.get("categoria"),
                api_subcategory=item.get("subcategoria"),
            )
            item["direction"] = "entrada" if float(item.get("valor") or 0.0) > 0 else "saida"
            if not _should_keep_transaction(item, prefs):
                continue
            items.append(item)
    items.sort(key=lambda row: (row.get("data") or "", row.get("id") or ""), reverse=True)
    return items


def filter_transactions(
    *,
    transactions: list[dict] | None = None,
    account_id: str = "",
    card_number: str = "",
    category: str = "",
    direction: str = "",
    date_start: str = "",
    date_end: str = "",
) -> list[dict]:
    start = parse_date(date_start)
    end = parse_date(date_end)
    card_number = normalize_card_number(card_number)
    result = []
    for tx in transactions if transactions is not None else list_transactions():
        if account_id and tx.get("account_id") != account_id:
            continue
        if card_number and tx.get("card_number") != card_number:
            continue
        if category and str(tx.get("categoria") or "") != category:
            continue
        if direction and str(tx.get("direction") or "") != direction:
            continue
        tx_date = parse_date(tx.get("data"))
        if start and tx_date and tx_date < start:
            continue
        if end and tx_date and tx_date > end:
            continue
        result.append(tx)
    return result


def build_dashboard_summary(transactions: list[dict] | None = None) -> dict:
    transactions = transactions if transactions is not None else list_transactions()
    accounts_by_id = {str(item.get("id") or "").strip(): item for item in load_accounts()}
    entradas = 0.0
    saidas = 0.0
    por_categoria = defaultdict(float)
    por_subcategoria = defaultdict(float)
    por_mes = defaultdict(lambda: {"entradas": 0.0, "saidas": 0.0})
    por_dia = defaultdict(lambda: {"entradas": 0.0, "saidas": 0.0})
    por_conta = defaultdict(lambda: {
        "label": "",
        "entradas": 0.0,
        "saidas": 0.0,
        "saldo": 0.0,
        "movimentado": 0.0,
        "transacoes": 0,
    })
    cartoes = defaultdict(float)
    max_tx_date = None
    min_tx_date = None
    involved_account_ids: set[str] = set()

    for tx in transactions:
        amount = round(float(tx.get("valor") or 0.0), 2)
        tx_date = parse_date(tx.get("data"))
        categoria = str(tx.get("categoria") or "Outros")
        subcategoria = str(tx.get("subcategoria") or categoria or "Outros")
        conta_label = str(tx.get("account_short_label") or tx.get("account_label") or "Conta")
        account_id = str(tx.get("account_id") or "").strip()
        if account_id:
            involved_account_ids.add(account_id)
        key_month = ""
        key_day = ""
        if tx_date:
            key_month = f"{tx_date.year:04d}-{tx_date.month:02d}"
            key_day = tx_date.isoformat()
            if min_tx_date is None or tx_date < min_tx_date:
                min_tx_date = tx_date
            if max_tx_date is None or tx_date > max_tx_date:
                max_tx_date = tx_date
        bucket_conta = por_conta[conta_label]
        bucket_conta["label"] = conta_label
        bucket_conta["saldo"] += amount
        bucket_conta["movimentado"] += abs(amount)
        bucket_conta["transacoes"] += 1
        por_categoria[categoria] += abs(amount)
        por_subcategoria[subcategoria] += abs(amount)
        if amount >= 0:
            entradas += amount
            if key_month:
                por_mes[key_month]["entradas"] += amount
            if key_day:
                por_dia[key_day]["entradas"] += amount
            bucket_conta["entradas"] += amount
        else:
            saidas += abs(amount)
            if key_month:
                por_mes[key_month]["saidas"] += abs(amount)
            if key_day:
                por_dia[key_day]["saidas"] += abs(amount)
            if tx.get("card_number"):
                cartoes[tx.get("card_number")] += abs(amount)
            bucket_conta["saidas"] += abs(amount)

    opening_balance = round(
        sum(float((accounts_by_id.get(account_id) or {}).get("saldo_inicial") or 0.0) for account_id in involved_account_ids),
        2,
    )

    monthly_all = []
    saldo_acumulado = opening_balance
    for key in sorted(por_mes.keys()):
        year, month = key.split("-", 1)
        entradas_mes = round(por_mes[key]["entradas"], 2)
        saidas_mes = round(por_mes[key]["saidas"], 2)
        saldo_inicial = round(saldo_acumulado, 2)
        geracao_caixa = round(entradas_mes - saidas_mes, 2)
        saldo_final = round(saldo_inicial + geracao_caixa, 2)
        monthly_all.append({
            "key": key,
            "label": f"{MONTH_LABELS.get(int(month), month)}/{year[-2:]}",
            "entradas": entradas_mes,
            "saidas": saidas_mes,
            "saldo_inicial": saldo_inicial,
            "geracao_caixa": geracao_caixa,
            "saldo_final": saldo_final,
        })
        saldo_acumulado = saldo_final

    monthly = monthly_all[-6:]

    total_movimentado = entradas + saidas
    top_categories = sorted(
        [
            {
                "categoria": categoria,
                "valor": round(valor, 2),
                "share": round((valor / total_movimentado) * 100, 1) if total_movimentado else 0.0,
            }
            for categoria, valor in por_categoria.items()
        ],
        key=lambda row: row["valor"],
        reverse=True,
    )
    top_subcategories = sorted(
        [
            {
                "subcategoria": subcategoria,
                "valor": round(valor, 2),
                "share": round((valor / total_movimentado) * 100, 1) if total_movimentado else 0.0,
            }
            for subcategoria, valor in por_subcategoria.items()
        ],
        key=lambda row: row["valor"],
        reverse=True,
    )
    top_cards = sorted(
        [
            {"card_number": card_number, "valor": round(valor, 2)}
            for card_number, valor in cartoes.items()
        ],
        key=lambda row: row["valor"],
        reverse=True,
    )[:4]
    account_breakdown = sorted(
        [
            {
                "label": values["label"],
                "entradas": round(values["entradas"], 2),
                "saidas": round(values["saidas"], 2),
                "saldo": round(values["saldo"], 2),
                "movimentado": round(values["movimentado"], 2),
                "transacoes": int(values["transacoes"]),
                "share": round((values["movimentado"] / total_movimentado) * 100, 1) if total_movimentado else 0.0,
            }
            for values in por_conta.values()
        ],
        key=lambda row: row["movimentado"],
        reverse=True,
    )[:6]
    daily = []
    if max_tx_date is not None:
        current = max(min_tx_date or max_tx_date, max_tx_date - timedelta(days=6))
        while current <= max_tx_date:
            key = current.isoformat()
            entradas_dia = round(por_dia[key]["entradas"], 2)
            saidas_dia = round(por_dia[key]["saidas"], 2)
            daily.append({
                "key": key,
                "label": current.strftime("%d/%m"),
                "entradas": entradas_dia,
                "saidas": saidas_dia,
                "saldo": round(entradas_dia - saidas_dia, 2),
            })
            current += timedelta(days=1)

    weekly_expenses = {}
    if max_tx_date is not None:
        week_end = max_tx_date
        week_start = week_end - timedelta(days=6)
        previous_end = week_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=6)

        days = []
        current_total = 0.0
        previous_total = 0.0
        max_day_value = 0.0

        current = week_start
        while current <= week_end:
            key = current.isoformat()
            amount = round(por_dia[key]["saidas"], 2)
            current_total += amount
            max_day_value = max(max_day_value, amount)
            days.append({
                "key": key,
                "label": WEEKDAY_LABELS.get(current.weekday(), current.strftime("%a")),
                "valor": amount,
            })
            current += timedelta(days=1)

        current = previous_start
        while current <= previous_end:
            previous_total += round(por_dia[current.isoformat()]["saidas"], 2)
            current += timedelta(days=1)

        axis_max = _nice_axis_max(max_day_value)
        peak_value = max([item["valor"] for item in days] or [0.0])
        for item in days:
            item["height_pct"] = round((item["valor"] / axis_max) * 100, 1) if axis_max else 0.0
            item["is_empty"] = item["valor"] <= 0
            item["is_peak"] = peak_value > 0 and item["valor"] == peak_value

        raw_change = 0.0
        if previous_total > 0:
            raw_change = ((current_total - previous_total) / previous_total) * 100

        if raw_change > 0.1:
            trend_direction = "up"
            trend_text = f"+{abs(raw_change):.1f}% vs semana anterior"
            trend_tone = "negative"
        elif raw_change < -0.1:
            trend_direction = "down"
            trend_text = f"-{abs(raw_change):.1f}% vs semana anterior"
            trend_tone = "positive"
        else:
            trend_direction = "flat"
            trend_text = "Estavel vs semana anterior"
            trend_tone = "neutral"

        weekly_expenses = {
            "total": round(current_total, 2),
            "previous_total": round(previous_total, 2),
            "days": days,
            "scale_top": round(axis_max, 2),
            "trend_direction": trend_direction,
            "trend_tone": trend_tone,
            "trend_text": trend_text,
            "range_label": f"{week_start.strftime('%d/%m')} a {week_end.strftime('%d/%m')}",
        }

    return {
        "opening_balance": opening_balance,
        "total_entradas": round(entradas, 2),
        "total_saidas": round(saidas, 2),
        "saldo_liquido": round(entradas - saidas, 2),
        "transacoes": len(transactions),
        "top_categories": top_categories,
        "top_subcategories": top_subcategories,
        "monthly": monthly,
        "monthly_cash": monthly,
        "daily": daily,
        "weekly_expenses": weekly_expenses,
        "account_breakdown": account_breakdown,
        "top_cards": top_cards,
        "recent": transactions[:10],
    }


def build_chat_context(question: str, *, session_history: list[dict] | None = None) -> dict:
    all_transactions = list_transactions()
    lower_question = str(question or "").casefold()
    selected = []
    for tx in all_transactions:
        desc = str(tx.get("descricao") or "").casefold()
        cat = str(tx.get("categoria") or "").casefold()
        if any(token in desc or token in cat for token in lower_question.split() if len(token) > 3):
            selected.append(tx)
        if len(selected) >= 40:
            break
    if not selected:
        selected = all_transactions[:40]

    today = date.today()
    month_transactions = [
        tx for tx in all_transactions
        if (parse_date(tx.get("data")) or today).year == today.year
        and (parse_date(tx.get("data")) or today).month == today.month
    ]
    return {
        "summary_all": build_dashboard_summary(all_transactions),
        "summary_month": build_dashboard_summary(month_transactions),
        "selected_transactions": selected[:40],
        "recent_history": (session_history or [])[-8:],
    }
