"""
Deteccion de idioma del cliente para multi-idioma (issue #9).

Si el restaurante esta en zona turistica, detectar el idioma permite
que los clientes extranjeros se sientan atendidos en su lengua,
captando reservas que de otra forma se perderian.

Estrategia (tras bug QA #A2: "me llamo Marta Ruiz" se detectaba como italiano):
  1. Saludos conocidos en otro idioma ("hello", "bonjour"...) -> ese idioma.
  2. Umbral de 4 palabras minimo antes de aceptar un cambio. Frases
     cortas con nombres propios tipo "me llamo Marta Ruiz" (4 palabras)
     o "llamame Ana Lopez" no deberian disparar cambios; subidas a 5 o
     mas se consideran fiables.
  3. Umbral de confianza 0.90 en langdetect (usamos detect_langs para
     tener la probabilidad).
  4. Si se pasa `historial`, se exige 0.95 de confianza para cambiar el
     idioma predominante del historial. Evita que una frase corta con
     nombre propio bastardee un flujo completo en espanol.

NO se aplica a voz (Vapi tiene voice/transcriber fijos).
"""
from typing import List, Optional

try:
    from langdetect import detect, detect_langs, DetectorFactory, LangDetectException
    DetectorFactory.seed = 0  # determinismo entre llamadas
    _LANGDETECT_DISPONIBLE = True
except ImportError:
    _LANGDETECT_DISPONIBLE = False


IDIOMAS_SOPORTADOS = {"es", "en", "fr", "it", "de", "pt"}

NOMBRE_IDIOMA = {
    "es": "espanol",
    "en": "ingles",
    "fr": "frances",
    "it": "italiano",
    "de": "aleman",
    "pt": "portugues",
}

NOMBRE_IDIOMA_NATIVO = {
    "es": "espanol",
    "en": "English",
    "fr": "francais",
    "it": "italiano",
    "de": "Deutsch",
    "pt": "portugues",
}


# Saludos cortos no ambiguos por idioma. Si el mensaje del cliente es
# (o empieza por) uno de estos, asignamos ese idioma directamente sin
# pasar por langdetect (que es poco fiable con frases de 1-2 palabras).
#
# IMPORTANTE: solo incluir aqui saludos INEQUIVOCOS de un idioma.
# NO incluir "ola" sin tilde en pt porque es un error tipografico muy
# comun en espanol ("ola" en vez de "hola") y genera falso positivo
# (QA round 2: "ola, somos 20 personas..." se detectaba como pt).
# Los portugueses usan "ola" con tilde ("olá") o con grafias inequivocas.
SALUDOS_INDICADORES = {
    "en": ["hello", "hi", "hey", "good morning", "good evening",
           "good afternoon", "good night", "thanks", "thank you"],
    "fr": ["bonjour", "bonsoir", "salut", "coucou", "merci"],
    "it": ["ciao", "buongiorno", "buonasera", "salve", "grazie"],
    "de": ["hallo", "guten tag", "guten abend", "danke"],
    "pt": ["olá", "bom dia", "boa tarde", "boa noite", "obrigado"],
}


def _idioma_por_saludo(texto: str) -> Optional[str]:
    """Si el texto es o empieza por un saludo de un idioma soportado,
    devuelve ese codigo. Si no, None."""
    t = texto.strip().lower().rstrip("!.,?")
    for lang, saludos in SALUDOS_INDICADORES.items():
        for s in saludos:
            if t == s or t.startswith(s + " ") or t.startswith(s + ","):
                return lang
    return None


_MIN_PALABRAS = 4
_MIN_CONFIANZA = 0.90
_MIN_CONFIANZA_SI_HISTORIAL_CONTRADICE = 0.95


def _idioma_predominante_historial(historial: List[dict]) -> Optional[str]:
    """
    Calcula el idioma predominante de los mensajes del cliente (role='user')
    en el historial. Devuelve None si no hay suficiente sustancia para
    decidir. Ignora los mensajes cortos (< _MIN_PALABRAS) para no
    contaminar con "si", "no", "vale", "confirmo".
    """
    if not _LANGDETECT_DISPONIBLE or not historial:
        return None
    langs = []
    for m in historial:
        if m.get("role") != "user":
            continue
        texto = (m.get("content") or "").strip()
        if len(texto.split()) < _MIN_PALABRAS:
            continue
        try:
            lang = detect(texto)
            if lang in IDIOMAS_SOPORTADOS:
                langs.append(lang)
        except LangDetectException:
            continue
    if not langs:
        return None
    # Idioma mas frecuente
    return max(set(langs), key=langs.count)


