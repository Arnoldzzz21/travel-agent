"""Motor Gemini (API REST de Google AI Studio, capa gratuita).

- Chat con herramientas (clima, cambio, rutas, lugares, Wikivoyage, fichas) y búsqueda con Google.
- La búsqueda con Google ("grounding") es gratis hasta ~500 consultas al día solo en los modelos 2.5 Flash / Flash-Lite
  y no se puede combinar con herramientas propias en la misma llamada, así que `buscar_web` es una llamada aparte.
- Fichas de país: dos investigaciones con búsqueda + un paso que las convierte en JSON.
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
    "Gemini 2.5 Flash (gratis · mejor calidad)": "gemini-2.5-flash",
    "Gemini 2.5 Flash-Lite (gratis · más rápido, más cupo)": "gemini-2.5-flash-lite",
}


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
                 "también puedes cambiar a Gemini 2.5 Flash-Lite, que tiene más cupo.",
        "network": "No pude conectar con Gemini. Revisa tu conexión e inténtalo de nuevo.",
        "blocked": "Gemini no quiso responder a ese mensaje. Reformúlalo e inténtalo de nuevo.",
    }.get(e.kind, f"Error de Gemini: {e}")


class GeminiClient:
    def __init__(self, api_key: str, timeout: int = 120, max_retries: int = 2, session=None, sleep=time.sleep):
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.sleep = sleep

    def generate(self, model: str, contents: list[dict], system: str | None = None, tools: list[dict] | None = None,
                 max_tokens: int = 8192, json_mode: bool = False, thinking_budget: int | None = None) -> dict:
        cfg: dict = {"maxOutputTokens": max_tokens}
        if json_mode:
            cfg["responseMimeType"] = "application/json"
        if thinking_budget is not None:
            cfg["thinkingConfig"] = {"thinkingBudget": thinking_budget}
        body: dict = {"contents": contents, "generationConfig": cfg}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = tools
        url = f"{BASE}/models/{model}:generateContent"
        for attempt in range(self.max_retries + 1):
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
            if r.status_code in (401, 403) or (r.status_code == 400 and "api key" in msg.lower()):
                raise GeminiError("auth", msg)
            if r.status_code in (429, 500, 503) and attempt < self.max_retries and (retry is None or retry <= 20):
                self.sleep(retry if retry else 3 * (attempt + 1))
                continue
            raise GeminiError("quota" if r.status_code == 429 else "other", msg, retry)
        raise GeminiError("other", "Sin respuesta")  # pragma: no cover


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


# ---------------------------------------------------------------- búsqueda con Google
SEARCH_SYSTEM = (
    "Eres un asistente de búsqueda para viajeros. Busca en Google y responde en español, con datos concretos y actuales "
    "(precios con su moneda, fechas, requisitos), indicando de qué sitio sale cada dato. Si algo no está confirmado, "
    "dilo y márcalo como aproximado. Máximo 300 palabras."
)


def grounded_search(client: GeminiClient, model: str, query: str, max_tokens: int = 3000) -> tuple[str, list[tuple[str, str]]]:
    resp = client.generate(
        model, [user_msg(f"Hoy es {date.today().isoformat()}. {query}")], system=SEARCH_SYSTEM,
        tools=[{"google_search": {}}], max_tokens=max_tokens, thinking_budget=0,
    )
    cands = resp.get("candidates") or []
    if not cands:
        return "", []
    return _text(cands[0].get("content") or {}), _grounding(cands[0])


# ---------------------------------------------------------------- bucle del agente
def run_agent(client: GeminiClient, model: str, system: str, messages: list[dict], ctx: T.ToolContext, max_searches: int,
              keep_turns: int = 8, on_tool=None, max_iters: int = 8, max_tokens: int = 8192, append_sources: bool = True) -> agent.AgentResult:
    """Un turno del agente con Gemini. `messages` es el historial en formato Gemini (se modifica)."""
    decls = function_declarations()
    if max_searches > 0:
        decls.append(BUSCAR_WEB)
    tools = [{"functionDeclarations": decls}]
    result = agent.AgentResult(text="")
    sources: dict[str, str] = {}
    final = ""
    for _ in range(max_iters):
        resp = client.generate(model, trim_messages(messages, keep_turns), system=system, tools=tools, max_tokens=max_tokens, thinking_budget=1024)
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
                            txt, srcs = grounded_search(client, model, str(args.get("consulta", "")))
                            for u, t in srcs:
                                sources.setdefault(u, t)
                            res = {"resumen": txt, "fuentes": sorted({t for _, t in srcs})} if txt else {"error": "La búsqueda no devolvió resultados."}
                        except GeminiError as e:
                            if e.kind in ("auth", "quota"):
                                raise
                            res = {"error": f"La búsqueda falló: {e}"}
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
        max_tokens=1500, thinking_budget=0,
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


def generate_ficha(client: GeminiClient, model: str, c, on_step=None) -> dict:
    """Dos investigaciones con búsqueda de Google + un paso que las convierte al JSON de la ficha."""
    rate = None
    if c.display_currency != c.currency:
        r = T.tool_tipo_de_cambio(None, 1, c.currency, c.display_currency)
        rate = r if "resultado" in r else None
    money = _money_rule(c, rate)
    today = date.today().isoformat()
    head = f"País: {c.es} ({c.en}). Hoy es {today}. {money}\nPrioriza sitios oficiales de operadores y autoridades de transporte. Marca como \"aprox.\" lo que no confirmes. Escribe notas ordenadas (viñetas), sin relleno, citando el nombre del sitio y, si lo conoces, su URL."
    topics = [
        "Investiga TRANSPORTE y TARJETAS/PASES: 4 a 7 medios (metro/tranvía, bus, tren interurbano, taxi o apps, aeropuerto→centro) con costo; y tarjetas o abonos de consorcio/operador y pases turísticos, indicando para quién son (turista, residente o todos), precio, vigencia, requisitos y dónde comprarlos.",
        "Investiga PAGOS y PRECIOS: si se paga con tarjeta bancaria o contactless en transporte y comercios, cuándo hace falta efectivo, apps o billeteras útiles; hasta 8 precios típicos (comida económica, restaurante medio, café, cerveza o agua, entrada a una atracción típica, alojamiento medio por noche); y 3 a 5 consejos breves.",
    ]
    notes, sources = [], {}
    for k, t in enumerate(topics, 1):
        if on_step:
            on_step(f"Buscando en Google ({k}/{len(topics)})…")
        txt, srcs = grounded_search(client, model, f"{head}\n\n{t}", max_tokens=6000)
        notes.append(txt)
        for u, title in srcs:
            sources.setdefault(u, title)
    if on_step:
        on_step("Armando la ficha…")
    user = (f"Convierte estas notas de investigación en la ficha de {c.es}. {money}\n"
            "Reglas: usa SOLO datos de las notas; lo no confirmado lleva \"aproximado\": true; no inventes URLs (solo las que aparezcan en las notas, o déjalas vacías); "
            "campos sin información van como cadena vacía. Responde solo con el JSON.\n\n"
            f"NOTAS:\n{chr(10).join(notes)}\n\nFormato exacto del JSON (respeta las claves):\n{ficha_mod.SCHEMA}")
    resp = client.generate(model, [user_msg(user)], system="Eres un editor meticuloso que estructura datos de viaje en JSON válido.",
                           max_tokens=8000, json_mode=True, thinking_budget=0)
    cands = resp.get("candidates") or []
    text = _text(cands[0].get("content") or {}) if cands else ""
    data = ficha_mod.parse_json(text) or {"resumen": "\n\n".join(notes), "_sin_formato": True}
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
