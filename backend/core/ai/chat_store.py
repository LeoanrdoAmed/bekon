# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.core.common.config import chat_sessions_json
from backend.core.common.json_store import read_json, write_json


def _normalize(data) -> list[dict]:
    if not isinstance(data, list):
        data = []
    sessions = []
    for item in data:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row.setdefault("id", "")
        row.setdefault("title", "Nova conversa")
        row.setdefault("created_at", "")
        row.setdefault("updated_at", "")
        row["messages"] = [
            message for message in (row.get("messages") or [])
            if isinstance(message, dict)
        ]
        sessions.append(row)
    return sessions


def load_chat_sessions() -> list[dict]:
    return _normalize(read_json(chat_sessions_json(), []))


def save_chat_sessions(data: list[dict]) -> None:
    write_json(chat_sessions_json(), _normalize(data))