def detectar_idioma(
    texto: str,
    default: str = "es",
    historial: Optional[List[dict]] = None,
) -> str:
    """
    Devuelve el codigo ISO del idioma detectado.

    Fallbacks a `default`:
    - Texto vacio o muy corto (< _MIN_PALABRAS) y no es un saludo conocido.
    - Idioma detectado no soportado.
    - Confianza de langdetect por debajo de _MIN_CONFIANZA.
    - Si se pasa `historial` y el idioma predominante difiere del nuevo,
      se exige _MIN_CONFIANZA_SI_HISTORIAL_CONTRADICE. Si no se alcanza,
      se devuelve el idioma del historial.
    """
    if not texto:
        return default

    palabras = texto.strip().split()

    # 1. Saludo no ambiguo (cubre "hello", "bonjour", "ciao"...).
    # Solo decide SOLO si el mensaje es corto. Si es largo, el saludo
    # es una pista pero validamos con el contenido completo via langdetect
    # (QA round 2: "ola, somos 20 personas..." no debe decidirse por "ola").
    por_saludo = _idioma_por_saludo(texto)
    if por_saludo and len(palabras) < _MIN_PALABRAS:
        return por_saludo

    if not _LANGDETECT_DISPONIBLE:
        return por_saludo or default

    # 2. Umbral de palabras: frases cortas con nombres propios
    # ("me llamo Marta Ruiz") son ruido.
    if len(palabras) < _MIN_PALABRAS:
        return por_saludo or default

    # 3. detect_langs nos da probabilidad; solo confiamos si es alta.
    try:
        candidatos = detect_langs(texto)
    except LangDetectException:
        return default
    if not candidatos:
        return default
    top = candidatos[0]
    lang_top = str(top.lang)
    prob_top = float(top.prob)

    if lang_top not in IDIOMAS_SOPORTADOS:
        return default
    if prob_top < _MIN_CONFIANZA:
        return default

    # 4. Contexto del historial: si el cliente llevaba hablando otro
    # idioma, exigimos mas confianza para el cambio. Evita que un nombre
    # propio o frase corta ambigua altere el idioma del flujo.
    predominante = _idioma_predominante_historial(historial or [])
    if predominante and predominante != lang_top:
        if prob_top < _MIN_CONFIANZA_SI_HISTORIAL_CONTRADICE:
            return predominante

    return lang_top


def bloque_idioma_para_prompt(idioma: str) -> str:
    """
    Devuelve un bloque a concatenar al system prompt cuando el idioma
    detectado NO es espanol. En espanol no hace falta nada (default).
    """
    if idioma == "es" or idioma not in NOMBRE_IDIOMA:
        return ""
    # Import local para evitar ciclo de imports (restaurante_data ->
    # prompts -> lang_detect). Igualmente es barato: dict ya cargado.
    from core.restaurante_data import RESTAURANTE
    nombre_es = NOMBRE_IDIOMA[idioma]
    nombre_nativo = NOMBRE_IDIOMA_NATIVO[idioma]
    nombre_restaurante = RESTAURANTE.get("nombre", "")
    return (
        "\n\n═══════════════════════════════════════════════════════════\n"
        f"IDIOMA DEL CLIENTE: {nombre_es} ({idioma}).\n"
        f"RESPONDE COMPLETAMENTE en {nombre_nativo}. NI UNA SOLA palabra "
        f"en espanol. Esto incluye palabras sueltas como 'confirma', \n"
        f"'gracias', 'perfecto', 'vale': dilo en {nombre_nativo}.\n"
        "\n"
        "EXCEPCIONES (mantener en espanol):\n"
        f"- Nombres propios del restaurante: '{nombre_restaurante}'.\n"
        "- Nombres de platos tradicionales de la carta (ej. 'paella', \n"
        "  'arroz negro', 'esgarraet'). La primera vez que aparezcan \n"
        "  puedes dar una breve traduccion entre \n"
        f"  parentesis en {nombre_nativo}.\n"
        "\n"
        "OTRAS REGLAS:\n"
        "- Las tools (consultar_carta, consultar_horario...) devuelven \n"
        "  contenido en espanol. Traducelo INTEGRAMENTE al responder.\n"
        f"- Botones de confirmacion / palabras de cortesia: en {nombre_nativo}.\n"
        "- Si en algun turno el cliente cambia al espanol, sigue al espanol.\n"
        "═══════════════════════════════════════════════════════════"
    )
