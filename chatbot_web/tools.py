"""Tools del chatbot WEB para Salon Mara.

Mismas tools que el canal WhatsApp pero adaptadas:
  - El identificador de canal aqui es session_id, no telefono.
  - El cliente puede o no dar su telefono. Si no lo da, no podemos
    agendar — la tool agendar_cita pedira a Claude que lo solicite.
"""
from chatbot_whatsapp.tools import (
    TOOLS as TOOLS_WA,
    tool_consultar_servicios,
    tool_consultar_disponibilidad,
    tool_consultar_horario,
)
from core.citas import (
    agendar_cita as _agendar_cita,
    buscar_citas as _buscar_citas,
    cancelar_cita as _cancelar_cita,
    modificar_cita as _modificar_cita,
)
from core.escalacion import escalar_a_humano as _escalar_a_humano
from core.logger import get_logger

log = get_logger(__name__)


# Reusamos el mismo catalogo (mismas firmas, mismas reglas).
TOOLS = TOOLS_WA


# En web no tenemos telefono del canal: el cliente lo da en input_data.
def tool_agendar_cita(input_data: dict, session_id: str) -> dict:
    return _agendar_cita(input_data, telefono_canal=None, canal_origen="web")


def tool_cancelar_cita(input_data: dict, session_id: str) -> dict:
    # En web no tenemos telefono del canal, asi que la verificacion solo
    # puede ser por nombre_confirmacion.
    return _cancelar_cita(input_data, telefono_canal=None, canal_actual="web")


def tool_buscar_citas(input_data: dict, session_id: str) -> dict:
    """En web exigimos nombre + telefono del cliente (no hay tel del canal)."""
    return _buscar_citas(
        telefono=input_data.get("telefono"),
        nombre=input_data.get("nombre"),
        solo_futuras=True,
    )


def tool_modificar_cita(input_data: dict, session_id: str) -> dict:
    """Modifica una cita existente in-place. Web no aporta tel del canal,
    pero modificar_cita localiza por id_cita (de buscar_citas)."""
    return _modificar_cita(input_data, telefono_canal=None, canal_origen="web")


def tool_escalar_a_humano(input_data: dict, session_id: str) -> dict:
    return _escalar_a_humano(input_data, telefono=None, canal_origen="web")


def ejecutar_tool(tool_name: str, tool_input: dict, session_id: str) -> str:
    log.info("[web] Ejecutando tool: %s | Input: %s", tool_name, tool_input)

    if tool_name == "agendar_cita":
        result = tool_agendar_cita(tool_input, session_id)
    elif tool_name == "consultar_disponibilidad":
        result = tool_consultar_disponibilidad(tool_input)
    elif tool_name == "cancelar_cita":
        result = tool_cancelar_cita(tool_input, session_id)
    elif tool_name == "buscar_citas":
        result = tool_buscar_citas(tool_input, session_id)
    elif tool_name == "modificar_cita":
        result = tool_modificar_cita(tool_input, session_id)
    elif tool_name == "consultar_servicios":
        result = tool_consultar_servicios(tool_input)
    elif tool_name == "consultar_horario":
        result = tool_consultar_horario(tool_input)
    elif tool_name == "escalar_a_humano":
        result = tool_escalar_a_humano(tool_input, session_id)
    else:
        result = {"status": "error", "mensaje": f"Tool desconocida: {tool_name}"}

    log.info("[web] Tool %s resultado: %s", tool_name, result)
    return str(result)
