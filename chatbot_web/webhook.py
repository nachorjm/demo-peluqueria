"""
webhook.py — Router FastAPI del chatbot web de Casa Lola
--------------------------------------------------------
Endpoint publico: POST /web/chat
  - Body JSON: { "session_id": "...", "message": "..." }
  - Response JSON: { "session_id": "...", "reply": "..." }

Si el cliente no envia session_id, se genera uno nuevo y se devuelve.
El frontend lo guarda en localStorage para mantener memoria entre
recargas.
"""
import uuid
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from core.config import claude, supabase, MODEL, MAX_TOKENS, MAX_HISTORY_MESSAGES, TEMPERATURE
from core.logger import get_logger
from core.prompts import prompt_web

log = get_logger(__name__)
from core.guardrails import (
    detectar_alucinacion,
    reply_recovery_para,
    mensaje_auto_retry,
)
from core.lang_detect import detectar_idioma, bloque_idioma_para_prompt
from chatbot_web.tools import TOOLS, ejecutar_tool


# Estados "exitosos" que cuenta cada tool. Si el resultado contiene uno
# de estos strings en su campo 'status', la tool se considera ejecutada
# correctamente y no dispara el guardrail.
_ESTADOS_EXITO_POR_TOOL = {
    "reservar_mesa": {"creada", "actualizada", "sin_cambios"},
    "modificar_reserva": {"actualizada", "sin_cambios"},
    "cancelar_reserva": {"cancelada", "ya_cancelada"},
    "escalar_a_humano": {"ok"},
    "derivar_a_whatsapp": {"ok"},
    "apuntar_lista_espera": {"ok", "ya_en_lista"},
}


def _tool_ejecutada_ok(tool_name: str, resultado_str: str) -> bool:
    """
    True si el resultado de la tool indica exito real (segun estados
    definidos por tool).
    """
    if not resultado_str:
        return False
    estados = _ESTADOS_EXITO_POR_TOOL.get(tool_name)
    if not estados:
        # Tools de lectura (consultar_*): no trackeamos estado.
        return False
    s = resultado_str.lower()
    for estado in estados:
        if f"'status': '{estado}'" in s or f'"status": "{estado}"' in s:
            return True
    return False


# ─── 2. Memoria en Supabase ─────────────────────────────────────────
def cargar_historial(session_id: str, limite: int = MAX_HISTORY_MESSAGES) -> list[dict]:
    try:
        res = (
            supabase.table("web_conversaciones")
            .select("role, content")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .limit(limite)
            .execute()
        )
        mensajes = list(reversed(res.data))
        return [{"role": m["role"], "content": m["content"]} for m in mensajes]
    except Exception as e:
        log.warning("Error cargando historial web: %s", e)
        return []


def guardar_mensaje(session_id: str, role: str, content: str) -> None:
    try:
        supabase.table("web_conversaciones").insert({
            "session_id": session_id,
            "role": role,
            "content": content,
        }).execute()
    except Exception as e:
        log.warning("Error guardando mensaje web: %s", e)


# ─── 3. Schema del request ──────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = Field(default=None, max_length=64)


# ─── 4. Router FastAPI ──────────────────────────────────────────────
router = APIRouter()


@router.post("/web/chat")
async def web_chat(payload: ChatRequest):
    """Recibe mensaje del visitante -> Claude (con tools) -> respuesta JSON."""
    session_id = payload.session_id or uuid.uuid4().hex
    user_msg = payload.message.strip()

    log.info("[web] Mensaje recibido | Session: %s | Texto: %s%s",
             session_id, user_msg[:120], "..." if len(user_msg) > 120 else "")

    historial = cargar_historial(session_id)
    log.info("[web] Historial: %d mensajes previos", len(historial))

    mensajes = historial + [{"role": "user", "content": user_msg}]

    # Multi-idioma (issue #9): detectamos idioma del mensaje. Si no es
    # espanol, anadimos al system prompt un bloque que pide responder
    # en el idioma del cliente. Tools y datos siguen en espanol; Claude
    # traduce al responder. Pasamos el historial para que frases cortas
    # con nombres propios no alteren el idioma del flujo (QA bug round 1).
    idioma_detectado = detectar_idioma(user_msg, historial=historial)
    bloque_idioma = bloque_idioma_para_prompt(idioma_detectado)
    if idioma_detectado != "es":
        log.info("[web] Idioma detectado: %s", idioma_detectado)

    reply_text = None
    tools_ok: set = set()

    def _ejecutar_ciclo(mensajes_in: list, tools_ok_set: set, max_iter: int = 5):
        """Bucle de tool use. Actualiza tools_ok_set y devuelve reply final."""
        reply = None
        for _ in range(max_iter):
            response = claude.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                system=prompt_web() + bloque_idioma,
                tools=TOOLS,
                messages=mensajes_in,
            )
            if response.stop_reason != "tool_use":
                text_blocks = [b.text for b in response.content if b.type == "text"]
                reply = "\n".join(text_blocks).strip()
                break
            mensajes_in.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    resultado = ejecutar_tool(block.name, block.input, session_id)
                    if _tool_ejecutada_ok(block.name, resultado):
                        tools_ok_set.add(block.name)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": resultado,
                    })
            mensajes_in.append({"role": "user", "content": tool_results})
        return reply

    try:
        reply_text = _ejecutar_ciclo(mensajes, tools_ok)

        if reply_text is None:
            reply_text = (
                "Lo siento, he tenido un problema procesando tu solicitud. "
                "¿Puedes intentarlo de nuevo?"
            )

        # GUARDRAIL anti-alucinacion (issues #20, #22). Si el bot afirma
        # una accion sin haber ejecutado la tool, hacemos 1 auto-retry
        # con un aviso interno. Solo damos por buena la respuesta si la
        # tool ESPERADA se ejecuto realmente; si Claude eligio otra
        # tool o ninguna, aplicamos recovery. Pasamos `historial` (sin
        # incluir este turno) para evitar falsos positivos en preguntas
        # pasivas sobre acciones ya hechas en turnos previos (#49).
        tool_alucinada = detectar_alucinacion(reply_text, tools_ok, historial=historial)
        if tool_alucinada:
            log.warning("[GUARDRAIL] Alucinacion '%s' detectada. Auto-retry. Reply original: %s",
                        tool_alucinada, reply_text[:200])
            mensajes.append({"role": "assistant", "content": reply_text})
            mensajes.append({"role": "user", "content": mensaje_auto_retry(tool_alucinada)})
            reply_text2 = _ejecutar_ciclo(mensajes, tools_ok, max_iter=3)
            if reply_text2 and tool_alucinada in tools_ok:
                log.info("[GUARDRAIL] Auto-retry exitoso: %s ejecutada.", tool_alucinada)
                reply_text = reply_text2
            else:
                ejecutadas = ", ".join(tools_ok) or "ninguna"
                log.warning("[GUARDRAIL] Auto-retry fallo. Esperada: %s. Ejecutadas: %s. Aplicando recovery.",
                            tool_alucinada, ejecutadas)
                reply_text = reply_recovery_para(tool_alucinada)

        log.info("[web] Reply: %s%s", reply_text[:150], "..." if len(reply_text) > 150 else "")

        guardar_mensaje(session_id, "user", user_msg)
        guardar_mensaje(session_id, "assistant", reply_text)

    except Exception as e:
        log.error("ERROR en /web/chat: %s", e, exc_info=True)
        reply_text = (
            "Lo siento, ha habido un problema procesando tu mensaje. "
            "Intentalo de nuevo en un momento."
        )

    return {
        "session_id": session_id,
        "reply": reply_text,
    }
