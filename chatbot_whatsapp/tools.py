"""Tools del chatbot WhatsApp para Salon Mara.

Catalogo de tools que Claude puede usar en el canal WhatsApp:
  - agendar_cita
  - consultar_disponibilidad
  - buscar_citas
  - modificar_cita
  - cancelar_cita
  - consultar_servicios
  - consultar_horario
  - escalar_a_humano

(derivar_a_whatsapp y consultar_historial son exclusivas del canal voz.)

La logica vive en `core/citas.py` y `core/servicios.py` para que web y
voz reusen lo mismo.
"""
from typing import Optional

from core.citas import (
    agendar_cita as _agendar_cita,
    buscar_citas as _buscar_citas,
    cancelar_cita as _cancelar_cita,
    consultar_disponibilidad as _consultar_disponibilidad,
    modificar_cita as _modificar_cita,
)
from core.peluqueria_data import (
    DIAS_NOMBRE,
    SALON,
    SERVICIOS,
    horario_completo_legible,
    horario_dia_legible,
    servicios_legibles,
)
from core.estilistas import equipo_legible
from core.escalacion import escalar_a_humano as _escalar_a_humano
from core.logger import get_logger

log = get_logger(__name__)


_NOMBRES_ESTILISTAS = []
try:
    from core.peluqueria_data import estilistas_activos
    _NOMBRES_ESTILISTAS = [e["nombre"] for e in estilistas_activos()]
except Exception:
    _NOMBRES_ESTILISTAS = []


