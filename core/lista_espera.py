"""
Logica de la lista de espera (issue #6).

Flujo:
  1. Cliente intenta reservar en fecha+turno lleno.
  2. Bot ofrece apuntarse a lista de espera -> tool `apuntar_lista_espera`.
  3. Cuando alguien cancela una reserva, el backend llama a
     `procesar_cancelacion(fecha, turno)` que busca el primer candidato
     compatible y le manda WhatsApp.
  4. El cliente responde SI/NO al WhatsApp.
     SI -> reserva automatica + sale de lista.
     NO o sin respuesta en 30 min -> se pasa al siguiente.

Configurable:
  - VENTANA_HORAS_RESPUESTA: tiempo para responder a la oferta antes
    de que expire. Por defecto 1h (mas estricto que recordatorios
    porque la mesa libre se la puede llevar otro).
"""
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Optional

from core.config import supabase
from core.logger import get_logger
from core.memory import _normalizar_telefono
from core.restaurante_data import RESTAURANTE
from core.whatsapp_out import enviar_whatsapp

log = get_logger(__name__)


VENTANA_HORAS_RESPUESTA = 1


# ════════════════════════════════════════════════════════════════════
# 1. Apuntar a lista de espera
# ════════════════════════════════════════════════════════════════════

def apuntar_en_lista_espera(input_data: dict, telefono_canal: Optional[str] = None,
                            canal_origen: str = "web") -> dict:
    """
    Anade un cliente a la lista de espera.

    Args en input_data:
        nombre, telefono, fecha (YYYY-MM-DD), hora (HH:MM, opcional),
        num_personas, alergias (opt), notas (opt).
    """
    nombre = (input_data.get("nombre") or "").strip()
    telefono = _normalizar_telefono(
        (input_data.get("telefono") or "").strip() or telefono_canal or ""
    )
    fecha = (input_data.get("fecha") or "").strip()
    hora = (input_data.get("hora") or "").strip() or None
    num_personas = input_data.get("num_personas")
    alergias = (input_data.get("alergias") or "").strip() or None
    notas = (input_data.get("notas") or "").strip() or None

    if not nombre:
        return {"status": "error", "mensaje": "Falta el nombre del cliente."}
    if not telefono:
        return {"status": "error", "mensaje": "Falta el telefono del cliente."}
    if not fecha:
        return {"status": "error", "mensaje": "Falta la fecha."}
    if not isinstance(num_personas, int) or num_personas < 1:
        return {"status": "error", "mensaje": "num_personas debe ser un entero >= 1."}

    # Inferir turno desde la hora si la dieron
    turno = None
    if hora:
        try:
            h = int(hora.split(":")[0])
            turno = "comida" if h < 18 else "cena"
        except (ValueError, IndexError):
            pass

    try:
        # Anti-duplicado: si ya esta en lista_espera para mismo dia+turno
        existentes = (
            supabase.table("lista_espera")
            .select("id, estado")
            .eq("telefono", telefono)
            .eq("fecha", fecha)
            .in_("estado", ["esperando", "notificado"])
            .limit(1)
            .execute()
        )
        if existentes.data:
            return {
                "status": "ya_en_lista",
                "lista_id": existentes.data[0]["id"],
                "mensaje": (
                    f"{nombre} ya esta en la lista de espera para el {fecha}. "
                    f"Te avisaremos si se libera mesa. No hace falta apuntarse otra vez."
                ),
            }

        registro = {
            "nombre": nombre,
            "telefono": telefono,
            "fecha": fecha,
            "hora_preferida": hora,
            "turno": turno,
            "num_personas": num_personas,
            "alergias": alergias,
            "notas": notas,
            "estado": "esperando",
            "canal_origen": canal_origen,
        }
        ins = supabase.table("lista_espera").insert(registro).execute()
        lista_id = ins.data[0]["id"] if ins.data else None

        return {
            "status": "ok",
            "lista_id": lista_id,
            "mensaje": (
                f"Apuntado en lista de espera para el {fecha}. Te avisaremos "
                f"por WhatsApp si se libera mesa para {num_personas} personas. "
                f"Cuando recibas el aviso, responde SI o NO en 1 hora para "
                f"asegurar la mesa."
            ),
        }

    except Exception as e:
        return {"status": "error", "mensaje": f"No pude apuntarte: {str(e)}"}


