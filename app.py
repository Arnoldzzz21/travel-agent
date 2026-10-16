"""Agente de viajes personal — app Streamlit (chat + mapa + ruta por carpetas)."""
from __future__ import annotations

import io
import os
import unicodedata
from pathlib import Path

import anthropic
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import agent
import ficha as ficha_mod
import gemini as gem
import tools as T
import exports
import plan
import ui
from countries import SUBREGIONS, load_countries
from storage import ROUTE_COLS, TripStore, normalize_route

st.set_page_config(page_title="Nómada · Arnoldo Cuéllar", page_icon="🧭", layout="centered", initial_sidebar_state="collapsed")
ui.inject_css()

ROOT = Path(os.environ.get("VIAJES_DIR", Path(__file__).parent / "viajes"))
store = TripStore(ROOT)
cfg = store.load_config()


@st.cache_resource
def get_geo(path: str) -> T.Geocoder:
    return T.Geocoder(path)


geo = get_geo(str(ROOT / "_geocache.json"))
COUNTRIES = load_countries()
SECTIONS = ["🧭 Inicio", "🗓️ Ruta", "🗺️ Mapa", "💬 Chat"]
MODE_LABELS = {"🚆 Transporte público": "transit", "🚗 Auto": "driving", "🚶 A pie": "walking", "🚲 Bici": "bicycling"}
CAT_COLORS = {"comida": "#E67E22", "turismo": "#6C5CE7", "transporte": "#2D98DA", "hospedaje": "#20A39E", "compras": "#D6336C", "otro": "#868E96"}


