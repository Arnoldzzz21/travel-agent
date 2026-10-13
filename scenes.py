"""Paisajes animados (SVG) por país, dibujados en código y de diseño propio.

Cada escena tiene: cielo en degradado, sol que respira, nubes que se desplazan, montañas en capas con leve
vaivén, nieve o pétalos cayendo (según la paleta) y un motivo propio del país (Fuji, Alpes, torre, castillo...).
Las animaciones viven en el CSS de ui.py (clases sc-*).
"""
from __future__ import annotations

import random

W, H = 400, 240
BASE = 190  # línea de suelo donde se apoyan los motivos

# (cielo arriba, cielo abajo, montañas lejanas, montañas medias, colinas cercanas, acento)
PALETTES = {
    "lavanda": ("#6F5FE8", "#F1D9FF", "#B9ADFF", "#7E6DF0", "#4A3FA6", "#FF9EC4"),
    "alba": ("#F08A6C", "#FFE7C8", "#F7BE9C", "#D9667A", "#7B3F8F", "#FFD27A"),
    "turquesa": ("#3FA3A5", "#DDF8EE", "#93D6CB", "#3C8F9A", "#2D5F7A", "#FF8A6C"),
    "azul": ("#4F7CE0", "#E2F2FF", "#A4C8F5", "#4A6FD0", "#2F3F8F", "#FFB36C"),
    "aurora": ("#2B2A6E", "#7BE0C8", "#6C70C4", "#4A4CA6", "#232465", "#7BE0C8"),
    "dorado": ("#E0A84F", "#FFF3D1", "#F4D08C", "#DB8F55", "#8F4B3A", "#C8473F"),
    "verde": ("#5BB98B", "#EAF9DC", "#A8DDB0", "#4FA377", "#2E6B58", "#F2C14E"),
}
SNOWY = {"lavanda", "azul", "aurora", "turquesa"}

# país (ISO2) -> (motivo, paleta)
SCENES = {
    "JP": ("fuji", "lavanda"), "AL": ("alps", "turquesa"), "AD": ("alps", "azul"), "AM": ("fuji", "alba"),
    "AT": ("alps", "lavanda"), "AZ": ("mosque", "dorado"), "BY": ("castle", "verde"), "BE": ("clock", "alba"),
    "BA": ("bridge", "turquesa"), "BG": ("onion", "alba"), "HR": ("sail", "turquesa"), "CY": ("temple", "dorado"),
    "CZ": ("spires", "lavanda"), "DK": ("sail", "azul"), "EE": ("spires", "azul"), "FI": ("fjord", "aurora"),
    "FR": ("tower", "alba"), "GE": ("alps", "verde"), "DE": ("temple", "azul"), "GR": ("temple", "azul"),
    "HU": ("bridge", "alba"), "IS": ("volcano", "aurora"), "IE": ("lighthouse", "verde"), "IT": ("colosseum", "dorado"),
    "KZ": ("yurt", "dorado"), "LV": ("spires", "turquesa"), "LI": ("castle", "verde"), "LT": ("spires", "alba"),
    "LU": ("fortress", "verde"), "MT": ("sail", "dorado"), "MD": ("fortress", "verde"), "MC": ("sail", "azul"),
    "ME": ("sail", "turquesa"), "NL": ("windmill", "azul"), "MK": ("alps", "verde"), "NO": ("fjord", "aurora"),
    "PL": ("castle", "alba"), "PT": ("lighthouse", "dorado"), "RO": ("fortress", "alba"), "RU": ("onion", "azul"),
    "SM": ("castle", "lavanda"), "RS": ("castle", "turquesa"), "SK": ("fortress", "verde"), "SI": ("alps", "turquesa"),
    "ES": ("arch", "dorado"), "SE": ("fjord", "azul"), "CH": ("alps", "azul"), "TR": ("mosque", "alba"),
    "UA": ("onion", "dorado"), "GB": ("clock", "azul"), "VA": ("dome", "dorado"),
}