# ════════════════════════════════════════════════════════════════════
# 2. Matching tras cancelacion
# ════════════════════════════════════════════════════════════════════

def buscar_candidato_compatible(fecha: str, turno: str, plazas_libres: int) -> Optional[dict]:
    """
    Busca el PRIMER cliente en lista_espera (FIFO) compatible con la
    mesa que se acaba de liberar.

    Compatible = mismo dia, mismo turno (o sin turno especificado),
    num_personas <= plazas_libres, estado='esperando'.
    """
    try:
        res = (
            supabase.table("lista_espera")
            .select("*")
            .eq("fecha", fecha)
            .eq("estado", "esperando")
            .lte("num_personas", plazas_libres)
            .order("created_at", desc=False)
            .execute()
        )
        candidatos = res.data or []
        # Filtrar por turno (si lo tienen, debe coincidir; si no, vale)
        for c in candidatos:
            t = c.get("turno")
            if not t or t == turno:
                return c
        return None
    except Exception as e:
        log.warning("Error buscando candidato lista_espera: %s", e)
        return None


def _construir_oferta_wa(candidato: dict, fecha: str, turno: str, hora_libre: str) -> str:
    nombre = candidato.get("nombre") or "hola"
    num = candidato.get("num_personas") or "?"
    return (
        f"¡Hola {nombre}! Soy el bot de {RESTAURANTE['nombre']}. Acaba de "
        f"liberarse una mesa para {num} personas el {fecha} a las {hora_libre}.\n\n"
        f"¿La quieres? Responde *SI* en menos de 1 hora y te la apunto. "
        f"Si no respondes, ofreceremos la mesa a otra persona."
    )


def notificar_candidato(candidato: dict, fecha: str, turno: str, hora_libre: str) -> dict:
    """
    Manda WhatsApp al candidato y marca el registro como 'notificado'.
    """
    telefono = _normalizar_telefono(candidato.get("telefono") or "")
    if not telefono.startswith("+"):
        return {"ok": False, "error": "telefono invalido"}

    mensaje = _construir_oferta_wa(candidato, fecha, turno, hora_libre)
    envio = enviar_whatsapp(telefono, mensaje)

    ahora = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table("lista_espera").update({
            "estado": "notificado",
            "notificado_at": ahora,
            "notificado_sid": envio.get("sid") if envio.get("ok") else None,
        }).eq("id", candidato["id"]).execute()
    except Exception as e:
        log.warning("No se pudo marcar notificado en BD: %s", e)

    return {
        "ok": envio.get("ok", False),
        "error": envio.get("error"),
        "lista_id": candidato.get("id"),
    }


def procesar_cancelacion(fecha: str, turno: str, hora_libre: str = "21:00") -> Optional[dict]:
    """
    Punto de entrada cuando una reserva se cancela. Busca primer candidato
    compatible y le manda oferta. Devuelve None si no hay candidatos.

    `hora_libre` es la hora de la reserva cancelada (para sugerirla en el WA).
    """
    # Calculamos plazas libres aproximadas tras la cancelacion mirando aforo.
    # Importacion tardia para evitar circular.
    from core.reservas import _huecos_libres
    huecos = _huecos_libres(fecha, turno)
    if huecos < 1:
        return None

    candidato = buscar_candidato_compatible(fecha, turno, huecos)
    if not candidato:
        return None

    log.info("Lista espera: notificando candidato %s para %s %s (%dp)",
             candidato["nombre"], fecha, turno, candidato["num_personas"])

    return notificar_candidato(candidato, fecha, turno, hora_libre)


# ════════════════════════════════════════════════════════════════════
# 3. Procesar respuesta SI/NO al WhatsApp de oferta
# ════════════════════════════════════════════════════════════════════

