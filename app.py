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
import tools as T
import ui
from countries import SUBREGIONS, load_countries
from storage import ROUTE_COLS, TripStore, normalize_route

st.set_page_config(page_title="Mi agente de viajes", page_icon="🧭", layout="centered", initial_sidebar_state="collapsed")
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
def get_api_key() -> str | None:
    key = st.session_state.get("api_key_input") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        try:
            key = st.secrets.get("ANTHROPIC_API_KEY")
        except Exception:
            key = None
    return key or None


def bump(name: str) -> None:
    st.session_state[name] = st.session_state.get(name, 0) + 1


def toggle_country(slug: str, es: str) -> None:
    store.toggle_country(slug, es)


def create_trip() -> None:
    name = st.session_state.get("new_trip_name", "").strip()
    if name:
        st.session_state["trip_slug"] = store.create(name)
        st.session_state["new_trip_name"] = ""


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
        labels = list(agent.MODELS)
        ids = list(agent.MODELS.values())
        idx = ids.index(cfg["model"]) if cfg["model"] in ids else 0
        label = st.selectbox("Modelo", labels, index=idx)
        searches = st.slider("Búsquedas web por respuesta", 0, 10, int(cfg["max_searches"]), help="Cada búsqueda web se cobra aparte. 0 las desactiva.")
        fsearch = st.slider("Búsquedas web por ficha de país", 2, 15, int(cfg["ficha_searches"]), help="La ficha de transporte y precios se guarda; solo se vuelve a gastar al actualizarla.")
        turns = st.slider("Memoria del chat (tus últimos mensajes)", 2, 20, int(cfg["history_turns"]), help="Menos memoria = respuestas más enfocadas y más baratas.")
        new = {"agent_name": name.strip() or "Nómada", "model": agent.MODELS[label], "max_searches": searches, "ficha_searches": fsearch, "history_turns": turns}
        if any(cfg.get(k) != v for k, v in new.items()):
            cfg.update(new)
            store.save_config(cfg)
            changed = True

        st.divider()
        if not (os.environ.get("ANTHROPIC_API_KEY") or _has_secret()):
            st.text_input("Clave de Anthropic (solo esta sesión)", type="password", key="api_key_input", help="Créala en console.anthropic.com y fija un límite de gasto mensual allí.")
        else:
            st.caption("🔑 Clave de Anthropic cargada desde el entorno.")
        if st.button("🧹 Vaciar caché de ubicaciones", width="stretch"):
            geo.clear()
            st.toast("Caché de ubicaciones vaciado")
        chat = st.session_state.get("chat")
        if chat:
            st.caption(f"Uso en esta conversación: {chat['in']:,} tokens de entrada · {chat['out']:,} de salida · {chat['searches']} búsquedas web")
    if changed:
        st.rerun()


def _has_secret() -> bool:
    try:
        return bool(st.secrets.get("ANTHROPIC_API_KEY"))
    except Exception:
        return False


# ============================================================ pantalla de bienvenida
def welcome() -> None:
    ui.top_header(cfg["agent_name"], "Bienvenido")
    ui.cover("JP", "Tu próximo viaje, a tu manera", "Crea una carpeta por viaje o ciudad (Madrid, Japón, Europa 2027…). Ahí se guardan tu ruta, tus lugares y tus notas, y tu agente te ayuda a planearlo.")
    st.text_input("Nombre del viaje", key="new_trip_name", placeholder="Ej. Madrid")
    st.button("¡Vamos!  →", type="primary", on_click=create_trip)


# ============================================================ Descubrir
def open_ficha(iso: str) -> None:
    st.session_state["ficha_iso"] = iso


def close_ficha() -> None:
    st.session_state.pop("ficha_iso", None)


def _sort_key(c) -> str:
    return unicodedata.normalize("NFKD", c.es).encode("ascii", "ignore").decode().lower()


