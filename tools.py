"""Herramientas que el agente puede llamar (clima, cambio, rutas, guardar lugares...)."""
from __future__ import annotations

import json
import math
import re
import threading
import unicodedata
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import requests

UA = {"User-Agent": "AgenteViajesPersonal/1.0 (uso personal)"}
MODES = ("transit", "driving", "walking", "bicycling")
CATEGORIES = ("comida", "turismo", "transporte", "hospedaje", "compras", "otro")


def _get_json(url: str, params: dict | None = None, timeout: int = 15):
    r = requests.get(url, params=params, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _norm(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(s).lower()) if not unicodedata.combining(ch)).strip()


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
        self._miss: dict[str, float] = {}
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
        """Ciudades, pueblos y lugares. Prueba Nominatim (OpenStreetMap) y, si falla o no encuentra, Open-Meteo Geocoding."""
        hit = self.cached(query)
        if hit:
            return hit
        key = self._key(query)
        if time.time() - self._miss.get(key, 0) < 600:  # no repetir búsquedas fallidas en cada recarga
            return None
        self.last_error = ""
        errors: list[str] = []
        with self._lock:
            parts = [x.strip() for x in query.split(",") if x.strip()]
            attempts = [(self._nominatim, query)]
            if len(parts) > 2:  # "hotel, barrio, ciudad, país" -> "ciudad, país"
                attempts.append((self._nominatim, f"{parts[-2]}, {parts[-1]}"))
            attempts.append((self._openmeteo, query))
            hit = None
            for fn, q in attempts:
                try:
                    hit = fn(q)
                except Exception as e:  # red caída, bloqueo por límite, etc.
                    errors.append(str(e))
                    hit = None
                if hit:
                    break
        if hit:
            self._cache[key] = hit
            self._save()
            return hit
        self._miss[key] = time.time()
        # solo es "error" si TODOS los intentos fallaron por problemas de red/servicio; si no, simplemente no existe
        if errors and len(errors) == len(attempts):
            self.last_error = errors[-1]
        return None

    def _nominatim(self, query: str) -> dict | None:
        wait = 1.1 - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            data = _get_json(
                "https://nominatim.openstreetmap.org/search",
                {"q": query, "format": "jsonv2", "limit": 1, "accept-language": "es"},
            )
        finally:
            self._last_call = time.time()
        if not data:
            return None
        return {"lat": float(data[0]["lat"]), "lon": float(data[0]["lon"]), "name": data[0].get("display_name", query)}

    @staticmethod
    def _openmeteo(query: str) -> dict | None:
        parts = [x.strip() for x in query.split(",") if x.strip()]
        if not parts:
            return None
        d = _get_json("https://geocoding-api.open-meteo.com/v1/search", {"name": parts[0], "count": 10, "language": "es", "format": "json"})
        res = d.get("results") or []
        if not res:
            return None
        rest = {_norm(x) for x in parts[1:]}
        if rest:  # con país/provincia: solo aceptamos coincidencias, para no ubicar un homónimo de otro país
            res = [r for r in res if rest & {_norm(r.get(k, "")) for k in ("country", "admin1", "admin2", "admin3", "country_code")}]
        if not res:
            return None
        r = res[0]
        name = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x)
        return {"lat": float(r["latitude"]), "lon": float(r["longitude"]), "name": name}

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def clear(self) -> None:
        self._cache = {}
        self._miss = {}
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


def gmaps_place_link(query: str) -> str:
    """Abre un lugar o ciudad en Google Maps (búsqueda por nombre, sin API ni clave)."""
    return "https://www.google.com/maps/search/?" + urlencode({"api": 1, "query": query})


def gmaps_streetview_link(lat: float, lon: float) -> str:
    """Abre Street View de Google en esas coordenadas, para 'caminar' el lugar antes de viajar."""
    return "https://www.google.com/maps/@?" + urlencode({"api": 1, "map_action": "pano", "viewpoint": f"{lat:.6f},{lon:.6f}"})


