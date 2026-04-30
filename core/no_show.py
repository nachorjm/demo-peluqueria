"""
Logica de deteccion de no-shows (issue #10).

Cron periodico (cada 30 min) que mira reservas confirmadas cuya hora
de inicio fue hace mas de N minutos. Como no tenemos boton "ha llegado"
en el panel todavia, asumimos no-show pasado ese margen y:
  1. Marcamos estado='no_show' + motivo_cancelacion='no_show_automatico'.
  2. Liberamos la mesa: la query de mesas_ocupadas ya filtra estado=
     'confirmada' asi que pasar a no_show la libera automaticamente.
  3. Disparamos el matching de lista de espera por si alguien queria
     esa franja.
  4. Acumulamos para email diario al duenno con el resumen del dia.

Configurable:
  - MARGEN_NO_SHOW_MIN: minutos tras hora de inicio sin llegada para
    considerarla no-show. Default 30 (margen de cortesia razonable).
"""
from datetime import date, datetime, timedelta, timezone
from typing import List

from core.config import supabase
from core.lista_espera import procesar_cancelacion
from core.logger import get_logger

log = get_logger(__name__)


MARGEN_NO_SHOW_MIN = 30


def reservas_candidatas_no_show(ahora: datetime) -> List[dict]:
    """
    Devuelve reservas confirmadas cuya hora de inicio fue hace mas de
    MARGEN_NO_SHOW_MIN minutos.

    Filtra solo por fecha=hoy para evitar marcar reservas pasadas
    historicas que se hayan quedado sin actualizar.
    """
    hoy = ahora.date().isoformat()
    hora_limite = (ahora - timedelta(minutes=MARGEN_NO_SHOW_MIN)).strftime("%H:%M:%S")

    try:
        res = (
            supabase.table("reservas")
            .select("id, nombre, telefono, fecha, hora, hora_fin, num_personas, turno")
            .eq("fecha", hoy)
            .eq("estado", "confirmada")
            .lt("hora", hora_limite)
            .execute()
        )
        return res.data or []
    except Exception as e:
        log.warning("Error consultando candidatos no_show: %s", e)
        return []


def marcar_no_show(reserva: dict) -> dict:
    """
    Marca una reserva como no_show y dispara matching lista de espera.
    """
    try:
        ahora_iso = datetime.now(timezone.utc).isoformat()
        supabase.table("reservas").update({
            "estado": "no_show",
            "motivo_cancelacion": "no_show_automatico",
            "updated_at": ahora_iso,
        }).eq("id", reserva["id"]).execute()
    except Exception as e:
        log.warning("Error marcando no_show %s: %s", reserva.get("id"), e)
        return {"ok": False, "error": str(e), "reserva_id": reserva.get("id")}

    # Liberar mesa: lista de espera puede aprovecharla
    try:
        procesar_cancelacion(
            fecha=reserva.get("fecha"),
            turno=reserva.get("turno") or "cena",
            hora_libre=(reserva.get("hora") or "21:00")[:5],
        )
    except Exception as e:
        log.warning("Lista espera matching tras no_show fallo: %s", e)

    return {
        "ok": True,
        "reserva_id": reserva.get("id"),
        "nombre": reserva.get("nombre"),
        "num_personas": reserva.get("num_personas"),
        "hora": reserva.get("hora"),
    }


def detectar_y_marcar_no_shows() -> dict:
    """
    Punto de entrada del cron. Detecta candidatos y los marca.
    Devuelve resumen con la lista de no-shows marcados.
    """
    ahora = datetime.now()  # local time (sin tz porque la BD usa fecha local)
    candidatos = reservas_candidatas_no_show(ahora)

    log.info("No-show detector: %d candidatos a las %s", len(candidatos), ahora.strftime("%H:%M"))

    marcados = []
    for r in candidatos:
        resultado = marcar_no_show(r)
        if resultado["ok"]:
            marcados.append(resultado)
            log.info("no_show: %s (%dp) hora prevista %s",
                     r.get("nombre"), r.get("num_personas"), r.get("hora"))

    return {
        "total_candidatos": len(candidatos),
        "marcados": len(marcados),
        "detalle": marcados,
    }
