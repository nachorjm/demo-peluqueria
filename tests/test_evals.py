"""
Tests evals (issue #12) — comportamiento del bot ante escenarios concretos.

Validan que el modelo Claude Haiku 4.5 + nuestros system prompts +
tools producen las respuestas esperadas. Diferencia con los smoke
tests:
  - Smoke (corren por defecto): "el endpoint responde 200".
  - Evals (corren con `pytest -m eval`): "el bot saluda con 3 opciones
    si el cliente dice hola".

Llaman a Claude REAL (gastan tokens). Coste estimado: ~0.0001€/eval
con haiku => 25 evals = ~0.0025€/run.

Las tools (Supabase, Twilio, Resend) siguen mockeadas via conftest.

Para correr: `pytest -m eval`
Si no hay ANTHROPIC_API_KEY real en .env, los evals se SKIPan.
"""
import pytest
from datetime import date, timedelta

from tests.eval_helpers import (
    correr_eval_web,
    correr_eval_whatsapp,
    assert_no_tool_called,
    assert_tool_called,
    assert_reply_contains_any,
    assert_reply_contains_all,
    assert_reply_no_contiene,
    assert_reply_no_contiene_any,
)


_FECHA_FUTURA = (date.today() + timedelta(days=14)).isoformat()
_FECHA_PASADA = "2020-01-01"


# ════════════════════════════════════════════════════════════════════
# WEB — saludos y consultas (sin tool)
# ════════════════════════════════════════════════════════════════════

@pytest.mark.eval
def test_eval_web_saludo_propone_3_opciones():
    r = correr_eval_web([{"role": "user", "content": "hola"}])
    assert_no_tool_called(r)
    assert_reply_contains_any(r, ["reservar", "carta", "horario"])


@pytest.mark.eval
def test_eval_web_buenas_dias_responde_natural():
    r = correr_eval_web([{"role": "user", "content": "buenas"}])
    assert_no_tool_called(r)
    assert_reply_contains_any(r, ["hola", "bienvenido", "ayudar", "casa lola"])


# ════════════════════════════════════════════════════════════════════
# WEB — consulta de horario y carta
# ════════════════════════════════════════════════════════════════════

@pytest.mark.eval
def test_eval_web_pregunta_horario_llama_tool():
    r = correr_eval_web([{"role": "user", "content": "que horario teneis el viernes?"}])
    assert_tool_called(r, "consultar_horario")


@pytest.mark.eval
def test_eval_web_pregunta_arroces_menciona_especialidades():
    """Claude puede responder con la lista de memoria o via tool.
    Lo importante es que el cliente reciba info util de arroces."""
    r = correr_eval_web([{"role": "user", "content": "que arroces teneis?"}])
    assert_reply_contains_any(r, [
        "paella", "senyoret", "arroz negro", "a banda", "valenciana",
    ])


@pytest.mark.eval
def test_eval_web_pregunta_sin_gluten_llama_carta_con_filtro():
    r = correr_eval_web([{"role": "user", "content": "tenemos un alergico al gluten, que platos hay?"}])
    assert_tool_called(r, "consultar_carta")
    # Bot deberia mencionar opciones safe
    assert_reply_contains_any(r, ["arroz", "carne", "lubina", "bacalao", "verdura", "sin gluten"])


# ════════════════════════════════════════════════════════════════════
# WEB — flujo de reserva
# ════════════════════════════════════════════════════════════════════

@pytest.mark.eval
def test_eval_web_reserva_datos_compactos_un_mensaje():
    """Cliente da todos los datos en 1 mensaje. Bot debe procesar y pedir
    confirmacion (o ya reservar si fue claro)."""
    r = correr_eval_web([
        {"role": "user", "content": f"reserva para 4 el {_FECHA_FUTURA} a las 21:00, soy Marta 600111222"}
    ])
    # No debe pedir personas/fecha/hora otra vez (ya las tiene).
    # Acepta cualquier flujo: o consulta dispo o pide confirmacion.
    nombres_tools = [t["name"] for t in r["tools"]]
    assert "reservar_mesa" in nombres_tools or "consultar_disponibilidad" in nombres_tools \
           or "confirma" in r["reply"].lower() or "marta" in r["reply"].lower(), \
           f"Esperaba que procesara los datos. Tools: {nombres_tools}, reply: {r['reply']}"


