"""
webhook.py — Router FastAPI del agente telefonico (Vapi) para Salon Mara
------------------------------------------------------------------------
El agente de voz se llama Mara.

Endpoints expuestos a Vapi (uno por tool):
  - POST /vapi/tool/agendar_cita
  - POST /vapi/tool/consultar_disponibilidad
  - POST /vapi/tool/cancelar_cita
  - POST /vapi/tool/buscar_citas
  - POST /vapi/tool/modificar_cita
  - POST /vapi/tool/consultar_servicios
  - POST /vapi/tool/consultar_horario
  - POST /vapi/tool/consultar_historial
  - POST /vapi/tool/escalar_a_humano
  - POST /vapi/tool/derivar_a_whatsapp

  - POST /vapi/server-url     (assistant-request + end-of-call-report)
"""
import json
from typing import Any, Callable

from fastapi import APIRouter, Request

from core.config import supabase
from core.logger import get_logger
from core.memory import (
    _normalizar_telefono,
    cargar_resumen_llamadas_previas,
    generar_resumen_llamada,
)

log = get_logger(__name__)
from agente_telefonico.tools import (
    tool_agendar_cita,
    tool_buscar_citas,
    tool_cancelar_cita,
    tool_consultar_disponibilidad,
    tool_consultar_historial,
    tool_consultar_horario,
    tool_consultar_servicios,
    tool_derivar_a_whatsapp,
    tool_escalar_a_humano,
    tool_modificar_cita,
)


router = APIRouter()


# ─── Helpers genericos ──────────────────────────────────────────────
def _extract_tool_calls(payload: dict) -> list:
    message = payload.get("message", {})
    return message.get("toolCallList", []) or message.get("toolCalls", [])


def _extract_call_meta(payload: dict) -> tuple:
    """Devuelve (telefono_raw, vapi_call_id) del payload Vapi."""
    message = payload.get("message", {})
    call_data = message.get("call", {})
    customer = call_data.get("customer", {})
    telefono = customer.get("number", "")
    vapi_call_id = call_data.get("id") or "desconocido"
    return telefono, vapi_call_id


def _parse_arguments(arguments: Any) -> dict:
    """Vapi a veces envia arguments como string JSON."""
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return {}
    if isinstance(arguments, dict):
        return arguments
    return {}


async def _despacho_vapi(
    request: Request,
    handler: Callable[[dict, str, str], dict],
    nombre_tool: str,
):
    """Wrapper comun: parsea payload Vapi y devuelve `{"results": [...]}`."""
    try:
        payload = await request.json()
        tool_calls = _extract_tool_calls(payload)
        if not tool_calls:
            return {"results": []}

        telefono, vapi_call_id = _extract_call_meta(payload)

        results = []
        for tool_call in tool_calls:
            tool_call_id = tool_call.get("id")
            arguments = _parse_arguments(tool_call.get("function", {}).get("arguments", {}))

            log.info("Vapi tool call: %s | De: %s | Call: %s | Args: %s",
                     nombre_tool, telefono or "(sin numero)", vapi_call_id, arguments)

            resultado = handler(arguments, telefono, vapi_call_id)

            log.info("Vapi tool %s resultado: %s", nombre_tool, resultado)

            mensaje = (
                resultado.get("mensaje")
                if isinstance(resultado, dict)
                else str(resultado)
            )
            results.append({"toolCallId": tool_call_id, "result": mensaje})

        return {"results": results}

    except Exception as e:
        log.error("ERROR endpoint %s: %s", nombre_tool, e, exc_info=True)
        return {"results": [{"toolCallId": "error", "result": f"Error interno: {str(e)}"}]}


# ════════════════════════════════════════════════════════════════════
# ENDPOINTS POR TOOL
# ════════════════════════════════════════════════════════════════════
@router.post("/vapi/tool/agendar_cita")
async def vapi_agendar_cita(request: Request):
    return await _despacho_vapi(
        request,
        handler=lambda args, tel, _cid: tool_agendar_cita(args, telefono=tel),
        nombre_tool="agendar_cita",
    )


@router.post("/vapi/tool/consultar_disponibilidad")
async def vapi_consultar_disponibilidad(request: Request):
    return await _despacho_vapi(
        request,
        handler=lambda args, _tel, _cid: tool_consultar_disponibilidad(args),
        nombre_tool="consultar_disponibilidad",
    )


@router.post("/vapi/tool/cancelar_cita")
async def vapi_cancelar_cita(request: Request):
    return await _despacho_vapi(
        request,
        handler=lambda args, tel, _cid: tool_cancelar_cita(args, telefono=tel),
        nombre_tool="cancelar_cita",
    )


@router.post("/vapi/tool/buscar_citas")
async def vapi_buscar_citas(request: Request):
    return await _despacho_vapi(
        request,
        handler=lambda args, tel, _cid: tool_buscar_citas(args, telefono=tel),
        nombre_tool="buscar_citas",
    )


@router.post("/vapi/tool/modificar_cita")
async def vapi_modificar_cita(request: Request):
    return await _despacho_vapi(
        request,
        handler=lambda args, tel, _cid: tool_modificar_cita(args, telefono=tel),
        nombre_tool="modificar_cita",
    )


@router.post("/vapi/tool/consultar_servicios")
async def vapi_consultar_servicios(request: Request):
    return await _despacho_vapi(
        request,
        handler=lambda args, _tel, _cid: tool_consultar_servicios(args),
        nombre_tool="consultar_servicios",
    )


