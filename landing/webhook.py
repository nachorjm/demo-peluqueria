"""
Router FastAPI para la landing del salon.

Endpoint(s):
  - POST /supabase/webhook/cita-nueva
      Lo llama Supabase via Database Webhook cuando hay un INSERT en la
      tabla `citas`. Envia email de notificacion al duenno.
  - POST /supabase/webhook/cita-modificada
      Lo llama Supabase via Database Webhook cuando hay un UPDATE en la
      tabla `citas`. Envia email diferenciado (modificacion o
      cancelacion, con tabla de cambios old->new) al duenno.
"""
import hmac
import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

from core.config import supabase
from core.logger import get_logger
from core.notifications import notificar_cambio_cita, notificar_nueva_cita

log = get_logger(__name__)

router = APIRouter()

# Secreto compartido con el webhook de Supabase. Configurado en .env.
WEBHOOK_SECRET = os.environ.get("SUPABASE_WEBHOOK_SECRET", "").strip()


def _cargar_servicios_de_cita(cita_id: str) -> list:
    """Helper local para no acoplar al modulo core.citas (que importa muchas cosas)."""
    if not cita_id:
        return []
    try:
        res = (
            supabase.table("cita_servicios")
            .select("*")
            .eq("cita_id", cita_id)
            .order("orden", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as e:
        log.warning("Error cargando cita_servicios %s: %s", cita_id, e)
        return []


@router.post("/supabase/webhook/cita-nueva")
async def supabase_cita_nueva(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """
    Recibe eventos de Supabase cuando se inserta una fila en `citas`.

    Payload esperado:
    {
      "type": "INSERT",
      "table": "citas",
      "schema": "public",
      "record": {
        "id": "...",
        "nombre": "...",
        "telefono": "...",
        "fecha": "...",
        "hora_inicio": "...",
        "hora_fin": "...",
        "estilista_id_yaml": "...",
        "alergias": "...",
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

    # 2. Parsear payload
    try:
        payload = await request.json()
    except Exception as e:
        log.error("Error parseando payload Supabase: %s", e)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("type")
    table = payload.get("table")
    record = payload.get("record") or {}

    log.info("Supabase webhook: %s on %s | record id=%s %s %s",
             event_type, table, record.get("id"), record.get("fecha"),
             record.get("hora_inicio"))

    # 3. Solo nos interesan INSERT sobre `citas` con estado confirmada
    if event_type != "INSERT" or table != "citas":
        log.info("Ignorado: no es INSERT en citas.")
        return {"status": "ignored", "reason": "not an INSERT on citas"}

    if record.get("estado") and record.get("estado") != "confirmada":
        log.info("Ignorado: estado=%s.", record.get("estado"))
        return {"status": "ignored", "reason": "cita no confirmada"}

    # 4. Cargar servicios asociados a la cita para incluirlos en el email
    servicios = _cargar_servicios_de_cita(record.get("id"))

    # 5. Enviar email
    result = notificar_nueva_cita(record, servicios=servicios)

    if result["ok"]:
        log.info("Email de nueva cita enviado (id=%s)", result["id"])
    else:
        log.error("Error enviando email de nueva cita: %s", result["error"])

    return {
        "status": "ok" if result["ok"] else "error",
        "email_id": result.get("id"),
        "error": result.get("error"),
    }


@router.post("/supabase/webhook/cita-modificada")
async def supabase_cita_modificada(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """
    Recibe eventos UPDATE en `citas`. Distingue cancelacion de modificacion.
    """
    if WEBHOOK_SECRET:
        if not x_webhook_secret or not hmac.compare_digest(
            x_webhook_secret, WEBHOOK_SECRET
        ):
            log.warning("Webhook cita-modificada con secreto invalido. Rechazado.")
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    try:
        payload = await request.json()
    except Exception as e:
        log.error("Error parseando payload UPDATE: %s", e)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("type")
    table = payload.get("table")
    record = payload.get("record") or {}
    old_record = payload.get("old_record") or {}

    log.info("Supabase webhook: %s on %s | record id=%s",
             event_type, table, record.get("id"))

    if event_type != "UPDATE" or table != "citas":
        log.info("Ignorado: no es UPDATE en citas (type=%s, table=%s).",
                 event_type, table)
        return {"status": "ignored", "reason": "not an UPDATE on citas"}

    result = notificar_cambio_cita(old_record, record)

    if result.get("skipped"):
        log.info("Cambio sin campos relevantes: ignorado (no email).")
        return {"status": "ignored", "reason": "cambio solo en campos internos"}

    if result.get("ok"):
        log.info("Email de cambio de cita enviado (id=%s)", result.get("id"))
    else:
        log.error("Error enviando email de cambio: %s", result.get("error"))

    return {
        "status": "ok" if result.get("ok") else "error",
        "email_id": result.get("id"),
        "error": result.get("error"),
    }