def candidato_con_oferta_reciente(telefono: str) -> Optional[dict]:
    """
    Busca un candidato cuya oferta de lista de espera fue enviada en las
    ultimas N horas y aun no tiene respuesta.
    """
    tel = _normalizar_telefono(telefono or "")
    if not tel:
        return None
    limite = (datetime.now(timezone.utc)
              - timedelta(hours=VENTANA_HORAS_RESPUESTA)).isoformat()
    try:
        res = (
            supabase.table("lista_espera")
            .select("*")
            .eq("telefono", tel)
            .eq("estado", "notificado")
            .gte("notificado_at", limite)
            .order("notificado_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]
        return None
    except Exception as e:
        log.warning("Error buscando oferta reciente: %s", e)
        return None


def _es_si(t):
    return (t or "").strip().lower() in {"si", "sí", "s", "ok", "vale", "la quiero", "yes"}


def _es_no(t):
    return (t or "").strip().lower() in {"no", "n", "paso", "no puedo"}


def procesar_respuesta_oferta(candidato: dict, texto: str) -> Optional[str]:
    """
    Procesa la respuesta del cliente a la oferta de lista de espera.

    SI -> intenta crear reserva con sus datos. Marca 'aceptado'.
    NO -> marca 'rechazado'. Pasa al siguiente candidato.
    Texto libre -> devuelve None y sigue el flujo normal del bot.
    """
    ahora = datetime.now(timezone.utc).isoformat()

    if _es_si(texto):
        # Crear reserva con los datos del candidato
        from core.reservas import reservar_mesa
        hora = candidato.get("hora_preferida") or "21:00"
        if isinstance(hora, str) and len(hora) > 5:
            hora = hora[:5]

        resultado = reservar_mesa({
            "nombre": candidato.get("nombre"),
            "telefono": candidato.get("telefono"),
            "fecha": candidato.get("fecha"),
            "hora": hora,
            "num_personas": candidato.get("num_personas"),
            "alergias": candidato.get("alergias"),
            "notas": candidato.get("notas"),
        }, telefono_canal=candidato.get("telefono"), canal_origen="whatsapp")

        try:
            supabase.table("lista_espera").update({
                "estado": "aceptado",
                "respuesta_at": ahora,
            }).eq("id", candidato["id"]).execute()
        except Exception as e:
            log.warning("Error marcando aceptado: %s", e)

        if resultado.get("status") in {"creada", "actualizada"}:
            return (
                f"¡Genial! Mesa apuntada para {candidato.get('fecha')}. "
                f"Te esperamos en {RESTAURANTE['nombre']}. Si necesitas "
                f"cambiar algo escribe por aqui."
            )
        else:
            # Algo fallo: reserva no se pudo crear (ej: turno se llen otra vez)
            return (
                "Perdona, parece que la mesa se acaba de ocupar. Vuelvo a "
                "ponerte en lista por si surge otra. Avisame si quieres "
                "buscar otra fecha."
            )

    if _es_no(texto):
        try:
            supabase.table("lista_espera").update({
                "estado": "rechazado",
                "respuesta_at": ahora,
            }).eq("id", candidato["id"]).execute()
        except Exception as e:
            log.warning("Error marcando rechazado: %s", e)

        # Pasar al siguiente candidato compatible para la misma fecha+turno
        try:
            from core.reservas import _huecos_libres
            fecha = candidato.get("fecha")
            turno = candidato.get("turno") or "cena"
            huecos = _huecos_libres(fecha, turno)
            if huecos > 0:
                siguiente = buscar_candidato_compatible(fecha, turno, huecos)
                if siguiente:
                    notificar_candidato(siguiente, fecha, turno,
                                        candidato.get("hora_preferida") or "21:00")
        except Exception as e:
            log.warning("Error notificando siguiente candidato: %s", e)

        return "Sin problema, gracias por avisar. Te quitamos de la lista."

    # Texto libre -> sigue al bot normal
    return None
