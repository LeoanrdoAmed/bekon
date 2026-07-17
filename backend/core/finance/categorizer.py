# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import unicodedata


API_CATEGORY_MAP = {
    "automatic investment": ("Investimentos", "Rendimento automatico"),
    "transfer pix": ("Transferencias", "Pix"),
    "transferencia pix": ("Transferencias", "Pix"),
    "income": ("Entradas", ""),
    "automotive": ("Automotivo", ""),
    "bank fees": ("Tarifas bancarias", ""),
    "bookstore": ("Livraria", ""),
    "clothing": ("Vestuario", ""),
    "digital services": ("Servicos digitais", ""),
    "eating out": ("Alimentacao", "Restaurantes"),
    "education": ("Educacao", ""),
    "electricity": ("Moradia", "Energia eletrica"),
    "electronics": ("Eletronicos", ""),
    "financing": ("Financiamento", ""),
    "food and drinks": ("Alimentacao", ""),
    "gas": ("Transporte", "Combustivel"),
    "groceries": ("Mercado", ""),
    "health insurance": ("Saude", "Plano de saude"),
    "healthcare": ("Saude", ""),
    "hospital clinics and labs": ("Saude", "Hospitais, clinicas e laboratorios"),
    "housing": ("Moradia", ""),
    "income taxes": ("Impostos", "Imposto de renda"),
    "insurance": ("Seguros", ""),
    "interests charged": ("Juros cobrados", ""),
    "internet": ("Telecomunicacoes", "Internet"),
    "transfer cash": ("Transferencias", "Transferencia em dinheiro"),
    "transfer bank slip": ("Transferencias", "Boleto"),
    "proceeds interests and dividends": ("Investimentos", "Rendimentos e dividendos"),
    "credit card payment": ("Cartao de credito", "Pagamento de cartao"),
    "online shopping": ("Compras", "Compras online"),
    "houseware": ("Casa e utilidades", "Casa e utilidades"),
    "same person transfer": ("Transferencias", "Mesma titularidade"),
    "entertainment": ("Lazer", "Lazer"),
    "food and drink": ("Alimentacao", ""),
    "transport": ("Transporte", "Transporte"),
    "investments": ("Investimentos", ""),
    "leisure": ("Lazer", ""),
    "life insurance": ("Seguros", "Seguro de vida"),
    "loans and financing": ("Financiamento", "Emprestimos e financiamentos"),
    "mutual funds": ("Investimentos", "Fundos de investimento"),
    "office supplies": ("Material de escritorio", ""),
    "parking": ("Transporte", "Estacionamento"),
    "services": ("Servicos", ""),
    "shopping": ("Compras", ""),
    "tax on financial operations": ("Impostos", "IOF"),
    "telecommunications": ("Telecomunicacoes", ""),
    "transfer check": ("Transferencias", "Transferencia por cheque"),
    "transfer internal": ("Transferencias", "Transferencia interna"),
    "transfer ted": ("Transferencias", "TED"),
    "transfers": ("Transferencias", ""),
    "transportation": ("Transporte", ""),
    "tv": ("TV", ""),
    "university": ("Educacao", "Universidade"),
    "wellness and fitness": ("Saude", "Bem-estar e fitness"),
}

API_LABEL_TRANSLATIONS = {
    "income": "Entradas",
    "automotive": "Automotivo",
    "bank fees": "Tarifas bancarias",
    "bookstore": "Livraria",
    "clothing": "Vestuario",
    "digital services": "Servicos digitais",
    "eating out": "Restaurantes",
    "education": "Educacao",
    "electricity": "Energia eletrica",
    "electronics": "Eletronicos",
    "financing": "Financiamento",
    "food and drinks": "Alimentacao",
    "gas": "Combustivel",
    "groceries": "Mercado",
    "health insurance": "Plano de saude",
    "healthcare": "Saude",
    "hospital clinics and labs": "Hospitais, clinicas e laboratorios",
    "housing": "Moradia",
    "income taxes": "Imposto de renda",
    "insurance": "Seguros",
    "interests charged": "Juros cobrados",
    "internet": "Internet",
    "transfer cash": "Transferencia em dinheiro",
    "transfer bank slip": "Boleto",
    "transfer pix": "Pix",
    "transferencia pix": "Pix",
    "proceeds interests and dividends": "Rendimentos e dividendos",
    "credit card payment": "Pagamento de cartao",
    "online shopping": "Compras online",
    "houseware": "Casa e utilidades",
    "same person transfer": "Mesma titularidade",
    "entertainment": "Lazer",
    "food and drink": "Alimentacao",
    "transport": "Transporte",
    "investments": "Investimentos",
    "leisure": "Lazer",
    "life insurance": "Seguro de vida",
    "loans and financing": "Emprestimos e financiamentos",
    "mutual funds": "Fundos de investimento",
    "office supplies": "Material de escritorio",
    "parking": "Estacionamento",
    "services": "Servicos",
    "shopping": "Compras",
    "tax on financial operations": "IOF",
    "telecommunications": "Telecomunicacoes",
    "transfer check": "Transferencia por cheque",
    "transfer internal": "Transferencia interna",
    "transfer ted": "TED",
    "transfers": "Transferencias",
    "transportation": "Transporte",
    "tv": "TV",
    "university": "Universidade",
    "wellness and fitness": "Bem-estar e fitness",
    "salary": "Salario",
    "investment funds": "Fundos de investimento",
}