def shade(hexcolor: str, f: float) -> str:
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % (min(255, int(r * f)), min(255, int(g * f)), min(255, int(b * f)))


def poly(points, fill, extra="") -> str:
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polygon points="{pts}" fill="{fill}" {extra}/>'


def snowcap(px, py, hw, h, depth) -> str:
    xo = depth * hw / h
    pts = [(px, py), (px - xo, py + depth), (px - xo * 0.55, py + depth * 0.78), (px - xo * 0.2, py + depth * 1.12),
           (px + xo * 0.1, py + depth * 0.8), (px + xo * 0.45, py + depth * 1.1), (px + xo, py + depth)]
    return poly(pts, "#fff", 'opacity=".96"')


def peak(px, py, hw, color, depth=None) -> str:
    h = BASE + 5 - py
    s = poly([(px - hw, BASE + 5), (px, py), (px + hw, BASE + 5)], color)
    s += poly([(px, py), (px + hw, BASE + 5), (px + hw * 0.25, BASE + 5)], shade(color, 0.82), 'opacity=".55"')
    return s + snowcap(px, py, hw, h, depth or h * 0.3)


def pines(xs, color) -> str:
    out = []
    for x, s in xs:
        for k in range(3):
            y = BASE + 4 - k * 9 * s
            w = (12 - k * 2.5) * s
            out.append(poly([(x - w, y), (x, y - 14 * s), (x + w, y)], color))
        out.append(f'<rect x="{x - 1:.1f}" y="{BASE + 4:.1f}" width="2" height="4" fill="{color}"/>')
    return "".join(out)


# ------------------------------------------------------------------ motivos
def m_fuji(cx, p, rng):
    top, bot, far, mid, near, acc = p
    py, hw = BASE - 138, 125
    return peak(cx, py, hw, mid, 46) + peak(cx - 150, BASE - 62, 70, shade(mid, 1.12), 18)


def m_alps(cx, p, rng):
    top, bot, far, mid, near, acc = p
    return (peak(cx - 100, BASE - 92, 75, shade(mid, 1.1)) + peak(cx + 95, BASE - 100, 78, shade(mid, 1.05))
            + peak(cx, BASE - 142, 95, mid) + pines([(cx - 150, 1.1), (cx - 130, 0.9), (cx + 150, 1.0)], shade(near, 0.8)))


def m_tower(cx, p, rng):
    dk = shade(p[4], 0.7)
    body = [(cx - 34, BASE + 5), (cx - 20, BASE - 40), (cx - 8, BASE - 95), (cx, BASE - 150), (cx + 8, BASE - 95),
            (cx + 20, BASE - 40), (cx + 34, BASE + 5), (cx + 14, BASE + 5), (cx, BASE - 36), (cx - 14, BASE + 5)]
    s = poly(body, dk)
    s += f'<rect x="{cx - 22}" y="{BASE - 42}" width="44" height="5" fill="{dk}"/><rect x="{cx - 11}" y="{BASE - 97}" width="22" height="4" fill="{dk}"/>'
    s += f'<circle cx="{cx}" cy="{BASE - 154}" r="2.5" fill="{p[5]}" class="sc-lamp"/>'
    return s


def m_castle(cx, p, rng):
    dk, acc = shade(p[4], 0.75), p[5]
    s = f'<rect x="{cx - 60}" y="{BASE - 45}" width="120" height="50" fill="{dk}"/>'
    s += "".join(f'<rect x="{cx - 60 + i * 15}" y="{BASE - 52}" width="8" height="8" fill="{dk}"/>' for i in range(8))
    for tx, h in ((cx - 72, 85), (cx + 50, 85), (cx - 11, 100)):
        s += f'<rect x="{tx}" y="{BASE + 5 - h}" width="22" height="{h}" fill="{dk}"/>'
        s += poly([(tx - 4, BASE + 5 - h), (tx + 11, BASE - h - 26), (tx + 26, BASE + 5 - h)], acc)
        s += f'<rect x="{tx + 8}" y="{BASE + 5 - h + 14}" width="6" height="10" rx="3" fill="#FFE9A8" class="sc-lamp"/>'
    s += f'<path d="M{cx - 14},{BASE + 5} v-18 a14,14 0 0 1 28,0 v18z" fill="#FFE9A8" opacity=".9"/>'
    return s


