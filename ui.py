"""Estilo visual (lavanda / índigo, tarjetas redondeadas) y componentes HTML con animaciones."""
from __future__ import annotations

from html import escape

import streamlit as st

import scenes

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Merriweather:wght@400;700&display=swap');
:root{--ink:#3A3578;--ink-2:#5b5890;--violet:#6C5CE7;--shadow:0 12px 36px rgba(63,59,125,.13);}
html,body,[data-testid="stApp"]{font-family:'Inter',system-ui,sans-serif;}
[data-testid="stApp"]{background:linear-gradient(180deg,#DFF1FC 0%,#EBF1FF 55%,#F3EEFF 100%);background-attachment:fixed;}
[data-testid="stHeader"]{background:transparent;}
.block-container{max-width:780px;padding-top:1.2rem;padding-bottom:7rem;}
h1,h2,h3{color:var(--ink);font-weight:800;letter-spacing:-.01em;}

/* ---------- cabecera ---------- */
.tc-top{display:flex;align-items:center;justify-content:space-between;margin:2px 0 14px;}
.tc-eyebrow{font-size:.78rem;font-weight:600;color:var(--ink-2);text-transform:uppercase;letter-spacing:.09em;}
.tc-title{font-size:2.1rem;font-weight:800;color:var(--ink);line-height:1.1;}
.tc-avatar{width:48px;height:48px;border-radius:50%;display:grid;place-items:center;color:#fff;font-weight:800;font-size:1.2rem;
  background:linear-gradient(135deg,#7C6CF0,#B8A9FF);box-shadow:var(--shadow);animation:pulse 4s ease-in-out infinite;}
.tc-hero{background:#fff;border-radius:28px;padding:20px 24px;box-shadow:var(--shadow);margin:6px 0 16px;position:relative;overflow:hidden;}
.tc-hero h2{font-family:'Merriweather',serif;font-size:1.6rem;margin:2px 0 6px;padding:0;color:var(--ink);}
.tc-meta{color:var(--ink-2);font-size:.9rem;font-weight:500;}
.tc-hero .tc-plane{position:absolute;right:22px;top:14px;font-size:2.2rem;animation:fly 5s ease-in-out infinite;}

/* ---------- tarjetas de país (animadas) ---------- */
.tc-country{position:relative;overflow:hidden;display:flex;align-items:center;gap:16px;border-radius:26px;padding:18px 20px;margin-top:10px;min-height:104px;color:#fff;
  background-size:220% 220%;animation:shift 9s ease-in-out infinite;box-shadow:var(--shadow);transition:transform .25s ease,box-shadow .25s ease;}
.tc-country:hover{transform:translateY(-4px) scale(1.01);box-shadow:0 18px 44px rgba(63,59,125,.22);}
.tc-flag{position:relative;flex:0 0 auto;width:62px;height:44px;border-radius:8px;overflow:hidden;box-shadow:0 6px 14px rgba(0,0,0,.28);
  transform-origin:left center;animation:wave 3.2s ease-in-out infinite;background:rgba(255,255,255,.3);display:grid;place-items:center;font-size:1.7rem;}
.tc-flag i{position:absolute;inset:0;background-size:cover;background-position:center;}
.tc-name{font-family:'Merriweather',serif;font-weight:700;font-size:1.12rem;line-height:1.2;}
.tc-region{font-size:.7rem;font-weight:600;opacity:.88;text-transform:uppercase;letter-spacing:.1em;margin-bottom:3px;}
.tc-float{position:absolute;right:18px;top:10px;font-size:2.7rem;filter:drop-shadow(0 6px 8px rgba(0,0,0,.22));animation:float 3.6s ease-in-out infinite;}
.tc-ghost{position:absolute;right:-10px;bottom:-26px;font-size:6.5rem;opacity:.14;transform:rotate(-12deg);}
.tc-badge{position:absolute;right:16px;bottom:12px;background:rgba(255,255,255,.28);backdrop-filter:blur(4px);border-radius:999px;padding:3px 11px;font-size:.72rem;font-weight:700;}

@keyframes shift{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
@keyframes wave{0%,100%{transform:perspective(260px) rotateY(0deg) skewY(0deg)}30%{transform:perspective(260px) rotateY(-14deg) skewY(2.5deg)}65%{transform:perspective(260px) rotateY(9deg) skewY(-2deg)}}
@keyframes float{0%,100%{transform:translateY(0) rotate(-4deg)}50%{transform:translateY(-9px) rotate(5deg)}}
@keyframes fly{0%,100%{transform:translate(0,0) rotate(-8deg)}50%{transform:translate(-14px,-8px) rotate(4deg)}}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(124,108,240,.45)}50%{box-shadow:0 0 0 10px rgba(124,108,240,0)}}
@media (prefers-reduced-motion:reduce){.tc-country,.tc-flag,.tc-float,.tc-avatar,.tc-plane{animation:none!important}}


/* ---------- paisajes animados (scenes.py) ---------- */
.sc-wrap{position:relative;overflow:hidden;border-radius:26px;box-shadow:var(--shadow);background:#b9adff;margin-top:10px;transition:transform .25s ease,box-shadow .25s ease;}
.sc-wrap:hover{transform:translateY(-3px);box-shadow:0 18px 44px rgba(63,59,125,.22);}
.sc-wrap .sc-svg{position:absolute;inset:0;width:100%;height:100%;display:block;}
.sc-scrim{position:absolute;left:0;right:0;bottom:0;height:68%;background:linear-gradient(to top,rgba(30,24,80,.66),rgba(30,24,80,0));}
.sc-text{position:absolute;left:18px;right:18px;bottom:14px;color:#fff;}
.sc-name{font-family:'Merriweather',serif;font-weight:700;font-size:1.3rem;line-height:1.15;text-shadow:0 2px 12px rgba(0,0,0,.35);}
.sc-sub{font-size:.68rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;opacity:.92;margin-bottom:2px;}
.sc-wrap .tc-flag{position:absolute;top:12px;left:12px;width:46px;height:32px;font-size:1.3rem;}
.sc-badge{position:absolute;top:12px;right:12px;background:rgba(255,255,255,.92);color:#3F3B7D;border-radius:999px;padding:3px 11px;font-size:.72rem;font-weight:700;}
.sc-cur{position:absolute;right:14px;bottom:14px;background:rgba(255,255,255,.22);backdrop-filter:blur(4px);color:#fff;border-radius:999px;padding:3px 11px;font-size:.72rem;font-weight:700;}
.sc-cloud{animation:scdrift 44s linear infinite;}
.sc-sun{animation:scsun 6s ease-in-out infinite;transform-box:fill-box;transform-origin:center;}
.sc-sway{animation:scsway 14s ease-in-out infinite alternate;}
.sc-sway-slow{animation:scsway 20s ease-in-out infinite alternate-reverse;}
.sc-flake{animation:scfall 8s linear infinite;}
.sc-petal{animation:scpetal 8s linear infinite;}
.sc-spin{animation:scspin 14s linear infinite;}
.sc-bob{animation:scbob 4s ease-in-out infinite;}
.sc-wave{animation:scwave 7s linear infinite;}
.sc-wave2{animation:scwave 10s linear infinite reverse;}
.sc-lamp{animation:sclamp 3s ease-in-out infinite;}
.sc-beam{animation:sclamp 4s ease-in-out infinite;}
.sc-smoke{animation:scsmoke 5s ease-out infinite;transform-box:fill-box;transform-origin:center;}
.sc-aurora{animation:scaurora 8s ease-in-out infinite alternate;}
@keyframes scdrift{from{transform:translateX(-90px)}to{transform:translateX(490px)}}
@keyframes scsun{0%,100%{transform:scale(1);opacity:.95}50%{transform:scale(1.1);opacity:1}}
@keyframes scsway{from{transform:translateX(-5px)}to{transform:translateX(5px)}}
@keyframes scfall{0%{transform:translate(0,0)}50%{transform:translate(8px,125px)}100%{transform:translate(-4px,255px)}}
@keyframes scpetal{0%{transform:translate(0,0) rotate(0deg)}50%{transform:translate(22px,125px) rotate(180deg)}100%{transform:translate(-10px,255px) rotate(360deg)}}
@keyframes scspin{to{transform:rotate(360deg)}}
@keyframes scbob{0%,100%{transform:translateY(0)}50%{transform:translateY(3px)}}
@keyframes scwave{from{transform:translateX(0)}to{transform:translateX(-80px)}}
@keyframes sclamp{0%,100%{opacity:.55}50%{opacity:1}}
@keyframes scsmoke{0%{transform:translateY(0) scale(.6);opacity:.7}100%{transform:translateY(-55px) scale(1.7);opacity:0}}
@keyframes scaurora{from{opacity:.45;transform:translateX(-12px)}to{opacity:1;transform:translateX(12px)}}
@media (prefers-reduced-motion:reduce){.sc-svg *{animation:none!important}}


/* ---------- estilo plantilla: barra superior, pestañas de texto, carrusel, hoja de detalle, barra inferior ---------- */
.tc-bar{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;margin:2px 0 14px;}
.tc-bar-l{font-size:.78rem;font-weight:700;color:var(--ink-2);}
.tc-bartitle{font-family:'Merriweather',serif;font-size:1.55rem;font-weight:700;color:#1f1d4d;text-align:center;}
.tc-bar .tc-avatar{justify-self:end;width:42px;height:42px;font-size:1.05rem;}

.st-key-view [role="radiogroup"]{background:transparent!important;border:none!important;gap:2px;padding:0;}
.st-key-view button[data-variant="segmented_control"]{background:transparent!important;border:none!important;color:#2B2A55!important;font-weight:500;padding:6px 10px;border-radius:0!important;box-shadow:none!important;}
.st-key-view button[data-selected="true"]{color:#3F3B7D!important;font-weight:800;border-bottom:2px solid #6C5CE7!important;}

.tc-rowtitle{display:flex;justify-content:space-between;align-items:baseline;margin:14px 2px 2px;}
.tc-rowtitle b{font-family:'Merriweather',serif;font-size:1.05rem;color:#1f1d4d;}
.tc-carousel{display:flex;gap:14px;overflow-x:auto;scroll-snap-type:x mandatory;padding:6px 2px 12px;scrollbar-width:none;-webkit-overflow-scrolling:touch;}
.tc-carousel::-webkit-scrollbar{display:none;}
.tc-carousel .sc-wrap{flex:0 0 78%;scroll-snap-align:center;margin-top:0;}
.sc-heart{position:absolute;right:14px;bottom:14px;width:30px;height:30px;border-radius:50%;background:#fff;display:grid;place-items:center;font-size:1rem;color:#9aa3bd;box-shadow:0 4px 10px rgba(0,0,0,.18);}
.sc-heart.on{color:#FF4D8D;}
.sc-wrap.flat{border-bottom-left-radius:0;border-bottom-right-radius:0;margin-top:4px;box-shadow:none;}
.sc-wrap.flat:hover{transform:none;box-shadow:none;}
.tc-sheet{position:relative;background:#fff;border-radius:28px;margin-top:-28px;padding:22px 22px 14px;box-shadow:0 -6px 24px rgba(63,59,125,.10),var(--shadow);margin-bottom:12px;}
.tc-sheet-title{font-family:'Merriweather',serif;font-weight:700;font-size:1.55rem;color:#1f1d4d;line-height:1.2;}
.tc-sheet-loc{font-size:.8rem;font-weight:600;color:#4a4880;margin:4px 0 14px;}
.tc-sheet-row{display:flex;align-items:baseline;gap:8px;margin-bottom:12px;}
.tc-price{font-size:1.9rem;font-weight:800;color:#3F3B7D;}
.tc-price-sub{font-size:.85rem;font-weight:700;color:#3F3B7D;}
.tc-sheet h4{font-family:'Merriweather',serif;font-size:1.05rem;color:#1f1d4d;margin:6px 0 4px;padding:0;}
.tc-sheet p{font-family:'Merriweather',serif;font-size:.88rem;line-height:1.7;color:#2B2A55;margin:0;}
.tc-cover{background:#fff;border-radius:0 0 28px 28px;padding:22px 24px 18px;box-shadow:var(--shadow);margin-top:-28px;position:relative;margin-bottom:14px;}
.tc-cover h2{font-family:'Merriweather',serif;font-size:1.7rem;line-height:1.2;color:#1f1d4d;margin:0 0 8px;padding:0;}
.tc-cover p{font-family:'Merriweather',serif;font-size:.85rem;line-height:1.7;color:#2B2A55;margin:0;}

/* barra de navegación inferior flotante (píldora) */
.st-key-section{position:fixed!important;left:50%;bottom:16px;transform:translateX(-50%);z-index:1000;width:min(94vw,440px)!important;background:#fff;border-radius:999px;box-shadow:0 14px 40px rgba(63,59,125,.24);padding:7px 8px;}
.st-key-section [data-testid="stWidgetLabel"]{display:none;}
.st-key-section [data-testid="stButtonGroup"]{width:100%!important;}
.st-key-section [role="radiogroup"]{display:flex;width:100%!important;max-width:none!important;gap:2px;background:transparent!important;border:none!important;padding:0;}
.st-key-section button[data-variant="segmented_control"]{flex:1 1 0;min-width:0;white-space:nowrap;border:none!important;background:transparent!important;color:#8c97b8!important;font-size:.72rem;font-weight:600;border-radius:999px!important;padding:8px 2px;box-shadow:none!important;}
.st-key-section button[data-selected="true"]{background:#EEF0FF!important;color:#3F3B7D!important;font-weight:800;}
[data-testid="stChatInput"]{margin-bottom:78px;}
.stButton button{min-height:2.3rem;padding:.2rem .7rem;font-size:.85rem;}

/* ---------- botones y controles ---------- */
button[kind="primary"],[data-testid="stBaseButton-primary"]{background:#3F3B7D!important;border:none!important;color:#fff!important;border-radius:999px!important;font-weight:600!important;}
button[kind="secondary"],[data-testid="stBaseButton-secondary"]{background:#fff!important;color:var(--ink)!important;border:1px solid rgba(63,59,125,.18)!important;border-radius:999px!important;font-weight:600!important;}
[data-testid="stBaseButton-primary"]:hover,[data-testid="stBaseButton-secondary"]:hover{transform:translateY(-1px);box-shadow:0 6px 16px rgba(63,59,125,.18);}
[data-testid="stLinkButton"] a{border-radius:999px!important;font-weight:600!important;}
[data-baseweb="input"],[data-baseweb="select"]>div,[data-testid="stTextInput"] input{border-radius:16px!important;}
[data-testid="stChatMessage"]{background:#fff;border-radius:22px;box-shadow:0 6px 22px rgba(63,59,125,.09);padding:.9rem 1.1rem;}
[data-testid="stChatInput"]{border-radius:999px;}
[data-testid="stDataFrame"],[data-testid="stDataEditor"]{border-radius:18px;overflow:hidden;box-shadow:0 6px 22px rgba(63,59,125,.09);}
[data-testid="stMetric"]{background:#fff;border-radius:20px;padding:12px 16px;box-shadow:0 6px 22px rgba(63,59,125,.09);}
.tc-section{font-family:'Merriweather',serif;font-weight:700;color:var(--ink);font-size:1.15rem;margin:18px 0 4px;}

/* ---------- marca ---------- */
.tc-brand{text-align:center;margin:28px 0 8px;font-size:.78rem;color:var(--ink-2);line-height:1.6;}
.tc-brand b{font-family:'Merriweather',serif;color:var(--ink);font-size:.9rem;letter-spacing:.01em;}
.tc-brand a{color:var(--violet);font-weight:700;text-decoration:none;}
.tc-brand a:hover{text-decoration:underline;}
.tc-brand .dot{opacity:.5;margin:0 .35em;}

/* ---------- celular ---------- */
/* botón de la barra lateral (Ajustes): siempre visible, redondo y fácil de tocar */
[data-testid="stExpandSidebarButton"],[data-testid="stSidebarCollapsedControl"] button{
  position:fixed!important;top:34px;left:14px;z-index:1001;width:44px;height:44px;border-radius:50%!important;
  background:#fff!important;box-shadow:0 6px 18px rgba(63,59,125,.20);display:grid;place-items:center;
  font-size:0!important;color:transparent!important;overflow:hidden;}
[data-testid="stExpandSidebarButton"] *,[data-testid="stSidebarCollapsedControl"] button *{display:none!important;}
[data-testid="stExpandSidebarButton"]::after,[data-testid="stSidebarCollapsedControl"] button::after{content:"⚙️";font-size:1.3rem;color:var(--ink);}
[data-testid="stExpandSidebarButton"]:active{transform:scale(.94);}
[data-testid="stHeader"]{pointer-events:none;}
[data-testid="stHeader"] button,[data-testid="stHeader"] a{pointer-events:auto;}

/* en pantallas táctiles no hay "hover": evita que las tarjetas se queden levantadas después de tocar */
@media (hover:none){
  .sc-wrap:hover,.tc-country:hover{transform:none;box-shadow:var(--shadow);}
  [data-testid="stBaseButton-primary"]:hover,[data-testid="stBaseButton-secondary"]:hover{transform:none;box-shadow:none;}
}

@media (max-width:640px){
  .block-container{padding-left:1rem;padding-right:1rem;padding-top:1.2rem;}
  /* el botón ⚙️ ocupa el lugar del nombre del agente en la cabecera */
  .tc-bar-l{visibility:hidden;}
  /* botones con tamaño táctil (44px) */
  .stButton button,[data-testid="stLinkButton"] a,[data-testid="stPopover"] button{min-height:2.75rem;font-size:.92rem;}
  .st-key-section button[data-variant="segmented_control"]{min-height:2.7rem;}
  /* selector de viaje + "Nuevo" en una sola fila */
  [data-testid="stHorizontalBlock"]:has(.st-key-trip_slug){flex-wrap:nowrap!important;gap:.5rem!important;}
  [data-testid="stHorizontalBlock"]:has(.st-key-trip_slug)>[data-testid="stColumn"]{min-width:0!important;}
  /* título y texto un poco más compactos */
  .tc-bartitle{font-size:1.35rem;}
  .tc-sheet-title{font-size:1.4rem;}
  /* mensajes del chat más anchos */
  [data-testid="stChatMessage"]{padding:.75rem .85rem;}
  /* pestañas de la ficha con desplazamiento horizontal suave */
  [data-baseweb="tab-list"]{overflow-x:auto;scrollbar-width:none;}
  [data-baseweb="tab-list"]::-webkit-scrollbar{display:none;}
  [data-baseweb="tab"]{white-space:nowrap;padding-left:.7rem;padding-right:.7rem;}
}
@media (max-width:360px){
  .st-key-section button[data-variant="segmented_control"]{font-size:.66rem;}
  .tc-bartitle{font-size:1.2rem;}
}
/* iPhone con muesca: respeta la zona segura de abajo */
@supports (padding:max(0px)){
  .st-key-section{bottom:max(16px,calc(env(safe-area-inset-bottom) + 8px));}
  [data-testid="stChatInput"]{margin-bottom:calc(78px + env(safe-area-inset-bottom));}
}
</style>
"""

GRADIENTS = [
    "linear-gradient(120deg,#6C5CE7,#A99BFF,#6C5CE7)",
    "linear-gradient(120deg,#4F7CE0,#9ED0F5,#4F7CE0)",
    "linear-gradient(120deg,#8A5FD0,#E3B5F0,#8A5FD0)",
    "linear-gradient(120deg,#3FA3A5,#A5E0D5,#3FA3A5)",
    "linear-gradient(120deg,#3F3B7D,#7C6CF0,#3F3B7D)",
    "linear-gradient(120deg,#E08A6C,#F7C8A8,#E08A6C)",
]


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


# Marca personal (cámbiala aquí si quieres otro nombre, enlace o lema)
BRAND_NAME = "Arnoldo Cuéllar"
BRAND_URL = "https://github.com/Arnoldzzz21"


def brand_footer(sidebar: bool = False) -> None:
    """Firma discreta al final de la página (o en la barra lateral)."""
    html = (
        f'<div class="tc-brand">✈️ <b>{escape(BRAND_NAME)}</b><br>'
        f'<a href="{escape(BRAND_URL)}" target="_blank" rel="noopener noreferrer">GitHub</a></div>'
    )
    if sidebar:
        st.sidebar.markdown(html, unsafe_allow_html=True)
    else:
        st.markdown(html, unsafe_allow_html=True)


def top_header(agent_name: str, title: str = "Descubrir") -> None:
    initial = escape((agent_name.strip() or "N")[0].upper())
    st.markdown(
        f'<div class="tc-bar"><div class="tc-bar-l">✈️ {escape(agent_name)}</div><div class="tc-bartitle">{escape(title)}</div><div class="tc-avatar">{initial}</div></div>',
        unsafe_allow_html=True,
    )


def trip_hero(name: str, n_countries: int, n_stops: int, n_places: int) -> None:
    st.markdown(
        f'<div class="tc-hero"><span class="tc-plane">✈️</span><div class="tc-eyebrow">Carpeta del viaje</div>'
        f'<h2>{escape(name)}</h2>'
        f'<div class="tc-meta">{n_countries} países · {n_stops} paradas · {n_places} lugares guardados</div></div>',
        unsafe_allow_html=True,
    )


def section_title(text: str) -> None:
    st.markdown(f'<div class="tc-section">{escape(text)}</div>', unsafe_allow_html=True)


def _flag(c) -> str:
    if not c.iso:
        return '<div class="tc-flag">🏳️</div>'
    return f'<div class="tc-flag">{c.flag_emoji}<i style="background-image:url(https://flagcdn.com/w160/{c.iso.lower()}.png)"></i></div>'


def _scene_html(c, in_trip: bool, height: int, big: bool, uid: str, text: bool, flat: bool, heart: bool) -> str:
    badge = '<span class="sc-badge">✓ En el viaje</span>' if (in_trip and not heart) else ""
    cur = f'<span class="sc-cur">{escape(c.display_currency)}</span>' if (c.currency and text and not heart) else ""
    name_size = "1.7rem" if big else "1.3rem"
    label = (f'<div class="sc-text"><div class="sc-sub">{escape(c.subregion)}</div><div class="sc-name" style="font-size:{name_size}">{escape(c.es)}</div></div>' if text else "")
    hrt = f'<span class="sc-heart{" on" if in_trip else ""}">{"♥" if in_trip else "♡"}</span>' if heart else ""
    return (f'<div class="sc-wrap{" flat" if flat else ""}" style="height:{height}px">{scenes.scene_svg(c.iso, uid)}<div class="sc-scrim"></div>'
            f'{_flag(c)}{badge}{label}{cur}{hrt}</div>')


def scene_card(c, in_trip: bool = False, height: int = 160, big: bool = False, uid: str = "", text: bool = True, flat: bool = False) -> None:
    """Tarjeta con el paisaje animado del país, bandera, nombre y moneda."""
    st.markdown(_scene_html(c, in_trip, height, big, uid, text, flat, False), unsafe_allow_html=True)


def carousel(items: list, title: str) -> None:
    """Carrusel horizontal con desplazamiento táctil; items = [(country, in_trip)]."""
    cards = "".join(_scene_html(c, inside, 200, True, f"c{i}", True, False, True) for i, (c, inside) in enumerate(items))
    st.markdown(f'<div class="tc-rowtitle"><b>{escape(title)}</b></div><div class="tc-carousel">{cards}</div>', unsafe_allow_html=True)


def row_title(title: str) -> None:
    st.markdown(f'<div class="tc-rowtitle"><b>{escape(title)}</b></div>', unsafe_allow_html=True)


def detail_header(c, in_trip: bool, description: str) -> None:
    """Pantalla de detalle: paisaje arriba y hoja blanca superpuesta con título, moneda y descripción."""
    st.markdown(
        _scene_html(c, in_trip, 250, True, "det", False, True, False)
        + f'<div class="tc-sheet"><div class="tc-sheet-title">{escape(c.es)}</div>'
        f'<div class="tc-sheet-loc">📍 {escape(c.subregion)} · {escape(c.region)}</div>'
        f'<div class="tc-sheet-row"><span class="tc-price">{escape(c.display_currency or "—")}</span><span class="tc-price-sub">/ moneda de los precios</span></div>'
        f'<h4>Descripción</h4><p>{escape(description)}</p></div>',
        unsafe_allow_html=True,
    )


def cover(iso: str, title: str, body: str) -> None:
    """Portada de bienvenida: ilustración con esquinas redondeadas y texto debajo."""
    st.markdown(
        f'<div class="sc-wrap flat" style="height:260px;margin-top:0">{scenes.scene_svg(iso, "cov")}<div class="sc-scrim" style="height:30%"></div></div>'
        f'<div class="tc-cover"><h2>{escape(title)}</h2><p>{escape(body)}</p></div>',
        unsafe_allow_html=True,
    )


def hero_scene(iso: str, eyebrow: str, title: str, meta: str, height: int = 210) -> None:
    """Portada: paisaje animado grande con el título del viaje."""
    st.markdown(
        f'<div class="sc-wrap" style="height:{height}px;margin-top:4px;margin-bottom:16px">{scenes.scene_svg(iso, "hero")}<div class="sc-scrim"></div>'
        f'<div class="sc-text"><div class="sc-sub">{escape(eyebrow)}</div><div class="sc-name" style="font-size:1.8rem">{escape(title)}</div>'
        f'<div style="font-size:.85rem;opacity:.92;margin-top:4px">{escape(meta)}</div></div></div>',
        unsafe_allow_html=True,
    )
