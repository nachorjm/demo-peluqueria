"""Tools del chatbot WEB para Casa Lola.

Mismas tools que el canal WhatsApp pero adaptadas:
  - El identificador de canal aqui es session_id, no telefono.
  - El cliente puede o no dar su telefono. Si no lo da, no podemos
    reservar — la tool reservar_mesa pedira a Claude que lo solicite.
"""
from chatbot_whatsapp.tools import (
    TOOLS as TOOLS_WA,
    tool_consultar_carta,
    tool_consultar_disponibilidad,
    tool_consultar_horario,
    tool_reservar_mesa as _tool_reservar_mesa_wa,
    tool_cancelar_reserva as _tool_cancelar_reserva_wa,
)
from core.escalacion_restaurante import escalar_a_humano as _escalar_a_humano
from core.logger import get_logger

log = get_logger(__name__)


# Reusamos el mismo catalogo (mismas firmas, mismas reglas).
TOOLS = TOOLS_WA


# En web no tenemos telefono del canal: el cliente lo da en input_data.
def tool_reservar_mesa(input_data: dict, session_id: str) -> dict:
    return _tool_reservar_mesa_wa(input_data, telefono_canal=None, canal_origen="web")


def tool_cancelar_reserva(input_data: dict, session_id: str) -> dict:
    # En web no tenemos telefono del canal, asi que la verificacion solo
    # puede ser por nombre_confirmacion (issue #18).
    from core.reservas import cancelar_reserva as _cancelar
    return _cancelar(input_data, telefono_canal=None, canal_actual="web")


def tool_buscar_reservas(input_data: dict, session_id: str) -> dict:
    """
    En web exigimos nombre + telefono del cliente (no hay tel del canal).
    Issue #33.
    """
    from core.reservas import buscar_reservas as _buscar
    return _buscar(
        telefono=input_data.get("telefono"),
        nombre=input_data.get("nombre"),
        solo_futuras=True,
    )


def tool_modificar_reserva(input_data: dict, session_id: str) -> dict:
    """
    Modifica una reserva existente in-place. Web no aporta tel del canal,
    pero modificar_reserva localiza por id_reserva (de buscar_reservas).
    """
    from core.reservas import modificar_reserva as _modificar
    return _modificar(input_data, telefono_canal=None, canal_origen="web")


def tool_escalar_a_humano(input_data: dict, session_id: str) -> dict:
    return _escalar_a_humano(input_data, telefono=None, canal_origen="web")


def tool_apuntar_lista_espera(input_data: dict, session_id: str) -> dict:
    from core.lista_espera import apuntar_en_lista_espera
    return apuntar_en_lista_espera(input_data, telefono_canal=None, canal_origen="web")


def ejecutar_tool(tool_name: str, tool_input: dict, session_id: str) -> str:
    log.info("[web] Ejecutando tool: %s | Input: %s", tool_name, tool_input)

    if tool_name == "reservar_mesa":
        result = tool_reservar_mesa(tool_input, session_id)
    elif tool_name == "consultar_disponibilidad":
        result = tool_consultar_disponibilidad(tool_input)
    elif tool_name == "cancelar_reserva":
        result = tool_cancelar_reserva(tool_input, session_id)
    elif tool_name == "buscar_reservas":
        result = tool_buscar_reservas(tool_input, session_id)
    elif tool_name == "modificar_reserva":
        result = tool_modificar_reserva(tool_input, session_id)
    elif tool_name == "apuntar_lista_espera":
        result = tool_apuntar_lista_espera(tool_input, session_id)
    elif tool_name == "consultar_carta":
        result = tool_consultar_carta(tool_input)
    elif tool_name == "consultar_horario":
        result = tool_consultar_horario(tool_input)
    elif tool_name == "escalar_a_humano":
        result = tool_escalar_a_humano(tool_input, session_id)
    else:
        result = {"status": "error", "mensaje": f"Tool desconocida: {tool_name}"}

    log.info("[web] Tool %s resultado: %s", tool_name, result)
    return str(result)