# ============================================================ utilidades
ENGINES = {"✨ Gemini (gratis)": "gemini", "🧠 Claude (API de pago)": "claude"}
ENGINE_NAME = {"gemini": "Gemini", "claude": "Claude", "tavily": "Tavily"}
KEY_SPEC = {  # motor -> (campo de la barra lateral, variables de entorno / secretos)
    "gemini": ("gemini_key_input", ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
    "claude": ("api_key_input", ("ANTHROPIC_API_KEY",)),
    "tavily": ("tavily_key_input", ("TAVILY_API_KEY",)),  # opcional: búsqueda web gratis (1,000 al mes)
}


def _env_key(engine: str) -> str | None:
    """Clave del entorno o de los secretos de Streamlit (no la escrita en la barra lateral)."""
    for name in KEY_SPEC[engine][1]:
        v = os.environ.get(name)
        if not v:
            try:
                v = st.secrets.get(name)
            except Exception:
                v = None
        if v:
            return str(v)
    return None


def get_api_key(engine: str | None = None) -> str | None:
    engine = engine or cfg["engine"]
    return st.session_state.get(KEY_SPEC[engine][0]) or _env_key(engine) or None


def _keep_key(field: str) -> None:
    """Copia la clave escrita a una variable que no se borra al cambiar de motor (Streamlit olvida los campos que no se dibujan)."""
    st.session_state[field] = st.session_state.get("_in_" + field, "")


def make_client(engine: str, key: str, timeout: int = 180):
    if engine == "gemini":
        chat = st.session_state.get("chat") or {}
        return gem.GeminiClient(key, timeout=timeout, tavily_key=get_api_key("tavily"), search_off=bool(chat.get("search_off")))
    return anthropic.Anthropic(api_key=key, max_retries=2, timeout=timeout)


def active_model() -> str:
    return cfg["gemini_model"] if cfg["engine"] == "gemini" else cfg["model"]


def bump(name: str) -> None:
    st.session_state[name] = st.session_state.get(name, 0) + 1


def toggle_country(slug: str, es: str) -> None:
    store.toggle_country(slug, es)


def create_trip() -> None:
    name = st.session_state.get("new_trip_name", "").strip()
    if name:
        st.session_state["trip_slug"] = store.create(name)
        st.session_state["new_trip_name"] = ""


def delete_trip(slug: str) -> None:
    """Borra la carpeta del viaje (ruta, lugares, notas). Se pide confirmación antes en la interfaz."""
    store.delete(slug)
    st.session_state.pop("trip_slug", None)
    st.session_state["del_ok"] = False
    if (st.session_state.get("chat") or {}).get("slug") == slug:
        st.session_state.pop("chat", None)
    for k in ("route_ver", "places_ver"):
        bump(k)


def restore_trip() -> None:
    """Crea un viaje nuevo a partir de un respaldo .zip subido por la persona."""
    f = st.session_state.get(f"restore_file_{st.session_state.get('restore_ver', 0)}")
    if f is None:
        return
    try:
        st.session_state["trip_slug"] = store.import_zip(f.getvalue())
        st.session_state["restore_msg"] = ("ok", "Viaje restaurado como una carpeta nueva.")
        for k in ("route_ver", "places_ver"):
            bump(k)
    except ValueError as e:
        st.session_state["restore_msg"] = ("err", str(e))
    bump("restore_ver")


def send_suggestion(suggestions: dict) -> None:
    """Un chip del chat envía su mensaje y queda desmarcado."""
    pick = st.session_state.get("chat_pills")
    if pick in suggestions:
        st.session_state["pending_prompt"] = suggestions[pick]
    st.session_state["chat_pills"] = None


def pick_country() -> None:
    """Al elegir un país en el buscador se abre su ficha y el buscador queda listo para otra búsqueda."""
    iso = st.session_state.get("country_pick")
    if iso:
        st.session_state["ficha_iso"] = iso
    st.session_state["country_pick"] = None


def stop_query(row) -> str:
    return ", ".join(x for x in (str(row["Ciudad"]).strip(), str(row["País"]).strip()) if x)


def clean_none(df: pd.DataFrame) -> pd.DataFrame:
    return df.astype(object).where(pd.notna(df), None)


# ============================================================ sidebar
def sidebar(slug: str | None) -> None:
    changed = False
    with st.sidebar:
        st.header("⚙️ Ajustes")
        name = st.text_input("Nombre de tu agente", cfg["agent_name"])
        eng_labels = list(ENGINES)
        eng_label = st.radio("Motor del chat", eng_labels, index=list(ENGINES.values()).index(cfg["engine"]) if cfg["engine"] in ENGINES.values() else 0,
                             help="Gemini tiene capa gratuita (incluye búsqueda en Google). Claude necesita crédito de API.")
        engine = ENGINES[eng_label]
        new = {"agent_name": name.strip() or "Nómada", "engine": engine}
        if engine == "gemini":
            new["gemini_model"] = gem.DEFAULT_MODEL
            st.caption("Modelo: Gemini 3.5 Flash-Lite (gratis).")
            searches = st.slider("Búsquedas web por respuesta", 0, 6, min(int(cfg["max_searches"]), 6), help="Necesitan la clave gratuita de Tavily (abajo). Sin ella, Gemini responde con las fichas base y Wikivoyage. 0 las desactiva.")
        else:
            labels, ids = list(agent.MODELS), list(agent.MODELS.values())
            label = st.selectbox("Modelo de Claude", labels, index=ids.index(cfg["model"]) if cfg["model"] in ids else 0)
            new["model"] = agent.MODELS[label]
            searches = st.slider("Búsquedas web por respuesta", 0, 10, int(cfg["max_searches"]), help="Cada búsqueda web se cobra aparte. 0 las desactiva.")
            new["ficha_searches"] = st.slider("Búsquedas web por ficha de país", 2, 15, int(cfg["ficha_searches"]), help="La ficha se guarda; solo se vuelve a gastar al actualizarla.")
        new["max_searches"] = searches
        new["history_turns"] = st.slider("Memoria del chat (tus últimos mensajes)", 2, 20, int(cfg["history_turns"]), help="Menos memoria = respuestas más enfocadas y menos consumo.")
        if any(cfg.get(k) != v for k, v in new.items()):
            cfg.update(new)
            store.save_config(cfg)
            changed = True

        st.divider()
        field = KEY_SPEC[engine][0]
        if _env_key(engine):
            st.caption(f"🔑 Clave de {ENGINE_NAME[engine]} cargada desde el entorno.")
        elif engine == "gemini":
            st.text_input("Clave de Gemini (solo esta sesión)", type="password", key="_in_" + field, value=st.session_state.get(field, ""), on_change=_keep_key, args=(field,), help="Gratis en aistudio.google.com/apikey (Get API key). No la compartas con nadie.")
        else:
            st.text_input("Clave de Anthropic (solo esta sesión)", type="password", key="_in_" + field, value=st.session_state.get(field, ""), on_change=_keep_key, args=(field,), help="Se crea en console.anthropic.com y requiere saldo. La suscripción gratuita de claude.ai no incluye API.")
        if engine == "gemini":
            st.caption("🔒 En el plan gratis, Google puede usar lo que envíes para mejorar sus productos: no escribas datos personales sensibles.")
            with st.expander("🔎 Búsqueda web gratis (opcional)"):
                st.caption("Gemini 3 ya no incluye búsqueda de Google gratis. Con una clave gratuita de Tavily (tavily.com, 1,000 búsquedas al mes) el chat y las fichas pueden buscar precios actuales.")
                if _env_key("tavily"):
                    st.caption("🔑 Clave de Tavily cargada desde el entorno.")
                else:
                    st.text_input("Clave de Tavily (solo esta sesión)", type="password", key="_in_tavily_key_input", value=st.session_state.get("tavily_key_input", ""), on_change=_keep_key, args=("tavily_key_input",))
        if st.button("🧹 Vaciar caché de ubicaciones", width="stretch"):
            geo.clear()
            st.toast("Caché de ubicaciones vaciado")
        chat = st.session_state.get("chat")
        if chat:
            st.caption(f"Uso en esta conversación: {chat['in']:,} tokens de entrada · {chat['out']:,} de salida · {chat['searches']} búsquedas web")
        st.divider()
        ui.brand_footer(sidebar=True)
    if changed:
        st.rerun()


# ============================================================ pantalla de bienvenida
def welcome() -> None:
    ui.top_header(cfg["agent_name"], "Bienvenido")
    ui.cover("JP", "Tu próximo viaje, a tu manera", "Crea una carpeta por viaje o ciudad (Madrid, Japón, Europa 2027…). Ahí se guardan tu ruta, tus lugares y tus notas, y tu agente te ayuda a planearlo.")
    st.text_input("Nombre del viaje", key="new_trip_name", placeholder="Ej. Madrid")
    st.button("¡Vamos!  →", type="primary", on_click=create_trip)
    ui.brand_footer()


# ============================================================ Descubrir
def open_ficha(iso: str) -> None:
    st.session_state["ficha_iso"] = iso


def close_ficha() -> None:
    st.session_state.pop("ficha_iso", None)


def _sort_key(c) -> str:
    return unicodedata.normalize("NFKD", c.es).encode("ascii", "ignore").decode().lower()


def _country_label(c) -> str:
    ascii_es = unicodedata.normalize("NFKD", c.es).encode("ascii", "ignore").decode()
    parts = [f"{c.flag_emoji} {c.es}"]
    if c.en.lower() != c.es.lower():
        parts.append(c.en)
    if ascii_es.lower() != c.es.lower():
        parts.append(ascii_es)  # para que «espana» o «japon» (sin tilde) también aparezcan
    return " · ".join(parts)


COUNTRY_LABEL = {c.iso: _country_label(c) for c in COUNTRIES}


def page_discover(slug: str, meta: dict, route: pd.DataFrame, places: list[dict]) -> None:
    iso = st.session_state.get("ficha_iso")
    if iso:
        page_ficha(slug, meta, iso)
        return
    selected = set(meta.get("paises", []))

    if not selected and route.empty:
        with st.container(border=True):
            st.markdown("**Cómo usar Nómada en 4 pasos**")
            st.markdown("1. **Inicio**: busca un país, mira su ficha (transporte, pagos, precios) y toca **＋ Agregar**.\n"
                        "2. **Ruta**: escribe tus ciudades o pueblos en orden, con fechas y hotel.\n"
                        "3. **Mapa**: ubica las paradas y ábrelas en **Google Maps**, **Street View** o **My Maps**.\n"
                        "4. **Chat**: pídele a tu agente rutas, horarios y precios.")
    view = st.segmented_control("Ver", ["Todos", "Mis países", "Europa", "Asia"], default="Todos", key="view", label_visibility="collapsed") or "Todos"
    zone = "Todas"
    if view in ("Europa", "Asia"):
        zones = sorted({c.subregion for c in COUNTRIES if c.region == view}, key=lambda z: list(SUBREGIONS).index(z) if z in SUBREGIONS else 99)
        zone = st.selectbox("Zona", ["Todas"] + zones, key=f"zone_{view}")
    st.selectbox("Buscar país", [c.iso for c in sorted(COUNTRIES, key=_sort_key)], index=None, format_func=lambda i: COUNTRY_LABEL[i],
                 placeholder="🔎 Escribe un país (ej. Portugal) y tócalo…", label_visibility="collapsed", key="country_pick", on_change=pick_country)
    q = ""

    items = [
        c for c in COUNTRIES
        if (view == "Todos" or (view == "Mis países" and c.es in selected) or c.region == view)
        and (zone == "Todas" or c.subregion == zone)
        and (not q or q in c.es.lower() or q in c.en.lower())
    ]
    items.sort(key=_sort_key)

    if view == "Todos" and not q:  # carrusel de destacados: primero tus países
        by_iso = {c.iso: c for c in COUNTRIES}
        feat = [c for c in COUNTRIES if c.es in selected]
        for code in ("JP", "FR", "IT", "ES", "CH", "NO", "IS", "GR"):
            if len(feat) >= 6:
                break
            if code in by_iso and by_iso[code] not in feat:
                feat.append(by_iso[code])
        ui.carousel([(c, c.es in selected) for c in feat[:8]], "Tus países" if selected else "Destacados")

    r1, r2 = st.columns([3, 2], vertical_alignment="center")
    with r1:
        ui.row_title(f"{'Mis países' if view == 'Mis países' else 'Recomendados'} ({len(items)})")
    limited = view == "Todos" and not q
    show_all = r2.toggle("Ver todos", value=False, key="show_all") if limited else True
    if limited and not show_all:
        items = items[:12]
    if view == "Mis países" and not items:
        st.info("Aún no agregaste países a este viaje. Elige algunos en «Todos».")
    cols = st.columns(2)
    for i, c in enumerate(items):
        with cols[i % 2]:
            inside = c.es in selected
            ui.scene_card(c, inside, height=170, uid=f"d{i}")
            b1, b2 = st.columns(2)
            b1.button("Ver ficha", key=f"f_{c.iso}", on_click=open_ficha, args=(c.iso,), width="stretch")
            b2.button("Quitar" if inside else "＋ Agregar", key=f"c_{c.iso}", on_click=toggle_country, args=(slug, c.es), type="primary" if inside else "secondary", width="stretch")
    if not items and view != "Mis países":
        st.info("No encontré países con ese filtro.")


def _s(x) -> str:
    return "" if x is None else str(x).strip()


def page_ficha(slug: str, meta: dict, iso: str) -> None:
    c = next((x for x in COUNTRIES if x.iso == iso), None)
    if c is None:
        close_ficha()
        return
    inside = c.es in set(meta.get("paises", []))
    st.button("← Volver a países", on_click=close_ficha, key="fic_back")
    engine = cfg["engine"]
    key = get_api_key()
    ficha = store.load_ficha(iso)
    desc = _s((ficha or {}).get("resumen")) if ficha and not ficha.get("_sin_formato") else ""
    ui.detail_header(c, inside, desc or f"Consulta transporte, tarjetas y pases para turistas y residentes, formas de pago y precios típicos de {c.es}. Los precios van en {c.display_currency}.")
    b1, b2 = st.columns(2)
    b1.button("Quitar del viaje" if inside else "＋ Agregar al viaje", key="fic_toggle", on_click=toggle_country, args=(slug, c.es), type="primary" if inside else "secondary", width="stretch")
    go = b2.button("🔄 Actualizar con la web" if ficha else "🔎 Consultar precios y transporte", key="fic_go", width="stretch", disabled=not key)
    if not key:
        st.caption(f"Para buscar en la web pega tu clave de {ENGINE_NAME[engine]} en ⚙️ Ajustes." + (" Es gratis en aistudio.google.com/apikey." if engine == "gemini" else ""))
    if go:
        with st.spinner(f"Buscando transporte, tarjetas y precios de {c.es} con {ENGINE_NAME[engine]}… (puede tardar 1–2 minutos)"):
            try:
                if engine == "gemini":
                    ficha = gem.generate_ficha(make_client(engine, key, 300), cfg["gemini_model"], c)
                else:
                    ficha = ficha_mod.generate_ficha(make_client(engine, key, 300), cfg["model"], c, int(cfg["ficha_searches"]))
                    ficha["_motor"] = "claude"
                store.save_ficha(iso, ficha)
            except gem.GeminiError as e:
                st.error(gem.friendly(e))
            except anthropic.AuthenticationError:
                st.error("La clave de Anthropic no es válida.")
            except anthropic.APIError as e:
                st.error(f"No pude consultar la ficha: {e}")
    if ficha:
        render_ficha(c, ficha)
    else:
        st.info(f"Aún no hay ficha de {c.es}. Pulsa «Consultar» para buscar transporte, tarjetas de turista y residente, formas de pago y precios típicos (en {c.display_currency}).")


def render_ficha(c, f: dict) -> None:
    if f.get("_sin_formato"):
        st.warning("No pude estructurar la respuesta; esto es lo que encontré:")
        st.markdown(_s(f.get("resumen")))
        return
    mon = f.get("moneda") or {}
    if f.get("_estatica"):
        st.caption("📚 Ficha base de la app, investigada en guías y sitios oficiales. Puedes actualizarla con la web.")
    elif f.get("_sin_busqueda"):
        st.warning("Esta ficha se armó SIN búsqueda web (con Wikivoyage y el conocimiento de Gemini): todos los precios son aproximados. Para precios actuales agrega la clave gratuita de Tavily en ⚙️ Ajustes y pulsa Actualizar.")
    elif f.get("_motor"):
        st.caption(f"🤖 Actualizada con búsqueda web usando {ENGINE_NAME.get(f['_motor'], f['_motor'])}.")
    st.caption(f"Consultado el {_s(f.get('fecha_consulta'))} · Moneda local: {_s(mon.get('codigo_local')) or c.currency} · Precios en: {_s(mon.get('mostrada_en')) or c.display_currency}"
               + (f" · {_s(mon.get('nota'))}" if _s(mon.get("nota")) else ""))
    t1, t2, t3, t4, t5 = st.tabs(["🚆 Transporte", "🎫 Tarjetas y pases", "💳 Pagos", "🍽️ Precios", "🔗 Fuentes"])
    with t1:
        for it in f.get("transporte") or []:
            with st.container(border=True):
                st.markdown(f"**{_s(it.get('medio'))}** · {_s(it.get('precio'))}" + (" _(aprox.)_" if it.get("aproximado") else ""))
                note = " · ".join(x for x in (_s(it.get("util_para")), _s(it.get("nota"))) if x)
                if note:
                    st.caption(note)
    with t2:
        for it in f.get("tarjetas_y_pases") or []:
            with st.container(border=True):
                who = _s(it.get("para")).lower()
                tag = {"turista": "🧳 Turista", "residente": "🏠 Residente", "todos": "👥 Todos"}.get(who, who.title())
                st.markdown(f"**{_s(it.get('nombre'))}** · {tag}" + (f" · {_s(it.get('precio'))}" if _s(it.get("precio")) else ""))
                for label, k in (("Vigencia", "vigencia"), ("Requisitos", "requisitos"), ("Dónde comprar", "donde_comprar")):
                    if _s(it.get(k)):
                        st.caption(f"{label}: {_s(it.get(k))}")
                if _s(it.get("url")).startswith("http"):
                    st.markdown(f"[Sitio oficial]({_s(it.get('url'))})")
    with t3:
        pago = f.get("pago") or {}
        for label, k in (("🚌 Tarjeta en transporte", "tarjeta_en_transporte"), ("🛍️ Tarjeta en comercios", "tarjeta_en_comercios"), ("💶 Efectivo", "efectivo"), ("📱 Contactless y billeteras", "contactless_y_wallet")):
            if _s(pago.get(k)):
                st.markdown(f"**{label}:** {_s(pago.get(k))}")
        tips = [t for t in (f.get("consejos") or []) if _s(t)]
        if tips:
            st.markdown("**💡 Consejos**\n" + "\n".join(f"- {_s(t)}" for t in tips))
    with t4:
        for it in f.get("precios_tipicos") or []:
            st.markdown(f"- **{_s(it.get('concepto'))}:** {_s(it.get('precio'))}" + (" _(aprox.)_" if it.get("aproximado") else ""))
        st.caption("Los precios cambian: úsalos como guía y confirma en el sitio oficial antes de comprar.")
    with t5:
        for src in f.get("fuentes") or []:
            st.markdown(f"- [{_s(src.get('titulo')) or _s(src.get('url'))}]({_s(src.get('url'))})")
        if not f.get("fuentes"):
            st.caption("Sin fuentes registradas.")


# ============================================================ Ruta
def page_route(slug: str, route: pd.DataFrame, places: list[dict]) -> None:
    sub = st.segmented_control("Vista de ruta", ["📍 Paradas", "🗓️ Itinerario", "💰 Presupuesto"], default="📍 Paradas", key="route_view", label_visibility="collapsed") or "📍 Paradas"
    if sub == "🗓️ Itinerario":
        page_itinerary(slug, route, places)
        return
    if sub == "💰 Presupuesto":
        page_budget(slug, places)
        return
    ui.section_title("Paradas del viaje")
    ver = st.session_state.get("route_ver", 0)
    options = sorted({c.es for c in COUNTRIES} | {p for p in route["País"].tolist() if p})
    edited = st.data_editor(
        route,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key=f"route_{slug}_{ver}",
        column_config={
            "Ciudad": st.column_config.TextColumn("Ciudad", required=True),
            "País": st.column_config.SelectboxColumn("País", options=options),
            "Llegada": st.column_config.DateColumn("Llegada", format="DD/MM/YYYY"),
            "Salida": st.column_config.DateColumn("Salida", format="DD/MM/YYYY"),
        },
    )
    c1, c2 = st.columns(2)
    if c1.button("💾 Guardar ruta", type="primary", width="stretch"):
        store.save_route(slug, edited)
        bump("route_ver")
        st.toast("Ruta guardada")
        st.rerun()
    buf = io.BytesIO()
    clean_none(edited).to_excel(buf, index=False, sheet_name="Ruta")
    c2.download_button("⬇️ Descargar Excel", buf.getvalue(), file_name=f"{slug}-ruta.xlsx", width="stretch", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.download_button("🖨️ Versión para llevar (imprimir o PDF)", print_html(slug, route, places), file_name=f"{slug}.html", mime="text/html", width="stretch",
                       help="Se abre sin internet; con Imprimir → Guardar como PDF la tienes en el celular.")

    with st.expander("📥 Importar mi ruta desde Excel o CSV"):
        st.caption("Columnas reconocidas: Ciudad, País, Llegada, Salida, Hotel, Notas (también en inglés).")
        up = st.file_uploader("Archivo", type=["xlsx", "csv"], label_visibility="collapsed")
        mode = st.radio("Al importar", ["Agregar al final", "Reemplazar la ruta"], horizontal=True)
        if st.button("Importar", disabled=up is None):
            raw = pd.read_csv(up) if up.name.lower().endswith(".csv") else pd.read_excel(up)
            new = normalize_route(raw)
            if new.empty:
                st.warning("No encontré filas con ciudad o país.")
            else:
                base = edited if mode.startswith("Agregar") else route.iloc[0:0]
                store.save_route(slug, pd.concat([base, new], ignore_index=True))
                bump("route_ver")
                if (new["Ciudad"] == "").all():
                    st.toast("Importé países sin ciudades; agrega las ciudades en la tabla.")
                st.rerun()

    ui.section_title("Lugares guardados")
    cols = ["nombre", "ciudad", "categoria", "precio", "moneda", "notas", "fuente", "lat", "lon"]
    pdf = pd.DataFrame(places, columns=cols) if places else pd.DataFrame({c: pd.Series(dtype="object") for c in cols})
    pdf["precio"] = pd.to_numeric(pdf["precio"], errors="coerce")
    pver = st.session_state.get("places_ver", 0)
    pedit = st.data_editor(
        pdf,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key=f"places_{slug}_{pver}",
        column_config={
            "categoria": st.column_config.SelectboxColumn("categoría", options=list(T.CATEGORIES)),
            "precio": st.column_config.NumberColumn("precio", format="%.2f"),
            "lat": None,
            "lon": None,
        },
    )
    priced = pedit.dropna(subset=["precio"])
    if len(priced):
        totals = priced.groupby(priced["moneda"].fillna("").replace("", "¿?"))["precio"].sum()
        for col, (cur, total) in zip(st.columns(max(1, min(len(totals), 3))), totals.items()):
            col.metric(f"Total estimado ({cur})", f"{total:,.2f}")
    if st.button("💾 Guardar lugares", width="stretch"):
        store.save_places(slug, clean_none(pedit).to_dict("records"))
        bump("places_ver")
        st.toast("Lugares guardados")
        st.rerun()


def page_itinerary(slug: str, route: pd.DataFrame, places: list[dict]) -> None:
    days = store.load_itinerary(slug)
    if not days:
        with st.container(border=True):
            st.markdown("**Aún no hay itinerario por día.**")
            st.markdown("1. Ve al **💬 Chat** y toca «🗓️ Arma mi itinerario por días».\n2. Cuando te guste, toca **💾 Guardar como itinerario** bajo la respuesta.\n3. Aquí lo verás por día y podrás editarlo.")
        if st.button("➕ Crear uno a mano", width="stretch"):
            store.save_itinerary(slug, [{"dia": 1, "fecha": "", "pais": "", "titulo": "", "items": [{"hora": "09:00", "lugar": "Mi primer lugar", "actividad": "", "aproximado": True}]}])
            bump("itin_ver")
            st.rerun()
        return
    for d in days:
        head = f"Día {d['dia']}" + (f" · {d['fecha']}" if d["fecha"] else "") + (f" · {d['titulo']}" if d["titulo"] else "")
        tot = plan.budget([d])["total"]
        day_cost = "  —  " + " + ".join(plan.money(c, v["total"]) for c, v in tot.items()) if tot else ""
        with st.expander(head + day_cost, expanded=d is days[0]):
            for it in d["items"]:
                costs = [c for c in (it["costo"], it["costo_transporte"]) if c is not None]
                cost = f" · **{sum(costs):,.2f} {it['moneda']}**" + (" (aprox.)" if it["aproximado"] else "") if costs else ""
                place = f"[{it['lugar']}]({T.gmaps_place_link(it['lugar'])})" if it["lugar"] else ""
                st.markdown(f"**{it['hora'] or '·'}** {place}{' — ' + it['actividad'] if it['actividad'] else ''}{cost}" + (f"  \n🚆 {it['transporte']}" if it["transporte"] else ""))
    ui.section_title("Editar itinerario")
    st.caption("Cada fila es una actividad; el número de **Día** la agrupa. Costos por persona. Marca «Aprox» si no está verificado.")
    iver = st.session_state.get("itin_ver", 0)
    edited = st.data_editor(
        plan.to_table(days), num_rows="dynamic", hide_index=True, width="stretch", key=f"itin_{slug}_{iver}",
        column_config={
            "Día": st.column_config.NumberColumn("Día", min_value=1, step=1, format="%d", required=True),
            "Costo": st.column_config.NumberColumn("Costo", min_value=0, format="%.2f"),
            "Costo transp.": st.column_config.NumberColumn("Costo transp.", min_value=0, format="%.2f"),
            "Aprox": st.column_config.CheckboxColumn("Aprox", default=True),
        },
    )
    c1, c2 = st.columns(2)
    if c1.button("💾 Guardar itinerario", type="primary", width="stretch"):
        store.save_itinerary(slug, plan.from_table(edited, days))
        bump("itin_ver")
        st.toast("Itinerario guardado")
        st.rerun()
    c2.download_button("🖨️ Versión para llevar", print_html(slug, route, places), file_name=f"{slug}.html", mime="text/html", width="stretch",
                       help="Se abre sin internet; con Imprimir → Guardar como PDF la tienes en el celular.")


def page_budget(slug: str, places: list[dict]) -> None:
    days = store.load_itinerary(slug)
    b = plan.budget(days, places)
    if not b["total"] and not b["otros_total"]:
        st.info("Todavía no hay costos. Guarda un itinerario con precios (desde el Chat) o agrega precios a tus lugares guardados.")
        return
    if b["total"]:
        ui.section_title("Total del itinerario (por persona)")
        cols = st.columns(max(1, min(len(b["total"]), 3)))
        for col, (cur, v) in zip(cols, b["total"].items()):
            col.metric(cur, f"{v['total']:,.2f}", help=f"De ese total, {v['aprox']:,.2f} son aproximados")
        if b["n_aprox"] or b["n_sin_costo"]:
            st.warning(f"{b['n_aprox']} de {b['n_items']} actividades tienen precio aproximado y {b['n_sin_costo']} no tienen costo. Confirma antes de pagar.")
        if len(b["total"]) > 1:
            st.caption("Los totales no convierten entre monedas; el agente puede convertirlos con tipo de cambio si se lo pides.")
        rows = [{"Día": r["dia"], "Título": r["titulo"], "País": r["pais"], **{c: round(v["total"], 2) for c, v in r["totales"].items()}} for r in b["por_dia"] if r["totales"]]
        if rows:
            ui.section_title("Por día")
            st.dataframe(pd.DataFrame(rows).fillna(""), hide_index=True, width="stretch")
        if any(k != "Sin país" for k in b["por_pais"]):
            ui.section_title("Por país")
            st.dataframe(pd.DataFrame([{"País": k, **{c: round(v["total"], 2) for c, v in tot.items()}} for k, tot in b["por_pais"].items()]).fillna(""), hide_index=True, width="stretch")
    if b["otros_total"]:
        ui.section_title("Otros lugares guardados (referencia)")
        st.caption("Lugares con precio que no están en el itinerario; no se suman al total de arriba.")
        for cur, v in b["otros_total"].items():
            st.metric(cur, f"{v['total']:,.2f}")


def print_html(slug: str, route: pd.DataFrame, places: list[dict]) -> bytes:
    meta = store.meta(slug)
    stops = []
    for _, r in route.iterrows():
        if str(r["Ciudad"]).strip():
            g = geo.cached(stop_query(r))
            stops.append({"ciudad": r["Ciudad"], "pais": r["País"], "llegada": r["Llegada"], "salida": r["Salida"], "hotel": r["Hotel"], "notas": r["Notas"],
                          "lat": g["lat"] if g else None, "lon": g["lon"] if g else None})
    days = store.load_itinerary(slug)
    return exports.build_html(meta.get("name", slug), meta.get("paises", []), stops, days, plan.budget(days, places), places, store.read_notes(slug)).encode("utf-8")


# ============================================================ Mapa
def page_map(slug: str, route: pd.DataFrame, places: list[dict]) -> None:
    rows = []
    for _, r in route.iterrows():
        if str(r["Ciudad"]).strip():
            q = stop_query(r)
            rows.append({"q": q, "row": r, "g": geo.cached(q)})
    pending = [x for x in rows if x["g"] is None]
    if pending:
        st.info(f"{len(pending)} parada(s) sin ubicar en el mapa.")
        if st.button("📍 Ubicar paradas (≈1 s por parada)", type="primary"):
            bar = st.progress(0.0)
            for i, x in enumerate(pending, 1):
                geo.lookup(x["q"])
                bar.progress(i / len(pending))
            missing = [x["q"] for x in pending if geo.cached(x["q"]) is None]
            if missing and geo.last_error:
                st.warning(f"No pude consultar el servicio de ubicaciones ({geo.last_error}). Inténtalo de nuevo en un momento.")
            else:
                st.session_state["geo_missing"] = missing
                st.rerun()
    if st.session_state.get("geo_missing"):
        lost = [q for q in st.session_state["geo_missing"] if geo.cached(q) is None]
        if lost:
            st.warning("No encontré: " + "; ".join(lost) + ". Prueba el nombre más completo: pueblo + provincia o región + país (ej. «Aljaraque, Huelva» en Ciudad y «España» en País).")

    located = [x for x in rows if x["g"]]
    last_route = store.load_json(slug, "ultima_ruta.json", None)
    placed = [p for p in places if p.get("lat") is not None and p.get("lon") is not None and pd.notna(p.get("lat"))]

    pts = [(x["g"]["lat"], x["g"]["lon"]) for x in located] + [(p["lat"], p["lon"]) for p in placed]
    if last_route:
        pts += [(s["lat"], s["lon"]) for s in last_route.get("paradas", [])]
    m = folium.Map(location=[45, 15], zoom_start=3, tiles="OpenStreetMap", control_scale=True)
    if pts:
        m.fit_bounds([[min(p[0] for p in pts), min(p[1] for p in pts)], [max(p[0] for p in pts), max(p[1] for p in pts)]], max_zoom=12, padding=(30, 30))

    def pin(n, color):
        return folium.DivIcon(
            html=f'<div style="background:{color};color:#fff;border-radius:50%;width:30px;height:30px;line-height:26px;text-align:center;font-weight:700;border:2px solid #fff;box-shadow:0 3px 10px rgba(0,0,0,.35)">{n}</div>',
            icon_size=(30, 30), icon_anchor=(15, 15), class_name="tc-pin",
        )

    g_route = folium.FeatureGroup("Ruta del viaje")
    for n, x in enumerate(located, 1):
        r = x["row"]
        dates = " → ".join(str(d) for d in (r["Llegada"], r["Salida"]) if d)
        popup = f"<b>{n}. {x['q']}</b><br>{dates}<br>{r['Hotel'] or ''}"
        folium.Marker([x["g"]["lat"], x["g"]["lon"]], icon=pin(n, "#6C5CE7"), tooltip=x["q"], popup=folium.Popup(popup, max_width=240)).add_to(g_route)
    if len(located) > 1:
        folium.PolyLine([(x["g"]["lat"], x["g"]["lon"]) for x in located], color="#6C5CE7", weight=4, opacity=0.8, dash_array="8 8").add_to(g_route)
    g_route.add_to(m)

    if placed:
        g_pl = folium.FeatureGroup("Lugares guardados")
        for p in placed:
            price = f"<br>{p.get('precio')} {p.get('moneda') or ''}" if p.get("precio") else ""
            folium.CircleMarker([p["lat"], p["lon"]], radius=8, color="#fff", weight=2, fill=True, fill_opacity=0.95,
                                fill_color=CAT_COLORS.get(p.get("categoria"), "#868E96"), tooltip=p["nombre"],
                                popup=folium.Popup(f"<b>{p['nombre']}</b><br>{p.get('categoria', '')}{price}", max_width=220)).add_to(g_pl)
        g_pl.add_to(m)

    if last_route and last_route.get("paradas"):
        g_ag = folium.FeatureGroup("Ruta del agente")
        coords = [(s["lat"], s["lon"]) for s in last_route["paradas"]]
        folium.PolyLine(coords, color="#20A39E", weight=5, opacity=0.9).add_to(g_ag)
        for n, s in enumerate(last_route["paradas"], 1):
            folium.Marker([s["lat"], s["lon"]], icon=pin(n, "#20A39E"), tooltip=s["nombre"]).add_to(g_ag)
        g_ag.add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)

    st_folium(m, height=460, use_container_width=True, returned_objects=[], key=f"map_{slug}_{len(located)}_{len(placed)}_{(last_route or {}).get('titulo', '')}")
    if not pts:
        st.caption("Agrega paradas en la pestaña Ruta o pídele al agente una ruta en el Chat.")

    ui.section_title("Abrir en Google Maps")
    mode_label = st.radio("Modo", list(MODE_LABELS), horizontal=True, label_visibility="collapsed")
    mode = MODE_LABELS[mode_label]
    names = [x["q"] for x in rows]
    links = T.gmaps_links(names, mode)
    for i, url in enumerate(links, 1):
        st.link_button(f"🧭 Ruta del viaje{f' · tramo {i}' if len(links) > 1 else ''}", url, width="stretch")
    if last_route and last_route.get("enlaces_google_maps"):
        for i, url in enumerate(last_route["enlaces_google_maps"], 1):
            st.link_button(f"🧭 {last_route.get('titulo', 'Ruta del agente')}{f' · tramo {i}' if len(last_route['enlaces_google_maps']) > 1 else ''}", url, width="stretch")
    if not links and not last_route:
        st.caption("Necesitas al menos 2 paradas con ciudad.")
    if rows or placed:
        with st.expander("👁️ Ver cada parada: Maps y Street View", expanded=False):
            st.caption("Street View abre el centro de la ciudad: arrastra al muñequito amarillo para «caminar» por las calles antes de viajar. «Llegar» usa el modo de arriba y muestra horarios en Google Maps.")
            for n, x in enumerate(rows, 1):
                links_ = [f"[📍 Mapa]({T.gmaps_place_link(x['q'])})"]
                if x["g"]:
                    links_.append(f"[👁️ Street View]({T.gmaps_streetview_link(x['g']['lat'], x['g']['lon'])})")
                if n < len(rows):
                    links_.append(f"[➡️ Llegar a {rows[n]['q'].split(',')[0]}]({T.gmaps_leg_link(x['q'], rows[n]['q'], mode)})")
                st.markdown(f"**{n}. {x['q']}**  \n" + " · ".join(links_))
            if placed:
                st.markdown("**Lugares guardados**")
                for p in placed:
                    st.markdown(f"{p['nombre']}  \n[📍 Mapa]({T.gmaps_place_link(str(p['lat']) + ',' + str(p['lon']))}) · [👁️ Street View]({T.gmaps_streetview_link(p['lat'], p['lon'])})")

    stops_kml = [{"name": f"{n}. {x['q']}", "lat": x["g"]["lat"], "lon": x["g"]["lon"],
                  "desc": " → ".join(str(d) for d in (x["row"]["Llegada"], x["row"]["Salida"]) if d) + (f"\nHotel: {x['row']['Hotel']}" if x["row"]["Hotel"] else "")}
                 for n, x in enumerate(located, 1)]
    places_kml = [{"name": p["nombre"], "lat": p["lat"], "lon": p["lon"], "desc": f"{p.get('categoria', '')} {p.get('precio') or ''} {p.get('moneda') or ''}".strip()} for p in placed]
    if last_route:
        places_kml += [{"name": s["nombre"], "lat": s["lat"], "lon": s["lon"], "desc": "Ruta del agente"} for s in last_route.get("paradas", [])]
    if stops_kml or places_kml:
        ui.section_title("Llevar a Google My Maps")
        st.download_button("⬇️ Descargar para Google My Maps (.kml)", exports.build_kml(store.meta(slug).get("name", "Viaje"), stops_kml, places_kml).encode("utf-8"),
                           file_name=f"{slug}.kml", mime="application/vnd.google-earth.kml+xml", width="stretch")
        st.caption("Pasos: abre mymaps.google.com → «Crear un nuevo mapa» → «Importar» → sube este archivo. Tu ruta y tus lugares quedan en tu cuenta de Google y los ves en la app de Google Maps (Guardado → Mapas).")

    if len(located) > 1:
        with st.expander("📏 Distancias entre paradas (línea recta)"):
            legs = []
            for a, b in zip(located, located[1:]):
                km = T.haversine_km(a["g"]["lat"], a["g"]["lon"], b["g"]["lat"], b["g"]["lon"])
                legs.append({"De": a["q"], "A": b["q"], "km": round(km), "Sugerencia": "✈️ vuelo" if km > 800 else ("🚆 tren/bus" if km > 60 else "🚇 local")})
            st.dataframe(pd.DataFrame(legs), hide_index=True, width="stretch")
            st.caption("Los enlaces de Google Maps no cubren vuelos entre países lejanos; para eso pregúntale al agente.")


# ============================================================ Chat
def seed_history(engine: str, display: list[dict]) -> list[dict]:
    """Reconstruye el historial de un motor a partir de lo mostrado (al cambiar de motor a mitad de conversación)."""
    if engine == "gemini":
        return [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["text"]}]} for m in display]
    return [{"role": m["role"], "content": m["text"]} for m in display]