DETAIL_RULES = [
    ("Transferencias", "Pix recebido", ["pix recebido"]),
    ("Transferencias", "Pix enviado", ["pix enviado"]),
    ("Investimentos", "Rendimento automatico", ["rendimento automatico", "automatic investment"]),
    ("Renda", "Salario", ["salario", "folha"]),
    ("Alimentacao", "Delivery", ["ifood", "delivery"]),
    ("Alimentacao", "Restaurantes", ["restaurante", "padaria", "cafe", "burger", "pizza"]),
    ("Transporte", "Mobilidade", ["uber", "99"]),
    ("Transporte", "Combustivel", ["posto", "ipiranga", "shell", "combust"]),
    ("Transporte", "Estacionamento", ["estacionamento"]),
    ("Moradia", "Moradia", ["aluguel", "condominio", "energia", "enel", "agua", "saneamento", "gas"]),
    ("Saude", "Saude", ["farmacia", "droga", "hospital", "clinica", "saude"]),
    ("Assinaturas", "Streaming e apps", ["netflix", "spotify", "youtube", "prime", "amazon", "disney", "apple com"]),
    ("Compras", "Compras online", ["mercado livre", "shopee", "magalu", "americanas", "casas bahia"]),
    ("Mercado", "Supermercado", ["supermercado", "mercad", "pao de acucar", "assai", "carrefour"]),
    ("Lazer", "Lazer", ["cinema", "show", "bar", "evento", "ingresso"]),
    ("Investimentos", "Investimentos", ["tesouro", "cdb", "corretora", "rico", "xp"]),
]


def _repair_text(value: str) -> str:
    text = str(value or "").strip()
    if not text or "Ã" not in text:
        return text
    try:
        repaired = text.encode("latin1").decode("utf-8")
        return repaired.strip() or text
    except Exception:
        return text


def _normalize_text(value: str) -> str:
    text = _repair_text(value)
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _translate_api_label(value: str) -> str:
    fixed = _repair_text(value)
    normalized = _normalize_text(fixed)
    translated = API_LABEL_TRANSLATIONS.get(normalized)
    if translated:
        return translated
    return fixed


def categorize_transaction_details(
    description: str,
    amount: float,
    *,
    api_category: str = "",
    api_subcategory: str = "",
) -> tuple[str, str]:
    normalized_desc = _normalize_text(description)
    normalized_api_category = _normalize_text(api_category)
    fixed_api_category = _repair_text(api_category)
    fixed_api_subcategory = _repair_text(api_subcategory)

    if normalized_desc.startswith("pix recebido"):
        return "Transferencias", "Pix recebido"
    if normalized_desc.startswith("pix enviado"):
        return "Transferencias", "Pix enviado"

    if normalized_api_category in API_CATEGORY_MAP:
        category, fallback_subcategory = API_CATEGORY_MAP[normalized_api_category]
        if category == "Transferencias":
            if "recebido" in normalized_desc:
                return category, "Pix recebido"
            if "enviado" in normalized_desc:
                return category, "Pix enviado"
        return category, _translate_api_label(fixed_api_subcategory) or fallback_subcategory

    for category, subcategory, keywords in DETAIL_RULES:
        if any(keyword in normalized_desc for keyword in keywords):
            return category, subcategory

    if fixed_api_category:
        return _translate_api_label(fixed_api_category), _translate_api_label(fixed_api_subcategory)
    if amount > 0:
        return "Entradas", ""
    return "Outros", ""


def categorize_transaction(description: str, amount: float, api_category: str = "") -> str:
    return categorize_transaction_details(description, amount, api_category=api_category)[0]
