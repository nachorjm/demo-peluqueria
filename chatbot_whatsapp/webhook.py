"""
webhook.py — Router FastAPI del chatbot WhatsApp de Casa Lola
-------------------------------------------------------------
Endpoints publicos:
  - POST /whatsapp        (Twilio sandbox, form-data + TwiML)
  - GET  /whatsapp/meta   (handshake Meta Cloud API)
  - POST /whatsapp/meta   (Meta Cloud API, JSON)

Flujo:
  1. Recibe mensajes de WhatsApp.
  2. Carga el historial del telefono desde Supabase.
  3. Si el telefono tiene un seguimiento pendiente desde una llamada de
     voz (Lola no pudo capturar un dato), se inyecta contexto extra.
  4. Envia mensaje + historial + tools a Claude.
  5. Si Claude pide tool, se ejecuta y se vuelve a llamar a Claude.
  6. Guarda en Supabase y responde via TwiML (Twilio) o POST async (Meta).
"""
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
from core.recordatorios import (
    reserva_con_recordatorio_reciente,
    procesar_respuesta_recordatorio,
)
from core.lista_espera import (
    candidato_con_oferta_reciente,
    procesar_respuesta_oferta,
)
from core.encuestas import (
    reserva_con_encuesta_reciente,
    procesar_respuesta_encuesta,
)
from chatbot_whatsapp.tools import TOOLS, ejecutar_tool


