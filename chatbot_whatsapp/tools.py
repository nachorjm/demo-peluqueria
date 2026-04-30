"""Tools del chatbot WhatsApp para Casa Lola.

Catalogo de tools que Claude puede usar en el canal WhatsApp:
  - reservar_mesa
  - consultar_disponibilidad
  - cancelar_reserva
  - consultar_carta
  - consultar_horario
  - escalar_a_humano

(derivar_a_whatsapp y consultar_historial son exclusivas del canal voz.)

La logica vive en `core/reservas.py` para que web y voz reusen lo mismo.
"""
from typing import Optional

from core.reservas import (
    buscar_reservas as _buscar_reservas,
    consultar_disponibilidad as _consultar_disponibilidad,
    reservar_mesa as _reservar_mesa,
    cancelar_reserva as _cancelar_reserva,
    modificar_reserva as _modificar_reserva,
)
from core.lista_espera import apuntar_en_lista_espera as _apuntar_en_lista_espera
from core.restaurante_data import (
    CARTA,
    DIAS_NOMBRE,
    FILTROS_ALERGENO,
    RESTAURANTE,
    carta_legible,
    horario_completo_legible,
    horario_dia_legible,
)
from core.escalacion_restaurante import escalar_a_humano as _escalar_a_humano
from core.logger import get_logger

log = get_logger(__name__)


