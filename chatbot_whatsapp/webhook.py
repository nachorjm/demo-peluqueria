"""
webhook.py — Router FastAPI del chatbot WhatsApp de Salon Mara
--------------------------------------------------------------
Endpoints publicos:
  - POST /whatsapp        (Twilio sandbox, form-data + TwiML)
  - GET  /whatsapp/meta   (handshake Meta Cloud API)
  - POST /whatsapp/meta   (Meta Cloud API, JSON)

Flujo:
  1. Recibe mensajes de WhatsApp.
  2. Carga el historial del telefono desde Supabase.
  3. Si el telefono tiene un seguimiento pendiente desde una llamada de
     voz (Mara no pudo capturar un dato), se inyecta contexto extra.
  4. Envia mensaje + historial + tools a Claude.
  5. Si Claude pide tool, se ejecuta y se vuelve a llamar a Claude.
  6. Guarda en Supabase y responde via TwiML (Twilio) o POST async (Meta).
"""
import re
from typing import Optional

from fastapi import APIRouter, Form, Request, Response

from core.config import claude, supabase, MODEL, MAX_TOKENS, MAX_HISTORY_MESSAGES, TEMPERATURE
from core.logger import get_logger
from core.memory import _normalizar_telefono

log = get_logger(__name__)
from core.messaging.twilio_provider import TwilioProvider
from core.messaging.meta_provider import MetaProvider
from core.prompts import prompt_whatsapp
from core.guardrails import (
    detectar_alucinacion,
    reply_recovery_para,
    mensaje_auto_retry,
)
from core.lang_detect import detectar_idioma, bloque_idioma_para_prompt
from chatbot_whatsapp.tools import TOOLS, ejecutar_tool


_ESTADOS_EXITO_POR_TOOL = {
    "agendar_cita": {"creada", "actualizada", "sin_cambios", "duplicada"},
    "modificar_cita": {"actualizada", "sin_cambios"},
    "cancelar_cita": {"cancelada", "ya_cancelada"},
    "escalar_a_humano": {"ok"},
    "derivar_a_whatsapp": {"ok"},
}


def _tool_ejecutada_ok(tool_name: str, resultado_str: str) -> bool:
    if not resultado_str:
        return False
    estados = _ESTADOS_EXITO_POR_TOOL.get(tool_name)
    if not estados:
        return False
    s = resultado_str.lower()
    for estado in estados:
        if f"'status': '{estado}'" in s or f'"status": "{estado}"' in s:
            return True
    return False


def _normalizar_asteriscos_wa(texto: str) -> str:
    """
    WhatsApp solo renderiza negrita con UN asterisco a cada lado (*asi*),
    no con dos (**asi**). Convertimos `**...**` a `*...*` antes de enviar.
    """
    if not texto:
        return texto
    return re.sub(r"\*\*(.+?)\*\*", r"*\1*", texto, flags=re.DOTALL)


# ─── 2. Memoria en Supabase ─────────────────────────────────────────
def cargar_historial(telefono: str, limite: int = MAX_HISTORY_MESSAGES) -> list:
    try:
        res = (
            supabase.table("whatsapp_conversaciones")
            .select("role, content")
            .eq("telefono", telefono)
            .order("created_at", desc=True)
            .limit(limite)
            .execute()
        )
        mensajes = list(reversed(res.data))
        return [{"role": m["role"], "content": m["content"]} for m in mensajes]
    except Exception as e:
        log.warning("Error cargando historial: %s", e)
        return []


def guardar_mensaje(telefono: str, role: str, content: str) -> None:
    try:
        supabase.table("whatsapp_conversaciones").insert({
            "telefono": telefono,
            "role": role,
            "content": content,
        }).execute()
    except Exception as e:
        log.warning("Error guardando mensaje: %s", e)