def page_discover(slug: str, meta: dict, route: pd.DataFrame, places: list[dict]) -> None:
    iso = st.session_state.get("ficha_iso")
    if iso:
        page_ficha(slug, meta, iso)
        return
    selected = set(meta.get("paises", []))

    view = st.segmented_control("Ver", ["Todos", "Mis países", "Europa", "Asia"], default="Todos", key="view", label_visibility="collapsed") or "Todos"
    zone = "Todas"
    if view in ("Europa", "Asia"):
        zones = sorted({c.subregion for c in COUNTRIES if c.region == view}, key=lambda z: list(SUBREGIONS).index(z) if z in SUBREGIONS else 99)
        zone = st.selectbox("Zona", ["Todas"] + zones, key=f"zone_{view}")
    q = st.text_input("Buscar país", placeholder="🔎 Buscar país…", label_visibility="collapsed", key="country_q").strip().lower()

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
    key = get_api_key()
    ficha = store.load_ficha(iso)
    desc = _s((ficha or {}).get("resumen")) if ficha and not ficha.get("_sin_formato") else ""
    ui.detail_header(c, inside, desc or f"Consulta transporte, tarjetas y pases para turistas y residentes, formas de pago y precios típicos de {c.es}. Los precios van en {c.display_currency}.")
    b1, b2 = st.columns(2)
    b1.button("Quitar del viaje" if inside else "＋ Agregar al viaje", key="fic_toggle", on_click=toggle_country, args=(slug, c.es), type="primary" if inside else "secondary", width="stretch")
    go = b2.button("🔄 Actualizar precios y transporte" if ficha else "🔎 Consultar precios y transporte", key="fic_go", width="stretch", disabled=not key)
    if not key:
        st.caption("Para consultar la web pega tu clave de Anthropic en ⚙️ Ajustes.")
    if go:
        with st.spinner(f"Buscando transporte, tarjetas y precios de {c.es} en la web… (puede tardar 1–2 minutos)"):
            try:
                client = anthropic.Anthropic(api_key=key, max_retries=2, timeout=300)
                ficha = ficha_mod.generate_ficha(client, cfg["model"], c, int(cfg["ficha_searches"]))
                store.save_ficha(iso, ficha)
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
            if geo.last_error and any(geo.cached(x["q"]) is None for x in pending):
                st.warning(f"No pude consultar el servicio de ubicaciones: {geo.last_error}")
            else:
                st.rerun()

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
    if len(located) > 1:
        with st.expander("📏 Distancias entre paradas (línea recta)"):
            legs = []
            for a, b in zip(located, located[1:]):
                km = T.haversine_km(a["g"]["lat"], a["g"]["lon"], b["g"]["lat"], b["g"]["lon"])
                legs.append({"De": a["q"], "A": b["q"], "km": round(km), "Sugerencia": "✈️ vuelo" if km > 800 else ("🚆 tren/bus" if km > 60 else "🚇 local")})
            st.dataframe(pd.DataFrame(legs), hide_index=True, width="stretch")
            st.caption("Los enlaces de Google Maps no cubren vuelos entre países lejanos; para eso pregúntale al agente.")