def page_chat(slug: str, meta: dict, route: pd.DataFrame, places: list[dict]) -> None:
    chat = st.session_state.get("chat")
    if not chat or chat["slug"] != slug:
        chat = st.session_state["chat"] = {"slug": slug, "messages": [], "gmessages": [], "display": [], "in": 0, "out": 0, "searches": 0}
    engine = cfg["engine"]
    hist_key = "gmessages" if engine == "gemini" else "messages"
    key = get_api_key()
    name = cfg["agent_name"]
    eng = ENGINE_NAME[engine]

    c1, c2 = st.columns(2)
    clear = c1.button("🧹 Nueva conversación", width="stretch", help="Vacía el chat; tu ruta, lugares y notas se conservan.")
    summ = c2.button("📝 Resumir y limpiar", width="stretch", disabled=not (key and chat["display"]), help="Guarda un resumen en las notas del viaje y vacía el chat.")
    if clear:
        chat.update(messages=[], gmessages=[], display=[])
        st.rerun()
    if summ:
        with st.spinner("Resumiendo…"):
            try:
                client = make_client(engine, key, 120)
                text = gem.summarize(client, cfg["gemini_model"], chat["display"]) if engine == "gemini" else agent.summarize(client, cfg["model"], chat["display"])
                store.append_note(slug, text)
                chat.update(messages=[], gmessages=[], display=[])
                st.toast("Resumen guardado en las notas del viaje")
                st.rerun()
            except gem.GeminiError as e:
                st.error(gem.friendly(e))
            except anthropic.APIError as e:
                st.error(f"No pude resumir: {e}")

    if not key:
        if engine == "gemini":
            st.info("Para chatear con Gemini pega tu clave gratuita en ⚙️ Ajustes (barra lateral): se crea en aistudio.google.com/apikey. El resto de la app, incluidas las fichas base de cada país, funciona sin ella.")
        else:
            st.info("Para chatear con Claude pega tu clave de Anthropic en ⚙️ Ajustes (barra lateral). El resto de la app funciona sin ella.")

    for m in chat["display"]:
        with st.chat_message(m["role"], avatar="🧑‍💻" if m["role"] == "user" else "🧭"):
            st.markdown(m["text"])
            if m.get("tools"):
                st.caption("🔧 " + ", ".join(m["tools"]))

    first_city = next((str(r["Ciudad"]).strip() for _, r in route.iterrows() if str(r["Ciudad"]).strip()), "")
    where = first_city or "mi viaje"
    suggestions = {
        "🗓️ Arma mi itinerario por días": f"Arma mi itinerario por días para {where} con horas, transporte y costos aproximados por persona. Pregúntame lo mínimo que te falte.",
        f"🚆 ¿Cómo me muevo en {where}?": f"¿Cómo me muevo en {where}? Dime los medios convenientes, cuánto cuestan, si se paga con tarjeta y qué pases existen.",
        "💳 ¿Cómo pago el transporte?": "¿Cómo pago el transporte en los países de mi ruta? ¿Tarjeta, contactless o efectivo? ¿Hay tarjeta o pase para turistas?",
        "💰 ¿Cuánto me costará?": "Con mi ruta y mi itinerario guardado, ¿cuánto me costaría el viaje por persona? Separa transporte, comida, entradas y hospedaje, marcando lo aproximado.",
        f"📍 Qué ver en {where}": f"¿Qué imperdibles recomiendas en {where}? Con precio de entrada y cuánto tiempo toma cada uno.",
    }
    chip_ph = st.empty()
    if key and not chat["display"]:
        with chip_ph.container():
            st.caption("Toca una sugerencia o escribe lo que quieras:")
            st.pills("Sugerencias", list(suggestions), selection_mode="single", key="chat_pills", label_visibility="collapsed", on_change=send_suggestion, args=(suggestions,))
    usage_ph = st.empty()
    prompt = st.chat_input(f"Escríbele a {name}…", disabled=not key) or st.session_state.pop("pending_prompt", None)
    if prompt and key:
        chip_ph.empty()
        if chat["display"] and (not chat[hist_key] or chat.get("last_engine", engine) != engine):  # cambio de motor: conserva el contexto ya mostrado
            chat[hist_key] = seed_history(engine, chat["display"])
        chat["last_engine"] = engine
        chat["display"].append({"role": "user", "text": prompt})
        with st.chat_message("user", avatar="🧑‍💻"):
            st.markdown(prompt)
        ctx = T.ToolContext(store=store, slug=slug, geo=geo)
        system = agent.build_system(
            name, meta.get("name", slug), meta.get("paises", []),
            [f"{i}. {r['Ciudad']} ({r['País']}) {r['Llegada'] or ''} → {r['Salida'] or ''} hotel: {r['Hotel'] or '-'}" for i, (_, r) in enumerate(route.iterrows(), 1)],
            [f"- {p['nombre']} ({p.get('ciudad', '')}, {p.get('categoria', '')}) {p.get('precio') or ''} {p.get('moneda') or ''}" for p in places[:40]],
            store.read_notes(slug),
            [f"Día {d['dia']} {d['fecha']} {d['titulo']}: " + "; ".join(f"{it['hora']} {it['lugar']}" for it in d["items"]) for d in store.load_itinerary(slug)],
        )
        hist = chat[hist_key]
        n0 = len(hist)
        hist.append(gem.user_msg(prompt) if engine == "gemini" else {"role": "user", "content": prompt})
        with st.chat_message("assistant", avatar="🧭"):
            status = st.status(f"{name} está pensando…", expanded=False)
            try:
                client = make_client(engine, key, 180)
                on_tool = lambda n, a: status.write(f"🔧 {n}")
                live = st.empty()
                if engine == "gemini":
                    res = gem.run_agent(client, cfg["gemini_model"], system, hist, ctx, cfg["max_searches"], cfg["history_turns"], on_tool=on_tool,
                                        on_text=lambda t: live.markdown(t + " ▌" if t else ""))
                else:
                    res = agent.run_agent(client, cfg["model"], system, hist, ctx, cfg["max_searches"], cfg["history_turns"], on_tool=on_tool)
                if engine == "gemini":
                    chat["search_off"] = bool(client.search_off and not client.tavily_key)
                status.update(label="Listo", state="complete")
                live.markdown(res.text)
                chat["display"].append({"role": "assistant", "text": res.text, "tools": sorted(set(res.tools_used))})
                chat["in"] += res.input_tokens
                chat["out"] += res.output_tokens
                chat["searches"] += res.searches
                if ctx.changed:
                    bump("route_ver")
                    bump("places_ver")
            except (gem.GeminiError, anthropic.AuthenticationError, anthropic.RateLimitError, anthropic.APIError) as e:
                del hist[n0:]
                chat["display"].pop()  # no dejar la pregunta sin respuesta en el historial mostrado
                status.update(label="Error", state="error")
                if isinstance(e, gem.GeminiError):
                    st.error(gem.friendly(e))
                elif isinstance(e, anthropic.AuthenticationError):
                    st.error("La clave de Anthropic no es válida.")
                elif isinstance(e, anthropic.RateLimitError):
                    st.error("Límite de uso alcanzado. Espera un momento e inténtalo de nuevo.")
                else:
                    st.error(f"Error de la API de Claude: {e}")
    if key and chat["display"] and chat["display"][-1]["role"] == "assistant":  # debajo de la última respuesta (también la que acaba de llegar)
        b1, b2 = st.columns(2)
        if b1.button("💾 Guardar como itinerario", width="stretch", help="El agente guarda en la pestaña Ruta → Itinerario lo que acaba de proponer."):
            st.session_state["pending_prompt"] = "Guarda en la app el itinerario por días que acabas de proponer (usa guardar_itinerario con todos los días, horas, lugares, transporte y costos)."
            st.rerun()
        if b2.button("💰 Calcular el costo", width="stretch"):
            st.session_state["pending_prompt"] = "Resume el costo total estimado de lo que acabas de proponer por persona, separando transporte, entradas y comida, y marca lo aproximado."
            st.rerun()
    usage_ph.caption(f"{eng} · memoria: últimos {cfg['history_turns']} mensajes tuyos · {chat['in'] + chat['out']:,} tokens usados en esta conversación")


