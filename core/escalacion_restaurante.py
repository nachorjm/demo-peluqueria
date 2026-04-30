"""
Logica de escalacion al dueño/encargado del restaurante.

Compartida por los 3 canales (web, wa, voz). Crea registro en
`escalaciones` y envia email al equipo via Resend.
"""
from typing import Optional

from core.config import supabase
from core.clientes import upsert_cliente
from core.logger import get_logger
from core.memory import _normalizar_telefono
from core.notifications import notificar_escalacion

log = get_logger(__name__)


MOTIVOS_VALIDOS = {
    "cliente_lo_pide",
    "queja_o_enfado",
    "grupo_grande",
    "evento_privado",
    "caso_complejo",
    "datos_no_capturados",
    "otro",
}


def escalar_a_humano(
    input_data: dict,
    telefono: Optional[str] = None,
    canal_origen: str = "web",
    vapi_call_id: Optional[str] = None,
) -> dict:
    """
    Crea un registro en `escalaciones` y notifica al dueño por email.

    Args (en input_data):
        motivo: enum de MOTIVOS_VALIDOS.
        contexto: descripcion breve.
        nombre, telefono, email: datos opcionales del cliente.
    """
    motivo = (input_data.get("motivo") or "otro").strip()
    if motivo not in MOTIVOS_VALIDOS:
        motivo = "otro"

    contexto = (input_data.get("contexto") or "").strip()
    if not contexto:
        return {
            "status": "error",
            "mensaje": (
                "Falta el campo 'contexto'. Antes de escalar tienes que "
                "explicar brevemente por que escalas."
            ),
        }

    # Telefono: prioriza el del payload, si no el del canal
    tel_payload = (input_data.get("telefono") or "").strip()
    tel_limpio = _normalizar_telefono(tel_payload or telefono or "")
    if not tel_limpio:
        tel_limpio = "(desconocido)"

    nombre_cliente = (input_data.get("nombre") or "").strip()

    # Validacion de datos minimos (QA round 2: email duplicado).
    # Escalar sin nombre ni telefono produce avisos al dueño sin datos
    # para poder contactar al cliente. Forzamos al bot a pedirlos antes.
    # - En web: el canal NO aporta telefono, asi que exigimos ambos.
    # - En whatsapp/voz: el telefono del canal cuenta. Exigimos solo el
    #   nombre si no se ha proporcionado.
    tiene_telefono_util = tel_limpio != "(desconocido)"
    faltantes = []
    if not nombre_cliente:
        faltantes.append("nombre")
    if not tiene_telefono_util:
        faltantes.append("telefono")
    if faltantes:
        return {
            "status": "datos_insuficientes",
            "faltantes": faltantes,
            "mensaje": (
                f"Faltan datos para escalar: {', '.join(faltantes)}. "
                "Pide al cliente esos datos explicitamente ANTES de "
                "volver a ejecutar esta tool. NO escales de forma "
                "parcial: confirmas al cliente que le llamaran solo "
                "despues de tener el registro completo."
            ),
        }

    datos_cliente = {
        "nombre": nombre_cliente or None,
        "email": input_data.get("email"),
        "telefono": tel_limpio if tiene_telefono_util else None,
    }
    datos_cliente = {k: v for k, v in datos_cliente.items() if v}

    try:
        registro = {
            "telefono": tel_limpio,
            "vapi_call_id": vapi_call_id,
            "motivo": motivo,
            "contexto": contexto,
            "datos_cliente": datos_cliente if datos_cliente else None,
        }
        res = supabase.table("escalaciones").insert(registro).execute()
        escalacion_id = res.data[0]["id"] if res.data else None
        created_at = res.data[0].get("created_at") if res.data else None

        # Mirror al CRM (clientes) si tenemos telefono real
        if tel_limpio != "(desconocido)":
            try:
                upsert_cliente(
                    telefono=tel_limpio,
                    nombre=datos_cliente.get("nombre"),
                    canal_origen="escalacion",
                    email=datos_cliente.get("email"),
                    notas=f"Escalacion ({motivo}): {contexto[:200]}",
                )
            except Exception as e:
                log.warning("upsert_cliente (escalacion) fallo: %s", e)

        # Email al equipo (best-effort)
        email_status = "pendiente"
        email_id = None
        email_error = None
        try:
            email_result = notificar_escalacion({
                "id": escalacion_id,
                "telefono": tel_limpio,
                "vapi_call_id": vapi_call_id,
                "motivo": motivo,
                "contexto": contexto,
                "datos_cliente": datos_cliente,
                "created_at": created_at,
            })
            if email_result.get("ok"):
                email_status = "enviado"
                email_id = email_result.get("id")
                log.info("Email de escalacion enviado: %s", email_id)
            else:
                email_status = "fallido"
                email_error = email_result.get("error")
                log.warning("Email de escalacion fallo: %s", email_error)
        except Exception as e:
            email_status = "fallido"
            email_error = str(e)
            log.error("Excepcion enviando email de escalacion: %s", e, exc_info=True)

        if escalacion_id:
            try:
                supabase.table("escalaciones").update({
                    "resend_message_id": email_id,
                    "email_status": email_status,
                    "email_error": email_error,
                }).eq("id", escalacion_id).execute()
            except Exception as e:
                log.warning("No se pudo actualizar email_status: %s", e)

        return {
            "status": "ok",
            "escalacion_id": escalacion_id,
            "mensaje": (
                f"Escalacion registrada (ID {escalacion_id}). El dueño recibe "
                f"ahora un aviso por email y contactara al cliente cuanto antes. "
                f"Confirma al cliente que su caso sera atendido personalmente."
            ),
        }

    except Exception as e:
        return {
            "status": "error",
            "mensaje": f"No se pudo registrar la escalacion: {str(e)}",
        }
