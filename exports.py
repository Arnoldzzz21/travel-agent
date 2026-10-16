"""Exportar el viaje a un archivo KML que se importa gratis en Google My Maps (mymaps.google.com)."""
from __future__ import annotations

import re
from datetime import date
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


# ---------------------------------------------------------------- versión para llevar (HTML imprimible / PDF)
_CSS = """
:root{color-scheme:light}*{box-sizing:border-box}
body{font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1d1b3a;margin:0;background:#fff}
main{max-width:820px;margin:0 auto;padding:20px 18px 48px}
h1{font-size:1.7rem;margin:.2em 0}h2{font-size:1.15rem;margin:1.6em 0 .5em;padding-bottom:.25em;border-bottom:2px solid #6C5CE7;color:#3b2fa8}
h3{font-size:1rem;margin:1.1em 0 .3em}.muted{color:#6b6a85;font-size:.9rem}
table{width:100%;border-collapse:collapse;font-size:.92rem}th,td{padding:6px 8px;border-bottom:1px solid #e6e4f5;text-align:left;vertical-align:top}
th{background:#f4f2ff;font-weight:600}a{color:#4b3fd1}.day{break-inside:avoid;margin-bottom:10px}
.tag{display:inline-block;background:#fff4d6;color:#7a5a00;border-radius:999px;padding:0 8px;font-size:.78rem}
.tot{font-weight:700}.note{white-space:pre-wrap;background:#f8f7ff;padding:10px 12px;border-radius:8px;font-size:.9rem}
button{background:#6C5CE7;color:#fff;border:0;border-radius:10px;padding:10px 16px;font-size:1rem;margin:6px 0 0}
@media print{button,.noprint{display:none}main{padding:0}a{color:inherit;text-decoration:none}h2{break-after:avoid}}
"""


def _link(label: str, url: str) -> str:
    return f'<a href="{_x(url)}">{_x(label)}</a>'


def _money(tot: dict) -> str:
    return " + ".join(f"{v:,.2f} {_x(c)}" for c, v in tot.items()) or "—"