def m_onion(cx, p, rng):
    dk, acc = shade(p[4], 0.75), p[5]
    s = ""
    for x, y, r in ((cx - 52, BASE - 48, 0.7), (cx + 52, BASE - 48, 0.7), (cx, BASE - 78, 1.0)):
        s += f'<rect x="{x - 12 * r}" y="{y}" width="{24 * r}" height="{BASE + 5 - y}" fill="{dk}"/>'
        s += f'<path d="M{x - 15 * r},{y} Q{x - 25 * r},{y - 20 * r} {x},{y - 46 * r} Q{x + 25 * r},{y - 20 * r} {x + 15 * r},{y}z" fill="{acc}"/>'
        s += f'<path d="M{x - 15 * r},{y} Q{x - 25 * r},{y - 20 * r} {x},{y - 46 * r}" stroke="#fff" stroke-width="1.5" fill="none" opacity=".6"/>'
        s += f'<line x1="{x}" y1="{y - 46 * r}" x2="{x}" y2="{y - 58 * r}" stroke="{acc}" stroke-width="2"/><line x1="{x - 4}" y1="{y - 53 * r}" x2="{x + 4}" y2="{y - 53 * r}" stroke="{acc}" stroke-width="2"/>'
    return s


def m_mosque(cx, p, rng):
    dk, acc = shade(p[4], 0.75), p[5]
    s = f'<rect x="{cx - 46}" y="{BASE - 34}" width="92" height="39" fill="{dk}"/>'
    s += f'<path d="M{cx - 38},{BASE - 34} A38,38 0 0 1 {cx + 38},{BASE - 34}z" fill="{acc}"/>'
    s += f'<circle cx="{cx}" cy="{BASE - 77}" r="3" fill="#fff"/>'
    for mx in (cx - 64, cx + 55):
        s += f'<rect x="{mx}" y="{BASE - 92}" width="9" height="97" fill="{dk}"/>' + poly([(mx - 2, BASE - 92), (mx + 4.5, BASE - 112), (mx + 11, BASE - 92)], acc)
        s += f'<rect x="{mx - 2}" y="{BASE - 66}" width="13" height="4" fill="{acc}"/>'
    s += f'<path d="M{cx - 10},{BASE + 5} v-14 a10,10 0 0 1 20,0 v14z" fill="#FFE9A8" opacity=".9"/>'
    return s


def m_dome(cx, p, rng):
    dk, acc = shade(p[4], 0.75), p[5]
    s = f'<rect x="{cx - 64}" y="{BASE - 28}" width="128" height="33" fill="{dk}"/>'
    s += "".join(f'<rect x="{cx - 60 + i * 12}" y="{BASE - 24}" width="4" height="29" fill="#fff" opacity=".5"/>' for i in range(10))
    s += f'<rect x="{cx - 24}" y="{BASE - 62}" width="48" height="36" fill="{dk}"/>'
    s += f'<path d="M{cx - 28},{BASE - 62} A28,34 0 0 1 {cx + 28},{BASE - 62}z" fill="{acc}"/>'
    s += f'<rect x="{cx - 4}" y="{BASE - 106}" width="8" height="12" fill="{dk}"/><line x1="{cx}" y1="{BASE - 106}" x2="{cx}" y2="{BASE - 120}" stroke="{acc}" stroke-width="2"/><line x1="{cx - 5}" y1="{BASE - 114}" x2="{cx + 5}" y2="{BASE - 114}" stroke="{acc}" stroke-width="2"/>'
    return s


