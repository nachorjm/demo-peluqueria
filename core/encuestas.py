"""
Logica de encuestas post-visita (issue #7).

Flujo:
  1. Cron diario al mediodia (12:00). Mira reservas con fecha=ayer y
     estado=confirmada (no canceladas, no no_show) que no hayan
     recibido encuesta aun.
  2. Manda WhatsApp: "Hola Marta, ¿que tal anoche en el restaurante?
     Puntuanos del 1 al 5 (responde solo el numero)".
  3. Cliente responde:
     - 1, 2 o 3 -> bot pide comentario. Lo guarda y manda email al duenno.
     - 4 o 5 -> bot agradece y manda enlace de Google Reviews.
     - Texto libre o nada -> queda sin valoracion.

Configurable:
  - GOOGLE_REVIEW_URL: url corta de Google Reviews del restaurante.
  - VENTANA_HORAS_RESPUESTA_ENCUESTA: tiempo desde envio en el que
    consideramos que la respuesta del cliente es a la encuesta.
"""
import os
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from core.config import supabase
from core.logger import get_logger
from core.memory import _normalizar_telefono
from core.notifications import send_email
from core.restaurante_data import RESTAURANTE
from core.whatsapp_out import enviar_whatsapp

log = get_logger(__name__)


GOOGLE_REVIEW_URL = os.environ.get(
    "GOOGLE_REVIEW_URL", "https://g.page/CasaLolaValencia/review"
).strip()
NOTIFICATIONS_TO = os.environ.get("NOTIFICATIONS_TO", "").strip()
VENTANA_HORAS_RESPUESTA_ENCUESTA = 24


# ════════════════════════════════════════════════════════════════════
# 1. Envio diario
# ════════════════════════════════════════════════════════════════════

def reservas_pendientes_encuesta(fecha_objetivo: date) -> List[dict]:
    """
    Devuelve reservas confirmadas para `fecha_objetivo` (ayer) sin
    encuesta enviada aun.
    """
    try:
        res = (
            supabase.table("reservas")
            .select("*")
            .eq("fecha", fecha_objetivo.isoformat())
            .eq("estado", "confirmada")
            .is_("encuesta_enviada_at", "null")
            .execute()
        )
        return res.data or []
    except Exception as e:
        log.warning("Error consultando reservas para encuesta: %s", e)
        return []


def _construir_mensaje_encuesta(reserva: dict) -> str:
    nombre = reserva.get("nombre") or "hola"
    return (
        f"¡Hola {nombre}! Soy {RESTAURANTE['nombre']}. ¿Qué tal la "
        f"experiencia ayer?\n\n"
        f"Puntúanos del 1 al 5 (responde solo el número):\n"
        f"5 = excelente, 1 = mal\n\n"
        f"Tu opinion nos ayuda a mejorar."
    )


def enviar_encuesta_a(reserva: dict) -> dict:
    telefono = _normalizar_telefono(reserva.get("telefono") or "")
    if not telefono.startswith("+"):
        return {"ok": False, "error": "telefono invalido", "reserva_id": reserva.get("id")}

    mensaje = _construir_mensaje_encuesta(reserva)
    envio = enviar_whatsapp(telefono, mensaje)
    ahora = datetime.now(timezone.utc).isoformat()

    try:
        supabase.table("reservas").update({
            "encuesta_enviada_at": ahora,
            "encuesta_sid": envio.get("sid") if envio.get("ok") else None,
        }).eq("id", reserva["id"]).execute()
    except Exception as e:
        log.warning("No se pudo marcar encuesta_enviada_at: %s", e)

    return {
        "ok": envio.get("ok", False),
        "error": envio.get("error"),
        "reserva_id": reserva.get("id"),
    }


def enviar_encuestas_de_ayer() -> dict:
    """Punto de entrada del cron diario."""
    ayer = date.today() - timedelta(days=1)
    pendientes = reservas_pendientes_encuesta(ayer)
    log.info("Encuestas para reservas del %s: %d pendientes", ayer, len(pendientes))

    resultados = {"total": len(pendientes), "enviadas": 0, "fallidas": 0, "detalle": []}
    for reserva in pendientes:
        r = enviar_encuesta_a(reserva)
        resultados["detalle"].append(r)
        if r["ok"]:
            resultados["enviadas"] += 1
        else:
            resultados["fallidas"] += 1

    log.info("Encuestas enviadas: %d / %d", resultados["enviadas"], resultados["total"])
    return resultados


