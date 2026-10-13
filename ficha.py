"""Ficha de país: transporte, tarjetas/pases (turista y residente), formas de pago y precios típicos.

Se genera con una consulta del agente a la web (una sola vez por país) y se guarda en viajes/_fichas/<ISO>.json.
"""
from __future__ import annotations

import json
import re
from datetime import date

import agent
import tools as T
from countries import Country

SCHEMA = """{
  "moneda": {"codigo_local": "EUR", "mostrada_en": "EUR", "nota": "tasa y fecha si hubo conversión; vacío si no"},
  "resumen": "2-3 frases sobre cómo moverse y pagar en el país",
  "transporte": [{"medio": "Metro de la capital", "util_para": "cuándo conviene", "precio": "texto con moneda, ej. 1,50 EUR por viaje", "aproximado": false, "nota": ""}],
  "tarjetas_y_pases": [{"nombre": "", "para": "turista | residente | todos", "precio": "", "vigencia": "", "requisitos": "ej. empadronamiento o identificación para residentes", "donde_comprar": "", "url": ""}],
  "pago": {"tarjeta_en_transporte": "", "tarjeta_en_comercios": "", "efectivo": "cuándo hace falta", "contactless_y_wallet": ""},
  "precios_tipicos": [{"concepto": "Comida económica", "precio": "", "aproximado": true}],
  "consejos": [""],
  "fuentes": [{"titulo": "", "url": ""}]
}"""


def build_prompt(c: Country) -> tuple[str, str]:
    if c.display_currency != c.currency:
        money = (
            f"MONEDA: la moneda local es {c.currency}, pero en esta ficha TODOS los precios van en {c.display_currency} "
            f"con el monto en {c.currency} entre paréntesis (ej. \"USD 1.40 (¥210)\"). Usa la herramienta tipo_de_cambio "
            f"({c.currency}→{c.display_currency}) y anota la tasa y su fecha en moneda.nota."
        )
    else:
        money = (
            f"MONEDA: todos los precios van en la moneda local de {c.es}, que debería ser {c.currency or 'la vigente'} "
            "(verifica que siga siendo la vigente). No conviertas a otra moneda."
        )
    system = (
        "Eres un investigador de viajes meticuloso. Buscas en la web datos actuales de transporte público y pagos para turistas "
        "y residentes, priorizando los sitios oficiales de los operadores, consorcios y autoridades de transporte. "
        "Si no encuentras un precio concreto, da una estimación razonable y márcala con \"aproximado\": true; "
        "nunca presentes una estimación como dato confirmado. No inventes URLs: pon solo enlaces que viste en tus búsquedas. "
        "Responde ÚNICAMENTE con un objeto JSON válido (sin texto antes ni después, sin bloque de código)."
    )
    user = f"""País: {c.es} ({c.en}). Fecha de hoy: {date.today().isoformat()}.
{money}

Investiga y completa esta ficha para un viajero que visitará varias ciudades:
- transporte: 4 a 7 medios (metro/tranvía, bus, tren interurbano, taxi o apps, bici/patinete, aeropuerto→centro) con costo aproximado de cada uno.
- tarjetas_y_pases: tarjetas o abonos de consorcio/operador y pases turísticos, indicando para quién son (turista, residente o todos), precio, vigencia, requisitos y dónde comprarlos. Si no existe ninguno relevante, incluye un elemento que lo diga.
- pago: si se puede pagar con tarjeta bancaria o contactless en transporte y comercios, y cuándo hace falta efectivo.
- precios_tipicos: hasta 8 (comida económica, comida en restaurante medio, café, agua o cerveza, entrada a una atracción típica, alojamiento medio por noche).
- consejos: 3 a 5 consejos breves.

Formato exacto del JSON (respeta las claves):
{SCHEMA}"""
    return system, user


def parse_json(text: str) -> dict | None:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        data = json.loads(text[i : j + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def generate_ficha(client, model: str, c: Country, max_searches: int = 8) -> dict:
    system, user = build_prompt(c)
    ctx = T.ToolContext(store=None, slug="", geo=None)
    res = agent.run_agent(
        client, model, system, [{"role": "user", "content": user}], ctx, max_searches,
        keep_turns=1, only_tools=["tipo_de_cambio"], append_sources=False, max_tokens=7000, max_iters=12,
    )
    data = parse_json(res.text)
    if data is None:
        data = {"resumen": res.text, "_sin_formato": True}
    # fuentes: las que citó el modelo + las de las búsquedas, sin duplicados
    seen, fuentes = set(), []
    for f in list(data.get("fuentes") or []) + [{"titulo": t, "url": u} for u, t in res.sources]:
        url = (f or {}).get("url", "")
        if url and url not in seen:
            seen.add(url)
            fuentes.append({"titulo": f.get("titulo") or url, "url": url})
    data["fuentes"] = fuentes[:12]
    data["pais_iso"] = c.iso
    data["fecha_consulta"] = date.today().isoformat()
    data["_uso"] = {"entrada": res.input_tokens, "salida": res.output_tokens, "busquedas": res.searches}
    return data
