"""Itinerario por día y presupuesto (lógica pura, sin Streamlit).

Formato guardado en itinerario.json:
[{"dia": 1, "fecha": "2027-03-01", "pais": "España", "titulo": "Madrid clásico",
  "items": [{"hora": "09:00", "lugar": "Museo del Prado", "actividad": "Visita", "costo": 15,
             "transporte": "Metro línea 2", "costo_transporte": 1.5, "moneda": "EUR", "aproximado": true}]}]
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd

TABLE_COLS = ["Día", "Hora", "Lugar", "Actividad", "Costo", "Transporte", "Costo transp.", "Moneda", "Aprox"]


def _num(x: Any) -> float | None:
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, str):
        m = re.search(r"-?\d+(?:[.,]\d+)?", x.replace(" ", ""))
        if not m:
            return None
        x = m.group(0).replace(",", ".")
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v >= 0 else None  # sin NaN ni negativos


def _s(x: Any) -> str:
    return "" if x is None or (isinstance(x, float) and x != x) else str(x).strip()


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", _s(s).lower()) if not unicodedata.combining(c))


def clean_itinerary(raw: Any) -> list[dict]:
    """Valida lo que manda el agente o la tabla: ignora basura, ordena por día y por hora."""
    days: list[dict] = []
    if not isinstance(raw, list):
        return days
    for i, d in enumerate(raw, 1):
        if not isinstance(d, dict):
            continue
        try:
            num = int(d.get("dia", i))
        except (TypeError, ValueError):
            num = i
        items = []
        for it in d.get("items") or []:
            if not isinstance(it, dict):
                continue
            lugar, act = _s(it.get("lugar")), _s(it.get("actividad"))
            if not (lugar or act):
                continue
            items.append({
                "hora": _s(it.get("hora")), "lugar": lugar, "actividad": act,
                "costo": _num(it.get("costo")), "transporte": _s(it.get("transporte")),
                "costo_transporte": _num(it.get("costo_transporte")),
                "moneda": _s(it.get("moneda")).upper()[:5],
                "aproximado": bool(it.get("aproximado", True)),
            })
        if not items and not _s(d.get("titulo")):
            continue
        items.sort(key=lambda x: x["hora"] or "99:99")
        days.append({"dia": num, "fecha": _s(d.get("fecha")), "pais": _s(d.get("pais")), "titulo": _s(d.get("titulo")), "items": items})
    days.sort(key=lambda d: d["dia"])
    return days


def merge_days(old: list[dict], new: list[dict]) -> list[dict]:
    """Agrega o reemplaza días por número (para que el agente pueda mandar solo los días que cambian)."""
    by = {d["dia"]: d for d in old}
    for d in new:
        by[d["dia"]] = d
    return [by[k] for k in sorted(by)]


def to_table(days: list[dict]) -> pd.DataFrame:
    rows = [{"Día": d["dia"], "Hora": it["hora"], "Lugar": it["lugar"], "Actividad": it["actividad"], "Costo": it["costo"],
             "Transporte": it["transporte"], "Costo transp.": it["costo_transporte"], "Moneda": it["moneda"], "Aprox": it["aproximado"]}
            for d in days for it in d["items"]]
    df = pd.DataFrame(rows, columns=TABLE_COLS)
    df["Costo"] = pd.to_numeric(df["Costo"], errors="coerce")
    df["Costo transp."] = pd.to_numeric(df["Costo transp."], errors="coerce")
    df["Día"] = pd.to_numeric(df["Día"], errors="coerce").astype("Int64")
    df["Aprox"] = df["Aprox"].fillna(True).astype(bool)
    return df


def from_table(df: pd.DataFrame, old: list[dict]) -> list[dict]:
    """Reconstruye los días desde la tabla editada, conservando fecha/país/título de los días que ya existían."""
    meta = {d["dia"]: d for d in old}
    by: dict[int, list[dict]] = {}
    for r in df.to_dict("records"):
        dia = _num(r.get("Día"))
        if dia is None:
            continue
        by.setdefault(int(dia), []).append({
            "hora": r.get("Hora"), "lugar": r.get("Lugar"), "actividad": r.get("Actividad"), "costo": r.get("Costo"),
            "transporte": r.get("Transporte"), "costo_transporte": r.get("Costo transp."), "moneda": r.get("Moneda"),
            "aproximado": True if r.get("Aprox") is None or (isinstance(r.get("Aprox"), float) and r.get("Aprox") != r.get("Aprox")) else bool(r.get("Aprox")),
        })
    raw = [{"dia": k, "fecha": meta.get(k, {}).get("fecha", ""), "pais": meta.get(k, {}).get("pais", ""), "titulo": meta.get(k, {}).get("titulo", ""), "items": v}
           for k, v in by.items()]
    return clean_itinerary(raw)


def _add(tot: dict, cur: str, amount: float | None, approx: bool) -> None:
    if amount is None:
        return
    cur = cur or "¿?"
    t = tot.setdefault(cur, {"total": 0.0, "aprox": 0.0})
    t["total"] += amount
    if approx:
        t["aprox"] += amount


def budget(days: list[dict], places: list[dict] | None = None) -> dict:
    """Totales por moneda, por día y por país. No convierte monedas (se muestran por separado).
    Los lugares guardados con precio cuentan solo si no están ya en el itinerario (para no sumar doble)."""
    total: dict = {}
    by_day, by_country = [], {}
    n_items = n_aprox = n_sin = 0
    names = {_norm(it["lugar"]) for d in days for it in d["items"] if it["lugar"]}
    for d in days:
        dt: dict = {}
        for it in d["items"]:
            n_items += 1
            has = False
            for amt in (it["costo"], it["costo_transporte"]):
                if amt is not None:
                    has = True
                    _add(dt, it["moneda"], amt, it["aproximado"])
                    _add(total, it["moneda"], amt, it["aproximado"])
                    _add(by_country.setdefault(d["pais"] or "Sin país", {}), it["moneda"], amt, it["aproximado"])
            n_sin += 0 if has else 1
            n_aprox += 1 if (has and it["aproximado"]) else 0
        by_day.append({"dia": d["dia"], "fecha": d["fecha"], "titulo": d["titulo"], "pais": d["pais"], "totales": dt})
    extra, extra_total = [], {}
    for p in places or []:
        amt = _num(p.get("precio"))
        nm = _norm(p.get("nombre", ""))
        if amt is None or (nm and any(nm in n or n in nm for n in names)):
            continue
        extra.append(p)
        _add(extra_total, _s(p.get("moneda")).upper(), amt, True)
    return {"total": total, "por_dia": by_day, "por_pais": by_country, "n_items": n_items, "n_aprox": n_aprox, "n_sin_costo": n_sin,
            "otros_lugares": extra, "otros_total": extra_total}


def money(cur: str, amount: float) -> str:
    return f"{amount:,.2f} {cur}"
