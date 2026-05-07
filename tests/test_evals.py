"""
Tests evals — comportamiento del bot ante escenarios concretos.

Validan que el modelo Claude Haiku 4.5 + nuestros system prompts +
tools producen las respuestas esperadas. Diferencia con los smoke tests:
  - Smoke (corren por defecto): "el endpoint responde 200".
  - Evals (corren con `pytest -m eval`): "el bot saluda con 3 opciones
    si el cliente dice hola".

Llaman a Claude REAL (gastan tokens). Coste estimado: ~0.0001€/eval
con haiku.

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
)


_FECHA_FUTURA = (date.today() + timedelta(days=14)).isoformat()


# ════════════════════════════════════════════════════════════════════
# WEB — saludos y consultas (sin tool)
# ════════════════════════════════════════════════════════════════════

@pytest.mark.eval
def test_eval_web_saludo_propone_3_opciones():
    r = correr_eval_web([{"role": "user", "content": "hola"}])
    assert_no_tool_called(r)
    assert_reply_contains_any(r, ["cita", "servicios", "horario", "agendar"])


@pytest.mark.eval
def test_eval_web_buenas_responde_natural():
    r = correr_eval_web([{"role": "user", "content": "buenas"}])
    assert_no_tool_called(r)
    assert_reply_contains_any(r, ["hola", "bienvenido", "ayudar", "salon mara"])


# ════════════════════════════════════════════════════════════════════
# WEB — consulta de horario y servicios
# ════════════════════════════════════════════════════════════════════

@pytest.mark.eval
def test_eval_web_pregunta_horario_llama_tool():
    r = correr_eval_web([
        {"role": "user", "content": "que horario teneis el viernes?"},
    ])
    assert_tool_called(r, "consultar_horario")


@pytest.mark.eval
def test_eval_web_pregunta_servicios_color_menciona_opciones():
    """Cliente pregunta por color: el bot debe mencionar opciones reales."""
    r = correr_eval_web([
        {"role": "user", "content": "que servicios de color teneis?"},
    ])
    assert_reply_contains_any(r, [
        "coloracion", "raiz", "completa", "mechas", "balayage",
    ])


@pytest.mark.eval
def test_eval_web_pregunta_corte_hombre_menciona_opciones():
    r = correr_eval_web([
        {"role": "user", "content": "cuanto cuesta cortarse el pelo (hombre)?"},
    ])
    assert_reply_contains_any(r, ["18", "corte hombre", "30 min"])


# ════════════════════════════════════════════════════════════════════
# WEB — agendar cita (no llega a tool sin todos los datos)
# ════════════════════════════════════════════════════════════════════

@pytest.mark.eval
def test_eval_web_pide_cita_sin_datos_pregunta_servicio():
    """Si el cliente solo dice 'quiero cita', el bot debe pedir servicio antes."""
    r = correr_eval_web([
        {"role": "user", "content": "quiero pedir cita"},
    ])
    assert_no_tool_called(r, "agendar_cita")
    assert_reply_contains_any(r, ["servicio", "que necesitas", "tipo de"])


@pytest.mark.eval
def test_eval_web_pide_corte_pregunta_estilista_o_fecha():
    r = correr_eval_web([
        {"role": "user", "content": "quiero corte mujer"},
    ])
    assert_no_tool_called(r, "agendar_cita")
    assert_reply_contains_any(r, ["fecha", "dia", "estilista", "preferencia"])


# ════════════════════════════════════════════════════════════════════
# WHATSAPP — saludo y consulta basica
# ════════════════════════════════════════════════════════════════════

@pytest.mark.eval
def test_eval_whatsapp_saludo_natural():
    r = correr_eval_whatsapp([{"role": "user", "content": "hola"}])
    assert_no_tool_called(r)


@pytest.mark.eval
def test_eval_whatsapp_pregunta_horario_llama_tool():
    r = correr_eval_whatsapp([
        {"role": "user", "content": "a que hora abris el sabado?"},
    ])
    assert_tool_called(r, "consultar_horario")
