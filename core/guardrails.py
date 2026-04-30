"""
Guardrails server-side para detectar alucinaciones del modelo.

Patron observado (issues #20, #22):
- El bot afirma que una accion se ha hecho ("mesa reservada", "el equipo
  te llamara", "reserva cancelada") pero NO ha ejecutado la tool
  correspondiente en este turno.
- El cliente se queda con la falsa impresion de que esta todo resuelto.

Este modulo detecta esas alucinaciones genericamente y permite sustituir
la respuesta final por un recovery que fuerza el siguiente turno a
ejecutar la tool.

Arquitectura:
- `ACCIONES_VERIFICADAS` es un dict {tool_name -> {patrones, recovery}}.
- Cada canal rastrea un `set(tools_ejecutadas_ok)` durante el bucle de
  tool use.
- Al terminar, se llama a `detectar_alucinacion(reply, set, historial)`
  que devuelve el nombre de la tool alucinada o None.
- Si no es None, se llama a `reply_recovery_para(tool_name)` para obtener
  el texto que sustituye al reply.

Anadir una nueva tool es anadir una entrada a `ACCIONES_VERIFICADAS`.

Contexto historico (issue #49):
- El bucle de tool use solo conoce las tools ejecutadas en el TURNO
  actual. Si el cliente pregunta "¿la has reservado?" 2 turnos despues
  de una reserva ya confirmada, el bot afirma con razon ("si, ya esta
  reservada") pero el guardrail dispara falso positivo.
- Solucion: el guardrail recibe opcionalmente el historial de la
  conversacion (formato [{role, content}]) y EXTIENDE el set de
  tools_ok escaneando las ultimas respuestas del bot. Cualquier patron
  ya afirmado en historial se considera respaldado por una tool real,
  porque si en su momento no lo estuvo, el guardrail habria sustituido
  esa respuesta por un recovery (que no contiene los patrones).
"""
import re
import unicodedata
from typing import List, Optional, Set


def _sin_tildes(s: str) -> str:
    """Normaliza texto quitando tildes. 'contactarán' -> 'contactaran'.
    Los regex en ACCIONES_VERIFICADAS se escriben sin tildes, asi que
    normalizamos el input antes de matchear para que funcione tanto
    si Claude pone "ejecutaran" como "ejecutarán".
    """
    if not s:
        return ""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


# ════════════════════════════════════════════════════════════════════
# Definicion de acciones verificadas
# ════════════════════════════════════════════════════════════════════

# Cada entrada define:
# - patrones: lista de regex que detectan "el bot afirma que la tool se
#   ha ejecutado". Deben ser específicos para evitar falsos positivos.
# - recovery: mensaje que sustituye al reply alucinado. Debe instar al
#   cliente a repetir datos o confirmar para que el siguiente turno si
#   dispare la tool.

