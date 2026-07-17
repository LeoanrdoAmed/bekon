# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import re
import secrets

import requests

from backend.core.ai.chat_store import load_chat_sessions, save_chat_sessions
from backend.core.common.utils import format_currency, now_str
from backend.core.finance.analytics import build_chat_context

LLM_PROVIDER = (os.getenv("LLM_PROVIDER", "ollama").strip().lower() or "ollama")
DEFAULT_OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini"
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3:8b").strip() or "llama3:8b"
OLLAMA_BASE_URL = (os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/") or "http://127.0.0.1:11434")
SYSTEM_INSTRUCTIONS = (
    "Voce e um assistente financeiro pessoal em portugues do Brasil. "
    "Responda apenas com base no contexto fornecido. "
    "Se o dado nao estiver no contexto, diga isso claramente. "
    "Sempre cite valores em reais, periodos e a logica do calculo em linguagem simples. "
    "Nao invente transacoes, bancos, categorias nem saldos. "
    "Priorize respostas objetivas, claras e uteis."
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(12)}"


def list_sessions() -> list[dict]:
    sessions = load_chat_sessions()
    sessions.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return sessions


def get_session(session_id: str) -> dict | None:
    return next((item for item in load_chat_sessions() if item.get("id") == session_id), None)


def ensure_session(session_id: str | None = None) -> dict:
    sessions = load_chat_sessions()
    if session_id:
        for session in sessions:
            if session.get("id") == session_id:
                return session
    new_session = {
        "id": _new_id("chat"),
        "title": "Nova conversa",
        "created_at": now_str(),
        "updated_at": now_str(),
        "messages": [],
    }
    sessions.append(new_session)
    save_chat_sessions(sessions)
    return new_session


def _save_session(updated_session: dict) -> dict:
    sessions = load_chat_sessions()
    for idx, session in enumerate(sessions):
        if session.get("id") == updated_session.get("id"):
            sessions[idx] = updated_session
            break
    else:
        sessions.append(updated_session)
    save_chat_sessions(sessions)
    return updated_session


def append_session_messages(session_id: str | None, entries: list[dict]) -> dict:
    session = ensure_session(session_id)
    sessions = load_chat_sessions()
    current = next((item for item in sessions if item.get("id") == session.get("id")), None) or session

    for entry in entries:
        role = str(entry.get("role") or "").strip() or "assistant"
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        current["messages"].append({
            "id": _new_id("msg"),
            "role": role,
            "content": content,
            "created_at": now_str(),
        })
        if len(current["messages"]) == 1 and role == "user":
            current["title"] = _short_title_from_text(content)

    current["updated_at"] = now_str()
    _save_session(current)
    return current


def update_session_data(session_id: str | None, **fields) -> dict:
    session = ensure_session(session_id)
    sessions = load_chat_sessions()
    current = next((item for item in sessions if item.get("id") == session.get("id")), None) or session

    for key, value in fields.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value

    current["updated_at"] = now_str()
    _save_session(current)
    return current


def _short_title_from_text(text: str) -> str:
    clean = re.sub(r"\s+", " ", str(text or "").strip())
    if not clean:
        return "Nova conversa"
    return clean[:42] + ("..." if len(clean) > 42 else "")


def _openai_enabled() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def _provider_chain() -> list[str]:
    if LLM_PROVIDER == "auto":
        return ["ollama", "openai"]
    if LLM_PROVIDER in {"ollama", "openai", "fallback"}:
        return [LLM_PROVIDER]
    return ["ollama"]


def _local_fallback_answer(question: str, context: dict) -> str:
    question_lower = str(question or "").casefold()
    month_summary = context.get("summary_month") or {}
    overall_summary = context.get("summary_all") or {}
    selected = context.get("selected_transactions") or []

    if "quanto gastei" in question_lower or "gastei" in question_lower:
        return (
            f"No periodo atual carregado, suas saidas somam {format_currency(month_summary.get('total_saidas', 0.0))} "
            f"e o saldo liquido ficou em {format_currency(month_summary.get('saldo_liquido', 0.0))}."
        )
    if "categoria" in question_lower or "onde" in question_lower or "gastos" in question_lower:
        top = month_summary.get("top_categories") or overall_summary.get("top_categories") or []
        if not top:
            return "Ainda nao encontrei categorias suficientes para montar esse recorte."
        lines = [f"{item['categoria']}: {format_currency(item['valor'])}" for item in top[:4]]
        return "As categorias mais pesadas no recorte atual foram: " + "; ".join(lines) + "."
    if "ultimas" in question_lower or "recentes" in question_lower:
        if not selected:
            return "Nao encontrei transacoes recentes importadas."
        lines = [
            f"{tx.get('data')}: {tx.get('descricao')} ({format_currency(tx.get('valor'))})"
            for tx in selected[:5]
        ]
        return "Estas sao as transacoes mais recentes que encontrei: " + "; ".join(lines) + "."
    return (
        "Posso responder melhor com um modelo de IA ativo. Sem ele, o resumo local atual mostra "
        f"{overall_summary.get('transacoes', 0)} transacoes, "
        f"{format_currency(overall_summary.get('total_entradas', 0.0))} em entradas e "
        f"{format_currency(overall_summary.get('total_saidas', 0.0))} em saidas."
    )


def _payload_for_model(question: str, context: dict) -> str:
    return json.dumps(
        {
            "pedido_usuario": question,
            "contexto_financeiro": context,
        },
        ensure_ascii=False,
    )


def _openai_answer(question: str, context: dict) -> tuple[str, str]:
    from openai import OpenAI

    client = OpenAI()
    response = client.responses.create(
        model=DEFAULT_OPENAI_MODEL,
        instructions=SYSTEM_INSTRUCTIONS,
        input=_payload_for_model(question, context),
        max_output_tokens=900,
    )
    answer = (response.output_text or "").strip()
    if not answer:
        raise RuntimeError("A OpenAI retornou uma resposta vazia.")
    return answer, DEFAULT_OPENAI_MODEL


def _ollama_answer(question: str, context: dict) -> tuple[str, str]:
    payload = {
        "model": DEFAULT_OLLAMA_MODEL,
        "stream": False,
        "keep_alive": "5m",
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": _payload_for_model(question, context)},
        ],
        "options": {
            "temperature": 0.2,
            "num_ctx": 8192,
        },
    }
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json=payload,
        timeout=180,
    )
    response.raise_for_status()
    data = response.json()
    message = data.get("message") or {}
    answer = str(message.get("content") or "").strip()
    if not answer:
        raise RuntimeError("O Ollama retornou uma resposta vazia.")
    return answer, f"ollama:{DEFAULT_OLLAMA_MODEL}"


