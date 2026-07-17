# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.core.common.config import customer_profile_json
from backend.core.common.json_store import read_json, write_json


def _normalize(data) -> dict:
    if not isinstance(data, dict):
        data = {}
    profile = dict(data)
    profile.setdefault("id", "customer_default")
    profile.setdefault("nome", "")
    profile.setdefault("cpf", "")
    profile.setdefault("email", "")
    profile.setdefault("telefone", "")
    profile.setdefault("logradouro", "")
    profile.setdefault("numero", "")
    profile.setdefault("bairro", "")
    profile.setdefault("complemento", "")
    profile.setdefault("cidade", "")
    profile.setdefault("estado", "")
    profile.setdefault("cep", "")
    profile.setdefault("created_at", "")
    profile.setdefault("updated_at", "")
    profile.setdefault("onboarding_completed_at", "")
    if not isinstance(profile.get("analysis_preferences"), dict):
        profile["analysis_preferences"] = {}
    profile["analysis_preferences"].setdefault("include_same_person_transfer_inflow", True)
    profile["analysis_preferences"].setdefault("include_same_person_transfer_outflow", True)
    return profile


def load_customer_profile() -> dict:
    return _normalize(read_json(customer_profile_json(), {}))


def save_customer_profile(data: dict) -> None:
    write_json(customer_profile_json(), _normalize(data))
