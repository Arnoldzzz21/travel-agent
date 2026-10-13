"""Herramientas que el agente puede llamar (clima, cambio, rutas, guardar lugares...)."""
from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

UA = {"User-Agent": "AgenteViajesPersonal/1.0 (uso personal)"}
MODES = ("transit", "driving", "walking", "bicycling")
CATEGORIES = ("comida", "turismo", "transporte", "hospedaje", "compras", "otro")


def _get_json(url: str, params: dict | None = None, timeout: int = 15):
    r = requests.get(url, params=params, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.json()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------- geocodificación
class Geocoder:
    """Nominatim (OpenStreetMap) con caché en disco. Respeta 1 petición por segundo."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._last_call = 0.0
        self.last_error = ""
        self._cache: dict[str, dict] = {}
        if self.path.exists():
            try:
                self._cache = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._cache = {}

    @staticmethod
    def _key(q: str) -> str:
        return " ".join(q.lower().split())

    def cached(self, query: str) -> dict | None:
        return self._cache.get(self._key(query))

    def lookup(self, query: str) -> dict | None:
        hit = self.cached(query)
        if hit:
            return hit
        with self._lock:
            wait = 1.1 - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            try:
                data = _get_json(
                    "https://nominatim.openstreetmap.org/search",
                    {"q": query, "format": "jsonv2", "limit": 1, "accept-language": "es"},
                )
            except Exception as e:  # red caída, límite, etc.
                self.last_error = str(e)
                return None
            finally:
                self._last_call = time.time()
        if not data:
            return None
        hit = {"lat": float(data[0]["lat"]), "lon": float(data[0]["lon"]), "name": data[0].get("display_name", query)}
        self._cache[self._key(query)] = hit
        self._save()
        return hit

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def clear(self) -> None:
        self._cache = {}
        self._save()


# ---------------------------------------------------------------- enlaces de Google Maps
def gmaps_links(stops: list[str], mode: str = "transit", chunk: int = 10) -> list[str]:
    """Enlaces de ruta de Google Maps (sin API ni clave). Divide en tramos de `chunk` paradas."""
    stops = [s for s in stops if s and s.strip()]
    if len(stops) < 2:
        return []
    mode = mode if mode in MODES else "transit"
    links = []
    i = 0
    while i < len(stops) - 1:
        seg = stops[i : i + chunk]
        params = {"api": 1, "origin": seg[0], "destination": seg[-1], "travelmode": mode}
        if len(seg) > 2:
            params["waypoints"] = "|".join(seg[1:-1])
        links.append("https://www.google.com/maps/dir/?" + urlencode(params))
        i += chunk - 1
    return links


# ---------------------------------------------------------------- contexto compartido
@dataclass
class ToolContext:
    store: Any
    slug: str
    geo: Geocoder
    route: dict | None = None  # última ruta dibujada
    changed: bool = False  # ¿el agente modificó datos del viaje?
    used: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- herramientas
def tool_clima(ctx: ToolContext, ciudad: str, dias: int = 7) -> dict:
    g = ctx.geo.lookup(ciudad)
    if not g:
        return {"error": f"No pude ubicar '{ciudad}'. {ctx.geo.last_error}".strip()}
    dias = max(1, min(int(dias), 16))
    d = _get_json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": g["lat"],
            "longitude": g["lon"],
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": dias,
        },
    )["daily"]
    out = [
        {
            "fecha": d["time"][i],
            "max_c": d["temperature_2m_max"][i],
            "min_c": d["temperature_2m_min"][i],
            "prob_lluvia_pct": d["precipitation_probability_max"][i],
        }
        for i in range(len(d["time"]))
    ]
    return {
        "ciudad": g["name"],
        "pronostico": out,
        "fuente": "Open-Meteo",
        "nota": "El pronóstico llega como máximo a 16 días. Para fechas más lejanas usa búsqueda web (clima típico del mes).",
    }


def tool_tipo_de_cambio(ctx: ToolContext, monto: float, de: str, a: str) -> dict:
    de, a = de.upper().strip(), a.upper().strip()
    errors = []
    for url, params in (
        ("https://api.frankfurter.dev/v1/latest", {"amount": monto, "base": de, "symbols": a}),
        ("https://api.frankfurter.app/latest", {"amount": monto, "from": de, "to": a}),
    ):
        try:
            d = _get_json(url, params)
            return {"monto": monto, "de": de, "a": a, "resultado": d["rates"][a], "fecha": d["date"], "fuente": "Frankfurter (tasas del BCE)"}
        except Exception as e:
            errors.append(str(e))
    return {"error": "No pude consultar el tipo de cambio (puede que la moneda no esté soportada). Usa búsqueda web.", "detalle": errors[-1]}


def tool_calcular_ruta(ctx: ToolContext, paradas: list[str], modo: str = "transit", titulo: str = "") -> dict:
    paradas = [p.strip() for p in paradas if p and p.strip()]
    if len(paradas) < 2:
        return {"error": "Necesito al menos 2 paradas."}
    if len(paradas) > 25:
        return {"error": "Máximo 25 paradas por ruta."}
    modo = modo if modo in MODES else "transit"
    stops, missing = [], []
    for p in paradas:
        g = ctx.geo.lookup(p)
        if g:
            stops.append({"nombre": p, "lat": g["lat"], "lon": g["lon"]})
        else:
            missing.append(p)
    legs = []
    for a, b in zip(stops, stops[1:]):
        km = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
        leg = {"de": a["nombre"], "a": b["nombre"], "km_linea_recta": round(km)}
        if modo == "driving" and km < 1500:
            try:
                r = _get_json(
                    f"https://router.project-osrm.org/route/v1/driving/{a['lon']},{a['lat']};{b['lon']},{b['lat']}",
                    {"overview": "false"},
                )["routes"][0]
                leg["km_por_carretera"] = round(r["distance"] / 1000)
                leg["horas_en_auto"] = round(r["duration"] / 3600, 1)
            except Exception:
                pass
        legs.append(leg)
    links = gmaps_links(paradas, modo)
    route = {"titulo": titulo or " → ".join(paradas[:3]), "modo": modo, "paradas": stops, "tramos": legs, "enlaces_google_maps": links}
    ctx.store.save_json(ctx.slug, "ultima_ruta.json", route)
    ctx.route = route
    ctx.changed = True
    res = dict(route)
    if missing:
        res["no_ubicadas"] = missing
    res["nota"] = "La ruta ya se dibujó en la pestaña Mapa de la app, con el enlace para abrirla en Google Maps."
    return res


def tool_guardar_lugar(ctx: ToolContext, nombre: str, ciudad: str, categoria: str = "turismo", precio: float | None = None, moneda: str = "", notas: str = "", fuente: str = "") -> dict:
    categoria = categoria if categoria in CATEGORIES else "otro"
    place = {
        "nombre": nombre,
        "ciudad": ciudad,
        "categoria": categoria,
        "precio": precio,
        "moneda": moneda.upper(),
        "notas": notas,
        "fuente": fuente,
        "guardado": date.today().isoformat(),
    }
    g = ctx.geo.lookup(f"{nombre}, {ciudad}")
    if g:
        place["lat"], place["lon"] = g["lat"], g["lon"]
    ctx.store.add_place(ctx.slug, place)
    ctx.changed = True
    return {"ok": True, "guardado": nombre, "ubicado_en_mapa": bool(g)}


def tool_agregar_parada(ctx: ToolContext, ciudad: str, pais: str = "", llegada: str = "", salida: str = "", hotel: str = "", notas: str = "") -> dict:
    ctx.store.add_stop(ctx.slug, ciudad, pais, llegada, salida, hotel, notas)
    ctx.changed = True
    return {"ok": True, "agregada": ciudad}


def tool_guardar_nota(ctx: ToolContext, texto: str) -> dict:
    ctx.store.append_note(ctx.slug, texto)
    ctx.changed = True
    return {"ok": True}


_FUNCS = {
    "clima": tool_clima,
    "tipo_de_cambio": tool_tipo_de_cambio,
    "calcular_ruta": tool_calcular_ruta,
    "guardar_lugar": tool_guardar_lugar,
    "agregar_parada": tool_agregar_parada,
    "guardar_nota": tool_guardar_nota,
}

_STR = {"type": "string"}
TOOLS: list[dict] = [
    {
        "name": "clima",
        "description": "Pronóstico del tiempo (hasta 16 días) para una ciudad. Úsalo solo si el viaje es en las próximas 2 semanas.",
        "input_schema": {"type": "object", "properties": {"ciudad": {**_STR, "description": "Ciudad y país, ej. 'Kioto, Japón'"}, "dias": {"type": "integer", "description": "Días de pronóstico (1-16)"}}, "required": ["ciudad"]},
    },
    {
        "name": "tipo_de_cambio",
        "description": "Convierte un monto entre dos monedas (códigos ISO como USD, EUR, JPY) con tasas del BCE.",
        "input_schema": {"type": "object", "properties": {"monto": {"type": "number"}, "de": _STR, "a": _STR}, "required": ["monto", "de", "a"]},
    },
    {
        "name": "calcular_ruta",
        "description": "Ubica las paradas, calcula distancias, dibuja la ruta en la pestaña Mapa de la app y devuelve enlaces para abrirla en Google Maps. Usa nombres completos con país, ej. 'Museo del Prado, Madrid, España'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "paradas": {"type": "array", "items": _STR, "description": "Paradas en orden (2 a 25)"},
                "modo": {"type": "string", "enum": list(MODES), "description": "transit (transporte público), driving, walking o bicycling"},
                "titulo": _STR,
            },
            "required": ["paradas"],
        },
    },
    {
        "name": "guardar_lugar",
        "description": "Guarda un lugar (restaurante, atracción, hotel...) con su precio en la carpeta del viaje. Úsalo cuando el usuario pida guardar algo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": _STR,
                "ciudad": {**_STR, "description": "Ciudad y país"},
                "categoria": {"type": "string", "enum": list(CATEGORIES)},
                "precio": {"type": "number", "description": "Precio por persona, si se conoce"},
                "moneda": {**_STR, "description": "Código ISO, ej. EUR"},
                "notas": _STR,
                "fuente": {**_STR, "description": "URL o fuente del precio"},
            },
            "required": ["nombre", "ciudad"],
        },
    },
    {
        "name": "agregar_parada",
        "description": "Agrega una ciudad a la tabla de ruta del viaje (fechas en formato AAAA-MM-DD).",
        "input_schema": {"type": "object", "properties": {"ciudad": _STR, "pais": _STR, "llegada": _STR, "salida": _STR, "hotel": _STR, "notas": _STR}, "required": ["ciudad"]},
    },
    {
        "name": "guardar_nota",
        "description": "Guarda una nota o decisión importante en notas.md del viaje.",
        "input_schema": {"type": "object", "properties": {"texto": _STR}, "required": ["texto"]},
    },
]


def build_tools(max_searches: int, only: list[str] | None = None) -> list[dict]:
    tools = [t for t in TOOLS if only is None or t["name"] in only]
    if max_searches > 0:
        tools.append({"type": "web_search_20250305", "name": "web_search", "max_uses": int(max_searches)})
    return tools


def execute_tool(ctx: ToolContext, name: str, args: dict) -> str:
    fn = _FUNCS.get(name)
    if fn is None:
        return json.dumps({"error": f"Herramienta desconocida: {name}"})
    ctx.used.append(name)
    try:
        return json.dumps(fn(ctx, **args), ensure_ascii=False, default=str)
    except TypeError as e:
        return json.dumps({"error": f"Argumentos inválidos: {e}"})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