def gmaps_leg_link(origin: str, destination: str, mode: str = "transit") -> str:
    """Cómo llegar de una parada a la siguiente (con horarios si el modo es transporte público)."""
    mode = mode if mode in MODES else "transit"
    return "https://www.google.com/maps/dir/?" + urlencode({"api": 1, "origin": origin, "destination": destination, "travelmode": mode})


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


def tool_guardar_itinerario(ctx: ToolContext, dias: list, modo: str = "reemplazar") -> dict:
    import plan
    new = plan.clean_itinerary(dias)
    if not new:
        return {"error": "No recibí días con actividades. Manda dias=[{dia, fecha, pais, titulo, items:[{hora, lugar, actividad, costo, transporte, costo_transporte, moneda, aproximado}]}]."}
    days = plan.merge_days(ctx.store.load_itinerary(ctx.slug), new) if modo == "agregar" else new
    ctx.store.save_itinerary(ctx.slug, days)
    ctx.changed = True
    b = plan.budget(days)
    return {"ok": True, "dias_guardados": len(new), "dias_en_total": len(days), "actividades": b["n_items"],
            "total_estimado": {c: round(v["total"], 2) for c, v in b["total"].items()}, "sin_costo": b["n_sin_costo"]}


def tool_guardar_nota(ctx: ToolContext, texto: str) -> dict:
    ctx.store.append_note(ctx.slug, texto)
    ctx.changed = True
    return {"ok": True}


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Divide un extracto de MediaWiki (explaintext) en (titulo, contenido)."""
    parts, title, buf = [], "Introducción", []
    for line in text.splitlines():
        m = re.match(r"^=+\s*(.+?)\s*=+\s*$", line)
        if m:
            parts.append((title, "\n".join(buf).strip()))
            title, buf = m.group(1), []
        else:
            buf.append(line)
    parts.append((title, "\n".join(buf).strip()))
    return [(t, c) for t, c in parts if c]


def tool_wikivoyage(ctx: ToolContext, lugar: str, seccion: str = "", idioma: str = "es") -> dict:
    """Guía de viaje libre (Wikivoyage, CC BY-SA). Sin seccion devuelve la introducción y la lista de secciones."""
    langs = list(dict.fromkeys([idioma if idioma in ("es", "en") else "es", "en"]))
    for lang in langs:
        try:
            d = _get_json(
                f"https://{lang}.wikivoyage.org/w/api.php",
                {"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1, "titles": lugar, "format": "json", "formatversion": 2},
            )
            page = (d.get("query", {}).get("pages") or [{}])[0]
        except Exception:
            continue
        if page.get("missing") or not page.get("extract"):
            continue
        secs = _split_sections(page["extract"])
        url = f"https://{lang}.wikivoyage.org/wiki/" + quote(str(page.get("title", lugar)).replace(" ", "_"))
        out = {"lugar": page.get("title", lugar), "idioma": lang, "fuente": "Wikivoyage (CC BY-SA)", "url": url}
        if seccion.strip():
            q = seccion.strip().lower()
            hits = [(t, c) for t, c in secs if q in t.lower()]
            if not hits:
                out["secciones_disponibles"] = [t for t, _ in secs]
                out["nota"] = f"No hay una sección que contenga '{seccion}'."
                return out
            out["contenido"] = "\n\n".join(f"## {t}\n{c}" for t, c in hits)[:6000]
        else:
            out["introduccion"] = secs[0][1][:1800] if secs else ""
            out["secciones_disponibles"] = [t for t, _ in secs]
        return out
    return {"error": f"No encontré '{lugar}' en Wikivoyage. Prueba con el nombre en inglés o usa buscar_web."}


def tool_ficha_pais(ctx: ToolContext, pais: str) -> dict:
    """Ficha guardada del país (transporte, pases, pagos, precios típicos). Es el dato más fiable y rápido: úsala antes de buscar en la web."""
    from countries import load_countries

    q = _norm(pais)
    c = next((x for x in load_countries() if q in (_norm(x.es), _norm(x.en), x.iso.lower())), None)
    if c is None or ctx.store is None:
        return {"error": f"País '{pais}' no encontrado en el catálogo."}
    f = ctx.store.load_ficha(c.iso)
    if not f or f.get("_sin_formato"):
        return {"disponible": False, "nota": f"Aún no hay ficha de {c.es}. Usa buscar_web o wikivoyage."}
    f = {k: v for k, v in f.items() if not k.startswith("_") or k in ("_estatica",)}
    f["disponible"] = True
    return f


_FUNCS = {
    "clima": tool_clima,
    "tipo_de_cambio": tool_tipo_de_cambio,
    "calcular_ruta": tool_calcular_ruta,
    "guardar_lugar": tool_guardar_lugar,
    "agregar_parada": tool_agregar_parada,
    "guardar_nota": tool_guardar_nota,
    "guardar_itinerario": tool_guardar_itinerario,
    "wikivoyage": tool_wikivoyage,
    "ficha_pais": tool_ficha_pais,
}

_STR = {"type": "string"}
TOOLS: list[dict] = [
    {
        "name": "ficha_pais",
        "description": "Ficha ya investigada de un país: transporte con precios, tarjetas/pases para turistas y residentes, formas de pago y precios típicos. Es el dato más rápido y fiable: consúltala ANTES de buscar en la web cuando pregunten por transporte, pases o pagos.",
        "input_schema": {"type": "object", "properties": {"pais": {**_STR, "description": "Nombre del país, ej. 'Japón'"}}, "required": ["pais"]},
    },
    {
        "name": "wikivoyage",
        "description": "Guía de viaje libre de Wikivoyage sobre una ciudad o región (cómo llegar, moverse, comer, dormir, qué ver). Sin 'seccion' devuelve la introducción y la lista de secciones; con 'seccion' (ej. 'Moverse', 'Get around', 'Comer') devuelve ese texto.",
        "input_schema": {"type": "object", "properties": {"lugar": {**_STR, "description": "Ciudad o región, ej. 'Kioto'"}, "seccion": _STR, "idioma": {"type": "string", "enum": ["es", "en"]}}, "required": ["lugar"]},
    },
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
        "name": "guardar_itinerario",
        "description": "Guarda el itinerario por día en la pestaña Ruta de la app (con horas, lugares, transporte y costos) para que el usuario lo vea y lo edite. Úsalo SOLO cuando el usuario pida guardarlo o confirme tu propuesta. Manda todos los días con sus actividades; con modo 'agregar' solo reemplazas los días que mandes. Costos por persona, como número, en la moneda local (en Japón: USD); marca aproximado=true si el dato no está verificado.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dias": {
                    "type": "array",
                    "description": "Lista de días",
                    "items": {
                        "type": "object",
                        "properties": {
                            "dia": {"type": "integer", "description": "Número de día: 1, 2, 3…"},
                            "fecha": {**_STR, "description": "AAAA-MM-DD si se conoce"},
                            "pais": _STR,
                            "titulo": {**_STR, "description": "Ej. 'Madrid clásico'"},
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "hora": {**_STR, "description": "HH:MM"},
                                        "lugar": _STR,
                                        "actividad": _STR,
                                        "costo": {"type": "number", "description": "Entrada o gasto de la actividad"},
                                        "transporte": {**_STR, "description": "Cómo llegar ahí, ej. 'Metro L2'"},
                                        "costo_transporte": {"type": "number"},
                                        "moneda": {**_STR, "description": "ISO, ej. EUR"},
                                        "aproximado": {"type": "boolean"},
                                    },
                                    "required": ["lugar"],
                                },
                            },
                        },
                        "required": ["dia", "items"],
                    },
                },
                "modo": {"type": "string", "enum": ["reemplazar", "agregar"]},
            },
            "required": ["dias"],
        },
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
