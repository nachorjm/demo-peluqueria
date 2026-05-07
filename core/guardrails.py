"""
Guardrails server-side para detectar alucinaciones del modelo.

Patron observado:
- El bot afirma que una accion se ha hecho ("cita agendada", "el equipo
  te llamara", "cita cancelada") pero NO ha ejecutado la tool
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
- Si no es None, se llama a `reply_recovery_para(tool_name)` para
  obtener el texto que sustituye al reply.

Anadir una nueva tool es anadir una entrada a `ACCIONES_VERIFICADAS`.

Contexto historico:
- El bucle de tool use solo conoce las tools ejecutadas en el TURNO
  actual. Si el cliente pregunta "¿la has agendado?" 2 turnos despues
  de una cita ya confirmada, el bot afirma con razon ("si, ya esta
  agendada") pero el guardrail dispararia falso positivo.
- Solucion: el guardrail recibe opcionalmente el historial de la
  conversacion (formato [{role, content}]) y EXTIENDE el set de
  tools_ok escaneando las ultimas respuestas del bot.
"""
import re
import unicodedata
from typing import List, Optional, Set


def _sin_tildes(s: str) -> str:
    """Normaliza texto quitando tildes."""
    if not s:
        return ""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


# ════════════════════════════════════════════════════════════════════
# Definicion de acciones verificadas
# ════════════════════════════════════════════════════════════════════