def m_temple(cx, p, rng):
    acc = p[5]
    s = f'<rect x="{cx - 72}" y="{BASE - 4}" width="144" height="9" fill="#fff" opacity=".9"/><rect x="{cx - 66}" y="{BASE - 11}" width="132" height="8" fill="#fff" opacity=".95"/>'
    s += "".join(f'<rect x="{cx - 56 + i * 22.4}" y="{BASE - 56}" width="8" height="46" fill="#fff" opacity=".95"/>' for i in range(6))
    s += f'<rect x="{cx - 64}" y="{BASE - 64}" width="128" height="9" fill="#fff"/>' + poly([(cx - 68, BASE - 64), (cx, BASE - 98), (cx + 68, BASE - 64)], acc)
    return s


def m_colosseum(cx, p, rng):
    dk, acc = shade(p[4], 0.7), p[5]
    s = f'<path d="M{cx - 82},{BASE + 5} v-62 q4,-8 14,-8 h136 q10,0 14,8 v62z" fill="{acc}"/>'
    for r in range(3):
        y = BASE - 46 + r * 18
        for i in range(9):
            x = cx - 72 + i * 16.5
            s += f'<path d="M{x:.1f},{y + 13} v-8 a4,4 0 0 1 8,0 v8z" fill="{dk}"/>'
    return s


def m_arch(cx, p, rng):
    dk, acc = shade(p[4], 0.7), p[5]
    s = f'<rect x="{cx - 76}" y="{BASE - 42}" width="152" height="47" fill="{acc}"/><rect x="{cx - 24}" y="{BASE - 86}" width="48" height="46" fill="{acc}"/>'
    s += "".join(f'<rect x="{cx - 76 + i * 10}" y="{BASE - 49}" width="6" height="8" fill="{acc}"/>' for i in range(16))
    for ax in (cx - 56, cx - 10, cx + 36):
        s += f'<path d="M{ax},{BASE + 5} v-18 a10,10 0 0 1 20,0 v18z" fill="{dk}"/>'
    s += f'<path d="M{cx - 8},{BASE - 58} v-10 a8,8 0 0 1 16,0 v10z" fill="{dk}"/>' + poly([(cx - 28, BASE - 86), (cx, BASE - 108), (cx + 28, BASE - 86)], dk)
    return s


def m_windmill(cx, p, rng):
    dk, acc = shade(p[4], 0.75), p[5]
    s = poly([(cx - 16, BASE + 5), (cx - 10, BASE - 55), (cx + 10, BASE - 55), (cx + 16, BASE + 5)], dk)
    s += poly([(cx - 13, BASE - 55), (cx, BASE - 70), (cx + 13, BASE - 55)], acc)
    s += (f'<g class="sc-spin" style="transform-origin:{cx}px {BASE - 52}px">'
          f'<rect x="{cx - 3}" y="{BASE - 52 - 52}" width="6" height="104" fill="#fff" opacity=".95"/>'
          f'<rect x="{cx - 52}" y="{BASE - 55}" width="104" height="6" fill="#fff" opacity=".95"/></g>')
    s += f'<circle cx="{cx}" cy="{BASE - 52}" r="4" fill="{acc}"/>'
    s += poly([(cx - 105, BASE + 5), (cx - 100, BASE - 35), (cx - 92, BASE - 35), (cx - 88, BASE + 5)], dk)
    s += (f'<g class="sc-spin" style="transform-origin:{cx - 96}px {BASE - 36}px;animation-duration:16s">'
          f'<rect x="{cx - 98}" y="{BASE - 36 - 30}" width="4" height="60" fill="#fff" opacity=".9"/><rect x="{cx - 126}" y="{BASE - 38}" width="60" height="4" fill="#fff" opacity=".9"/></g>')
    return s