# ─── Catalogo de TOOLS para Claude ──────────────────────────────────
TOOLS = [
    {
        "name": "agendar_cita",
        "description": (
            "Crea una cita en el salon. Usala SOLO cuando el cliente haya "
            "CONFIRMADO explicitamente despues de que le hayas resumido los "
            "datos. Necesitas: nombre, telefono, fecha (YYYY-MM-DD), "
            "hora_inicio (HH:MM) y servicios (lista de nombres exactos del "
            "catalogo). Si el cliente prefiere un estilista, pasalo en "
            "estilista_preferido. La duracion total se calcula automaticamente "
            "sumando las duraciones de cada servicio."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string", "description": "Nombre completo del cliente."},
                "telefono": {"type": "string", "description": "Telefono en formato +34XXXXXXXXX."},
                "fecha": {"type": "string", "description": "Fecha en formato YYYY-MM-DD."},
                "hora_inicio": {"type": "string", "description": "Hora de inicio en formato HH:MM (24h)."},
                "servicios": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Lista de nombres exactos del catalogo "
                        "(ej. ['Corte mujer', 'Coloracion raiz']). Usa "
                        "consultar_servicios primero si el cliente no ha "
                        "elegido aun."
                    ),
                },
                "estilista_preferido": {
                    "type": "string",
                    "description": (
                        "Nombre del estilista preferido (opcional). "
                        f"Equipo activo: {', '.join(_NOMBRES_ESTILISTAS)}."
                    ),
                },
                "alergias": {
                    "type": "string",
                    "description": (
                        "Alergias o sensibilidades del cliente, sobre todo "
                        "a tintes/productos (opcional)."
                    ),
                },
                "notas": {
                    "type": "string",
                    "description": "Notas o peticiones especificas (opcional).",
                },
            },
            "required": ["nombre", "telefono", "fecha", "hora_inicio", "servicios"],
        },
    },
    {
        "name": "consultar_disponibilidad",
        "description": (
            "Comprueba si hay un estilista libre para los servicios pedidos "
            "en una fecha y hora concretas. Usala antes de agendar si el "
            "cliente pregunta '¿hay hueco el viernes a las 17h para corte y "
            "color?' o quieres confirmar antes de pedir el resto de datos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha": {"type": "string", "description": "Fecha en formato YYYY-MM-DD."},
                "hora_inicio": {"type": "string", "description": "Hora en formato HH:MM (24h)."},
                "servicios": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de nombres exactos del catalogo.",
                },
                "estilista_preferido": {
                    "type": "string",
                    "description": "Nombre del estilista preferido (opcional).",
                },
            },
            "required": ["fecha", "hora_inicio", "servicios"],
        },
    },
    {
        "name": "buscar_citas",
        "description": (
            "Busca citas futuras del cliente. Usala al INICIO del flujo de "
            "cancelacion o modificacion, ANTES de cancelar_cita o "
            "modificar_cita, para encontrar la(s) cita(s) del cliente y "
            "confirmarle cual quiere tocar. En WhatsApp/voz, pasa solo "
            "'telefono' (el del canal). En web, pasa 'nombre' + 'telefono' "
            "que te haya dado el cliente. Devuelve dict con status, total y "
            "citas (lista con id, nombre, fecha, hora_inicio, hora_fin, "
            "estilista, servicios)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "telefono": {
                    "type": "string",
                    "description": (
                        "Telefono del cliente. En WA/voz, el del canal (ya "
                        "lo tienes). En web, el que te de el cliente."
                    ),
                },
                "nombre": {
                    "type": "string",
                    "description": (
                        "Nombre (total o parcial) del cliente. Obligatorio "
                        "en web. Opcional en WA/voz."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "modificar_cita",
        "description": (
            "Modifica una cita EXISTENTE in-place (no crea otra ni cancela "
            "la anterior). USALA para mover una cita a otra fecha/hora, "
            "cambiar servicios, cambiar estilista, alergias o notas. NUNCA "
            "uses cancelar_cita + agendar_cita para 'mover' una cita: eso "
            "genera duplicados. Llamala despues de buscar_citas pasando el "
            "id_cita que te devolvio. Si la nueva combinacion no cabe, "
            "devuelve estado de error y la cita original NO se toca."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id_cita": {
                    "type": "string",
                    "description": "ID de la cita a modificar (de buscar_citas).",
                },
                "fecha": {"type": "string", "description": "Nueva fecha YYYY-MM-DD (opcional)."},
                "hora_inicio": {"type": "string", "description": "Nueva hora HH:MM (opcional)."},
                "servicios": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Nueva lista de servicios (opcional, sustituye la anterior).",
                },
                "estilista_preferido": {
                    "type": "string",
                    "description": "Nuevo estilista preferido (opcional).",
                },
                "alergias": {"type": "string", "description": "Nuevas alergias (opcional, '' para borrar)."},
                "notas": {"type": "string", "description": "Nuevas notas (opcional)."},
                "nombre": {"type": "string", "description": "Nuevo nombre (raro, opcional)."},
            },
            "required": ["id_cita"],
        },
    },
    {
        "name": "cancelar_cita",
        "description": (
            "Cancela una cita confirmada. Llamala SOLO DESPUES de haber "
            "ejecutado buscar_citas y de que el cliente haya confirmado "
            "cual anular. Identifica la cita con id_cita (preferible) o "
            "con telefono+fecha. Por seguridad, NUNCA canceles sin "
            "verificar identidad: o bien la cita es del mismo canal+telefono "
            "actuales, o bien el cliente confirma el nombre exacto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id_cita": {"type": "string", "description": "ID de la cita (opcional si das telefono+fecha)."},
                "telefono": {"type": "string", "description": "Telefono usado al agendar."},
                "fecha": {"type": "string", "description": "Fecha de la cita (YYYY-MM-DD)."},
                "motivo": {"type": "string", "description": "Motivo de cancelacion (opcional)."},
                "nombre_confirmacion": {
                    "type": "string",
                    "description": (
                        "Nombre exacto con el que el cliente agendo la cita. "
                        "Es la verificacion de identidad. Pidelo SIEMPRE "
                        "antes de cancelar salvo que la cita sea del mismo "
                        "canal y telefono actuales."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "consultar_servicios",
        "description": (
            "Devuelve el catalogo de servicios del salon. Puedes pedir una "
            "categoria concreta o filtrar por especialidad. Usala cuando el "
            "cliente pregunte que servicios hay, precios, duraciones o "
            "tecnicas concretas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "categoria": {
                    "type": "string",
                    "enum": list(SERVICIOS.keys()) + ["todo"],
                    "description": "Categoria a mostrar. Usa 'todo' o omite para el catalogo completo.",
                },
                "especialidad": {
                    "type": "string",
                    "description": (
                        "Filtra solo servicios de una especialidad concreta "
                        "(ej. 'color', 'corte_hombre', 'mechas'). Opcional."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "consultar_horario",
        "description": (
            "Devuelve el horario del salon. Si el cliente pregunta por un "
            "dia concreto, pasalo en 'dia'. Si no, devuelve la semana entera."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dia": {
                    "type": "string",
                    "enum": list(DIAS_NOMBRE.values()),
                    "description": "Dia de la semana (lunes, martes...). Omite para semana completa.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "escalar_a_humano",
        "description": (
            "Pasa el caso al duenno/encargado por email. Usala cuando: el "
            "cliente lo pida explicitamente, sea una queja, pida un servicio "
            "que no esta en el catalogo (extensiones, depilacion, etc.), sea "
            "un caso fuera de lo normal o no puedas resolverlo. Necesitas un "
            "motivo y un contexto breve."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "motivo": {
                    "type": "string",
                    "enum": [
                        "cliente_lo_pide",
                        "queja_o_enfado",
                        "servicio_no_disponible",
                        "caso_complejo",
                        "datos_no_capturados",
                        "otro",
                    ],
                    "description": "Motivo principal de la escalacion.",
                },
                "contexto": {
                    "type": "string",
                    "description": "Resumen breve de la situacion (1-3 frases).",
                },
                "nombre": {"type": "string", "description": "Nombre del cliente (opcional)."},
                "telefono": {"type": "string", "description": "Telefono del cliente (opcional)."},
            },
            "required": ["motivo", "contexto"],
        },
    },
]


# ─── Implementaciones (delegan a core/) ─────────────────────────────
def tool_agendar_cita(input_data: dict, telefono_canal: Optional[str], canal_origen: str = "whatsapp") -> dict:
    return _agendar_cita(input_data, telefono_canal=telefono_canal, canal_origen=canal_origen)


def tool_consultar_disponibilidad(input_data: dict) -> dict:
    return _consultar_disponibilidad(
        fecha=input_data.get("fecha", ""),
        hora_inicio=input_data.get("hora_inicio", ""),
        servicios=input_data.get("servicios") or [],
        estilista_preferido=input_data.get("estilista_preferido"),
    )


def tool_cancelar_cita(input_data: dict, telefono_canal: Optional[str]) -> dict:
    return _cancelar_cita(input_data, telefono_canal=telefono_canal, canal_actual="whatsapp")


def tool_modificar_cita(input_data: dict, telefono_canal: Optional[str]) -> dict:
    return _modificar_cita(input_data, telefono_canal=telefono_canal, canal_origen="whatsapp")


def tool_buscar_citas(input_data: dict, telefono_canal: Optional[str]) -> dict:
    """En WhatsApp el telefono del canal es la clave principal."""
    tel = input_data.get("telefono") or telefono_canal or ""
    return _buscar_citas(
        telefono=tel,
        nombre=input_data.get("nombre"),
        solo_futuras=True,
    )


def tool_consultar_servicios(input_data: dict) -> dict:
    categoria = input_data.get("categoria")
    if categoria == "todo":
        categoria = None
    especialidad = input_data.get("especialidad")
    texto = servicios_legibles(categoria=categoria, especialidad=especialidad)
    return {"status": "ok", "mensaje": texto}


def tool_consultar_horario(input_data: dict) -> dict:
    dia_nombre = (input_data.get("dia") or "").strip().lower()
    if dia_nombre:
        for dia_idx, nombre in DIAS_NOMBRE.items():
            if nombre == dia_nombre:
                return {"status": "ok", "mensaje": horario_dia_legible(dia_idx)}
        return {
            "status": "error",
            "mensaje": f"Dia '{dia_nombre}' no reconocido. Usa nombres en castellano (lunes, martes...).",
        }
    cabecera = (
        f"Horario de {SALON['nombre']} ({SALON.get('ciudad', '')}). "
        f"Direccion: {SALON.get('direccion', '')}. "
        f"Telefono: {SALON.get('telefono', '')}.\n"
        f"Equipo: {equipo_legible()}.\n"
    )
    return {"status": "ok", "mensaje": cabecera + horario_completo_legible()}


def tool_escalar_a_humano_wrapper(input_data: dict, telefono_canal: Optional[str]) -> dict:
    return _escalar_a_humano(input_data, telefono=telefono_canal, canal_origen="whatsapp")


# ─── Despachador ────────────────────────────────────────────────────
def ejecutar_tool(tool_name: str, tool_input: dict, telefono: str) -> str:
    """Despacha la tool que Claude ha pedido y devuelve el mensaje (string)."""
    log.info("Ejecutando tool: %s | Input: %s", tool_name, tool_input)

    if tool_name == "agendar_cita":
        result = tool_agendar_cita(tool_input, telefono)
    elif tool_name == "consultar_disponibilidad":
        result = tool_consultar_disponibilidad(tool_input)
    elif tool_name == "cancelar_cita":
        result = tool_cancelar_cita(tool_input, telefono)
    elif tool_name == "modificar_cita":
        result = tool_modificar_cita(tool_input, telefono)
    elif tool_name == "buscar_citas":
        result = tool_buscar_citas(tool_input, telefono)
    elif tool_name == "consultar_servicios":
        result = tool_consultar_servicios(tool_input)
    elif tool_name == "consultar_horario":
        result = tool_consultar_horario(tool_input)
    elif tool_name == "escalar_a_humano":
        result = tool_escalar_a_humano_wrapper(tool_input, telefono)
    else:
        result = {"status": "error", "mensaje": f"Tool desconocida: {tool_name}"}

    log.info("Tool %s resultado: %s", tool_name, result)
    return str(result)