# ─── Catalogo de TOOLS para Claude ──────────────────────────────────
TOOLS = [
    {
        "name": "reservar_mesa",
        "description": (
            "Crea una reserva en el restaurante. Usala SOLO cuando el cliente haya "
            "CONFIRMADO explicitamente despues de que le hayas resumido los datos. "
            "Necesitas como minimo: nombre, telefono, fecha (YYYY-MM-DD), hora (HH:MM) "
            "y num_personas. Si el cliente menciona alergias o celebra algo, recogelo. "
            "Si la reserva es para 11 o mas personas, NO uses esta tool: usa "
            "escalar_a_humano con motivo 'grupo_grande'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string", "description": "Nombre completo del cliente."},
                "telefono": {"type": "string", "description": "Telefono en formato +34XXXXXXXXX."},
                "fecha": {"type": "string", "description": "Fecha en formato YYYY-MM-DD."},
                "hora": {"type": "string", "description": "Hora en formato HH:MM (24h)."},
                "num_personas": {"type": "integer", "description": "Numero de comensales (1-20)."},
                "alergias": {"type": "string", "description": "Alergias o intolerancias del grupo (opcional)."},
                "ocasion_especial": {"type": "string", "description": "Cumpleanos, aniversario, etc (opcional)."},
                "notas": {"type": "string", "description": "Cualquier otra peticion (mesa terraza, silla bebe, etc)."},
            },
            "required": ["nombre", "telefono", "fecha", "hora", "num_personas"],
        },
    },
    {
        "name": "consultar_disponibilidad",
        "description": (
            "Comprueba si hay sitio para num_personas en una fecha y hora "
            "concretas. Usala antes de reservar si el cliente pregunta '¿hay "
            "sitio el viernes a las 21h para 4?' o quieres confirmar antes "
            "de pedir el resto de datos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha": {"type": "string", "description": "Fecha en formato YYYY-MM-DD."},
                "hora": {"type": "string", "description": "Hora en formato HH:MM (24h)."},
                "num_personas": {"type": "integer", "description": "Numero de comensales (1-20)."},
                "turno_flexible": {
                    "type": "boolean",
                    "description": "Si True y no hay hueco, sugerimos el otro turno del mismo dia.",
                },
            },
            "required": ["fecha", "hora", "num_personas"],
        },
    },
    {
        "name": "buscar_reservas",
        "description": (
            "Busca reservas futuras del cliente. Usala al INICIO del flujo "
            "de cancelacion, ANTES de cancelar_reserva, para encontrar la(s) "
            "reserva(s) del cliente y confirmarle cual quiere anular. Modos: "
            "(a) en WhatsApp/voz, pasa solo 'telefono' (el del canal); "
            "(b) en web, pasa 'nombre' + 'telefono' que te haya dado el cliente. "
            "Devuelve un dict con status, total y reservas (lista con id, nombre, "
            "fecha, hora, num_personas). Si total=0, responde al cliente que no "
            "encuentras reserva y pregunta si hizo la reserva con otros datos. "
            "Si total=1, muestra al cliente esa reserva y pide confirmacion antes "
            "de cancelar. Si total>1, listalas numeradas y deja que elija."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "telefono": {
                    "type": "string",
                    "description": (
                        "Telefono del cliente. En WA/voz, el del canal (ya lo "
                        "tienes). En web, el que te de el cliente."
                    ),
                },
                "nombre": {
                    "type": "string",
                    "description": (
                        "Nombre (total o parcial) del titular. Obligatorio en web. "
                        "Opcional en WA/voz (si hay varias reservas del mismo "
                        "telefono con titulares distintos, ayuda a filtrar)."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "modificar_reserva",
        "description": (
            "Modifica una reserva EXISTENTE in-place (no crea nueva ni "
            "cancela la anterior). USA ESTA TOOL para mover una reserva a "
            "otra fecha/hora, cambiar num_personas, alergias, ocasion o "
            "notas. NUNCA uses cancelar_reserva + reservar_mesa para "
            "'mover' una reserva: eso genera duplicados y emails confusos. "
            "Llamala despues de buscar_reservas pasando el id_reserva que "
            "te devolvio. Si la nueva fecha/hora esta llena, devuelve "
            "'lleno' SIN tocar la reserva original. Si solo necesitas "
            "cambios sin reasignacion (alergias, ocasion, notas), tambien "
            "vale: la usas igual."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id_reserva": {
                    "type": "string",
                    "description": "ID de la reserva a modificar (de buscar_reservas).",
                },
                "fecha": {"type": "string", "description": "Nueva fecha YYYY-MM-DD (opcional)."},
                "hora": {"type": "string", "description": "Nueva hora HH:MM (opcional)."},
                "num_personas": {"type": "integer", "description": "Nuevo num personas (opcional)."},
                "alergias": {"type": "string", "description": "Nuevas alergias (opcional, '' para borrar)."},
                "ocasion_especial": {"type": "string", "description": "Nueva ocasion (opcional)."},
                "notas": {"type": "string", "description": "Nuevas notas (opcional)."},
                "nombre": {"type": "string", "description": "Nuevo nombre (raro, opcional)."},
            },
            "required": ["id_reserva"],
        },
    },
    {
        "name": "cancelar_reserva",
        "description": (
            "Cancela una reserva confirmada. Llamala SOLO DESPUES de haber "
            "ejecutado buscar_reservas y de que el cliente haya confirmado "
            "cual anular. Identifica la reserva con id_reserva (preferible, "
            "lo tienes del resultado de buscar_reservas) o con telefono+fecha. "
            "Por seguridad, NUNCA canceles sin verificar identidad previa via "
            "buscar_reservas (match por telefono del canal en WA/voz, o por "
            "nombre+telefono del cliente en web)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id_reserva": {"type": "string", "description": "ID de la reserva (opcional si das telefono+fecha)."},
                "telefono": {"type": "string", "description": "Telefono usado al reservar."},
                "fecha": {"type": "string", "description": "Fecha de la reserva (YYYY-MM-DD)."},
                "motivo": {"type": "string", "description": "Motivo de cancelacion (opcional)."},
                "nombre_confirmacion": {
                    "type": "string",
                    "description": (
                        "Nombre exacto con el que el cliente hizo la reserva. "
                        "Es la verificacion de identidad. Pidelo SIEMPRE antes "
                        "de cancelar salvo que la reserva sea del mismo canal y "
                        "telefono actuales."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "consultar_carta",
        "description": (
            "Devuelve la carta del restaurante. Puedes pedir una categoria "
            "concreta o filtrar por alergeno. Usala cuando el cliente "
            "pregunte que platos hay, precios, o si tienen opciones para "
            "alergicos/vegetarianos/veganos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "categoria": {
                    "type": "string",
                    "enum": list(CARTA.keys()) + ["todo"],
                    "description": "Categoria a mostrar. Usa 'todo' o omite para la carta completa.",
                },
                "filtro_alergeno": {
                    "type": "string",
                    "enum": list(FILTROS_ALERGENO.keys()),
                    "description": "Filtra solo platos compatibles (sin_gluten, sin_lactosa, vegetariano, vegano).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "consultar_horario",
        "description": (
            "Devuelve el horario del restaurante. Si el cliente pregunta por "
            "un dia concreto, pasalo en 'dia'. Si no, devuelve la semana entera."
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
        "name": "apuntar_lista_espera",
        "description": (
            "Apunta al cliente en la lista de espera para una fecha+hora "
            "que esta llena. Usala cuando consultar_disponibilidad devuelva "
            "'lleno' y el cliente acepte que se le avise si se libera mesa. "
            "Cuando otra reserva se cancela en esa fecha+turno, el sistema "
            "manda WhatsApp automatico al primero de la lista."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string", "description": "Nombre completo del cliente."},
                "telefono": {"type": "string", "description": "Telefono en formato +34XXXXXXXXX."},
                "fecha": {"type": "string", "description": "Fecha en formato YYYY-MM-DD."},
                "hora": {"type": "string", "description": "Hora preferida en HH:MM (opcional, mejora el match)."},
                "num_personas": {"type": "integer", "description": "Numero de comensales (1-20)."},
                "alergias": {"type": "string", "description": "Alergias o intolerancias (opcional)."},
                "notas": {"type": "string", "description": "Cualquier otra peticion (opcional)."},
            },
            "required": ["nombre", "telefono", "fecha", "num_personas"],
        },
    },
    {
        "name": "escalar_a_humano",
        "description": (
            "Pasa el caso al duenno/encargado por email. Usala cuando: el "
            "cliente lo pida explicitamente, sea una queja, sea un grupo de "
            "11+ personas, sea un caso fuera de lo normal, o no puedas "
            "resolverlo. Necesitas un motivo y un contexto breve."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "motivo": {
                    "type": "string",
                    "enum": [
                        "cliente_lo_pide",
                        "queja_o_enfado",
                        "grupo_grande",
                        "evento_privado",
                        "caso_complejo",
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
def tool_reservar_mesa(input_data: dict, telefono_canal: Optional[str], canal_origen: str = "whatsapp") -> dict:
    return _reservar_mesa(input_data, telefono_canal=telefono_canal, canal_origen=canal_origen)


def tool_consultar_disponibilidad(input_data: dict) -> dict:
    return _consultar_disponibilidad(
        fecha=input_data.get("fecha", ""),
        hora=input_data.get("hora", ""),
        num_personas=int(input_data.get("num_personas") or 0),
        turno_flexible=bool(input_data.get("turno_flexible", False)),
    )


def tool_cancelar_reserva(input_data: dict, telefono_canal: Optional[str]) -> dict:
    return _cancelar_reserva(input_data, telefono_canal=telefono_canal, canal_actual="whatsapp")


def tool_modificar_reserva(input_data: dict, telefono_canal: Optional[str]) -> dict:
    return _modificar_reserva(input_data, telefono_canal=telefono_canal, canal_origen="whatsapp")


def tool_buscar_reservas(input_data: dict, telefono_canal: Optional[str]) -> dict:
    """
    En WhatsApp el telefono del canal es la clave principal: si el cliente
    no da telefono explicito en input_data, usamos el del canal.
    """
    tel = input_data.get("telefono") or telefono_canal or ""
    return _buscar_reservas(
        telefono=tel,
        nombre=input_data.get("nombre"),
        solo_futuras=True,
    )


def tool_consultar_carta(input_data: dict) -> dict:
    categoria = input_data.get("categoria")
    if categoria == "todo":
        categoria = None
    filtro = input_data.get("filtro_alergeno")
    texto = carta_legible(categoria=categoria, filtro_alergeno=filtro)
    return {"status": "ok", "mensaje": texto}


def tool_apuntar_lista_espera(input_data: dict, telefono_canal: Optional[str], canal_origen: str = "whatsapp") -> dict:
    return _apuntar_en_lista_espera(input_data, telefono_canal=telefono_canal, canal_origen=canal_origen)


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
        f"Horario de {RESTAURANTE['nombre']} ({RESTAURANTE['ciudad']}). "
        f"Direccion: {RESTAURANTE['direccion']}. "
        f"Telefono: {RESTAURANTE['telefono']}.\n"
    )
    return {"status": "ok", "mensaje": cabecera + horario_completo_legible()}


def tool_escalar_a_humano_wrapper(input_data: dict, telefono_canal: Optional[str]) -> dict:
    return _escalar_a_humano(input_data, telefono=telefono_canal, canal_origen="whatsapp")


# ─── Despachador ────────────────────────────────────────────────────
def ejecutar_tool(tool_name: str, tool_input: dict, telefono: str) -> str:
    """Despacha la tool que Claude ha pedido y devuelve el mensaje (string)."""
    log.info("Ejecutando tool: %s | Input: %s", tool_name, tool_input)

    if tool_name == "reservar_mesa":
        result = tool_reservar_mesa(tool_input, telefono)
    elif tool_name == "consultar_disponibilidad":
        result = tool_consultar_disponibilidad(tool_input)
    elif tool_name == "cancelar_reserva":
        result = tool_cancelar_reserva(tool_input, telefono)
    elif tool_name == "modificar_reserva":
        result = tool_modificar_reserva(tool_input, telefono)
    elif tool_name == "buscar_reservas":
        result = tool_buscar_reservas(tool_input, telefono)
    elif tool_name == "apuntar_lista_espera":
        result = tool_apuntar_lista_espera(tool_input, telefono)
    elif tool_name == "consultar_carta":
        result = tool_consultar_carta(tool_input)
    elif tool_name == "consultar_horario":
        result = tool_consultar_horario(tool_input)
    elif tool_name == "escalar_a_humano":
        result = tool_escalar_a_humano_wrapper(tool_input, telefono)
    else:
        result = {"status": "error", "mensaje": f"Tool desconocida: {tool_name}"}

    log.info("Tool %s resultado: %s", tool_name, result)
    return str(result)