# ============================================================ main
trips = store.list_trips()
sidebar(trips[0][0] if trips else None)
if not trips:
    welcome()
    st.stop()

names = dict(trips)
TITLES = {SECTIONS[0]: "Descubrir", SECTIONS[1]: "Mi ruta", SECTIONS[2]: "Mapa", SECTIONS[3]: "Chat"}
section = st.segmented_control("Sección", SECTIONS, default=SECTIONS[0], key="section", label_visibility="collapsed")
section = section or st.session_state.get("_last_section", SECTIONS[0])
st.session_state["_last_section"] = section

ui.top_header(cfg["agent_name"], TITLES[section])
col_a, col_b = st.columns([5, 3])
slug = col_a.selectbox("Viaje", list(names), format_func=names.get, key="trip_slug", label_visibility="collapsed")
with col_b.popover("⋯ Viajes", width="stretch"):
    st.markdown("**＋ Nuevo viaje**")
    st.text_input("Nombre del viaje", key="new_trip_name", placeholder="Ej. Tokio")
    st.button("Crear carpeta", type="primary", on_click=create_trip)
    st.divider()
    st.markdown("**💾 Respaldo**")
    st.caption("☁️ En la nube gratuita los viajes pueden borrarse cuando la app se reinicia. Descarga un respaldo cuando termines de planear.")
    st.download_button("⬇️ Descargar respaldo de este viaje", store.export_zip(slug), file_name=f"nomada-{slug}.zip", mime="application/zip", width="stretch")
    st.file_uploader("Restaurar desde un respaldo (.zip)", type=["zip"], key=f"restore_file_{st.session_state.get('restore_ver', 0)}")
    st.button("Restaurar respaldo", on_click=restore_trip)
    _msg = st.session_state.pop("restore_msg", None)
    if _msg:
        (st.success if _msg[0] == "ok" else st.error)(_msg[1])
    st.divider()
    st.markdown(f"**🗑️ Eliminar «{names[slug]}»**")
    st.caption("Borra su ruta, lugares y notas. No se puede deshacer.")
    st.checkbox("Sí, quiero borrar este viaje", key="del_ok")
    st.button("Eliminar viaje", on_click=delete_trip, args=(slug,), disabled=not st.session_state.get("del_ok"))

meta = store.meta(slug)
route = store.load_route(slug)
places = store.load_places(slug)

if section == SECTIONS[0]:
    page_discover(slug, meta, route, places)
elif section == SECTIONS[1]:
    page_route(slug, route, places)
elif section == SECTIONS[2]:
    page_map(slug, route, places)
else:
    page_chat(slug, meta, route, places)

if section != SECTIONS[3]:  # en el chat el campo de texto ya ocupa el borde inferior
    ui.brand_footer()