_ESTADOS_EXITO_POR_TOOL = {
    "reservar_mesa": {"creada", "actualizada", "sin_cambios"},
    "modificar_reserva": {"actualizada", "sin_cambios"},
    "cancelar_reserva": {"cancelada", "ya_cancelada"},
    "escalar_a_humano": {"ok"},
    "derivar_a_whatsapp": {"ok"},
    "apuntar_lista_espera": {"ok", "ya_en_lista"},
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
    no con dos (**asi**). Si el modelo se despista y genera markdown
    estandar (comun en respuestas largas tipo lista/carta), convertimos
    los pares `**...**` en `*...*` antes de enviarlo al cliente. Fail-safe
    para reforzar el prompt (issue #22 follow-up tras QA).

    Regex no-greedy para no romper pares cruzados. Tolera espacios entre
    asteriscos y texto. No toca asteriscos aislados o impares.
    """
    if not texto:
        return texto
    # Sustituye **x** por *x* (no-greedy, permite saltos de linea)
    import re
    return re.sub(r"\*\*(.+?)\*\*", r"*\1*", texto, flags=re.DOTALL)


# ─── 2. Memoria en Supabase ─────────────────────────────────────────
def cargar_historial(telefono: str, limite: int = MAX_HISTORY_MESSAGES) -> list[dict]:
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
    llamada de voz en la que Lola no pudo capturar un dato).
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
    para anadir al system prompt. Personaliza el saludo (issue #3).
    Si no hay datos, devuelve cadena vacia.
    """
    from core.reservas import historial_cliente_resumen
    info = historial_cliente_resumen(telefono)
    if not info["es_recurrente"] and not info["reservas_futuras"]:
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
            bloques.append(
                f"- CLIENTE RECURRENTE: ya estuvo 1 vez (el {ultima['fecha']}, "
                f"{ultima['num_personas']} personas). Saludalo asi: "
                f"\"¡Hola {nombre}! ¿Que tal? ¿Que necesitas hoy?\" o similar."
            )
        elif n > 1 and ultima:
            bloques.append(
                f"- CLIENTE RECURRENTE: tiene {n} visitas previas. La ultima "
                f"fue el {ultima['fecha']} ({ultima['num_personas']} personas). "
                f"Saludalo asi: \"¡Hola {nombre}! ¿Que tal? ¿Otra vez por aqui?\" "
                f"o similar. NO le tratas como cliente nuevo."
            )
        if ultima and ultima.get("alergias"):
            bloques.append(
                f"- ALERGIAS conocidas: {ultima['alergias']}. "
                f"Si va a reservar, puedes preguntar si siguen aplicando "
                f"sin asumir que si automaticamente."
            )
        if ultima and ultima.get("ocasion_especial"):
            bloques.append(
                f"- Su ultima visita fue por: {ultima['ocasion_especial']}."
            )

    if info["reservas_futuras"]:
        bloques.append("- TIENE RESERVA(S) ACTIVA(S):")
        for r in info["reservas_futuras"]:
            bloques.append(
                f"    · {r['fecha']} a las {r['hora']}, "
                f"{r['num_personas']} personas (id {r['id']})"
            )
        if nombre:
            bloques.append(
                f"  Mencionalas en tu primer mensaje usando el nombre "
                f"{nombre}, ejemplo: \"Hola {nombre}, veo que tienes "
                f"mesa el [fecha]. ¿Quieres modificarla, anularla, o "
                f"vienes a otra cosa?\". Si pide nueva reserva, primero "
                f"confirma si quiere modificar la existente o crear otra."
            )
        else:
            bloques.append(
                "  Mencionalas en tu primer mensaje. Si pide nueva reserva, "
                "primero confirma si quiere modificar la existente o crear otra."
            )

    if info["tiene_no_show_reciente"]:
        bloques.append(
            "- ATENCION: tuvo un no-show en los ultimos 2 meses. NO menciones "
            "esto al cliente, pero usa tono educadamente formal (no familiaridad "
            "exagerada que pueda sonar incomoda)."
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
        "alergias": "las alergias o intolerancias del grupo",
        "fecha_y_hora": "el dia y la hora de la reserva",
        "num_personas": "el numero de comensales",
        "confirmacion": "la confirmacion final de los datos",
        "nombre": "el nombre completo para la reserva",
        "otro": "un dato adicional que falto",
    }
    que_falta = mapa_pregunta.get(pregunta, "un dato adicional")

    return (
        "\n\n═══════════════════════════════════════════════════════════\n"
        "CONTEXTO IMPORTANTE — HANDOFF DESDE LLAMADA TELEFONICA:\n"
        "═══════════════════════════════════════════════════════════\n"
        f"Este cliente acaba de hablar por telefono con Lola (nuestra "
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
        "antes de llamar a reservar_mesa.\n"
        "═══════════════════════════════════════════════════════════\n"
    )


# ─── 4. Router FastAPI ──────────────────────────────────────────────
router = APIRouter()


def procesar_mensaje_wa(clave_sesion: str, texto: str, profile_name: str = "") -> str:
    """
    Logica de negocio del chatbot WhatsApp, INDEPENDIENTE del proveedor.
    """
    log.info("De: %s | Nombre: %s | Texto: %s", clave_sesion, profile_name, texto)

    # ─── 0a. Detectar si es respuesta a un recordatorio (issue #5) ─
    reserva_recordada = reserva_con_recordatorio_reciente(clave_sesion)
    if reserva_recordada:
        respuesta = procesar_respuesta_recordatorio(reserva_recordada, texto)
        if respuesta is not None:
            log.info("Respuesta a recordatorio detectada: %s", respuesta[:80])
            guardar_mensaje(clave_sesion, "user", texto)
            guardar_mensaje(clave_sesion, "assistant", respuesta)
            return respuesta
        # Si la respuesta es texto libre, sigue al flujo normal del bot.

    # ─── 0b. Detectar si es respuesta a oferta de lista de espera (#6) ─
    candidato = candidato_con_oferta_reciente(clave_sesion)
    if candidato:
        respuesta = procesar_respuesta_oferta(candidato, texto)
        if respuesta is not None:
            log.info("Respuesta a oferta lista espera: %s", respuesta[:80])
            guardar_mensaje(clave_sesion, "user", texto)
            guardar_mensaje(clave_sesion, "assistant", respuesta)
            return respuesta

    # ─── 0c. Detectar si es respuesta a encuesta post-visita (#7) ──
    reserva_encuesta = reserva_con_encuesta_reciente(clave_sesion)
    if reserva_encuesta:
        respuesta = procesar_respuesta_encuesta(reserva_encuesta, texto)
        if respuesta is not None:
            log.info("Respuesta a encuesta: %s", respuesta[:80])
            guardar_mensaje(clave_sesion, "user", texto)
            guardar_mensaje(clave_sesion, "assistant", respuesta)
            return respuesta

    historial = cargar_historial(clave_sesion)
    log.info("Historial: %d mensajes previos", len(historial))

    seguimiento = cargar_seguimiento_pendiente(clave_sesion)
    system_prompt_final = prompt_whatsapp()
    if seguimiento:
        log.info("Seguimiento pendiente detectado: id=%s pregunta=%s",
                 seguimiento.get("id"), seguimiento.get("pregunta_pendiente"))
        system_prompt_final = system_prompt_final + construir_contexto_seguimiento(seguimiento)

    # Cliente recurrente / con reserva activa (issue #3): inyectar
    # contexto para personalizar el saludo. clave_sesion en WA viene
    # como "whatsapp:+34..." asi que se normaliza dentro de la funcion.
    contexto_recurrente = construir_contexto_cliente_recurrente(clave_sesion)
    if contexto_recurrente:
        log.info("Contexto cliente recurrente inyectado")
        system_prompt_final = system_prompt_final + contexto_recurrente

    mensajes = historial + [{"role": "user", "content": texto}]

    # Multi-idioma (issue #9). Pasamos el historial para que nombres
    # propios tipo "me llamo Marta Ruiz" no disparen cambios espurios
    # a italiano (QA bug round 1).
    idioma_detectado = detectar_idioma(texto, historial=historial)
    bloque_idioma = bloque_idioma_para_prompt(idioma_detectado)
    if idioma_detectado != "es":
        log.info("Idioma detectado: %s", idioma_detectado)

    reply_text = None
    tools_ok: set = set()
    reservar_mesa_ok = False  # solo para marcar seguimiento como completado

    def _ejecutar_ciclo(mensajes_in: list, tools_ok_set: set, max_iter: int = 5):
        reply = None
        nonlocal reservar_mesa_ok
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
                        if block.name == "reservar_mesa":
                            reservar_mesa_ok = True
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

        # GUARDRAIL anti-alucinacion con auto-retry (issues #20, #22).
        # Pasamos `historial` (estado de la conversacion ANTES de este
        # turno) para que el guardrail considere tools afirmadas en
        # turnos previos y no dispare falsos positivos cuando el
        # cliente pregunta de forma pasiva por algo ya hecho (#49).
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
                log.warning("[GUARDRAIL WA] Auto-retry fallo. Esperada: %s. Ejecutadas: %s. Aplicando recovery.",
                            tool_alucinada, ejecutadas)
                reply_text = reply_recovery_para(tool_alucinada)

        log.info("Claude: %s%s", reply_text[:150], "..." if len(reply_text) > 150 else "")

        guardar_mensaje(clave_sesion, "user", texto)
        guardar_mensaje(clave_sesion, "assistant", reply_text)

        if seguimiento and reservar_mesa_ok:
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
    # Blindaje markdown: WhatsApp solo soporta asteriscos simples.
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
    # Blindaje markdown: WhatsApp solo soporta asteriscos simples.
    reply_text = _normalizar_asteriscos_wa(reply_text)

    resultado_envio = meta.enviar(entrante.telefono, reply_text)
    if not resultado_envio.get("ok"):
        log.warning("Meta enviar fallo: %s", resultado_envio.get("error"))

    return {"status": "ok"}
