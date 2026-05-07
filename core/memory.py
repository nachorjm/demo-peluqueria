"""Funciones de memoria compartidas entre el chatbot y el agente de voz.

Aqui viven utilidades que tocan tablas de Supabase relacionadas con la
memoria persistente del agente telefonico (`llamadas_voz`) y helpers
que normalizan el numero de telefono entre canales (voz / WhatsApp).
"""
from core.config import claude, supabase
from core.logger import get_logger

log = get_logger(__name__)


import re

_PREFIJOS_CANAL = ("voz:", "vapi:", "whatsapp:")
# Moviles espanoles empiezan por 6, 7 o 9 y tienen 9 digitos totales.
_RE_MOVIL_ES_SIN_PREFIJO = re.compile(r"^[679]\d{8}$")


def _normalizar_telefono(numero):
    """
    Normaliza un telefono a formato internacional `+34...`.

    1. Quita prefijos de canal (voz:, vapi:, whatsapp:).
    2. Limpia espacios, guiones.
    3. Si tras limpiar quedan 9 digitos empezando por 6/7/9 (movil ES
       sin prefijo), anade `+34` delante. Asi un cliente que escribe
       `611223344` en el chat web queda guardado igual que uno que
       escribe `+34611223344` -> deduplicacion y busquedas consistentes
       (issue #35).
    4. Otros formatos (con prefijo +XX, numeros cortos, etc) se devuelven
       tal cual.
    """
    if not numero:
        return ""
    for prefijo in _PREFIJOS_CANAL:
        if numero.startswith(prefijo):
            numero = numero[len(prefijo):]
            break
    numero = numero.strip().replace(" ", "").replace("-", "")
    # Movil espanol sin prefijo -> anadir +34
    if _RE_MOVIL_ES_SIN_PREFIJO.match(numero):
        return "+34" + numero
    return numero


def cargar_resumen_llamadas_previas(telefono, max_llamadas=3):
    """
    Devuelve un texto breve con los resúmenes de las últimas N llamadas
    del mismo teléfono. None si no hay historial.
    """
    try:
        res = (
            supabase.table("llamadas_voz")
            .select("resumen, created_at")
            .eq("telefono", telefono)
            .not_.is_("resumen", "null")
            .order("created_at", desc=True)
            .limit(max_llamadas)
            .execute()
        )
        if not res.data:
            return None

        bloques = []
        for fila in res.data:
            fecha = fila["created_at"][:10]
            bloques.append(f"- ({fecha}) {fila['resumen']}")
        return "\n".join(bloques)
    except Exception as e:
        log.warning("Error cargando historial de llamadas: %s", e)
        return None


RESUMEN_SYSTEM_PROMPT = """Eres un asistente que resume llamadas a una peluqueria \
para que el equipo del salon pueda revisarlas rapido y para que el agente \
de voz reconozca al cliente en futuras llamadas.

Genera el resumen en castellano de Espana, en tercera persona, con esta \
estructura EXACTA (4 lineas, sin lineas en blanco entre ellas):

CLIENTE: <nombre o "anonimo"> | <alergias o sensibilidades a productos si las dijo>
INTERES: <que servicio quiere o que pregunto, en una frase corta>
RESULTADO: <que se acordo o que paso al colgar (cita agendada / consultando / pendiente / escalacion / sin accion)>
PROXIMO PASO: <accion concreta para el equipo (ej: 'llamar antes del lunes', 'preparar producto sin amoniaco', 'ninguna') o 'ninguno'>

Sin emojis. Sin markdown. Frases cortas. Si no se sabe un dato, escribe 'no indicado'."""


def generar_resumen_llamada(transcripcion):
    """
    Genera un resumen estructurado de la llamada usando Claude Haiku.

    Devuelve un string con 4 lineas (CLIENTE / INTERES / RESULTADO / PROXIMO PASO)
    optimo para que un comercial pueda revisar 50 resumenes rapido y para
    que Kara use ese contexto en futuras llamadas.
    """
    if not transcripcion:
        return ""

    lines = []
    for turno in transcripcion:
        role = turno.get("role", "?")
        content = turno.get("content", "") or turno.get("message", "")
        if content:
            lines.append(f"{role}: {content}")
    texto = "\n".join(lines)

    if not texto.strip():
        return ""

    try:
        response = claude.messages.create(
            model="claude-haiku-4-5",
            max_tokens=250,
            temperature=0.2,  # resumen tiene que ser fiel a los datos, sin creatividad
            system=RESUMEN_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": f"Resume esta llamada:\n\n{texto}"},
            ],
        )
        return response.content[0].text.strip()
    except Exception as e:
        log.warning("Error generando resumen de llamada: %s", e)
        return ""
