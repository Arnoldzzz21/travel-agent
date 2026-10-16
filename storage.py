"""Almacenamiento por carpetas de viaje (local).

viajes/
  _config.json            ajustes de la app (nombre del agente, modelo...)
  _geocache.json          caché de ubicaciones
  madrid/
    trip.json             nombre y países del viaje
    ruta.csv              paradas (ciudad, país, fechas, hotel, notas)
    lugares.json          lugares guardados (restaurantes, sitios, precios)
    notas.md              notas y resúmenes de conversaciones
    ultima_ruta.json      última ruta calculada por el agente
    itinerario.json       itinerario por día (horas, lugares, transporte, costos)

Si más adelante se quiere guardar en Google Drive, solo hay que reemplazar esta clase
por otra con los mismos métodos.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
import unicodedata
from datetime import date, datetime
from pathlib import Path

import pandas as pd

TRIP_FILES = ("trip.json", "ruta.csv", "lugares.json", "notas.md", "ultima_ruta.json", "itinerario.json")
ROUTE_COLS = ["Ciudad", "País", "Llegada", "Salida", "Hotel", "Notas"]
DATE_COLS = ["Llegada", "Salida"]

STATIC_FICHAS = Path(__file__).parent / "data" / "fichas"

DEFAULT_CONFIG = {
    "agent_name": "Nómada",
    "engine": "gemini",
    "gemini_model": "gemini-3.5-flash-lite",
    "model": "claude-sonnet-5-5",
    "max_searches": 5,
    "ficha_searches": 8,
    "history_turns": 8,
}

_ALIASES = {
    "Ciudad": ["ciudad", "city", "destino", "destination", "lugar", "town"],
    "País": ["país", "pais", "country", "nación"],
    "Llegada": ["llegada", "arrival", "desde", "from", "fecha llegada", "check-in", "checkin", "inicio", "start"],
    "Salida": ["salida", "departure", "hasta", "to", "fecha salida", "check-out", "checkout", "fin", "end"],
    "Hotel": ["hotel", "alojamiento", "hospedaje", "accommodation"],
    "Notas": ["notas", "notes", "nota", "comentarios", "comments"],
}


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60]


def empty_route() -> pd.DataFrame:
    df = pd.DataFrame({c: pd.Series(dtype="object") for c in ROUTE_COLS})
    return df


def _clean_dates(df: pd.DataFrame) -> pd.DataFrame:
    for c in DATE_COLS:
        parsed = pd.to_datetime(df[c], errors="coerce", dayfirst=False)
        df[c] = [None if pd.isna(v) else v.date() for v in parsed]
    return df


def normalize_route(df: pd.DataFrame) -> pd.DataFrame:
    """Acepta un Excel/CSV con columnas en español o inglés y devuelve el formato estándar."""
    lookup = {str(c).strip().lower(): c for c in df.columns}
    out = pd.DataFrame(index=df.index)
    for target in ROUTE_COLS:
        src = next((lookup[a] for a in [target.lower()] + _ALIASES[target] if a in lookup), None)
        out[target] = df[src] if src is not None else None
    for c in ("Ciudad", "País", "Hotel", "Notas"):
        out[c] = out[c].fillna("").astype(str).str.strip()
    out = _clean_dates(out)
    out = out[(out["Ciudad"] != "") | (out["País"] != "")].reset_index(drop=True)
    return out[ROUTE_COLS]


class TripStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------- carpetas ----------
    def _dir(self, slug: str) -> Path:
        if not slug or slug != slugify(slug):
            raise ValueError(f"Nombre de carpeta inválido: {slug!r}")
        return self.root / slug

    def list_trips(self) -> list[tuple[str, str]]:
        trips = []
        for d in sorted(self.root.iterdir()):
            if d.is_dir() and not d.name.startswith(("_", ".")) and (d / "trip.json").exists():
                meta = self.load_json(d.name, "trip.json", {})
                trips.append((d.name, meta.get("name", d.name)))
        return trips

    def create(self, name: str) -> str:
        name = name.strip()
        base = slugify(name) or "viaje"
        slug, n = base, 2
        while (self.root / slug).exists():
            slug, n = f"{base}-{n}", n + 1
        self._dir(slug).mkdir(parents=True)
        self.save_json(slug, "trip.json", {"name": name or "Viaje", "paises": [], "creado": date.today().isoformat()})
        return slug

    def delete(self, slug: str) -> None:
        shutil.rmtree(self._dir(slug))

    # ---------- respaldo ----------
    def export_zip(self, slug: str) -> bytes:
        """Todo el viaje (ruta, lugares, notas) en un .zip para guardarlo fuera de la app."""
        buf, d = io.BytesIO(), self._dir(slug)
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in TRIP_FILES:
                if (d / f).exists():
                    z.write(d / f, f)
        return buf.getvalue()

    def import_zip(self, data: bytes) -> str:
        """Crea un viaje nuevo a partir de un respaldo. Solo se leen los archivos conocidos (nada de rutas ajenas)."""
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise ValueError("El archivo no es un .zip válido.") from e
        found = {Path(i.filename).name: i for i in z.infolist() if not i.is_dir() and Path(i.filename).name in TRIP_FILES}
        if "trip.json" not in found:
            raise ValueError("No parece un respaldo de Nómada (falta trip.json).")
        if sum(i.file_size for i in found.values()) > 10_000_000:
            raise ValueError("El respaldo es demasiado grande.")
        try:
            meta = json.loads(z.read(found["trip.json"]).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError("trip.json está dañado.") from e
        if not isinstance(meta, dict):
            raise ValueError("trip.json está dañado.")
        meta["name"] = str(meta.get("name") or "Viaje restaurado")
        meta["paises"] = [str(x) for x in meta.get("paises", [])] if isinstance(meta.get("paises"), list) else []
        if any(n == meta["name"] for _, n in self.list_trips()):
            meta["name"] += " (restaurado)"
        slug = self.create(meta["name"])
        for f, info in found.items():
            if f != "trip.json":
                (self._dir(slug) / f).write_bytes(z.read(info))
        self.save_json(slug, "trip.json", meta)
        return slug

    # ---------- json genérico ----------
    def load_json(self, slug: str, fname: str, default):
        p = self._dir(slug) / fname
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    def save_json(self, slug: str, fname: str, data) -> None:
        (self._dir(slug) / fname).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def meta(self, slug: str) -> dict:
        return self.load_json(slug, "trip.json", {"name": slug, "paises": []})

    def toggle_country(self, slug: str, country_es: str) -> None:
        meta = self.meta(slug)
        paises = meta.setdefault("paises", [])
        if country_es in paises:
            paises.remove(country_es)
        else:
            paises.append(country_es)
        self.save_json(slug, "trip.json", meta)

    # ---------- ruta ----------
    def load_route(self, slug: str) -> pd.DataFrame:
        p = self._dir(slug) / "ruta.csv"
        if not p.exists():
            return empty_route()
        df = pd.read_csv(p, dtype=str, keep_default_na=False)
        for c in ROUTE_COLS:
            if c not in df.columns:
                df[c] = ""
        df = _clean_dates(df[ROUTE_COLS].copy())
        return df

    def save_route(self, slug: str, df: pd.DataFrame) -> None:
        out = df.copy()
        for c in ROUTE_COLS:
            if c not in out.columns:
                out[c] = None
        out = out[ROUTE_COLS]
        for c in ("Ciudad", "País", "Hotel", "Notas"):
            out[c] = out[c].fillna("").astype(str)
        out = out[(out["Ciudad"].str.strip() != "") | (out["País"].str.strip() != "")]
        out.to_csv(self._dir(slug) / "ruta.csv", index=False, encoding="utf-8-sig")

    def add_stop(self, slug: str, ciudad: str, pais: str = "", llegada: str = "", salida: str = "", hotel: str = "", notas: str = "") -> None:
        df = self.load_route(slug)
        row = pd.DataFrame([{"Ciudad": ciudad, "País": pais, "Llegada": llegada or None, "Salida": salida or None, "Hotel": hotel, "Notas": notas}])
        row = _clean_dates(row)
        df = pd.concat([df, row], ignore_index=True) if len(df) else row
        self.save_route(slug, df)

    # ---------- lugares ----------
    def load_places(self, slug: str) -> list[dict]:
        return self.load_json(slug, "lugares.json", [])

    def save_places(self, slug: str, places: list[dict]) -> None:
        self.save_json(slug, "lugares.json", places)

    def add_place(self, slug: str, place: dict) -> None:
        places = self.load_places(slug)
        places.append(place)
        self.save_places(slug, places)

    # ---------- itinerario por día ----------
    def load_itinerary(self, slug: str) -> list[dict]:
        import plan
        return plan.clean_itinerary(self.load_json(slug, "itinerario.json", []))

    def save_itinerary(self, slug: str, days: list[dict]) -> None:
        import plan
        self.save_json(slug, "itinerario.json", plan.clean_itinerary(days))

    # ---------- notas ----------
    def read_notes(self, slug: str) -> str:
        p = self._dir(slug) / "notas.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def append_note(self, slug: str, text: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(self._dir(slug) / "notas.md", "a", encoding="utf-8") as f:
            f.write(f"\n### {stamp}\n{text.strip()}\n")

    # ---------- fichas de país (compartidas entre viajes) ----------
    def load_ficha(self, iso: str) -> dict | None:
        """Primero la ficha actualizada por el usuario (viajes/_fichas); si no hay, la ficha base del repositorio (data/fichas)."""
        for p in (self.root / "_fichas" / f"{iso.upper()}.json", STATIC_FICHAS / f"{iso.upper()}.json"):
            if p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
        return None

    def static_isos(self) -> set[str]:
        return {p.stem.upper() for p in STATIC_FICHAS.glob("*.json")} if STATIC_FICHAS.exists() else set()

    def save_ficha(self, iso: str, data: dict) -> None:
        d = self.root / "_fichas"
        d.mkdir(exist_ok=True)
        (d / f"{iso.upper()}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- configuración global ----------
    def load_config(self) -> dict:
        p = self.root / "_config.json"
        cfg = dict(DEFAULT_CONFIG)
        if p.exists():
            try:
                cfg.update(json.loads(p.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
        return cfg

    def save_config(self, cfg: dict) -> None:
        (self.root / "_config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