def m_clock(cx, p, rng):
    dk, acc = shade(p[4], 0.72), p[5]
    s = f'<rect x="{cx - 70}" y="{BASE - 30}" width="80" height="35" fill="{dk}"/>'
    s += "".join(poly([(cx - 68 + i * 18, BASE - 30), (cx - 59 + i * 18, BASE - 42), (cx - 50 + i * 18, BASE - 30)], dk) for i in range(4))
    s += f'<rect x="{cx + 6}" y="{BASE - 112}" width="34" height="117" fill="{acc}"/><rect x="{cx + 2}" y="{BASE - 118}" width="42" height="10" fill="{dk}"/>'
    s += poly([(cx + 4, BASE - 112), (cx + 23, BASE - 148), (cx + 42, BASE - 112)], dk)
    s += f'<circle cx="{cx + 23}" cy="{BASE - 92}" r="11" fill="#fff" stroke="{dk}" stroke-width="2"/>'
    s += f'<line x1="{cx + 23}" y1="{BASE - 92}" x2="{cx + 23}" y2="{BASE - 99}" stroke="{dk}" stroke-width="2"/><line x1="{cx + 23}" y1="{BASE - 92}" x2="{cx + 29}" y2="{BASE - 90}" stroke="{dk}" stroke-width="2"/>'
    s += "".join(f'<rect x="{cx + 12 + i * 10}" y="{BASE - 66}" width="5" height="16" rx="2.5" fill="#FFE9A8" class="sc-lamp"/>' for i in range(3))
    return s


def m_bridge(cx, p, rng):
    dk, acc = shade(p[4], 0.72), p[5]
    s = f'<rect x="{cx - 130}" y="{BASE - 28}" width="260" height="6" fill="{dk}"/>'
    for tx in (cx - 55, cx + 47):
        s += f'<rect x="{tx}" y="{BASE - 88}" width="8" height="70" fill="{dk}"/>' + poly([(tx - 3, BASE - 88), (tx + 4, BASE - 100), (tx + 11, BASE - 88)], acc)
    s += (f'<path d="M{cx - 130},{BASE - 28} Q{cx - 95},{BASE - 36} {cx - 51},{BASE - 86} Q{cx},{BASE - 20} {cx + 51},{BASE - 86} Q{cx + 95},{BASE - 36} {cx + 130},{BASE - 28}" '
          f'stroke="{dk}" stroke-width="2.2" fill="none"/>')
    s += "".join(f'<line x1="{cx - 120 + i * 20}" y1="{BASE - 28}" x2="{cx - 120 + i * 20}" y2="{BASE - 40 + abs(i - 6) * 2}" stroke="{dk}" stroke-width="1" opacity=".6"/>' for i in range(13))
    s += f'<rect x="{cx - 130}" y="{BASE - 22}" width="260" height="30" fill="#fff" opacity=".18"/>'
    return s


def m_sail(cx, p, rng):
    dk, acc = shade(p[4], 0.72), p[5]
    s = poly([(cx - 190, BASE + 12), (cx - 190, BASE - 48), (cx - 150, BASE - 62), (cx - 108, BASE - 30), (cx - 70, BASE + 12)], shade(p[3], 0.8))
    s += poly([(cx - 190, BASE - 48), (cx - 150, BASE - 62), (cx - 140, BASE - 56), (cx - 190, BASE - 38)], "#fff", 'opacity=".25"')
    for bx, by, k, d in ((cx - 10, BASE - 8, 1.0, 0), (cx + 70, BASE - 2, 0.7, 2)):
        s += (f'<g class="sc-bob" style="animation-delay:-{d}s"><g transform="translate({bx},{by}) scale({k})">'
              f'<path d="M-22,0 L22,0 L14,9 L-14,9z" fill="{dk}"/><line x1="0" y1="0" x2="0" y2="-46" stroke="{dk}" stroke-width="2"/>'
              f'<polygon points="2,-44 2,-4 26,-4" fill="#fff"/><polygon points="-2,-38 -2,-4 -20,-4" fill="{acc}"/></g></g>')
    return s