# ════════════════════════════════════════════════════════════════════
# 2. Respuesta del cliente a la encuesta
# ════════════════════════════════════════════════════════════════════

def reserva_con_encuesta_reciente(telefono: str) -> Optional[dict]:
    """
    Devuelve la reserva mas reciente del cliente cuya encuesta se mando
    en las ultimas N horas y aun NO tiene feedback registrado.
    """
    tel = _normalizar_telefono(telefono or "")
    if not tel:
        return None

    limite = (datetime.now(timezone.utc)
              - timedelta(hours=VENTANA_HORAS_RESPUESTA_ENCUESTA)).isoformat()
    try:
        # Reservas del cliente con encuesta enviada recientemente
        res = (
            supabase.table("reservas")
            .select("*")
            .eq("telefono", tel)
            .gte("encuesta_enviada_at", limite)
            .order("encuesta_enviada_at", desc=True)
            .limit(5)
            .execute()
        )
        reservas = res.data or []
        if not reservas:
            return None

        # Filtrar las que ya tienen feedback (no procesar dos veces)
        ids = [r["id"] for r in reservas]
        feedbacks = (
            supabase.table("feedback_clientes")
            .select("reserva_id")
            .in_("reserva_id", ids)
            .execute()
        )
        ids_con_feedback = {f["reserva_id"] for f in (feedbacks.data or [])}
        for r in reservas:
            if r["id"] not in ids_con_feedback:
                return r
        return None
    except Exception as e:
        log.warning("Error buscando encuesta reciente: %s", e)
        return None


