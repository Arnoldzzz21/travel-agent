"""Motor Gemini (API REST de Google AI Studio, capa gratuita).

- Chat con herramientas (clima, cambio, rutas, lugares, Wikivoyage, fichas) y búsqueda web.
- Los modelos 2.5 ya no se ofrecen a cuentas nuevas. Con Gemini 3.x la búsqueda de Google NO es gratis en la capa gratuita,
  así que `buscar_web` usa, en este orden: Tavily (1,000 búsquedas gratis al mes, clave opcional) y la búsqueda de Google
  de Gemini (solo funciona si tu proyecto la tiene habilitada). Si ninguna está disponible, el agente responde con las
  fichas base, Wikivoyage y su conocimiento, marcando lo dudoso como aproximado.
- Fichas de país: investigación con búsqueda + un paso que la convierte en JSON; sin búsqueda, versión "sin web" marcada.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date

import requests

import agent
import ficha as ficha_mod
import tools as T

BASE = "https://generativelanguage.googleapis.com/v1beta"

MODELS = {
    "Gemini 3.8 Flash (gratis · mejor calidad)": "gemini-3.8-flash",
    "Gemini 3.5 Flash-Lite (gratis · más rápido)": "gemini-3.5-flash-lite",
}
DEFAULT_MODEL = "gemini-3.8-flash"
RETIRED = ("no longer available", "no longer supported", "is not found", "not supported for generatecontent")


class SearchUnavailable(Exception):
    """No hay ninguna búsqueda web disponible (sin clave de Tavily y sin búsqueda de Google en tu plan)."""


class GeminiError(Exception):
    """kind: auth | quota | blocked | network | other"""

    def __init__(self, kind: str, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after


def friendly(e: GeminiError) -> str:
    return {
        "auth": "La clave de Gemini no es válida o no tiene permiso. Revísala en aistudio.google.com/apikey.",
        "quota": "Se agotó el cupo gratuito de Gemini (por minuto o por día). Espera un momento o prueba mañana; "
                 "también puedes cambiar a Gemini 3.5 Flash-Lite en ⚙️ Ajustes.",
        "network": "No pude conectar con Gemini. Revisa tu conexión e inténtalo de nuevo.",
        "blocked": "Gemini no quiso responder a ese mensaje. Reformúlalo e inténtalo de nuevo.",
    }.get(e.kind, f"Error de Gemini: {e}")


class GeminiClient:
    def __init__(self, api_key: str, timeout: int = 120, max_retries: int = 2, session=None, sleep=time.sleep,
                 tavily_key: str | None = None, search_off: bool = False):
        self.api_key = api_key
        self.tavily_key = tavily_key or None
        self.search_off = search_off  # la búsqueda de Google ya falló antes en esta sesión
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.sleep = sleep

    def generate(self, model: str, contents: list[dict], system: str | None = None, tools: list[dict] | None = None,
                 max_tokens: int = 8192, json_mode: bool = False, thinking: str | None = None) -> dict:
        """thinking: None (por defecto del modelo), "off" (lo mínimo posible) o "low"."""
        cfg: dict = {"maxOutputTokens": max_tokens}
        if json_mode:
            cfg["responseMimeType"] = "application/json"
        think = _thinking_cfg(model, thinking)
        if think:
            cfg["thinkingConfig"] = think
        body: dict = {"contents": contents, "generationConfig": cfg}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = tools
        url = f"{BASE}/models/{model}:generateContent"
        switched = False
        for attempt in range(self.max_retries + 2):
            try:
                r = self.session.post(url, json=body, headers={"x-goog-api-key": self.api_key}, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt < self.max_retries:
                    self.sleep(2)
                    continue
                raise GeminiError("network", str(e)) from e
            if r.status_code == 200:
                return r.json()
            msg, retry = _error_info(r)
            low = msg.lower()
            if r.status_code in (400, 404) and "thinking" in low and "thinkingConfig" in cfg:  # modelo que no acepta ese ajuste
                cfg.pop("thinkingConfig")
                continue
            if r.status_code in (400, 404) and any(x in low for x in RETIRED) and model != DEFAULT_MODEL and not switched:
                model, switched = DEFAULT_MODEL, True  # modelo retirado (p. ej. un 2.5 guardado en Ajustes): pasa al vigente
                url = f"{BASE}/models/{model}:generateContent"
                continue
            if r.status_code in (401, 403) or (r.status_code == 400 and "api key" in low):
                raise GeminiError("auth", msg)
            if r.status_code in (429, 500, 503) and attempt < self.max_retries and (retry is None or retry <= 20):
                self.sleep(retry if retry else 3 * (attempt + 1))
                continue
            raise GeminiError("quota" if r.status_code == 429 else "other", msg, retry)
        raise GeminiError("other", "Sin respuesta")  # pragma: no cover


def _thinking_cfg(model: str, level: str | None) -> dict | None:
    """Gemini 2.5 usa un presupuesto de tokens; Gemini 3.x usa niveles (el más bajo documentado es "low")."""
    if level is None:
        return None
    if model.startswith("gemini-2.5"):
        return {"thinkingBudget": 0 if level == "off" else 1024}
    return {"thinkingLevel": "low"}


def _error_info(r) -> tuple[str, float | None]:
    try:
        err = r.json().get("error", {})
    except ValueError:
        return f"HTTP {r.status_code}", None
    retry = None
    for d in err.get("details", []) or []:
        m = re.match(r"([\d.]+)s", str(d.get("retryDelay", "")))
        if m:
            retry = float(m.group(1))
    return str(err.get("message") or f"HTTP {r.status_code}"), retry


# ---------------------------------------------------------------- helpers de formato
def function_declarations(only: list[str] | None = None) -> list[dict]:
    return [
        {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}
        for t in T.TOOLS
        if only is None or t["name"] in only
    ]


BUSCAR_WEB = {
    "name": "buscar_web",
    "description": "Busca en Google información actual: precios, tarifas, horarios, requisitos, apertura de lugares, noticias. Devuelve un resumen con fuentes. Úsala cuando ficha_pais y wikivoyage no alcancen.",
    "parameters": {"type": "object", "properties": {"consulta": {"type": "string", "description": "Qué buscar, con ciudad/país y año si importa"}}, "required": ["consulta"]},
}


def _parts(content: dict) -> list[dict]:
    return (content or {}).get("parts") or []


def _text(content: dict) -> str:
    return "".join(p.get("text", "") for p in _parts(content) if not p.get("thought")).strip()


def _grounding(cand: dict) -> list[tuple[str, str]]:
    out = []
    for ch in (cand.get("groundingMetadata") or {}).get("groundingChunks") or []:
        w = ch.get("web") or {}
        if w.get("uri"):
            out.append((w["uri"], w.get("title") or w["uri"]))
    return out


def _usage(resp: dict) -> tuple[int, int]:
    u = resp.get("usageMetadata") or {}
    return int(u.get("promptTokenCount", 0)), int(u.get("candidatesTokenCount", 0)) + int(u.get("thoughtsTokenCount", 0))


def trim_messages(messages: list[dict], keep_turns: int) -> list[dict]:
    """Conserva los últimos `keep_turns` mensajes del usuario (texto) sin separar functionCall/functionResponse."""
    starts = [i for i, m in enumerate(messages) if m["role"] == "user" and any("text" in p for p in _parts(m))]
    if len(starts) <= keep_turns:
        return messages
    return messages[starts[-keep_turns]:]


def user_msg(text: str) -> dict:
    return {"role": "user", "parts": [{"text": text}]}


# ---------------------------------------------------------------- búsqueda web
SEARCH_SYSTEM = (
    "Eres un asistente de búsqueda para viajeros. Busca en Google y responde en español, con datos concretos y actuales "
    "(precios con su moneda, fechas, requisitos), indicando de qué sitio sale cada dato. Si algo no está confirmado, "
    "dilo y márcalo como aproximado. Máximo 300 palabras."
)


def grounded_search(client: GeminiClient, model: str, query: str, max_tokens: int = 3000) -> tuple[str, list[tuple[str, str]]]:
    """Búsqueda de Google a través de Gemini. En la capa gratuita de Gemini 3.x no está disponible."""
    resp = client.generate(
        model, [user_msg(f"Hoy es {date.today().isoformat()}. {query}")], system=SEARCH_SYSTEM,
        tools=[{"google_search": {}}], max_tokens=max_tokens, thinking="off",
    )
    cands = resp.get("candidates") or []
    if not cands:
        return "", []
    return _text(cands[0].get("content") or {}), _grounding(cands[0])


def tavily_search(client: GeminiClient, query: str, max_results: int = 5) -> tuple[str, list[tuple[str, str]]]:
    """Tavily: 1,000 búsquedas gratis al mes con una clave gratuita (tavily.com)."""
    try:
        r = client.session.post(
            "https://api.tavily.com/search",
            json={"query": query, "max_results": max_results, "include_answer": "basic", "search_depth": "basic"},
            headers={"Authorization": f"Bearer {client.tavily_key}"}, timeout=40,
        )
    except requests.RequestException as e:
        raise SearchUnavailable(f"Tavily sin conexión: {e}") from e
    if r.status_code != 200:
        raise SearchUnavailable(f"Tavily respondió {r.status_code} (clave inválida o cupo mensual agotado)")
    d = r.json()
    results = d.get("results") or []
    lines = [f"Respuesta: {d['answer']}"] if d.get("answer") else []
    lines += [f"- {x.get('title', '')} ({x.get('url', '')}): {str(x.get('content', ''))[:450]}" for x in results]
    return "\n".join(lines), [(x["url"], x.get("title") or x["url"]) for x in results if x.get("url")]


def web_search(client: GeminiClient, model: str, query: str, max_tokens: int = 3000) -> tuple[str, list[tuple[str, str]]]:
    """Tavily si hay clave; si no, la búsqueda de Google de Gemini. Lanza SearchUnavailable si ninguna sirve."""
    if client.tavily_key:
        try:
            return tavily_search(client, query)
        except SearchUnavailable:
            if client.search_off:
                raise
    if client.search_off:
        raise SearchUnavailable("La búsqueda de Google no está disponible en tu plan de Gemini.")
    try:
        return grounded_search(client, model, query, max_tokens)
    except GeminiError as e:
        client.search_off = True
        raise SearchUnavailable(str(e)) from e


# ---------------------------------------------------------------- bucle del agente
def run_agent(client: GeminiClient, model: str, system: str, messages: list[dict], ctx: T.ToolContext, max_searches: int,
              keep_turns: int = 8, on_tool=None, max_iters: int = 8, max_tokens: int = 8192, append_sources: bool = True) -> agent.AgentResult:
    """Un turno del agente con Gemini. `messages` es el historial en formato Gemini (se modifica)."""
    def make_tools() -> list[dict]:
        decls = function_declarations()
        if max_searches > 0 and not (client.search_off and not client.tavily_key):
            decls.append(BUSCAR_WEB)
        return [{"functionDeclarations": decls}]

    tools = make_tools()
    result = agent.AgentResult(text="")
    sources: dict[str, str] = {}
    final = ""
    search_failed = False
    for _ in range(max_iters):
        resp = client.generate(model, trim_messages(messages, keep_turns), system=system, tools=tools, max_tokens=max_tokens, thinking="low")
        i, o = _usage(resp)
        result.input_tokens += i
        result.output_tokens += o
        cands = resp.get("candidates") or []
        if not cands:
            reason = (resp.get("promptFeedback") or {}).get("blockReason")
            raise GeminiError("blocked", f"Sin respuesta ({reason or 'sin motivo'})")
        cand = cands[0]
        content = dict(cand.get("content") or {})
        content["role"] = "model"
        content.setdefault("parts", [])
        messages.append(content)
        calls = [p["functionCall"] for p in content["parts"] if "functionCall" in p]
        if calls:
            out_parts = []
            for fc in calls:
                name, args = fc.get("name", ""), fc.get("args") or {}
                if on_tool:
                    on_tool(name, args)
                if name == "buscar_web":
                    ctx.used.append("buscar_web")
                    if result.searches >= max_searches:
                        res = {"error": "Ya usaste todas las búsquedas web permitidas para esta respuesta; responde con lo que tienes y marca lo dudoso como aproximado."}
                    else:
                        result.searches += 1
                        try:
                            txt, srcs = web_search(client, model, str(args.get("consulta", "")))
                            for u, t in srcs:
                                sources.setdefault(u, t)
                            res = {"resumen": txt, "fuentes": sorted({t for _, t in srcs})} if txt else {"error": "La búsqueda no devolvió resultados."}
                        except SearchUnavailable:
                            search_failed = True
                            res = {"error": "La búsqueda web no está disponible. Responde con ficha_pais, wikivoyage y lo que sabes, marcando lo dudoso como aproximado y sin inventar precios exactos."}
                            tools = make_tools()
                else:
                    res = json.loads(T.execute_tool(ctx, name, args))
                part = {"functionResponse": {"name": name, "response": {"output": res}}}
                if fc.get("id"):
                    part["functionResponse"]["id"] = fc["id"]
                out_parts.append(part)
            messages.append({"role": "user", "parts": out_parts})
            continue
        final = _text(content)
        if cand.get("finishReason") == "MAX_TOKENS":
            final += "\n\n_(La respuesta se cortó por longitud; pídeme que continúe.)_"
        break
    else:
        final = "_(Llegué al máximo de pasos; pídeme que continúe.)_"

    text = final.strip() or "No pude generar una respuesta. Intenta de nuevo."
    if search_failed:
        text += "\n\n_ℹ️ La búsqueda web no estuvo disponible (en el plan gratis de Gemini 3 no incluye búsqueda de Google). Usé las fichas, Wikivoyage y mi conocimiento: confirma los precios antes de pagar._"
    result.sources = list(sources.items())
    if sources and append_sources:
        text += "\n\n**Fuentes:**\n" + "\n".join(f"- [{t}]({u})" for u, t in list(sources.items())[:6])
    result.text = text
    result.tools_used = list(ctx.used)
    return result


def summarize(client: GeminiClient, model: str, transcript: list[dict]) -> str:
    convo = "\n".join(f"{'Usuario' if m['role'] == 'user' else 'Agente'}: {m['text']}" for m in transcript)[-12000:]
    resp = client.generate(
        model, [user_msg(convo or "(conversación vacía)")],
        system="Resumes conversaciones de planificación de viajes en notas breves en español: decisiones tomadas, lugares y precios con su fuente, pendientes. Viñetas cortas, sin relleno.",
        max_tokens=1500, thinking="off",
    )
    cands = resp.get("candidates") or []
    return _text(cands[0].get("content") or {}) if cands else ""


# ---------------------------------------------------------------- fichas de país
def _money_rule(c, rate: dict | None) -> str:
    if c.display_currency != c.currency:
        base = (f"MONEDA: la moneda local es {c.currency}, pero TODOS los precios van en {c.display_currency} "
                f"con el monto en {c.currency} entre paréntesis (ej. \"USD 1.40 (¥210)\").")
        if rate:
            base += f" Usa esta tasa: 1 {c.currency} = {rate['resultado']} {c.display_currency} (BCE, {rate['fecha']})."
        return base
    return f"MONEDA: todos los precios van en la moneda local de {c.es}, que debería ser {c.currency or 'la vigente'}. No conviertas a otra moneda."


def _wiki_notes(c) -> str:
    """Texto libre de Wikivoyage sobre cómo moverse por el país (sin costo, sin clave)."""
    out = []
    for lugar, sec, lang in ((c.es, "Moverse", "es"), (c.en, "Get around", "en")):
        r = T.tool_wikivoyage(None, lugar, sec, lang)
        if r.get("contenido"):
            out.append(f"[Wikivoyage: {r['lugar']}]\n{r['contenido'][:3500]}")
            break
    return "\n\n".join(out)


def generate_ficha(client: GeminiClient, model: str, c, on_step=None) -> dict:
    """Investiga con búsqueda web (Tavily o Google) y estructura el resultado. Sin búsqueda disponible,
    arma una versión con Wikivoyage y el conocimiento del modelo, con todo marcado como aproximado."""
    rate = None
    if c.display_currency != c.currency:
        r = T.tool_tipo_de_cambio(None, 1, c.currency, c.display_currency)
        rate = r if "resultado" in r else None
    money = _money_rule(c, rate)
    today = date.today().isoformat()
    head = f"País: {c.es} ({c.en}). Hoy es {today}. {money}\nPrioriza sitios oficiales de operadores y autoridades de transporte. Marca como \"aprox.\" lo que no confirmes. Escribe notas ordenadas (viñetas), sin relleno, citando el nombre del sitio y, si lo conoces, su URL."
    topics = [
        "Investiga TRANSPORTE: 4 a 7 medios (metro/tranvía, bus, tren interurbano, taxi o apps, aeropuerto→centro) con su costo actual.",
        "Investiga TARJETAS Y PASES: tarjetas o abonos de consorcio/operador y pases turísticos, indicando para quién son (turista, residente o todos), precio, vigencia, requisitos y dónde comprarlos, con el enlace oficial.",
        "Investiga PAGOS Y PRECIOS: si se paga con tarjeta bancaria o contactless en transporte y comercios, cuándo hace falta efectivo, apps o billeteras útiles; hasta 8 precios típicos (comida económica, restaurante medio, café, cerveza o agua, entrada a una atracción típica, alojamiento medio por noche); y 3 a 5 consejos breves.",
    ]
    notes, sources, sin_web = [], {}, False
    for k, t in enumerate(topics, 1):
        if on_step:
            on_step(f"Buscando en la web ({k}/{len(topics)})…")
        try:
            txt, srcs = web_search(client, model, f"{head}\n\n{t}", max_tokens=6000)
        except SearchUnavailable:
            sin_web = True
            break
        notes.append(txt)
        for u, title in srcs:
            sources.setdefault(u, title)
    if sin_web:
        if on_step:
            on_step("Sin búsqueda web: uso Wikivoyage y conocimiento del modelo…")
        wiki = _wiki_notes(c)
        if wiki:
            sources[f"https://{'es' if 'es.wikivoyage' in wiki else 'en'}.wikivoyage.org/wiki/{c.es}"] = "Wikivoyage"
        notes = [wiki or "(sin notas externas)",
                 "No hay búsqueda web: completa con lo que sabes y marca TODOS los precios como aproximados; no inventes URLs."]
    if on_step:
        on_step("Armando la ficha…")
    user = (f"Convierte estas notas de investigación en la ficha de {c.es}. {money}\n"
            "Reglas: usa SOLO datos de las notas" + (" y tu conocimiento general (todo con \"aproximado\": true)" if sin_web else "")
            + "; lo no confirmado lleva \"aproximado\": true; no inventes URLs (solo las que aparezcan en las notas, o déjalas vacías); "
            "campos sin información van como cadena vacía. Responde solo con el JSON.\n\n"
            f"NOTAS:\n{chr(10).join(notes)}\n\nFormato exacto del JSON (respeta las claves):\n{ficha_mod.SCHEMA}")
    resp = client.generate(model, [user_msg(user)], system="Eres un editor meticuloso que estructura datos de viaje en JSON válido.",
                           max_tokens=8000, json_mode=True, thinking="off")
    cands = resp.get("candidates") or []
    text = _text(cands[0].get("content") or {}) if cands else ""
    data = ficha_mod.parse_json(text) or {"resumen": "\n\n".join(notes), "_sin_formato": True}
    if sin_web:  # nada está confirmado: que la interfaz lo muestre
        for it in (data.get("transporte") or []) + (data.get("precios_tipicos") or []):
            if isinstance(it, dict):
                it["aproximado"] = True
        data["_sin_busqueda"] = True
    seen, fuentes = set(), []
    for f in list(data.get("fuentes") or []) + [{"titulo": t, "url": u} for u, t in sources.items()]:
        url = (f or {}).get("url", "")
        if url and url not in seen:
            seen.add(url)
            fuentes.append({"titulo": f.get("titulo") or url, "url": url})
    data["fuentes"] = fuentes[:12]
    data["pais_iso"] = c.iso
    data["fecha_consulta"] = today
    data["_motor"] = "gemini"
    return data