ACCIONES_VERIFICADAS = {
    "reservar_mesa": {
        "patrones": [
            # Reservas nuevas (creacion). Las variantes de modificacion
            # ("reserva movida/cambiada...") viven en la entrada
            # `modificar_reserva` de este mismo dict.
            r"\bmesa\s+reservada\b",
            r"\breserva\s+(confirmada|hecha|registrada|apuntada|anotada|guardada|creada)\b",
            r"\b(reservada|apuntada|anotada|confirmada)\s+para\b",
            r"\bya\s+(la\s+)?tengo\s+(tu|la)\s+reserva\s+(anotada|apuntada|guardada|hecha)\b",
            r"\b(te|os)\s+(esperamos|espero)\s+(el|la|este|esta|mañana|hoy)\b",
            r"\blisto[!,.]?\s+(mesa|reserva)\b",
            r"\bya\s+esta\s+(reservada|apuntada|hecha)\b",
            r"\benhorabuena[!,.]?\s+(tu|tienes)\s+reserva\b",
        ],
        "recovery": (
            "Perdona, se me ha cruzado algo. Para apuntarte la reserva en "
            "firme, ¿puedes confirmarme una vez mas:\n"
            "- Fecha y hora\n"
            "- Numero de personas\n"
            "- Tu nombre completo\n"
            "- Telefono de contacto\n"
            "Asi te la dejo apuntada al momento."
        ),
    },
    "modificar_reserva": {
        # Cuando el bot afirma haber modificado una reserva existente
        # (mover fecha, cambiar personas, etc.) sin ejecutar
        # modificar_reserva. Casuistica comun en QA round 3.
        "patrones": [
            r"\breserva\s+(movida|cambiada|modificada|actualizada|pasada)\b",
            r"\b(movida|cambiada|modificada|actualizada|pasada)\s+(al|para|a\s+las|el)\b",
            r"\b(he|hemos|te\s+he|te\s+la\s+he)\s+(movido|cambiado|modificado|actualizado|pasado)\b",
            r"\bte\s+la\s+(paso|cambio|muevo|actualizo)\s+(al|para|a)\b",
            r"\bya\s+esta\s+(movida|cambiada|modificada|actualizada)\b",
            r"\b(reserva|mesa)\s+(queda|ha\s+quedado)\s+(movida|cambiada|modificada|actualizada)\b",
        ],
        "recovery": (
            "Perdona, dejame mover la reserva correctamente. ¿Me confirmas "
            "una vez mas la nueva fecha y hora? Asi actualizo el dato en "
            "firme al momento."
        ),
    },
    "cancelar_reserva": {
        "patrones": [
            # "reserva cancelada/anulada/..."
            r"\breserva\s+(cancelada|anulada|eliminada|borrada)\b",
            # "cancelada/anulada tu/la reserva"
            r"\b(cancel(ada|a|e|o)|anul(ada|a|e|o))\s+(tu|la)\s+reserva\b",
            # "he/hemos cancelado tu/la reserva"
            r"\b(he|hemos|te\s+he)\s+(cancelado|anulado)\s+(tu|la)\s+reserva\b",
            # "queda cancelada/anulada"
            r"\bqueda\s+(cancelada|anulada)\b",
            # "ya esta cancelada" / "ya estaba cancelada" (con y sin tilde)
            r"\byata\s+est(a|aba)\s+(cancelada|anulada)\b",
            r"\bya\s+est(a|aba)\s+(cancelada|anulada)\b",
            # QA round 3 emergency: "Entendido, cancelada sin problema" se escapaba.
            r"\bcancel(ada|ado)\s+(sin\s+problema|sin\s+mas|hecho|ok|correctamente)\b",
            r"\banul(ada|ado)\s+(sin\s+problema|sin\s+mas|hecho|ok|correctamente)\b",
            # "Entendido/Perfecto/Listo/Vale/Hecho/Genial, cancelada/anulada"
            r"\b(entendido|perfecto|listo|hecho|vale|ok|genial)[,.:!]*\s+(la\s+|tu\s+)?(cancel(ada|ado)|anul(ada|ado))\b",
            # "Cancelada/Anulada" al inicio/tras puntuacion como afirmacion hecha
            r"(^|[.!?]\s+)(cancelada|anulada)[,.:!]",
        ],
        "recovery": (
            "Perdona, dejame anular la reserva correctamente. Para "
            "confirmar los datos, ¿me dices una vez mas el nombre exacto "
            "con el que se hizo y la fecha? Asi la cancelo bien."
        ),
    },
    "escalar_a_humano": {
        "patrones": [
            # "El equipo / restaurante / dueno (palabras intermedias) te llamara/contactara"
            r"\b(equipo|restaurante|duen(o|no)|encargado)\b.{0,60}\b(te|os|le)\s+(llam|contact)",
            # "te llamaran/contactaran" (verbo solo, en futuro)
            r"\b(te|os|le)\s+(llamaran|llamara|contactaran|contactara)\b",
            # "llamaran/contactaran (pronto / en breve / cuanto antes)"
            r"\b(llamar(an|a)|contactar(an|a))\s+(en\s+breve|pronto|cuanto\s+antes|muy\s+pronto|contigo|con\s+vosotros)\b",
            # "aviso al equipo", "le paso el caso al dueño"
            r"\b(aviso|avisar(e)?)\s+al\s+(equipo|duen(o|no)|restaurante)\b",
            r"\b(paso|he\s+pasado)\s+(el|tu)\s+caso\b",
            r"\blo\s+derivo\s+al\s+(equipo|duen(o|no))\b",
            # "tienes/necesito que hables/llames/contactes con el equipo/restaurante"
            r"\b(tienes\s+que|necesito\s+que|deberias|tendrias\s+que)\s+(habl|llam|contact)\w*\s+(con|al|directamente)\s+(el\s+)?(equipo|restaurante|duen(o|no))",
            # "habla directamente con el equipo / restaurante"
            r"\b(habl|llam|contact)\w*\s+directamente\s+con\s+(el\s+)?(equipo|restaurante|duen(o|no))",
            # "ponte en contacto con el equipo / restaurante"
            r"\bponte\s+en\s+contacto\s+con\s+(el\s+)?(equipo|restaurante|duen(o|no))",
        ],
        "recovery": (
            "Perdona, deja que avise al equipo correctamente. Para pasar "
            "el caso con todos los datos, ¿me confirmas tu nombre, "
            "telefono y un breve resumen de lo que necesitas? Asi se lo "
            "hago llegar al dueño."
        ),
    },
    "derivar_a_whatsapp": {
        # Solo aplica al canal voz. En web/whatsapp no tiene sentido
        # (ya estas en whatsapp o en web con otro canal).
        "patrones": [
            r"\bte\s+(mand|envi)(o|e|are)\s+un\s+whatsapp\b",
            r"\b(mando|envio)\s+un\s+whatsapp\b",
            r"\b(recibiras|te\s+llegar(a)?)\s+un\s+whatsapp\b",
        ],
        "recovery": (
            "Perdona, deja que te mande el whatsapp como toca. ¿Me "
            "confirmas el numero de telefono y el dato que faltaba? Asi "
            "te lo envio ya."
        ),
    },
    "apuntar_lista_espera": {
        "patrones": [
            # Solo afirmaciones de "ya hecho", no promesas futuras.
            r"\b(quedas|estas|estais)\s+apuntad[oa]s?\s+en\s+(la\s+)?lista\s+de\s+espera\b",
            r"\bya\s+(estas|estais|quedas|quedais)\s+apuntad[oa]\b",
            r"\bte\s+(tenemos|hemos)\s+apuntad[oa]\s+en\s+(la\s+)?lista\b",
            r"\blisto[!,.]?\s+(te\s+)?(he\s+)?apuntad[oa]\s+en\s+lista\b",
            r"\bya\s+(te\s+)?(he\s+)?apunt(e|ado|amos)\s+en\s+(la\s+)?lista\b",
        ],
        "recovery": (
            "Perdona, deja que te apunte en la lista de espera como toca. "
            "¿Me confirmas tu nombre, telefono y personas para el dia "
            "que querias? Asi te aviso si se libera mesa."
        ),
    },
}