def _es_valoracion(texto: str) -> Optional[int]:
    """Si el texto es claramente un numero 1-5, lo devuelve. Si no, None."""
    if not texto:
        return None
    t = texto.strip().lower().rstrip(".,!?")
    # Numeros: "5", "5 estrellas", "5/5", "un 5"
    for n in range(1, 6):
        if t == str(n) or t.startswith(f"{n} ") or t.startswith(f"{n}/"):
            return n
        if t == f"un {n}" or t == f"le doy un {n}":
            return n
    # Palabras
    palabras_a_num = {
        "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    }
    for palabra, n in palabras_a_num.items():
        if t == palabra or t == f"un {palabra}":
            return n
    return None


def _guardar_feedback(reserva: dict, valoracion: int, comentario: Optional[str] = None,
                      enviado_a_review: bool = False) -> None:
    try:
        supabase.table("feedback_clientes").insert({
            "reserva_id": reserva["id"],
            "telefono": reserva.get("telefono"),
            "nombre": reserva.get("nombre"),
            "valoracion": valoracion,
            "comentario": comentario,
            "enviado_a_review": enviado_a_review,
        }).execute()
    except Exception as e:
        log.warning("Error guardando feedback: %s", e)


def _notificar_feedback_negativo(reserva: dict, valoracion: int, comentario: str) -> None:
    """Envia email al duenno cuando un cliente ha valorado bajo."""
    if not NOTIFICATIONS_TO:
        return
    nombre = reserva.get("nombre") or "(sin nombre)"
    telefono = reserva.get("telefono") or "(sin telefono)"
    fecha = reserva.get("fecha") or ""
    subject = f"⚠️ Feedback negativo ({valoracion}/5) — {nombre}"
    html = f"""
<!doctype html>
<html><body style="font-family:Georgia,serif; padding:24px; background:#FAF7F2; color:#2A2118;">
<div style="max-width:580px;margin:0 auto;background:white;border:1px solid #E7DFD2;border-radius:12px;padding:32px;">
  <div style="background:#FEE7C7;color:#7A4500;padding:4px 10px;border-radius:999px;display:inline-block;font-size:12px;font-weight:600;margin-bottom:12px;">
    ATENCIÓN — VALORACIÓN BAJA
  </div>
  <h1 style="color:#7A1F1F;font-size:22px;margin:0 0 16px 0;">
    {nombre} ha puntuado {valoracion}/5
  </h1>
  <p style="color:#6B5E4A;margin-bottom:24px;">
    Reserva del {fecha}. Considera contactar al cliente personalmente.
  </p>
  <table style="width:100%;border-collapse:collapse;font-size:15px;">
    <tr><td style="padding:8px 0;color:#8A7B66;width:130px;">Cliente</td>
        <td style="padding:8px 0;"><strong>{nombre}</strong></td></tr>
    <tr><td style="padding:8px 0;color:#8A7B66;">Telefono</td>
        <td style="padding:8px 0;">{telefono}</td></tr>
    <tr><td style="padding:8px 0;color:#8A7B66;">Valoracion</td>
        <td style="padding:8px 0;font-size:24px;font-weight:600;color:#C0392B;">{valoracion} / 5</td></tr>
    <tr><td style="padding:8px 0;color:#8A7B66;vertical-align:top;">Comentario</td>
        <td style="padding:8px 0;white-space:pre-wrap;">{comentario}</td></tr>
  </table>
</div>
</body></html>
""".strip()
    text = (
        f"VALORACION BAJA — {nombre} ({valoracion}/5)\n"
        f"--------------------------------------------\n"
        f"Cliente:    {nombre}\n"
        f"Telefono:   {telefono}\n"
        f"Reserva:    {fecha}\n"
        f"Valoracion: {valoracion}/5\n"
        f"Comentario: {comentario}\n"
    )
    send_email(subject=subject, html=html, text=text)


def procesar_respuesta_encuesta(reserva: dict, texto: str) -> Optional[str]:
    """
    Procesa la respuesta del cliente a la encuesta.

    - Si es 4-5 -> agradece + manda enlace Google Reviews.
    - Si es 1-3 -> pide comentario y guarda. (segundo turno: el comentario
      llega como texto libre y lo trataremos como comentario asociado.)
    - Si no es valoracion clara -> devuelve None (sigue al bot normal).
    """
    valoracion = _es_valoracion(texto)
    if valoracion is None:
        # Quizas es el comentario tras una valoracion baja previa.
        # Buscamos si hay feedback reciente sin comentario.
        return _procesar_posible_comentario(reserva, texto)

    if valoracion >= 4:
        _guardar_feedback(reserva, valoracion, enviado_a_review=True)
        nombre = reserva.get("nombre") or "hola"
        return (
            f"¡{nombre}, qué alegría! Si te ha gustado tanto, ¿nos dejas "
            f"una resena en Google? Solo te lleva un minuto:\n\n"
            f"{GOOGLE_REVIEW_URL}\n\n"
            f"¡Te esperamos pronto!"
        )

    # valoracion <= 3
    _guardar_feedback(reserva, valoracion)
    return (
        "Lo sentimos mucho. ¿Nos cuentas que pudimos hacer mejor? Tu "
        "comentario llega directo al duenno y nos ayuda a corregir."
    )


def _procesar_posible_comentario(reserva: dict, texto: str) -> Optional[str]:
    """
    Si el cliente acaba de dar una valoracion baja y este texto parece
    el comentario que estabamos esperando, lo guardamos y notificamos
    al duenno por email.
    """
    if len(texto.strip()) < 4:
        return None  # demasiado corto, probablemente otra cosa
    try:
        # Buscar feedback reciente del cliente sin comentario
        limite = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        res = (
            supabase.table("feedback_clientes")
            .select("*")
            .eq("reserva_id", reserva["id"])
            .gte("created_at", limite)
            .is_("comentario", "null")
            .lte("valoracion", 3)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not res.data:
            return None
        feedback = res.data[0]
        # Actualizar comentario
        supabase.table("feedback_clientes").update({
            "comentario": texto.strip(),
        }).eq("id", feedback["id"]).execute()
        # Notificar al duenno
        _notificar_feedback_negativo(reserva, feedback["valoracion"], texto.strip())
        return (
            "Gracias por contarnoslo. Le he hecho llegar tu comentario "
            "al duenno. Esperamos compensarte la proxima vez."
        )
    except Exception as e:
        log.warning("Error procesando comentario de feedback: %s", e)
        return None