@pytest.mark.eval
def test_eval_web_reserva_paella_ofrece_vino():
    """Issue #19: si menciona paella, debe ofrecer vino."""
    r = correr_eval_web([
        {"role": "user", "content": f"reserva para 4 el {_FECHA_FUTURA} a las 14:00, soy Pablo 600222333, queremos paella"}
    ])
    assert_reply_contains_any(r, ["vino", "tinto", "mustiguillo", "utiel"])


@pytest.mark.eval
def test_eval_web_reserva_paella_recuerda_35_min():
    r = correr_eval_web([
        {"role": "user", "content": f"reserva para 2 el {_FECHA_FUTURA} a las 14:00, soy Ana 600333444, queremos paella valenciana"}
    ])
    assert_reply_contains_any(r, ["35 min", "35 minutos", "treinta y cinco", "coccion"])


# ════════════════════════════════════════════════════════════════════
# WEB — escalaciones y limites
# ════════════════════════════════════════════════════════════════════

@pytest.mark.eval
def test_eval_web_grupo_18_personas_escala():
    """17+ personas debe escalar."""
    r = correr_eval_web([
        {"role": "user", "content": f"reserva para 18 personas el {_FECHA_FUTURA} a las 21:00, soy Antonio 600444555"}
    ])
    assert_tool_called(r, "escalar_a_humano")


@pytest.mark.eval
def test_eval_web_grupo_10_personas_NO_escala():
    """10 personas SI se reserva (umbral 17)."""
    r = correr_eval_web([
        {"role": "user", "content": f"reserva para 10 el {_FECHA_FUTURA} a las 21:00, soy Pedro 600555666"}
    ])
    nombres = [t["name"] for t in r["tools"]]
    assert "escalar_a_humano" not in nombres, f"NO debia escalar 10p, llamo: {nombres}"


@pytest.mark.eval
def test_eval_web_evento_privado_escala():
    r = correr_eval_web([
        {"role": "user", "content": f"queremos hacer una despedida de soltero con menu cerrado y barra libre el {_FECHA_FUTURA}"}
    ])
    assert_tool_called(r, "escalar_a_humano")


@pytest.mark.eval
def test_eval_web_queja_escala():
    r = correr_eval_web([
        {"role": "user", "content": "fui ayer y la paella estaba fria, quiero que el dueno lo sepa"}
    ])
    assert_tool_called(r, "escalar_a_humano")


# ════════════════════════════════════════════════════════════════════
# WEB — fuera de ambito y reglas duras
# ════════════════════════════════════════════════════════════════════

@pytest.mark.eval
def test_eval_web_fuera_ambito_no_escala():
    """Pregunta fuera del restaurante no debe llamar tools."""
    r = correr_eval_web([
        {"role": "user", "content": "que tiempo hace en valencia manana?"}
    ])
    # No debe llamar escalar ni reservar
    nombres = [t["name"] for t in r["tools"]]
    assert "escalar_a_humano" not in nombres, f"No debia escalar, llamo: {nombres}"
    assert "reservar_mesa" not in nombres


@pytest.mark.eval
def test_eval_web_fecha_pasada_rechaza():
    r = correr_eval_web([
        {"role": "user", "content": f"reserva para 2 el {_FECHA_PASADA} a las 21:00, soy Pepe 600666777"}
    ])
    # El bot debe rechazar (mencionar pasada / antigua / otra fecha)
    assert_reply_contains_any(r, ["pasad", "futur", "no puedo", "otro", "dame otra fecha"])


@pytest.mark.eval
def test_eval_web_no_menciona_codigos_mesa():
    """El bot no debe decir M1, M7+M8 etc al cliente."""
    r = correr_eval_web([
        {"role": "user", "content": f"reserva para 2 el {_FECHA_FUTURA} a las 21:00, soy Marina 600777888"}
    ])
    # Codigos tipicos: M1, M7, M14, M7+M8, mesa M..
    assert_reply_no_contiene_any(r, ["M1", "M2", "M7", "M14", "M7+", "+M8"])


# ════════════════════════════════════════════════════════════════════
# WEB — multi-idioma
# ════════════════════════════════════════════════════════════════════

@pytest.mark.eval
def test_eval_web_ingles_largo_responde_ingles():
    r = correr_eval_web([
        {"role": "user", "content": "Hi, do you have a table for 4 tomorrow night around 9?"}
    ])
    # Reply debe contener palabras en ingles
    assert_reply_contains_any(r, ["table", "tomorrow", "night", "yes", "we have", "i can"])