def build_html(title: str, countries: list[str], stops: list[dict], itinerary: list[dict], budget: dict | None,
               places: list[dict], notes: str, mode: str = "transit") -> str:
    """Página única, sin internet ni librerías: se abre en cualquier navegador y se guarda como PDF con Imprimir.
    stops: [{ciudad, pais, llegada, salida, hotel, notas, lat?, lon?}]."""
    from tools import gmaps_leg_link, gmaps_place_link, gmaps_streetview_link
    h = [f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
         f"<title>{_x(title)}</title><style>{_CSS}</style></head><body><main>",
         f"<h1>✈️ {_x(title)}</h1>",
         f'<div class="muted">{_x(", ".join(countries)) or "Sin países definidos"} · generado el {date.today().isoformat()}</div>',
         '<button class="noprint" onclick="window.print()">🖨️ Imprimir / Guardar como PDF</button>']
    if stops:
        h.append("<h2>Ruta</h2><table><tr><th>#</th><th>Ciudad</th><th>Fechas</th><th>Hotel</th><th>Enlaces</th></tr>")
        for n, s_ in enumerate(stops, 1):
            q = ", ".join(x for x in (s_.get("ciudad", ""), s_.get("pais", "")) if x)
            links = [_link("Mapa", gmaps_place_link(q))]
            if s_.get("lat") is not None and s_.get("lon") is not None:
                links.append(_link("Street View", gmaps_streetview_link(s_["lat"], s_["lon"])))
            if n < len(stops):
                nxt = ", ".join(x for x in (stops[n].get("ciudad", ""), stops[n].get("pais", "")) if x)
                links.append(_link("Llegar a " + stops[n].get("ciudad", ""), gmaps_leg_link(q, nxt, mode)))
            dates = " → ".join(str(d) for d in (s_.get("llegada"), s_.get("salida")) if d)
            h.append(f"<tr><td>{n}</td><td><b>{_x(q)}</b><br><span class='muted'>{_x(s_.get('notas', ''))}</span></td><td>{_x(dates)}</td>"
                     f"<td>{_x(s_.get('hotel', ''))}</td><td>{' · '.join(links)}</td></tr>")
        h.append("</table>")
    if itinerary:
        h.append("<h2>Itinerario por día</h2>")
        for d in itinerary:
            head = f"Día {d['dia']}" + (f" · {d['fecha']}" if d.get("fecha") else "") + (f" · {d['titulo']}" if d.get("titulo") else "")
            h.append(f'<div class="day"><h3>{_x(head)}</h3><table><tr><th>Hora</th><th>Lugar y actividad</th><th>Transporte</th><th>Costo</th></tr>')
            for it in d["items"]:
                costs = [f"{c:,.2f}" for c in (it.get("costo"), it.get("costo_transporte")) if c is not None]
                cost = (" + ".join(costs) + f" {_x(it.get('moneda', ''))}") if costs else "—"
                tag = ' <span class="tag">aprox.</span>' if costs and it.get("aproximado") else ""
                place = _link(it["lugar"], gmaps_place_link(it["lugar"])) if it.get("lugar") else ""
                h.append(f"<tr><td>{_x(it.get('hora', ''))}</td><td>{place}<br><span class='muted'>{_x(it.get('actividad', ''))}</span></td>"
                         f"<td>{_x(it.get('transporte', ''))}</td><td>{cost}{tag}</td></tr>")
            h.append("</table></div>")
    if budget and (budget["total"] or budget["otros_total"]):
        h.append("<h2>Presupuesto estimado (por persona)</h2><table><tr><th>Concepto</th><th>Total</th></tr>")
        h.append(f"<tr><td class='tot'>Itinerario</td><td class='tot'>{_x(_money({c: v['total'] for c, v in budget['total'].items()}))}</td></tr>")
        for row in budget["por_dia"]:
            if row["totales"]:
                h.append(f"<tr><td>Día {row['dia']} {_x(row['titulo'])}</td><td>{_x(_money({c: v['total'] for c, v in row['totales'].items()}))}</td></tr>")
        if budget["otros_total"]:
            h.append(f"<tr><td>Otros lugares guardados (referencia)</td><td>{_x(_money({c: v['total'] for c, v in budget['otros_total'].items()}))}</td></tr>")
        h.append("</table>")
        h.append(f"<p class='muted'>{budget['n_aprox']} de {budget['n_items']} actividades tienen precio aproximado y {budget['n_sin_costo']} no tienen costo. "
                 "Confirma los precios antes de pagar; los totales no convierten entre monedas.</p>")
    if places:
        h.append("<h2>Lugares guardados</h2><table><tr><th>Lugar</th><th>Ciudad</th><th>Precio</th><th>Enlaces</th></tr>")
        for p in places:
            links = [_link("Mapa", gmaps_place_link(f"{p.get('nombre', '')} {p.get('ciudad', '')}".strip()))]
            if p.get("lat") is not None and p.get("lon") is not None:
                try:
                    links.append(_link("Street View", gmaps_streetview_link(float(p["lat"]), float(p["lon"]))))
                except (TypeError, ValueError):
                    pass
            price = f"{p.get('precio')} {p.get('moneda') or ''}" if p.get("precio") not in (None, "") else "—"
            h.append(f"<tr><td><b>{_x(p.get('nombre', ''))}</b><br><span class='muted'>{_x(p.get('categoria', ''))} {_x(p.get('notas', ''))}</span></td>"
                     f"<td>{_x(p.get('ciudad', ''))}</td><td>{_x(price)}</td><td>{' · '.join(links)}</td></tr>")
        h.append("</table>")
    if notes.strip():
        h.append(f"<h2>Notas</h2><div class='note'>{_x(notes.strip())}</div>")
    h.append("<p class='muted'>Hecho con Nómada · Arnoldo Cuéllar</p></main></body></html>")
    return "".join(h)
