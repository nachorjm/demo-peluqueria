"""Tools del agente telefonico (Vapi) de Casa Lola.

El agente de voz se llama "Lola". Tiene 8 tools:
  - reservar_mesa, consultar_disponibilidad, cancelar_reserva (logica en core/reservas.py)
  - consultar_carta, consultar_horario (datos en core/restaurante_data.py)
  - escalar_a_humano (core/escalacion_restaurante.py)
  - consultar_historial (memoria persistente, reconocer cliente recurrente)
  - derivar_a_whatsapp (handoff voz->WhatsApp cuando no capturamos dato por voz)
"""
from datetime import date, timedelta
from typing import Optional

from core.config import supabase
from core.logger import get_logger
from core.memory import _normalizar_telefono, cargar_resumen_llamadas_previas
from core.whatsapp_out import enviar_whatsapp
from core.escalacion_restaurante import escalar_a_humano as _escalar_a_humano
from core.restaurante_data import RESTAURANTE

log = get_logger(__name__)


_DIAS_ES = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
_MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
             "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _bloque_fecha_actual_voz() -> str:
    """
    Bloque de fecha + calendario de 14 dias para Lola.

    Lo inyectamos en la respuesta de `consultar_historial` porque el system
    prompt de Vapi es estatico: al llamar esta tool (que Lola invoca al
    inicio de cada llamada), Claude recibe la fecha actualizada.
    """
    hoy = date.today()
    lineas = [
        f"FECHA DE HOY: {_DIAS_ES[hoy.weekday()]} {hoy.day} de "
        f"{_MESES_ES[hoy.month - 1]} de {hoy.year} (ISO: {hoy.isoformat()}).",
        "",
        "PROXIMOS 14 DIAS (usa esta tabla para resolver 'manana', 'el viernes', "
        "'el sabado que viene'. NO calcules fechas tu mismo):",
    ]
    for delta in range(0, 15):
        d = hoy + timedelta(days=delta)
        etiqueta = "  <- HOY" if delta == 0 else ("  <- MANANA" if delta == 1 else "")
        lineas.append(f"  {_DIAS_ES[d.weekday()]:10s} {d.isoformat()}{etiqueta}")
    return "\n".join(lineas)

# Reutilizamos las implementaciones de las tools de reserva y consulta
# del canal WhatsApp (mismas funciones para todos los canales).
from chatbot_whatsapp.tools import (
    tool_reservar_mesa as _tool_reservar_mesa_wa,
    tool_consultar_disponibilidad,
    tool_cancelar_reserva as _tool_cancelar_reserva_wa,
    tool_consultar_carta,
    tool_consultar_horario,
)


# ════════════════════════════════════════════════════════════════════
# Tool: reservar_mesa (canal voz)
# ════════════════════════════════════════════════════════════════════
def tool_reservar_mesa(input_data: dict, telefono: str, canal_origen: str = "voz") -> dict:
    return _tool_reservar_mesa_wa(input_data, telefono_canal=telefono, canal_origen=canal_origen)


def tool_cancelar_reserva(input_data: dict, telefono: Optional[str]) -> dict:
    from core.reservas import cancelar_reserva as _cancelar
    return _cancelar(input_data, telefono_canal=telefono, canal_actual="voz")


def tool_buscar_reservas(input_data: dict, telefono: Optional[str]) -> dict:
    """
    En voz el telefono del canal es la clave. Como en WA, si el cliente
    no da telefono explicito usamos el del canal. Issue #33.
    """
    from core.reservas import buscar_reservas as _buscar
    tel = input_data.get("telefono") or telefono or ""
    return _buscar(
        telefono=tel,
        nombre=input_data.get("nombre"),
        solo_futuras=True,
    )


def tool_modificar_reserva(input_data: dict, telefono: Optional[str]) -> dict:
    """Modifica una reserva existente in-place (UPDATE, no cancel+create)."""
    from core.reservas import modificar_reserva as _modificar
    return _modificar(input_data, telefono_canal=telefono, canal_origen="voz")


# ════════════════════════════════════════════════════════════════════
# Tool: escalar_a_humano (canal voz)
# ════════════════════════════════════════════════════════════════════
def tool_escalar_a_humano(
    input_data: dict,
    telefono: Optional[str],
    vapi_call_id: Optional[str] = None,
) -> dict:
    return _escalar_a_humano(
        input_data,
        telefono=telefono,
        canal_origen="escalacion",
        vapi_call_id=vapi_call_id,
    )


# ════════════════════════════════════════════════════════════════════
# Tool: consultar_historial (reconocer cliente recurrente)
# ════════════════════════════════════════════════════════════════════
def tool_consultar_historial(telefono: str) -> str:
    """
    Busca llamadas previas del mismo telefono y devuelve contexto.
    Incluye SIEMPRE la fecha actual + tabla de 14 dias para que Claude
    resuelva fechas relativas durante la llamada (el system prompt de
    Vapi es estatico y no sabe que dia es hoy).
    """
    bloque_fecha = _bloque_fecha_actual_voz()

    telefono_limpio = _normalizar_telefono(telefono)
    if not telefono_limpio:
        return (
            bloque_fecha + "\n\n"
            "HISTORIAL: No tengo el numero del cliente, no puedo consultar "
            "llamadas previas. Pide los datos desde cero."
        )

    resumen = cargar_resumen_llamadas_previas(telefono_limpio)

    if not resumen:
        return (
            bloque_fecha + "\n\n"
            "HISTORIAL: Este telefono no tiene llamadas previas registradas. "
            "Es la primera vez que llama. Saluda con normalidad."
        )

    return (
        bloque_fecha + "\n\n"
        "HISTORIAL — Llamadas previas de este cliente (mas recientes primero):\n"
        f"{resumen}\n\n"
        "Saluda con familiaridad reconociendo lo que ya sabes de el. "
        "No pidas datos que ya te dio antes."
    )


