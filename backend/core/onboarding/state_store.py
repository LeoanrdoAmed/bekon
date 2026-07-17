# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.core.common.config import onboarding_state_json
from backend.core.common.json_store import read_json, write_json


def _normalize(data) -> dict:
    if not isinstance(data, dict):
        data = {}
    state = dict(data)
    state.setdefault("stage", "")
    state.setdefault("mode", "field")
    state.setdefault("cursor", 0)
    state.setdefault("messages", [])
    state.setdefault("current_account_draft", {})
    state.setdefault("current_card_draft", {})
    state.setdefault("current_card_account_id", "")
    state.setdefault("last_account_id", "")
    return state


def load_onboarding_state() -> dict:
    return _normalize(read_json(onboarding_state_json(), {}))


def save_onboarding_state(data: dict) -> None:
    write_json(onboarding_state_json(), _normalize(data))


def reset_onboarding_state() -> None:
    write_json(onboarding_state_json(), {})