ACCIONES_VERIFICADAS = {
    "agendar_cita": {
        "patrones": [
            r"\bcita\s+(agendada|reservada|confirmada|hecha|registrada|apuntada|anotada|guardada|creada)\b",
            r"\b(agendada|apuntada|anotada|confirmada|reservada)\s+para\b",
            r"\bya\s+(la\s+)?tengo\s+(tu|la)\s+cita\s+(anotada|apuntada|guardada|hecha|agendada)\b",
            r"\b(te|os)\s+(esperamos|espero)\s+(el|la|este|esta|mañana|hoy)\b",
            r"\blisto[!,.]?\s+cita\b",
            r"\bya\s+esta\s+(agendada|apuntada|hecha|reservada)\b",
        ],
        "recovery": (
            "Perdona, se me ha cruzado algo. Para apuntarte la cita en "
            "firme, ¿puedes confirmarme una vez mas:\n"
            "- Fecha y hora\n"
            "- Servicio o servicios\n"
            "- Estilista (si tienes preferencia)\n"
            "- Tu nombre completo\n"
            "- Telefono de contacto\n"
            "Asi te la dejo apuntada al momento."
        ),
    },
    "modificar_cita": {
        "patrones": [
            r"\bcita\s+(movida|cambiada|modificada|actualizada|pasada)\b",
            r"\b(movida|cambiada|modificada|actualizada|pasada)\s+(al|para|a\s+las|el)\b",
            r"\b(he|hemos|te\s+he|te\s+la\s+he)\s+(movido|cambiado|modificado|actualizado|pasado)\b",
            r"\bte\s+la\s+(paso|cambio|muevo|actualizo)\s+(al|para|a)\b",
            r"\bya\s+esta\s+(movida|cambiada|modificada|actualizada)\b",
            r"\bcita\s+(queda|ha\s+quedado)\s+(movida|cambiada|modificada|actualizada)\b",
        ],
        "recovery": (
            "Perdona, dejame mover la cita correctamente. ¿Me confirmas "
            "una vez mas la nueva fecha y hora? Asi actualizo el dato en "
            "firme al momento."
        ),
    },
    "cancelar_cita": {
        "patrones": [
            r"\bcita\s+(cancelada|anulada|eliminada|borrada)\b",
            r"\b(cancel(ada|a|e|o)|anul(ada|a|e|o))\s+(tu|la)\s+cita\b",
            r"\b(he|hemos|te\s+he)\s+(cancelado|anulado)\s+(tu|la)\s+cita\b",
            r"\bqueda\s+(cancelada|anulada)\b",
            r"\bya\s+est(a|aba)\s+(cancelada|anulada)\b",
            r"\bcancel(ada|ado)\s+(sin\s+problema|sin\s+mas|hecho|ok|correctamente)\b",
            r"\banul(ada|ado)\s+(sin\s+problema|sin\s+mas|hecho|ok|correctamente)\b",
            r"\b(entendido|perfecto|listo|hecho|vale|ok|genial)[,.:!]*\s+(la\s+|tu\s+)?(cancel(ada|ado)|anul(ada|ado))\b",
            r"(^|[.!?]\s+)(cancelada|anulada)[,.:!]",
        ],
        "recovery": (
            "Perdona, dejame anular la cita correctamente. Para confirmar "
            "los datos, ¿me dices una vez mas el nombre exacto con el que "
            "se hizo y la fecha? Asi la cancelo bien."
        ),
    },
    "escalar_a_humano": {
        "patrones": [
            r"\b(equipo|salon|duen(o|na|no)|encargada?)\b.{0,60}\b(te|os|le)\s+(llam|contact)",
            r"\b(te|os|le)\s+(llamaran|llamara|contactaran|contactara)\b",
            r"\b(llamar(an|a)|contactar(an|a))\s+(en\s+breve|pronto|cuanto\s+antes|muy\s+pronto|contigo|con\s+vosotros)\b",
            r"\b(aviso|avisar(e)?)\s+al\s+(equipo|duen(o|na|no)|salon)\b",
            r"\b(paso|he\s+pasado)\s+(el|tu)\s+caso\b",
            r"\blo\s+derivo\s+al\s+(equipo|duen(o|na|no))\b",
            r"\b(tienes\s+que|necesito\s+que|deberias|tendrias\s+que)\s+(habl|llam|contact)\w*\s+(con|al|directamente)\s+(el\s+|la\s+)?(equipo|salon|duen(o|na|no))",
            r"\b(habl|llam|contact)\w*\s+directamente\s+con\s+(el\s+|la\s+)?(equipo|salon|duen(o|na|no))",
            r"\bponte\s+en\s+contacto\s+con\s+(el\s+|la\s+)?(equipo|salon|duen(o|na|no))",
        ],
        "recovery": (
            "Perdona, deja que avise al equipo correctamente. Para pasar "
            "el caso con todos los datos, ¿me confirmas tu nombre, "
            "telefono y un breve resumen de lo que necesitas? Asi se lo "
            "hago llegar al equipo."
        ),
    },
    "derivar_a_whatsapp": {
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
}


_REGEX_POR_TOOL = {
    tool: re.compile("|".join(cfg["patrones"]), re.IGNORECASE)
    for tool, cfg in ACCIONES_VERIFICADAS.items()
}


_LOOKBACK_HISTORIAL = 12


def _tools_ya_afirmadas_en_historial(historial: Optional[List[dict]]) -> Set[str]:
    """Escanea ultimos turnos del bot y marca tools ya afirmadas."""
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
    Devuelve el nombre de la primera tool que el bot afirma haber
    ejecutado sin que de hecho se haya ejecutado en este turno o en
    turnos previos. None si todo esta consistente.
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
        return (
            "Perdona, se me ha cruzado algo. ¿Puedes repetirme los datos "
            "para que lo apunte bien? Gracias."
        )
    return cfg["recovery"]


def mensaje_auto_retry(tool_name: str) -> str:
    """Mensaje neutro que se inyecta como turno user para forzar tool."""
    return (
        "[AVISO SISTEMA INTERNO — no lo menciones al cliente] Tu "
        "respuesta anterior afirmaba una accion concreta (detectada "
        f"como '{tool_name}') pero NO ejecutaste ninguna tool en este "
        "turno. Esto engana al cliente porque cree que algo paso y no "
        "paso. DEBES ejecutar AHORA la tool correcta basandote en la "
        "intencion real del cliente. Guia DURA:\n"
        "- Si el cliente quiere agendar una cita y tienes los datos "
        "(nombre, telefono, fecha, hora, servicios), ejecuta "
        "agendar_cita.\n"
        "- Si el cliente quiere cancelar Y has verificado identidad "
        "(nombre exacto o mismo canal+telefono), ejecuta cancelar_cita.\n"
        "- Si el cliente quiere MODIFICAR una cita existente (mover "
        "fecha/hora, cambiar servicios o estilista, etc.), ejecuta "
        "buscar_citas primero para obtener el id y luego "
        "modificar_cita(id_cita=..., ...). NUNCA uses cancelar_cita + "
        "agendar_cita para 'mover': eso crea duplicados y confunde al "
        "duenno.\n"
        "- Si es queja seria / servicio que no ofrecemos / caso que no "
        "puedes resolver, ejecuta escalar_a_humano.\n"
        "- Si pidio mandarle whatsapp por voz, ejecuta derivar_a_whatsapp.\n"
        "Tras ejecutar, responde al cliente con la confirmacion REAL. "
        "No menciones este aviso."
    )