@pytest.mark.eval
def test_eval_web_saludo_hello_responde_ingles():
    r = correr_eval_web([{"role": "user", "content": "hello"}])
    # Saludo en ingles -> reply en ingles
    assert_reply_contains_any(r, ["hi", "hello", "welcome", "how can i", "may i help"])


@pytest.mark.eval
def test_eval_web_frances_responde_frances():
    r = correr_eval_web([
        {"role": "user", "content": "Bonjour, je voudrais reserver une table pour ce soir"}
    ])
    assert_reply_contains_any(r, ["bonjour", "bonsoir", "pour combien", "personnes", "ce soir", "merci"])


# ════════════════════════════════════════════════════════════════════
# WEB — formato (sin asteriscos literales)
# ════════════════════════════════════════════════════════════════════

@pytest.mark.eval
def test_eval_web_no_asteriscos_brutos_en_reply():
    """El bot puede usar **negrita** (frontend lo renderiza). Lo que NO
    debe es escribir secuencias raras como ## titulo o > cita."""
    r = correr_eval_web([
        {"role": "user", "content": f"que platos teneis vegetarianos?"}
    ])
    assert_reply_no_contiene_any(r, ["##", ">", "```"])


# ════════════════════════════════════════════════════════════════════
# WHATSAPP — saludos, formato, idioma
# ════════════════════════════════════════════════════════════════════

@pytest.mark.eval
def test_eval_wa_saludo_propone_opciones():
    r = correr_eval_whatsapp([{"role": "user", "content": "hola"}])
    assert_no_tool_called(r)
    assert_reply_contains_any(r, ["reservar", "carta", "horario"])


@pytest.mark.eval
def test_eval_wa_no_doble_asterisco():
    """WhatsApp solo renderiza *un asterisco*. NUNCA debe escribir **doble**."""
    r = correr_eval_whatsapp([
        {"role": "user", "content": f"reserva para 2 el {_FECHA_FUTURA} a las 21:00, soy Sara 600888999"}
    ])
    assert_reply_no_contiene(r, "**")


@pytest.mark.eval
def test_eval_wa_ingles_completo_no_palabras_espanol():
    """Cliente escribe ingles -> bot responde COMPLETO en ingles, sin
    palabras sueltas en espanol como 'confirma', 'gracias', 'perfecto'."""
    r = correr_eval_whatsapp([
        {"role": "user", "content": "Hi, I would like to book a table for 4 tomorrow night at 9"}
    ])
    # Palabras espanolas comunes que el bot NO debe meter en respuesta inglesa
    assert_reply_no_contiene_any(r, [
        " confirma", " gracias", " perfecto", " vale ", " hola ", " por favor",
    ])


# ════════════════════════════════════════════════════════════════════
# WHATSAPP — cancelacion segura
# ════════════════════════════════════════════════════════════════════

@pytest.mark.eval
def test_eval_wa_cancelar_pide_nombre():
    """Issue #18: para cancelar, bot debe pedir nombre antes."""
    r = correr_eval_whatsapp([
        {"role": "user", "content": f"quiero anular mi reserva del {_FECHA_FUTURA}"}
    ])
    assert_reply_contains_any(r, ["nombre", "como te llamas", "a nombre de", "identidad"])


# ════════════════════════════════════════════════════════════════════
# WHATSAPP — escalaciones
# ════════════════════════════════════════════════════════════════════

@pytest.mark.eval
def test_eval_wa_grupo_grande_escala():
    """Claude puede escalar en el primer turno, o pedir confirmacion antes
    de escalar. Aceptamos las dos formas: tool ejecutada O reply mencionando
    explicitamente que el caso lo lleva el equipo / es grupo grande."""
    r = correr_eval_whatsapp([
        {"role": "user", "content": f"reserva para 25 el {_FECHA_FUTURA} a las 21:00, somos un grupo de empresa"}
    ])
    nombres_tools = [t["name"] for t in r["tools"]]
    if "escalar_a_humano" in nombres_tools:
        return  # OK, escalo directo
    # Si no escalo, al menos debe MENCIONAR que es grupo grande/empresa
    # y derivara al equipo, no proceder con flujo normal.
    assert_reply_contains_any(r, [
        "grupo grande", "equipo", "duenno", "duen",
        "directamente", "por telefono", "personalmente", "evento",
    ])