def m_volcano(cx, p, rng):
    dk = shade(p[3], 0.55)
    s = poly([(cx - 118, BASE + 5), (cx - 22, BASE - 104), (cx + 22, BASE - 104), (cx + 118, BASE + 5)], dk)
    s += poly([(cx - 22, BASE - 104), (cx - 38, BASE - 82), (cx - 24, BASE - 88), (cx - 14, BASE - 74), (cx - 4, BASE - 90), (cx + 14, BASE - 78), (cx + 40, BASE - 84), (cx + 22, BASE - 104)], "#fff", 'opacity=".9"')
    s += f'<ellipse cx="{cx}" cy="{BASE - 104}" rx="22" ry="5" fill="#FF8A5C"/>'
    s += f'<path d="M{cx - 4},{BASE - 100} L{cx - 14},{BASE - 40}" stroke="#FF8A5C" stroke-width="3" opacity=".7" class="sc-lamp"/>'
    for i, dx in enumerate((0, 12, -10)):
        s += f'<circle class="sc-smoke" cx="{cx + dx}" cy="{BASE - 108}" r="{9 + i * 2}" fill="#fff" style="animation-delay:-{i * 2}s"/>'
    return s


def m_fjord(cx, p, rng):
    top, bot, far, mid, near, acc = p
    s = f'<path class="sc-aurora" d="M0,60 Q80,20 160,56 T320,40 T420,58 L420,90 Q330,70 250,92 T90,80 T0,96z" fill="url(#au-{{u}})"/>'
    s += peak(cx - 160, BASE - 112, 100, shade(mid, 0.95)) + peak(cx + 120, BASE - 100, 105, shade(mid, 0.85))
    s += f'<rect x="0" y="{BASE - 6}" width="{W}" height="20" fill="{shade(mid, 1.15)}" opacity=".6"/>'
    s += pines([(cx - 40, 1.1), (cx - 18, 0.9), (cx + 20, 1.2), (cx + 44, 0.9), (cx - 120, 1.0)], shade(near, 0.75))
    return s


def m_lighthouse(cx, p, rng):
    dk, acc = shade(p[4], 0.72), p[5]
    s = poly([(cx - 50, BASE + 5), (cx - 32, BASE - 22), (cx + 30, BASE - 22), (cx + 54, BASE + 5)], dk)
    s += poly([(cx - 10, BASE - 22), (cx - 6, BASE - 88), (cx + 6, BASE - 88), (cx + 10, BASE - 22)], "#fff")
    s += f'<rect x="{cx - 9}" y="{BASE - 66}" width="18" height="10" fill="{acc}"/><rect x="{cx - 8}" y="{BASE - 44}" width="16" height="9" fill="{acc}"/>'
    s += f'<rect x="{cx - 8}" y="{BASE - 100}" width="16" height="12" fill="#FFE9A8" class="sc-lamp"/>' + poly([(cx - 11, BASE - 100), (cx, BASE - 112), (cx + 11, BASE - 100)], dk)
    s += poly([(cx + 8, BASE - 96), (cx + 120, BASE - 112), (cx + 120, BASE - 76)], "#fff", 'opacity=".22" class="sc-beam"')
    return s


def m_yurt(cx, p, rng):
    dk, acc = shade(p[4], 0.72), p[5]
    s = f'<rect x="{cx - 36}" y="{BASE - 30}" width="72" height="35" fill="#fff"/>' + poly([(cx - 42, BASE - 30), (cx, BASE - 66), (cx + 42, BASE - 30)], acc)
    s += f'<rect x="{cx - 8}" y="{BASE - 20}" width="16" height="25" fill="{dk}"/><rect x="{cx - 36}" y="{BASE - 30}" width="72" height="4" fill="{acc}"/>'
    s += f'<circle cx="{cx}" cy="{BASE - 66}" r="3" fill="{dk}"/>'
    s += f'<g class="sc-bob" style="animation-duration:5s"><path d="M{cx + 80},{BASE - 70} q10,-8 20,0 q-10,-3 -20,0z" fill="{dk}"/></g>'
    return s