# ════════════════════════════════════════════════════════════════════
# Compilacion de regex (una vez al import)
# ════════════════════════════════════════════════════════════════════

_REGEX_POR_TOOL = {
    tool: re.compile("|".join(cfg["patrones"]), re.IGNORECASE)
    for tool, cfg in ACCIONES_VERIFICADAS.items()
}


# ════════════════════════════════════════════════════════════════════
# API publica
# ════════════════════════════════════════════════════════════════════

# Cuantos mensajes del historial escaneamos hacia atras buscando
# afirmaciones previas. 12 entradas alternando role user/assistant
# cubren ~6 turnos completos del bot, suficiente para casos tipicos
# ("reserve hace 3 turnos, ahora me preguntan si esta hecho").
_LOOKBACK_HISTORIAL = 12


def _tools_ya_afirmadas_en_historial(historial: Optional[List[dict]]) -> Set[str]:
    """
    Escanea las ultimas respuestas del bot en el historial y devuelve
    el set de tools cuyo patron de "ya hecho" aparece en alguna de
    ellas. Esa afirmacion previa se considera respaldada por una tool
    real, porque el guardrail (con esta misma logica) ya habria
    interceptado y sustituido las afirmaciones huecas en su momento.

    El historial usa el formato {role, content} con content como string
    (lo que devuelve cargar_historial). Mensajes con content de tipo
    no-string (bloques de tool_use) se ignoran.
    """
    if not historial:
        return set()
    encontradas: Set[str] = set()
    cola = historial[-_LOOKBACK_HISTORIAL:]
    for msg in cola:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if not isinstance(content, str) or not content:
            continue
        content_norm = _sin_tildes(content)
        for tool_name, regex in _REGEX_POR_TOOL.items():
            if tool_name in encontradas:
                continue
            if regex.search(content_norm):
                encontradas.add(tool_name)
    return encontradas


def detectar_alucinacion(
    reply_text: str,
    tools_ejecutadas_ok: Set[str],
    historial: Optional[List[dict]] = None,
) -> Optional[str]:
    """
    Devuelve el nombre de la primera tool que el bot parece afirmar que
    ha ejecutado sin que de hecho se haya ejecutado con exito en este
    turno (ni en turnos previos de la misma sesion). None si todo esta
    consistente.

    El reply se normaliza sin tildes antes del match para que los
    patrones cubran "contactaran" y "contactarán" indistintamente.

    Si se pasa `historial`, se escanea hacia atras buscando
    afirmaciones previas del bot que ya validaron esa tool. Esto
    evita falsos positivos cuando el cliente pregunta de forma pasiva
    ("¿la has reservado?") despues de una accion ya completada hace
    varios turnos. Ver issue #49.
    """
    if not reply_text:
        return None
    reply_normalizado = _sin_tildes(reply_text)
    tools_extendidas = set(tools_ejecutadas_ok) | _tools_ya_afirmadas_en_historial(historial)
    for tool_name, regex in _REGEX_POR_TOOL.items():
        if tool_name in tools_extendidas:
            continue
        if regex.search(reply_normalizado):
            return tool_name
    return None