@router.post("/vapi/tool/consultar_horario")
async def vapi_consultar_horario(request: Request):
    return await _despacho_vapi(
        request,
        handler=lambda args, _tel, _cid: tool_consultar_horario(args),
        nombre_tool="consultar_horario",
    )


@router.post("/vapi/tool/escalar_a_humano")
async def vapi_escalar_a_humano(request: Request):
    return await _despacho_vapi(
        request,
        handler=lambda args, tel, cid: tool_escalar_a_humano(args, telefono=tel, vapi_call_id=cid),
        nombre_tool="escalar_a_humano",
    )


@router.post("/vapi/tool/derivar_a_whatsapp")
async def vapi_derivar_a_whatsapp(request: Request):
    return await _despacho_vapi(
        request,
        handler=lambda args, tel, cid: tool_derivar_a_whatsapp(args, telefono=tel, vapi_call_id=cid),
        nombre_tool="derivar_a_whatsapp",
    )


@router.post("/vapi/tool/consultar_historial")
async def vapi_consultar_historial(request: Request):
    """consultar_historial no recibe args; usa el tel del caller."""
    try:
        payload = await request.json()
        tool_calls = _extract_tool_calls(payload)
        if not tool_calls:
            return {"results": []}

        telefono, _ = _extract_call_meta(payload)

        results = []
        for tool_call in tool_calls:
            tool_call_id = tool_call.get("id")

            log.info("Vapi tool call: consultar_historial | De: %s", telefono or "(sin numero)")

            resultado = tool_consultar_historial(telefono)

            log.info("Vapi consultar_historial resultado: %s%s",
                     resultado[:150], "..." if len(resultado) > 150 else "")

            results.append({"toolCallId": tool_call_id, "result": resultado})

        return {"results": results}

    except Exception as e:
        log.error("ERROR endpoint consultar_historial: %s", e, exc_info=True)
        return {"results": [{"toolCallId": "error", "result": f"Error interno: {str(e)}"}]}


# ════════════════════════════════════════════════════════════════════
# /vapi/server-url — assistant-request y end-of-call-report
# ════════════════════════════════════════════════════════════════════
@router.post("/vapi/server-url")
async def vapi_server_url(request: Request):
    """
    Eventos del ciclo de vida de la llamada:
      - assistant-request: al inicio, devolvemos overrides con contexto previo.
      - end-of-call-report: al colgar, guardamos transcripcion + resumen.
    """
    try:
        payload = await request.json()
        message = payload.get("message", {})
        message_type = message.get("type")

        log.info("Vapi server-url event: %s", message_type)

        if message_type == "assistant-request":
            customer = message.get("call", {}).get("customer", {})
            telefono_raw = customer.get("number", "")
            telefono = _normalizar_telefono(telefono_raw)

            log.info("Telefono cliente: %s", telefono or "(desconocido)")

            resumen_previo = None
            if telefono:
                resumen_previo = cargar_resumen_llamadas_previas(telefono)

            assistant_overrides = {}
            if resumen_previo:
                contexto_extra = (
                    "\n\n═══════════════════════════════════════════════════════════\n"
                    "CONTEXTO IMPORTANTE — VISITAS / LLAMADAS PREVIAS DE ESTE CLIENTE:\n"
                    "═══════════════════════════════════════════════════════════\n"
                    f"{resumen_previo}\n"
                    "═══════════════════════════════════════════════════════════\n\n"
                    "Saluda al cliente reconociendo lo que sabes de el. Por "
                    "ejemplo: 'Hola de nuevo, ¿que tal? ¿Vienes a por otra "
                    "cita?' No le preguntes datos que ya te dio."
                )
                assistant_overrides["model"] = {
                    "messages": [
                        {"role": "system", "content": contexto_extra}
                    ]
                }
                log.info("Inyectando contexto previo:\n%s", resumen_previo)
            else:
                log.info("Sin historial previo.")

            response = {}
            if assistant_overrides:
                response["assistantOverrides"] = assistant_overrides
            return response

        elif message_type == "end-of-call-report":
            call_data = message.get("call", {})
            customer = call_data.get("customer", {})
            telefono = _normalizar_telefono(customer.get("number", ""))
            vapi_call_id = call_data.get("id") or message.get("call", {}).get("id") or "desconocido"

            transcripcion = (
                message.get("messages", [])
                or message.get("artifact", {}).get("messages", [])
            )
            duracion = message.get("durationSeconds") or message.get("duration", 0)
            ended_reason = message.get("endedReason", "")
            coste = message.get("cost", 0)

            log.info("end-of-call | tel=%s call=%s duracion=%ss coste=$%s end_reason=%s mensajes=%d",
                     telefono, vapi_call_id, duracion, coste, ended_reason, len(transcripcion))

            resumen = generar_resumen_llamada(transcripcion)
            preview = resumen[:120] + "..." if len(resumen) > 120 else resumen
            log.info("Resumen generado: %s", preview)

            if telefono and telefono != "":
                try:
                    supabase.table("llamadas_voz").insert({
                        "telefono": telefono,
                        "vapi_call_id": vapi_call_id,
                        "duracion_segundos": int(duracion) if duracion else None,
                        "resumen": resumen if resumen else None,
                        "transcripcion": transcripcion,
                        "ended_reason": ended_reason,
                        "coste_usd": float(coste) if coste else None,
                    }).execute()
                    log.info("Llamada guardada en Supabase.")
                except Exception as e:
                    log.warning("Error guardando llamada: %s", e)
            else:
                log.info("Llamada sin telefono (test web), no se guarda.")

            return {"status": "ok"}

        return {"status": "ignored"}

    except Exception as e:
        log.error("ERROR en /vapi/server-url: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