def m_spires(cx, p, rng):
    dk, acc = shade(p[4], 0.72), p[5]
    s = ""
    for i in range(9):
        x, h = cx - 98 + i * 21, rng.randint(22, 36)
        s += f'<rect x="{x}" y="{BASE + 5 - h}" width="18" height="{h}" fill="{dk}"/>' + poly([(x - 1, BASE + 5 - h), (x + 9, BASE - h - 7), (x + 19, BASE + 5 - h)], shade(dk, 1.35))
    for sx, h in ((cx - 55, 108), (cx + 5, 132), (cx + 62, 96)):
        top = BASE + 5 - h * 0.55
        s += f'<rect x="{sx - 8}" y="{top}" width="16" height="{h * 0.55}" fill="{dk}"/>' + poly([(sx - 10, top), (sx, BASE + 5 - h - 10), (sx + 10, top)], acc)
        s += f'<rect x="{sx - 2.5}" y="{top + 10}" width="5" height="11" rx="2.5" fill="#FFE9A8" class="sc-lamp"/>'
    return s


def m_fortress(cx, p, rng):
    dk, acc = shade(p[4], 0.72), p[5]
    s = poly([(cx - 90, BASE + 5), (cx - 55, BASE - 32), (cx + 55, BASE - 32), (cx + 90, BASE + 5)], shade(p[3], 0.8))
    s += f'<rect x="{cx - 48}" y="{BASE - 56}" width="96" height="26" fill="{dk}"/>'
    s += "".join(f'<rect x="{cx - 48 + i * 12}" y="{BASE - 62}" width="7" height="7" fill="{dk}"/>' for i in range(8))
    for tx in (cx - 60, cx + 40):
        s += f'<rect x="{tx}" y="{BASE - 78}" width="20" height="48" fill="{dk}"/>' + poly([(tx - 3, BASE - 78), (tx + 10, BASE - 100), (tx + 23, BASE - 78)], acc)
    s += f'<rect x="{cx - 12}" y="{BASE - 104}" width="24" height="74" fill="{dk}"/>' + poly([(cx - 17, BASE - 104), (cx, BASE - 138), (cx + 17, BASE - 104)], acc)
    s += f'<line x1="{cx}" y1="{BASE - 138}" x2="{cx}" y2="{BASE - 150}" stroke="{dk}" stroke-width="2"/><polygon points="{cx},{BASE - 150} {cx + 12},{BASE - 146} {cx},{BASE - 142}" fill="{acc}"/>'
    s += f'<rect x="{cx - 3}" y="{BASE - 90}" width="6" height="12" rx="3" fill="#FFE9A8" class="sc-lamp"/>'
    return s


MOTIFS = {
    "fuji": m_fuji, "alps": m_alps, "tower": m_tower, "castle": m_castle, "onion": m_onion, "mosque": m_mosque,
    "dome": m_dome, "temple": m_temple, "colosseum": m_colosseum, "arch": m_arch, "windmill": m_windmill,
    "clock": m_clock, "bridge": m_bridge, "sail": m_sail, "volcano": m_volcano, "fjord": m_fjord,
    "lighthouse": m_lighthouse, "yurt": m_yurt, "spires": m_spires, "fortress": m_fortress,
}
NO_GENERIC_MOUNTAINS = {"fuji", "alps", "fjord", "volcano"}


def _cloud(y, scale, delay, dur) -> str:
    return (f'<g class="sc-cloud" style="animation-delay:-{delay}s;animation-duration:{dur}s"><g transform="translate(0,{y}) scale({scale})" fill="#fff" opacity=".78">'
            '<ellipse cx="0" cy="0" rx="30" ry="9"/><ellipse cx="-15" cy="-6" rx="16" ry="9"/><ellipse cx="12" cy="-9" rx="19" ry="11"/></g></g>')