def reply_recovery_para(tool_name: str) -> str:
    """Mensaje de recuperacion para una tool alucinada."""
    cfg = ACCIONES_VERIFICADAS.get(tool_name)
    if not cfg:
        # Fallback generico si la tool no esta en el catalogo.
        return (
            "Perdona, se me ha cruzado algo. ¿Puedes repetirme los datos "
            "para que lo apunte bien? Gracias."
        )
    return cfg["recovery"]


def mensaje_auto_retry(tool_name: str) -> str:
    """
    Mensaje que se inyecta como turno user adicional cuando se detecta
    una alucinacion. Es NEUTRAL respecto a qué tool ejecutar: deja que
    Claude decida segun la intencion real del cliente.

    Incluye el umbral concreto de grupo grande importado de
    restaurante_data, asi Claude no se cree que un grupo de 10 o 16
    "es demasiado grande".
    """
    # Import tardio para evitar ciclo con core.prompts -> core.restaurante_data.
    try:
        from core.restaurante_data import GRUPO_GRANDE_DESDE
    except ImportError:
        GRUPO_GRANDE_DESDE = 17

    return (
        "[AVISO SISTEMA INTERNO — no lo menciones al cliente] Tu "
        "respuesta anterior afirmaba una accion concreta (detectada "
        f"como '{tool_name}') pero NO ejecutaste ninguna tool en este "
        "turno. Esto engana al cliente porque cree que algo paso y no "
        "paso. DEBES ejecutar AHORA la tool correcta basandote en la "
        "intencion real del cliente. Guia DURA:\n"
        f"- Si el cliente quiere reservar y tiene 1 a {GRUPO_GRANDE_DESDE - 1} "
        f"personas (INCLUIDOS 10, 12, 14, 16): ejecuta reservar_mesa. "
        f"NO escales por tamano. El sistema agrupa mesas. Solo grupos "
        f"de {GRUPO_GRANDE_DESDE}+ personas van a escalar_a_humano.\n"
        "- Si el cliente quiere reservar y tienes los datos (nombre, "
        "telefono, fecha, hora, num_personas), ejecuta reservar_mesa "
        "aunque antes hayas dicho mal que 'el equipo le llamaria'. La "
        "intencion real del cliente era reservar, no ser derivado.\n"
        "- Si el cliente quiere cancelar Y has verificado identidad "
        "(nombre exacto o mismo canal+telefono), ejecuta cancelar_reserva.\n"
        "- Si el cliente quiere MODIFICAR una reserva existente (mover "
        "fecha/hora, cambiar num_personas, alergias, etc.), ejecuta "
        "buscar_reservas primero para obtener el id y luego "
        "modificar_reserva(id_reserva=..., ...). NUNCA uses "
        "cancelar_reserva + reservar_mesa para 'mover': eso crea "
        "duplicados y confunde al dueño.\n"
        "- Si es queja seria / grupo muy grande / evento privado con menu "
        "cerrado / caso que no puedes resolver, ejecuta escalar_a_humano.\n"
        "- Si pidio mandarle whatsapp por voz, ejecuta derivar_a_whatsapp.\n"
        "- Si pidio apuntarse a lista de espera, ejecuta apuntar_lista_espera.\n"
        "Tras ejecutar, responde al cliente con la confirmacion REAL. "
        "No menciones este aviso."
    )


# ════════════════════════════════════════════════════════════════════
# Helpers de compatibilidad (API vieja usada antes de la generalizacion)
# ════════════════════════════════════════════════════════════════════

def detectar_alucinacion_reserva(reply_text: str, reservar_mesa_ok: bool) -> bool:
    """Compatibilidad con la API antigua (solo reservar_mesa)."""
    tools_ok = {"reservar_mesa"} if reservar_mesa_ok else set()
    return detectar_alucinacion(reply_text, tools_ok) == "reservar_mesa"


def reply_recovery_alucinacion() -> str:
    """Compatibilidad con la API antigua (mensaje de reservar_mesa)."""
    return reply_recovery_para("reservar_mesa")