# ════════════════════════════════════════════════════════════════════
# Tool: derivar_a_whatsapp (handoff voz -> WhatsApp)
# ════════════════════════════════════════════════════════════════════
# Lola la invoca cuando no ha podido capturar un dato por voz (tipico:
# alergias largas, nombre con ortografia dificil, num_reserva para cancelar).
# El backend:
#   1. Registra un seguimiento pendiente en Supabase.
#   2. Envia WhatsApp al cliente invitandole a responder por texto.

PREGUNTAS_VALIDAS = {
    "alergias",
    "fecha_y_hora",
    "num_personas",
    "confirmacion",
    "nombre",
    "otro",
}


def tool_derivar_a_whatsapp(
    input_data: dict,
    telefono: str,
    vapi_call_id: Optional[str] = None,
) -> dict:
    """
    Crea seguimiento pendiente y envia WhatsApp al cliente.
    """
    pregunta = (input_data.get("pregunta_pendiente") or "otro").strip()
    if pregunta not in PREGUNTAS_VALIDAS:
        pregunta = "otro"

    datos_parciales = input_data.get("datos_parciales") or {}
    if not isinstance(datos_parciales, dict):
        datos_parciales = {}

    contexto = (input_data.get("contexto") or "").strip()
    nombre = datos_parciales.get("nombre") or "hola"

    telefono_limpio = _normalizar_telefono(telefono)
    if not telefono_limpio or not telefono_limpio.startswith("+"):
        return {
            "status": "error",
            "mensaje": (
                "No tengo un numero valido para enviar WhatsApp. Pide "
                "al cliente que te lo confirme o continua por voz."
            ),
        }

    try:
        registro = {
            "telefono": telefono_limpio,
            "datos_parciales": datos_parciales,
            "pregunta_pendiente": pregunta,
            "contexto": contexto or None,
            "estado": "pendiente",
            "vapi_call_id": vapi_call_id,
        }
        res = supabase.table("seguimientos_pendientes").insert(registro).execute()
        seguimiento_id = res.data[0]["id"] if res.data else None
    except Exception as e:
        return {
            "status": "error",
            "mensaje": f"No pude registrar el seguimiento: {str(e)}",
        }

    # Mensaje segun pregunta
    nombre_resto = RESTAURANTE["nombre"]
    if pregunta == "alergias":
        mensaje_wa = (
            f"¡Hola {nombre}! Soy el bot de {nombre_resto}. Hemos hablado hace "
            f"un momento. Para cerrar la reserva con calma, ¿me escribes aqui "
            f"las alergias o intolerancias del grupo? 🌿"
        )
    elif pregunta == "fecha_y_hora":
        mensaje_wa = (
            f"¡Hola {nombre}! Soy el bot de {nombre_resto}. Para cerrar tu "
            f"reserva, ¿me escribes aqui el dia y la hora que quieres? 📅"
        )
    elif pregunta == "num_personas":
        mensaje_wa = (
            f"¡Hola {nombre}! Soy el bot de {nombre_resto}. ¿Cuantos sereis "
            f"al final? Escribelo aqui cuando lo sepas."
        )
    elif pregunta == "confirmacion":
        mensaje_wa = (
            f"¡Hola {nombre}! Te he apuntado la reserva tras la llamada. "
            f"¿Todo correcto o cambiamos algo? Responde aqui si quieres modificar."
        )
    elif pregunta == "nombre":
        mensaje_wa = (
            f"¡Hola! Soy el bot de {nombre_resto}. Para cerrar la reserva "
            f"¿me escribes aqui tu nombre completo, tal y como quieres que "
            f"figure en la mesa?"
        )
    else:
        mensaje_wa = (
            f"¡Hola {nombre}! Soy el bot de {nombre_resto}, hemos hablado "
            f"por telefono. Escribeme aqui y terminamos el proceso tranquilo."
        )

    resultado_envio = enviar_whatsapp(telefono_limpio, mensaje_wa)

    if resultado_envio["ok"]:
        try:
            supabase.table("seguimientos_pendientes").update({
                "twilio_message_sid": resultado_envio["sid"],
            }).eq("id", seguimiento_id).execute()
        except Exception:
            pass

        return {
            "status": "ok",
            "seguimiento_id": seguimiento_id,
            "twilio_sid": resultado_envio["sid"],
            "mensaje": (
                f"He enviado un WhatsApp a {nombre} para que responda por ahi. "
                f"Diselo: 'Te acabo de mandar un mensaje por WhatsApp para que "
                f"puedas escribirlo tranquilamente.'"
            ),
        }
    else:
        log.warning("WhatsApp no enviado: %s", resultado_envio["error"])
        return {
            "status": "parcial",
            "seguimiento_id": seguimiento_id,
            "mensaje": (
                "He intentado enviar el WhatsApp pero no he podido "
                "(posiblemente el numero no esta en el sandbox). El "
                "seguimiento queda registrado para que el restaurante "
                "contacte al cliente."
            ),
            "error_envio": resultado_envio["error"],
        }