def scene_svg(iso: str, uid: str = "") -> str:
    motif, pal = SCENES.get(iso.upper() if iso else "", ("alps", "lavanda"))
    p = PALETTES[pal]
    top, bot, far, mid, near, acc = p
    rng = random.Random(iso or "xx")
    u = f"{(iso or 'xx').lower()}{uid}"
    cx = 262
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" class="sc-svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice" aria-hidden="true">']
    out.append(
        f'<defs><linearGradient id="sk-{u}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bot}"/></linearGradient>'
        f'<radialGradient id="su-{u}"><stop offset="0" stop-color="#fff" stop-opacity=".95"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>'
        f'<linearGradient id="au-{u}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7BFFC8" stop-opacity=".0"/><stop offset=".5" stop-color="#7BFFC8" stop-opacity=".55"/><stop offset="1" stop-color="#B38CFF" stop-opacity="0"/></linearGradient></defs>'
    )
    out.append(f'<rect width="{W}" height="{H}" fill="url(#sk-{u})"/>')
    sx, sy = rng.randint(70, 150), rng.randint(52, 78)
    out.append(f'<g class="sc-sun"><circle cx="{sx}" cy="{sy}" r="34" fill="url(#su-{u})"/><circle cx="{sx}" cy="{sy}" r="11" fill="#fff" opacity=".92"/></g>')
    # montañas lejanas
    pts = [(-20, H)] + [(x, BASE - 38 - rng.randint(8, 62)) for x in range(-20, 440, 46)] + [(440, H)]
    far_poly = poly(pts, far, 'opacity=".85"')
    out.append(f'<g class="sc-sway-slow">{far_poly}</g>')
    out.append(_cloud(68, 1.0, 0, 44) + _cloud(104, 0.7, 17, 58) + _cloud(54, 0.55, 31, 70))
    # montañas medias genéricas
    if motif not in NO_GENERIC_MOUNTAINS:
        mt = ""
        for x in (28, 118, 330, 395):
            mt += peak(x + rng.randint(-10, 10), BASE - rng.randint(48, 78), rng.randint(46, 62), mid)
        out.append(f'<g class="sc-sway">{mt}</g>')
    motif_svg = MOTIFS[motif](cx, p, rng).replace("{u}", u)
    out.append(f'<g class="sc-sway">{motif_svg}</g>')
    # primer plano
    if motif == "sail":
        seg = " t40,0" * 13
        out.append(f'<g class="sc-wave"><path d="M-40,{BASE} q20,-7 40,0{seg} V{H} H-40z" fill="{shade(near, 1.25)}"/></g>')
        out.append(f'<g class="sc-wave2"><path d="M-40,{BASE + 16} q20,-7 40,0{seg} V{H} H-40z" fill="{near}"/></g>')
    else:
        out.append(f'<path d="M0,{H} L0,{BASE + 2} Q100,{BASE - 22} 200,{BASE - 4} T400,{BASE - 8} L400,{H}z" fill="{near}"/>')
        out.append(pines([(18, 1.2), (38, 0.9), (372, 1.1), (388, 0.8)], shade(near, 0.7)))
    if motif == "windmill":
        for i in range(16):
            out.append(f'<circle cx="{rng.randint(10, 390)}" cy="{rng.randint(BASE + 8, H - 8)}" r="2.4" fill="{rng.choice(["#FF6B8B", "#FFD166", "#FF9EC4", "#fff"])}"/>')
    # partículas
    if iso == "JP":
        for i in range(16):
            out.append(f'<ellipse class="sc-petal" cx="{rng.randint(0, W)}" cy="-8" rx="3.2" ry="2" fill="#FFC2DC" style="animation-duration:{rng.randint(6, 11)}s;animation-delay:-{rng.randint(0, 10)}s"/>')
    elif pal in SNOWY:
        for i in range(16):
            out.append(f'<circle class="sc-flake" cx="{rng.randint(0, W)}" cy="-8" r="{rng.choice([1.4, 1.8, 2.3])}" fill="#fff" opacity=".85" style="animation-duration:{rng.randint(6, 12)}s;animation-delay:-{rng.randint(0, 12)}s"/>')
    out.append("</svg>")
    return "".join(out)