def _generate_answer(question: str, context: dict) -> tuple[str, str]:
    failures = []
    for provider in _provider_chain():
        try:
            if provider == "ollama":
                return _ollama_answer(question, context)
            if provider == "openai":
                if not _openai_enabled():
                    failures.append("OpenAI sem chave configurada.")
                    continue
                return _openai_answer(question, context)
            if provider == "fallback":
                break
        except Exception as exc:
            failures.append(f"{provider}: {exc}")

    fallback = _local_fallback_answer(question, context)
    if failures:
        return f"Encontrei uma indisponibilidade temporaria no assistente. {fallback}", "fallback-local"
    return fallback, "fallback-local"


def send_chat_message(session_id: str | None, user_message: str) -> dict:
    session = ensure_session(session_id)
    sessions = load_chat_sessions()
    current = next((item for item in sessions if item.get("id") == session.get("id")), None) or session

    user_entry = {
        "id": _new_id("msg"),
        "role": "user",
        "content": str(user_message or "").strip(),
        "created_at": now_str(),
    }
    current["messages"].append(user_entry)
    current["updated_at"] = now_str()
    if len(current["messages"]) == 1:
        current["title"] = _short_title_from_text(user_message)

    context = build_chat_context(user_message, session_history=current.get("messages") or [])
    answer, model_name = _generate_answer(user_message, context)

    assistant_entry = {
        "id": _new_id("msg"),
        "role": "assistant",
        "content": answer,
        "created_at": now_str(),
    }
    current["messages"].append(assistant_entry)
    current["updated_at"] = now_str()
    _save_session(current)
    return current
