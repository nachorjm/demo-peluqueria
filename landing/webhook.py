"""
Router FastAPI para la landing del restaurante.

Endpoint(s):
  - POST /supabase/webhook/reserva-nueva
      Lo llama Supabase via Database Webhook cuando hay un INSERT en la
      tabla `reservas`. Envia email de notificacion al dueño.
  - POST /supabase/webhook/reserva-modificada  (issue #31)
      Lo llama Supabase via Database Webhook cuando hay un UPDATE en la
      tabla `reservas`. Envia email diferenciado (modificacion o
      cancelacion, con tabla de cambios old->new) al dueño.
"""
import hmac
import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

from core.logger import get_logger
from core.notifications import notificar_cambio_reserva, notificar_nueva_reserva

log = get_logger(__name__)

router = APIRouter()

# Secreto compartido con el webhook de Supabase. Configurado en .env.
WEBHOOK_SECRET = os.environ.get("SUPABASE_WEBHOOK_SECRET", "").strip()


@router.post("/supabase/webhook/reserva-nueva")
async def supabase_reserva_nueva(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """
    Recibe eventos de Supabase cuando se inserta una fila en `reservas`.

    Payload esperado:
    {
      "type": "INSERT",
      "table": "reservas",
      "schema": "public",
      "record": {
        "id": "...",
        "nombre": "...",
        "telefono": "...",
        "fecha": "...",
        "hora": "...",
        "num_personas": 4,
        "alergias": "...",
        "ocasion_especial": "...",
        "notas": "...",
        "canal_origen": "web",
        "estado": "confirmada",
        "created_at": "..."
      },
      "old_record": null
    }
    """
    # 1. Verificar el secreto compartido (si esta configurado)
    if WEBHOOK_SECRET:
        if not x_webhook_secret or not hmac.compare_digest(
            x_webhook_secret, WEBHOOK_SECRET
        ):
            log.warning("Webhook Supabase con secreto invalido. Rechazado.")
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    # 2. Parsear el payload
    try:
        payload = await request.json()
    except Exception as e:
        log.error("Error parseando payload Supabase: %s", e)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("type")
    table = payload.get("table")
    record = payload.get("record") or {}

    log.info("Supabase webhook: %s on %s | record id=%s %s %s",
             event_type, table, record.get("id"), record.get("fecha"), record.get("hora"))

    # 3. Solo nos interesan INSERT sobre `reservas` con estado confirmada
    if event_type != "INSERT" or table != "reservas":
        log.info("Ignorado: no es INSERT en reservas.")
        return {"status": "ignored", "reason": "not an INSERT on reservas"}

    if record.get("estado") and record.get("estado") != "confirmada":
        log.info("Ignorado: estado=%s.", record.get("estado"))
        return {"status": "ignored", "reason": "reserva no confirmada"}

    # 4. Enviar email
    result = notificar_nueva_reserva(record)

    if result["ok"]:
        log.info("Email de nueva reserva enviado (id=%s)", result["id"])
    else:
        log.error("Error enviando email de nueva reserva: %s", result["error"])

    return {
        "status": "ok" if result["ok"] else "error",
        "email_id": result.get("id"),
        "error": result.get("error"),
    }


@router.post("/supabase/webhook/reserva-modificada")
async def supabase_reserva_modificada(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """
    Recibe eventos de Supabase cuando se actualiza una fila en `reservas`
    (issue #31).

    Payload esperado de Supabase DB webhook UPDATE:
    {
      "type": "UPDATE",
      "table": "reservas",
      "schema": "public",
      "record": { ... fila nueva ... },
      "old_record": { ... fila previa ... }
    }

    Logica:
      - Filtramos a cambios en campos relevantes (fecha, hora,
        num_personas, estado, alergias, ocasion, notas). Cambios
        solo en campos internos (updated_at, recordatorio_enviado_at,
        mesas_asignadas) se ignoran sin email.
      - Si el cambio es una CANCELACION (estado: confirmada -> cancelada),
        email con subject "Reserva CANCELADA" (rojo).
      - Si es otro cambio relevante, subject "Reserva MODIFICADA" (naranja)
        con tabla old -> new.
    """
    # 1. Verificar secreto
    if WEBHOOK_SECRET:
        if not x_webhook_secret or not hmac.compare_digest(
            x_webhook_secret, WEBHOOK_SECRET
        ):
            log.warning("Webhook reserva-modificada con secreto invalido. Rechazado.")
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    # 2. Parsear payload
    try:
        payload = await request.json()
    except Exception as e:
        log.error("Error parseando payload UPDATE: %s", e)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("type")
    table = payload.get("table")
    record = payload.get("record") or {}
    old_record = payload.get("old_record") or {}

    log.info(
        "Supabase webhook: %s on %s | record id=%s",
        event_type, table, record.get("id"),
    )

    # 3. Filtrar: solo UPDATE en tabla reservas
    if event_type != "UPDATE" or table != "reservas":
        log.info("Ignorado: no es UPDATE en reservas (type=%s, table=%s).",
                 event_type, table)
        return {"status": "ignored", "reason": "not an UPDATE on reservas"}

    # 4. Calcular diff y decidir si enviar email
    result = notificar_cambio_reserva(old_record, record)

    if result.get("skipped"):
        log.info("Cambio sin campos relevantes: ignorado (no email).")
        return {"status": "ignored", "reason": "cambio solo en campos internos"}

    if result.get("ok"):
        log.info("Email de cambio de reserva enviado (id=%s)", result.get("id"))
    else:
        log.error("Error enviando email de cambio: %s", result.get("error"))

    return {
        "status": "ok" if result.get("ok") else "error",
        "email_id": result.get("id"),
        "error": result.get("error"),
    }