# ============================================================ Chat
def page_chat(slug: str, meta: dict, route: pd.DataFrame, places: list[dict]) -> None:
    chat = st.session_state.get("chat")
    if not chat or chat["slug"] != slug:
        chat = st.session_state["chat"] = {"slug": slug, "messages": [], "display": [], "in": 0, "out": 0, "searches": 0}
    key = get_api_key()
    name = cfg["agent_name"]

    c1, c2 = st.columns(2)
    clear = c1.button("🧹 Nueva conversación", width="stretch", help="Vacía el chat; tu ruta, lugares y notas se conservan.")
    summ = c2.button("📝 Resumir y limpiar", width="stretch", disabled=not (key and chat["display"]), help="Guarda un resumen en las notas del viaje y vacía el chat.")
    if clear:
        chat.update(messages=[], display=[])
        st.rerun()
    if summ:
        with st.spinner("Resumiendo…"):
            try:
                client = anthropic.Anthropic(api_key=key, max_retries=2, timeout=120)
                text = agent.summarize(client, cfg["model"], chat["display"])
                store.append_note(slug, text)
                chat.update(messages=[], display=[])
                st.toast("Resumen guardado en las notas del viaje")
                st.rerun()
            except anthropic.APIError as e:
                st.error(f"No pude resumir: {e}")

    if not key:
        st.info("Para chatear pega tu clave de Anthropic en ⚙️ Ajustes (barra lateral). El resto de la app funciona sin ella.")

    if not chat["display"]:
        st.caption(f"Pregúntale a {name}:")
        for s in ["¿Cuál es el mejor transporte en la ciudad de mi próxima parada y cuánto cuesta?", "Dónde comer bien y barato en mi próxima parada", "Arma el recorrido de un día con precios de entradas"]:
            st.button(s, key=f"sug_{s[:20]}", on_click=lambda v=s: st.session_state.update(pending_prompt=v), disabled=not key)

    for m in chat["display"]:
        with st.chat_message(m["role"], avatar="🧑‍💻" if m["role"] == "user" else "🧭"):
            st.markdown(m["text"])
            if m.get("tools"):
                st.caption("🔧 " + ", ".join(m["tools"]))

    usage_ph = st.empty()
    prompt = st.chat_input(f"Escríbele a {name}…", disabled=not key) or st.session_state.pop("pending_prompt", None)
    if prompt and key:
        chat["display"].append({"role": "user", "text": prompt})
        with st.chat_message("user", avatar="🧑‍💻"):
            st.markdown(prompt)
        ctx = T.ToolContext(store=store, slug=slug, geo=geo)
        system = agent.build_system(
            name, meta.get("name", slug), meta.get("paises", []),
            [f"{i}. {r['Ciudad']} ({r['País']}) {r['Llegada'] or ''} → {r['Salida'] or ''} hotel: {r['Hotel'] or '-'}" for i, (_, r) in enumerate(route.iterrows(), 1)],
            [f"- {p['nombre']} ({p.get('ciudad', '')}, {p.get('categoria', '')}) {p.get('precio') or ''} {p.get('moneda') or ''}" for p in places[:40]],
            store.read_notes(slug),
        )
        n0 = len(chat["messages"])
        chat["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("assistant", avatar="🧭"):
            status = st.status(f"{name} está pensando…", expanded=False)
            try:
                client = anthropic.Anthropic(api_key=key, max_retries=2, timeout=180)
                res = agent.run_agent(client, cfg["model"], system, chat["messages"], ctx, cfg["max_searches"], cfg["history_turns"], on_tool=lambda n, a: status.write(f"🔧 {n}"))
                status.update(label="Listo", state="complete")
                st.markdown(res.text)
                chat["display"].append({"role": "assistant", "text": res.text, "tools": sorted(set(res.tools_used))})
                chat["in"] += res.input_tokens
                chat["out"] += res.output_tokens
                chat["searches"] += res.searches
                if ctx.changed:
                    bump("route_ver")
                    bump("places_ver")
            except anthropic.AuthenticationError:
                del chat["messages"][n0:]
                status.update(label="Error", state="error")
                st.error("La clave de Anthropic no es válida.")
            except anthropic.RateLimitError:
                del chat["messages"][n0:]
                status.update(label="Error", state="error")
                st.error("Límite de uso alcanzado. Espera un momento e inténtalo de nuevo.")
            except anthropic.APIError as e:
                del chat["messages"][n0:]
                status.update(label="Error", state="error")
                st.error(f"Error de la API: {e}")
    usage_ph.caption(f"Memoria: últimos {cfg['history_turns']} mensajes tuyos · {chat['in'] + chat['out']:,} tokens usados en esta conversación")


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
col_a, col_b = st.columns([3, 1])
slug = col_a.selectbox("Viaje", list(names), format_func=names.get, key="trip_slug", label_visibility="collapsed")
with col_b.popover("＋ Nuevo", width="stretch"):
    st.text_input("Nombre del viaje", key="new_trip_name", placeholder="Ej. Tokio")
    st.button("Crear carpeta", type="primary", on_click=create_trip)

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
