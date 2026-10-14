"""Bucle del agente: Claude + herramientas (tool use) + búsqueda web."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import tools as T

MODELS = {
    "Claude Sonnet 5.5 (recomendado)": "claude-sonnet-5-5",
    "Claude Haiku 5.5 (más barato)": "claude-haiku-5-5",
    "Claude Opus 5.5 (más potente)": "claude-opus-5-5",
}


@dataclass
class AgentResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    searches: int = 0
    tools_used: list[str] = field(default_factory=list)
    sources: list[tuple[str, str]] = field(default_factory=list)  # (url, título)


def build_system(agent_name: str, trip_name: str, countries: list[str], route_rows: list[str], places: list[str], notes: str) -> str:
    notes = notes.strip()[-3000:] if notes else "(sin notas)"
    return f"""Eres {agent_name}, el agente de viajes personal del usuario. Hablas en español (o en el idioma en que te escriba), con tono cercano y directo.
Hoy es {date.today().isoformat()}.

VIAJE ACTUAL: {trip_name}
Países: {", ".join(countries) or "(aún sin definir)"}
Ruta (tabla de la app):
{chr(10).join(route_rows) or "(vacía)"}
Lugares guardados:
{chr(10).join(places) or "(ninguno)"}
Notas del viaje:
{notes}

CÓMO TRABAJAS
- La ruta la elige el usuario; tú la respetas y la mejoras solo si te lo pide.
- Si faltan datos clave (fechas, presupuesto, ritmo, con quién viaja), pregunta lo mínimo antes de armar un itinerario largo.
- Para transporte, pases, pagos y precios típicos de un país, parte de ficha_pais (datos ya investigados, con su fecha) y luego VERIFICA en la web (con la herramienta de búsqueda que tengas) los precios, horarios y requisitos vigentes, citando fuente y fecha. Para describir una ciudad o pueblo usa wikivoyage.
- Si la búsqueda web no está disponible, responde con la ficha y wikivoyage, di que no pudiste verificarlo en la web y marca los precios como "aprox.".
- Si no encuentras un precio, da una estimación razonable y márcala como "aprox."; nunca la presentes como dato confirmado.
- MONEDA: da los precios en la moneda local del país. Única excepción: en Japón conviértelos a dólares estadounidenses (USD), con los yenes entre paréntesis, usando la herramienta tipo_de_cambio.
- TRANSPORTE: cuando el usuario pregunte cómo moverse, recomienda los medios más convenientes para su ruta y di siempre: costo aproximado de cada uno, si se puede pagar con tarjeta bancaria o contactless (o si hay que llevar efectivo / una tarjeta propia de la ciudad), y si existe tarjeta o abono de consorcio/operador para turistas y para residentes (precio, vigencia, requisitos y dónde comprarla, con el enlace oficial).
- Para recorridos usa calcular_ruta: dibuja el mapa en la app y da el enlace de Google Maps. Entre países lejanos (por ejemplo Europa y Japón) ese enlace no cubre vuelos; busca vuelos o trenes en la web.
- Itinerarios por día: horario aproximado, entrada con precio, transporte entre puntos y total estimado del día.
- Guarda lugares (guardar_lugar), paradas (agregar_parada) o notas solo cuando el usuario lo pida o lo confirme.
- Respuestas concisas y fáciles de leer en el celular."""


def trim_messages(messages: list[dict], keep_turns: int) -> list[dict]:
    """Conserva solo los últimos `keep_turns` mensajes reales del usuario (y todo lo que sigue),
    sin separar pares tool_use / tool_result."""
    starts = [i for i, m in enumerate(messages) if m["role"] == "user" and isinstance(m["content"], str)]
    if len(starts) <= keep_turns:
        return messages
    return messages[starts[-keep_turns] :]


def _collect(resp, texts: list[str], sources: dict[str, str]) -> None:
    for b in resp.content:
        if b.type == "text":
            texts.append(b.text)
            for c in getattr(b, "citations", None) or []:
                url = getattr(c, "url", None)
                if url:
                    sources.setdefault(url, getattr(c, "title", None) or url)


def run_agent(client, model: str, system: str, messages: list[dict], ctx: T.ToolContext, max_searches: int, keep_turns: int = 8, on_tool=None, max_iters: int = 10, only_tools: list[str] | None = None, append_sources: bool = True, max_tokens: int = 4096) -> AgentResult:
    """Ejecuta un turno del agente. Modifica `messages` (agrega los mensajes del asistente y de herramientas)."""
    tool_defs = T.build_tools(max_searches, only_tools)
    result = AgentResult(text="")
    last_texts: list[str] = []
    sources: dict[str, str] = {}
    for _ in range(max_iters):
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=tool_defs,
            messages=trim_messages(messages, keep_turns),
        )
        result.input_tokens += resp.usage.input_tokens
        result.output_tokens += resp.usage.output_tokens
        st = getattr(resp.usage, "server_tool_use", None)
        result.searches += getattr(st, "web_search_requests", 0) or 0
        messages.append({"role": "assistant", "content": resp.content})
        last_texts = []
        _collect(resp, last_texts, sources)

        if resp.stop_reason == "tool_use":
            results = []
            for b in resp.content:
                if b.type == "tool_use":
                    if on_tool:
                        on_tool(b.name, b.input)
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": T.execute_tool(ctx, b.name, b.input)})
            messages.append({"role": "user", "content": results})
            continue
        if resp.stop_reason == "pause_turn":  # la búsqueda web necesita más tiempo: continuar
            continue
        if resp.stop_reason == "max_tokens":
            last_texts.append("\n\n_(La respuesta se cortó por longitud; pídeme que continúe.)_")
        break
    else:
        last_texts.append("\n\n_(Llegué al máximo de pasos; pídeme que continúe.)_")

    text = "".join(last_texts).strip() or "No pude generar una respuesta. Intenta de nuevo."
    result.sources = list(sources.items())
    if sources and append_sources:
        text += "\n\n**Fuentes:**\n" + "\n".join(f"- [{t}]({u})" for u, t in list(sources.items())[:8])
    result.text = text
    result.tools_used = list(ctx.used)
    return result


def summarize(client, model: str, transcript: list[dict]) -> str:
    """Resume la conversación (lista de {role, text}) en notas breves para guardar en notas.md."""
    convo = "\n".join(f"{'Usuario' if m['role'] == 'user' else 'Agente'}: {m['text']}" for m in transcript)[-12000:]
    resp = client.messages.create(
        model=model,
        max_tokens=1200,
        system="Resumes conversaciones de planificación de viajes en notas breves en español: decisiones tomadas, lugares y precios con su fuente, pendientes. Viñetas cortas, sin relleno.",
        messages=[{"role": "user", "content": convo or "(conversación vacía)"}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
