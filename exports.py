"""Exportar el viaje a un archivo KML que se importa gratis en Google My Maps (mymaps.google.com)."""
from __future__ import annotations

import re
from xml.sax.saxutils import escape

_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _x(text) -> str:
    return escape(_BAD.sub("", "" if text is None else str(text)))


def _placemark(name: str, lat: float, lon: float, desc: str = "") -> str:
    return (f"<Placemark><name>{_x(name)}</name><description>{_x(desc)}</description>"
            f"<Point><coordinates>{float(lon):.6f},{float(lat):.6f},0</coordinates></Point></Placemark>")


def build_kml(title: str, stops: list[dict], places: list[dict]) -> str:
    """stops: [{name, lat, lon, desc}] en orden de viaje; places: [{name, lat, lon, desc}]."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>', f"<name>{_x(title)}</name>"]
    if stops:
        out.append("<Folder><name>Ruta</name>")
        out += [_placemark(s["name"], s["lat"], s["lon"], s.get("desc", "")) for s in stops]
        if len(stops) > 1:
            coords = " ".join(f"{float(s['lon']):.6f},{float(s['lat']):.6f},0" for s in stops)
            out.append(f"<Placemark><name>Recorrido</name><LineString><tessellate>1</tessellate><coordinates>{coords}</coordinates></LineString></Placemark>")
        out.append("</Folder>")
    if places:
        out.append("<Folder><name>Lugares guardados</name>")
        out += [_placemark(p["name"], p["lat"], p["lon"], p.get("desc", "")) for p in places]
        out.append("</Folder>")
    out.append("</Document></kml>")
    return "\n".join(out)
