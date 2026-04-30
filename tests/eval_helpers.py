"""
Helpers para tests evals (issue #12).

Los evals validan COMPORTAMIENTO del bot ante escenarios concretos.
Llaman a Claude REAL (no FakeClaude) para detectar regresiones cuando
tocamos prompts.

Las tools (Supabase, Twilio, Resend) siguen mockeadas via conftest
porque solo nos interesa lo que dice/hace el modelo, no escribir BD
real ni mandar emails reales.

Uso:
    @pytest.mark.eval
    def test_eval_saludo_web():
        r = correr_eval_web([{"role": "user", "content": "hola"}])
        assert_no_tool_called(r)
        assert_reply_contains_any(r, ["reservar", "carta", "horario"])
"""
import os
from typing import Any, Dict, List

import pytest


def _key_anthropic_real() -> str:
    """
    Devuelve la API key de Anthropic REAL leida del .env del repo.
    Conftest pisa os.environ['ANTHROPIC_API_KEY'] con dummy para que los
    smoke tests no toquen la API. Para evals leemos directo del .env
    para evitar el pisado.
    """
    try:
        from dotenv import dotenv_values
        env = dotenv_values(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            os.pardir,
            ".env",
        ))
        key = (env.get("ANTHROPIC_API_KEY") or "").strip()
    except Exception:
        key = ""
    return key


def _claude_real():
    """Cliente Anthropic real, o pytest.skip si no hay key valida."""
    key = _key_anthropic_real()
    if not key or key.startswith("sk-test") or key.startswith("PEGA_"):
        pytest.skip("Evals requieren ANTHROPIC_API_KEY real en .env")
    from anthropic import Anthropic
    return Anthropic(api_key=key)


# ════════════════════════════════════════════════════════════════════
# Runner: ejecuta una conversacion contra Claude real con prompt y tools
# ════════════════════════════════════════════════════════════════════

def _correr_conversacion(prompt_system: str, mensajes: List[Dict],
                         tools_catalogo, ejecutar_tool_fn,
                         contexto_id: str = "eval_session") -> Dict[str, Any]:
    """
    Ejecuta el bucle tool_use contra Claude real.

    Returns:
        {
          "reply": str,                       # ultimo mensaje del bot
          "tools": [{"name": str, "input": dict}],  # tools llamadas
          "iteraciones": int,                 # vueltas del bucle
        }
    """
    client = _claude_real()
    tools_llamadas = []
    reply = ""
    iteraciones = 0
    max_iter = 5

    historial = list(mensajes)

    for _ in range(max_iter):
        iteraciones += 1
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=500,
            temperature=0.3,
            system=prompt_system,
            tools=tools_catalogo,
            messages=historial,
        )
        if response.stop_reason != "tool_use":
            text_blocks = [b.text for b in response.content if b.type == "text"]
            reply = "\n".join(text_blocks).strip()
            break

        historial.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tools_llamadas.append({"name": block.name, "input": block.input})
                resultado = ejecutar_tool_fn(block.name, block.input, contexto_id)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": resultado,
                })
        historial.append({"role": "user", "content": tool_results})

    return {"reply": reply, "tools": tools_llamadas, "iteraciones": iteraciones}


def correr_eval_web(mensajes: List[Dict]) -> Dict[str, Any]:
    """Eval para chatbot WEB. Mensajes son lista de dicts {role, content}."""
    from core.prompts import prompt_web
    from core.lang_detect import detectar_idioma, bloque_idioma_para_prompt
    from chatbot_web.tools import TOOLS, ejecutar_tool

    # Replicar logica del webhook: detectar idioma del primer mensaje user.
    primer_user = next((m["content"] for m in mensajes if m["role"] == "user"), "")
    idioma = detectar_idioma(primer_user)
    bloque = bloque_idioma_para_prompt(idioma)

    return _correr_conversacion(
        prompt_system=prompt_web() + bloque,
        mensajes=mensajes,
        tools_catalogo=TOOLS,
        ejecutar_tool_fn=ejecutar_tool,
        contexto_id="eval_web",
    )


def correr_eval_whatsapp(mensajes: List[Dict]) -> Dict[str, Any]:
    """Eval para chatbot WhatsApp."""
    from core.prompts import prompt_whatsapp
    from core.lang_detect import detectar_idioma, bloque_idioma_para_prompt
    from chatbot_whatsapp.tools import TOOLS, ejecutar_tool

    primer_user = next((m["content"] for m in mensajes if m["role"] == "user"), "")
    idioma = detectar_idioma(primer_user)
    bloque = bloque_idioma_para_prompt(idioma)

    return _correr_conversacion(
        prompt_system=prompt_whatsapp() + bloque,
        mensajes=mensajes,
        tools_catalogo=TOOLS,
        ejecutar_tool_fn=ejecutar_tool,
        contexto_id="whatsapp:+34600000000",
    )


# ════════════════════════════════════════════════════════════════════
# Asserts compuestos
# ════════════════════════════════════════════════════════════════════

def assert_no_tool_called(r: Dict, name: str = None):
    nombres = [t["name"] for t in r["tools"]]
    if name is None:
        assert not r["tools"], f"No esperabamos tools, se llamaron: {nombres}"
    else:
        assert name not in nombres, f"No esperabamos tool '{name}', se llamaron: {nombres}"


def assert_tool_called(r: Dict, name: str):
    nombres = [t["name"] for t in r["tools"]]
    assert name in nombres, f"Esperabamos tool '{name}'; se llamaron: {nombres}"


def assert_reply_contains_any(r: Dict, opciones: List[str]):
    reply = r["reply"].lower()
    assert any(o.lower() in reply for o in opciones), (
        f"Reply no contiene NINGUNA de {opciones}.\nReply: {r['reply']}"
    )


def assert_reply_contains_all(r: Dict, fragmentos: List[str]):
    reply = r["reply"].lower()
    faltan = [f for f in fragmentos if f.lower() not in reply]
    assert not faltan, f"Reply no contiene {faltan}.\nReply: {r['reply']}"


def assert_reply_no_contiene(r: Dict, texto: str):
    assert texto.lower() not in r["reply"].lower(), (
        f"Reply contiene '{texto}' (no debia).\nReply: {r['reply']}"
    )


def assert_reply_no_contiene_any(r: Dict, prohibidos: List[str]):
    encontrados = [p for p in prohibidos if p.lower() in r["reply"].lower()]
    assert not encontrados, (
        f"Reply contiene {encontrados} (no debia).\nReply: {r['reply']}"
    )