# ─── 3. Seguimientos pendientes (handoff voz -> WhatsApp) ───────────
def cargar_seguimiento_pendiente(telefono: str) -> Optional[dict]:
    """
    Busca un seguimiento pendiente para este telefono (viene de una
    llamada de voz en la que Mara no pudo capturar un dato).
    """
    tel_limpio = _normalizar_telefono(telefono)
    if not tel_limpio:
        return None
    try:
        res = (
            supabase.table("seguimientos_pendientes")
            .select("*")
            .eq("telefono", tel_limpio)
            .eq("estado", "pendiente")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]
        return None
    except Exception as e:
        log.warning("Error cargando seguimiento pendiente: %s", e)
        return None


def marcar_seguimiento_completado(seguimiento_id: str) -> None:
    try:
        from datetime import datetime, timezone
        supabase.table("seguimientos_pendientes").update({
            "estado": "completado",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", seguimiento_id).execute()
        log.info("Seguimiento %s marcado como completado.", seguimiento_id)
    except Exception as e:
        log.warning("Error marcando seguimiento completado: %s", e)


def construir_contexto_cliente_recurrente(telefono: str) -> str:
    """
    Si el cliente tiene historial relevante, devuelve un bloque de contexto
    para anadir al system prompt. Personaliza el saludo. Si no hay datos,
    devuelve cadena vacia.
    """
    from core.citas import historial_cliente_resumen
    info = historial_cliente_resumen(telefono)
    if not info["es_recurrente"] and not info["citas_futuras"]:
        return ""

    bloques = ["\n\n═══════════════════════════════════════════════════════════",
               "CONTEXTO DEL CLIENTE — historial reciente:",
               "═══════════════════════════════════════════════════════════"]

    nombre = info.get("nombre_preferido")
    if nombre:
        bloques.append(
            f"- NOMBRE conocido: {nombre}. SIEMPRE saluda usando este nombre "
            f"(no '¡Hola!' generico). Tutea con familiaridad."
        )

    if info["es_recurrente"]:
        n = info["num_visitas_pasadas"]
        ultima = info["ultima_visita"]
        if n == 1 and ultima:
            est = ultima.get("estilista")
            con_quien = f" con {est}" if est else ""
            bloques.append(
                f"- CLIENTE RECURRENTE: ya estuvo 1 vez (el {ultima['fecha']}{con_quien}). "
                f"Saludalo asi: \"¡Hola {nombre}! ¿Que tal? ¿En que te ayudo hoy?\" o similar."
            )
        elif n > 1 and ultima:
            est = ultima.get("estilista")
            con_quien = f" con {est}" if est else ""
            bloques.append(
                f"- CLIENTE RECURRENTE: tiene {n} visitas previas. La ultima "
                f"fue el {ultima['fecha']}{con_quien}. "
                f"Saludalo asi: \"¡Hola {nombre}! ¿Que tal? ¿Otra vez por aqui?\" "
                f"o similar. NO le tratas como cliente nuevo."
            )
        if ultima and ultima.get("alergias"):
            bloques.append(
                f"- ALERGIAS / SENSIBILIDADES conocidas: {ultima['alergias']}. "
                f"Si va a agendar color/mechas, puedes confirmar si siguen "
                f"aplicando sin asumir que si automaticamente."
            )

    if info["citas_futuras"]:
        bloques.append("- TIENE CITA(S) ACTIVA(S):")
        for r in info["citas_futuras"]:
            est = r.get("estilista") or "?"
            bloques.append(
                f"    · {r['fecha']} a las {r['hora_inicio']} con {est} "
                f"(id {r['id']})"
            )
        if nombre:
            bloques.append(
                f"  Mencionalas en tu primer mensaje usando el nombre "
                f"{nombre}, ejemplo: \"Hola {nombre}, veo que tienes "
                f"cita el [fecha]. ¿Quieres modificarla, anularla, o "
                f"vienes a otra cosa?\". Si pide cita nueva, primero "
                f"confirma si quiere modificar la existente o crear otra."
            )
        else:
            bloques.append(
                "  Mencionalas en tu primer mensaje. Si pide cita nueva, "
                "primero confirma si quiere modificar la existente o crear otra."
            )

    bloques.append("═══════════════════════════════════════════════════════════")
    return "\n".join(bloques)


def construir_contexto_seguimiento(seguimiento: dict) -> str:
    """Bloque de contexto que se anade al system prompt cuando hay handoff."""
    datos = seguimiento.get("datos_parciales") or {}
    pregunta = seguimiento.get("pregunta_pendiente", "otro")
    contexto = seguimiento.get("contexto") or ""

    datos_str = ", ".join(f"{k}: {v}" for k, v in datos.items() if v) or "(ninguno aun)"

    mapa_pregunta = {
        "servicio": "el servicio o servicios que quiere",
        "fecha_y_hora": "el dia y la hora de la cita",
        "estilista": "la preferencia de estilista",
        "alergias": "las alergias a productos / sensibilidades",
        "confirmacion": "la confirmacion final de los datos",
        "nombre": "el nombre completo para la cita",
        "otro": "un dato adicional que falto",
    }
    que_falta = mapa_pregunta.get(pregunta, "un dato adicional")

    return (
        "\n\n═══════════════════════════════════════════════════════════\n"
        "CONTEXTO IMPORTANTE — HANDOFF DESDE LLAMADA TELEFONICA:\n"
        "═══════════════════════════════════════════════════════════\n"
        f"Este cliente acaba de hablar por telefono con Mara (nuestra "
        f"agente de voz). No se pudo capturar {que_falta} por voz, asi "
        f"que le hemos derivado aqui para terminar por texto.\n\n"
        f"DATOS QUE YA NOS DIO EN LA LLAMADA: {datos_str}\n"
        f"CONTEXTO DE LA LLAMADA: {contexto or '(sin contexto adicional)'}\n"
        f"DATO QUE FALTA: {que_falta}\n\n"
        "INSTRUCCIONES:\n"
        "- Saluda con familiaridad reconociendo que vienes de la llamada.\n"
        "- NO vuelvas a pedir los datos que ya tienes.\n"
        f"- Pide SOLO {que_falta}.\n"
        "- Cuando lo tengas, resume todos los datos y pide confirmacion "
        "antes de llamar a agendar_cita.\n"
        "═══════════════════════════════════════════════════════════\n"
    )


# ─── 4. Router FastAPI ──────────────────────────────────────────────
router = APIRouter()


def procesar_mensaje_wa(clave_sesion: str, texto: str, profile_name: str = "") -> str:
    """Logica de negocio del chatbot WhatsApp, INDEPENDIENTE del proveedor."""
    log.info("De: %s | Nombre: %s | Texto: %s", clave_sesion, profile_name, texto)

    historial = cargar_historial(clave_sesion)
    log.info("Historial: %d mensajes previos", len(historial))

    seguimiento = cargar_seguimiento_pendiente(clave_sesion)
    system_prompt_final = prompt_whatsapp()
    if seguimiento:
        log.info("Seguimiento pendiente detectado: id=%s pregunta=%s",
                 seguimiento.get("id"), seguimiento.get("pregunta_pendiente"))
        system_prompt_final = system_prompt_final + construir_contexto_seguimiento(seguimiento)

    contexto_recurrente = construir_contexto_cliente_recurrente(clave_sesion)
    if contexto_recurrente:
        log.info("Contexto cliente recurrente inyectado")
        system_prompt_final = system_prompt_final + contexto_recurrente

    mensajes = historial + [{"role": "user", "content": texto}]

    idioma_detectado = detectar_idioma(texto, historial=historial)
    bloque_idioma = bloque_idioma_para_prompt(idioma_detectado)
    if idioma_detectado != "es":
        log.info("Idioma detectado: %s", idioma_detectado)

    reply_text = None
    tools_ok: set = set()
    agendar_cita_ok = False

    def _ejecutar_ciclo(mensajes_in: list, tools_ok_set: set, max_iter: int = 5):
        reply = None
        nonlocal agendar_cita_ok
        for _ in range(max_iter):
            response = claude.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                system=system_prompt_final + bloque_idioma,
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
                    resultado = ejecutar_tool(block.name, block.input, clave_sesion)
                    if _tool_ejecutada_ok(block.name, resultado):
                        tools_ok_set.add(block.name)
                        if block.name == "agendar_cita":
                            agendar_cita_ok = True
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

        # GUARDRAIL anti-alucinacion con auto-retry.
        tool_alucinada = detectar_alucinacion(reply_text, tools_ok, historial=historial)
        if tool_alucinada:
            log.warning("[GUARDRAIL WA] Alucinacion '%s'. Auto-retry. Reply original: %s",
                        tool_alucinada, reply_text[:200])
            mensajes.append({"role": "assistant", "content": reply_text})
            mensajes.append({"role": "user", "content": mensaje_auto_retry(tool_alucinada)})
            reply_text2 = _ejecutar_ciclo(mensajes, tools_ok, max_iter=3)
            if reply_text2 and tool_alucinada in tools_ok:
                log.info("[GUARDRAIL WA] Auto-retry exitoso: %s ejecutada.", tool_alucinada)
                reply_text = reply_text2
            else:
                ejecutadas = ", ".join(tools_ok) or "ninguna"
                log.warning("[GUARDRAIL WA] Auto-retry fallo. Esperada: %s. Ejecutadas: %s.",
                            tool_alucinada, ejecutadas)
                reply_text = reply_recovery_para(tool_alucinada)

        log.info("Claude: %s%s", reply_text[:150], "..." if len(reply_text) > 150 else "")

        guardar_mensaje(clave_sesion, "user", texto)
        guardar_mensaje(clave_sesion, "assistant", reply_text)

        if seguimiento and agendar_cita_ok:
            marcar_seguimiento_completado(seguimiento["id"])

    except Exception as e:
        log.error("ERROR procesando mensaje WA: %s", e, exc_info=True)
        reply_text = (
            "Lo siento, ha habido un problema procesando tu mensaje. "
            "Intentalo de nuevo en un momento."
        )

    return reply_text


# ══════════════════════════════════════════════════════════════════════
# ENDPOINT 1: Twilio (form-data + respuesta TwiML)
# ══════════════════════════════════════════════════════════════════════
@router.post("/whatsapp")
async def whatsapp_webhook_twilio(
    Body: str = Form(...),
    From: str = Form(...),
    ProfileName: str = Form(default=""),
):
    log.info("[Twilio] Mensaje entrante")
    reply_text = procesar_mensaje_wa(
        clave_sesion=From,
        texto=Body,
        profile_name=ProfileName,
    )
    reply_text = _normalizar_asteriscos_wa(reply_text)

    provider = TwilioProvider()
    resp = provider.responder_webhook_sincrono(reply_text)
    return Response(content=resp["body"], media_type=resp["media_type"])


# ══════════════════════════════════════════════════════════════════════
# ENDPOINT 2: Meta Cloud API
# ══════════════════════════════════════════════════════════════════════
@router.get("/whatsapp/meta")
async def whatsapp_webhook_meta_verify(
    hub_mode: str = "", hub_verify_token: str = "", hub_challenge: str = "",
):
    meta = MetaProvider()
    challenge = meta.verificar_webhook(hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        return Response(status_code=403)
    return Response(content=str(challenge), media_type="text/plain")


@router.post("/whatsapp/meta")
async def whatsapp_webhook_meta(request: Request):
    log.info("[Meta] Mensaje entrante")
    try:
        payload = await request.json()
    except Exception as e:
        log.error("Payload Meta invalido: %s", e)
        return {"status": "error", "error": str(e)}

    meta = MetaProvider()
    try:
        entrante = meta.parsear_entrante(payload)
    except ValueError as e:
        log.info("[Meta] Ignorado: %s", e)
        return {"status": "ignored"}

    clave_sesion = f"whatsapp:{entrante.telefono}"

    reply_text = procesar_mensaje_wa(
        clave_sesion=clave_sesion,
        texto=entrante.texto,
        profile_name=entrante.profile_name,
    )
    reply_text = _normalizar_asteriscos_wa(reply_text)

    resultado_envio = meta.enviar(entrante.telefono, reply_text)
    if not resultado_envio.get("ok"):
        log.warning("Meta enviar fallo: %s", resultado_envio.get("error"))

    return {"status": "ok"}
