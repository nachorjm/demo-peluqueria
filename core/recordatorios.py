"""
Logica de recordatorios automaticos de reservas (issue #5).

Flujo:
  1. Cron diario llama a `enviar_recordatorios_del_dia_siguiente()`.
  2. Para cada reserva confirmada de manana sin recordatorio enviado,
     se manda un WhatsApp con resumen y se marca el envio.
  3. El cliente responde "SI" / "NO" / texto libre. El handler del
     webhook WA (chatbot_whatsapp/webhook.py) detecta si es respuesta
     a un recordatorio reciente y llama aqui a `procesar_respuesta_recordatorio()`.
  4. SI -> marca confirmado.
     NO -> cancela la reserva + lo registra.
     Texto -> sigue al flujo normal del bot (no es respuesta valida).

Configurable:
  - VENTANA_HORAS_RESPUESTA_RECORDATORIO: cuanto tiempo desde el envio
    consideramos que la respuesta del cliente sigue siendo "del recordatorio".
    Por defecto 4h.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from core.config import supabase
from core.logger import get_logger
from core.memory import _normalizar_telefono
from core.restaurante_data import RESTAURANTE
from core.whatsapp_out import enviar_whatsapp

log = get_logger(__name__)


VENTANA_HORAS_RESPUESTA_RECORDATORIO = 4


# ════════════════════════════════════════════════════════════════════
# 1. Envio
# ════════════════════════════════════════════════════════════════════

def _formato_fecha_humana(iso_fecha: str) -> str:
    """'2026-04-25' -> 'sabado 25 de abril'."""
    dias = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
             "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    try:
        d = datetime.strptime(iso_fecha, "%Y-%m-%d").date()
        return f"{dias[d.weekday()]} {d.day} de {meses[d.month - 1]}"
    except (ValueError, TypeError):
        return iso_fecha


def _construir_mensaje_recordatorio(reserva: dict) -> str:
    nombre = reserva.get("nombre") or "hola"
    fecha_humana = _formato_fecha_humana(reserva.get("fecha", ""))
    hora = (reserva.get("hora") or "")[:5]
    num = reserva.get("num_personas") or "?"
    return (
        f"Hola {nombre}, recordatorio de tu reserva en {RESTAURANTE['nombre']}:\n\n"
        f"📅 *{fecha_humana} a las {hora}*\n"
        f"👥 {num} personas\n\n"
        f"¿Confirmas que vienes? Responde *SI* para confirmar o *NO* "
        f"para anular. Si no respondes, mantenemos tu mesa."
    )


def reservas_pendientes_de_recordatorio(fecha_objetivo: date) -> list:
    """Devuelve reservas confirmadas para `fecha_objetivo` sin recordatorio enviado."""
    try:
        res = (
            supabase.table("reservas")
            .select("*")
            .eq("fecha", fecha_objetivo.isoformat())
            .eq("estado", "confirmada")
            .is_("recordatorio_enviado_at", "null")
            .execute()
        )
        return res.data or []
    except Exception as e:
        log.warning("Error consultando reservas pendientes recordatorio: %s", e)
        return []


def enviar_recordatorio_a(reserva: dict) -> dict:
    """
    Manda WhatsApp con el recordatorio. Marca la reserva con
    `recordatorio_enviado_at` y `recordatorio_sid`.
    """
    telefono = _normalizar_telefono(reserva.get("telefono") or "")
    if not telefono or not telefono.startswith("+"):
        return {"ok": False, "error": "telefono invalido", "reserva_id": reserva.get("id")}

    mensaje = _construir_mensaje_recordatorio(reserva)
    envio = enviar_whatsapp(telefono, mensaje)

    ahora = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table("reservas").update({
            "recordatorio_enviado_at": ahora,
            "recordatorio_sid": envio.get("sid") if envio.get("ok") else None,
        }).eq("id", reserva["id"]).execute()
    except Exception as e:
        log.warning("No se pudo marcar recordatorio enviado en BD: %s", e)

    return {
        "ok": envio.get("ok", False),
        "error": envio.get("error"),
        "reserva_id": reserva.get("id"),
        "telefono": telefono,
    }


def enviar_recordatorios_del_dia_siguiente() -> dict:
    """
    Punto de entrada del cron diario. Manda recordatorios para reservas
    de manana. Devuelve resumen.
    """
    manana = date.today() + timedelta(days=1)
    pendientes = reservas_pendientes_de_recordatorio(manana)

    log.info("Recordatorios para %s: %d reservas pendientes", manana.isoformat(), len(pendientes))

    resultados = {"total": len(pendientes), "enviados": 0, "fallidos": 0, "detalle": []}
    for reserva in pendientes:
        r = enviar_recordatorio_a(reserva)
        resultados["detalle"].append(r)
        if r["ok"]:
            resultados["enviados"] += 1
        else:
            resultados["fallidos"] += 1

    log.info("Recordatorios enviados: %d / %d", resultados["enviados"], resultados["total"])
    return resultados


# ════════════════════════════════════════════════════════════════════
# 2. Respuestas al recordatorio
# ════════════════════════════════════════════════════════════════════

def reserva_con_recordatorio_reciente(telefono_canal: str) -> Optional[dict]:
    """
    Busca una reserva del cliente cuyo recordatorio se haya enviado en
    las ultimas N horas y aun no tenga respuesta procesada.
    """
    tel = _normalizar_telefono(telefono_canal or "")
    if not tel:
        return None
    limite = (datetime.now(timezone.utc)
              - timedelta(hours=VENTANA_HORAS_RESPUESTA_RECORDATORIO)).isoformat()
    try:
        res = (
            supabase.table("reservas")
            .select("*")
            .eq("telefono", tel)
            .eq("estado", "confirmada")
            .gte("recordatorio_enviado_at", limite)
            .is_("recordatorio_respuesta", "null")
            .order("recordatorio_enviado_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]
        return None
    except Exception as e:
        log.warning("Error buscando recordatorio reciente: %s", e)
        return None


def _es_si(texto: str) -> bool:
    t = (texto or "").strip().lower()
    return t in {"si", "sí", "s", "ok", "vale", "confirmo", "confirmado", "perfecto", "yes"}


def _es_no(texto: str) -> bool:
    t = (texto or "").strip().lower()
    return t in {"no", "n", "nope", "anula", "anular", "cancelar", "cancela", "no puedo"}


def procesar_respuesta_recordatorio(reserva: dict, texto: str) -> Optional[str]:
    """
    Procesa la respuesta del cliente al recordatorio.

    Returns:
        - str con la respuesta del bot al cliente, si la respuesta era SI/NO.
        - None si el texto no parece una respuesta al recordatorio (sigue
          flujo normal del bot).
    """
    ahora = datetime.now(timezone.utc).isoformat()

    if _es_si(texto):
        try:
            supabase.table("reservas").update({
                "recordatorio_respuesta": "confirmado",
                "recordatorio_respuesta_at": ahora,
            }).eq("id", reserva["id"]).execute()
        except Exception as e:
            log.warning("Error marcando confirmado: %s", e)
        nombre = reserva.get("nombre") or ""
        return (
            f"Genial {nombre}, te esperamos. Si necesitas cambiar algo, "
            f"escribe por aqui."
        )

    if _es_no(texto):
        try:
            supabase.table("reservas").update({
                "estado": "cancelada",
                "motivo_cancelacion": "cancelada por recordatorio",
                "recordatorio_respuesta": "cancelado",
                "recordatorio_respuesta_at": ahora,
                "updated_at": ahora,
            }).eq("id", reserva["id"]).execute()
        except Exception as e:
            log.warning("Error cancelando por recordatorio: %s", e)
        return (
            "Reserva anulada, gracias por avisar. Cuando quieras volver, "
            "aqui estamos."
        )

    # Texto libre: dejar que el flujo normal del bot la procese.
    return None
