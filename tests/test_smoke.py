"""
Smoke tests de demo-peluqueria (Salon Mara).

OBJETIVO: garantizar que los endpoints clave responden y que la logica
core (citas, servicios, estilistas, guardrails) hace lo basico bien.
TODO mockeado: NO red, NO tokens, NO BD real (ver conftest.py).
"""
from typing import Any


# ════════════════════════════════════════════════════════════════════
# 1. Endpoints publicos
# ════════════════════════════════════════════════════════════════════

def test_root_devuelve_html(client):
    """GET / devuelve la landing como HTML."""
    r = client.get("/")
    assert r.status_code == 200
    assert "html" in r.headers.get("content-type", "")


def test_api_status_endpoint(client):
    """GET /api/status responde ok con la lista de endpoints."""
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "Salon" in data["service"]
    assert "agente" in data["endpoints"]


def test_api_salon_devuelve_datos(client):
    """GET /api/salon expone nombre, ciudad y branding del YAML."""
    r = client.get("/api/salon")
    assert r.status_code == 200
    data = r.json()
    assert data["nombre"] == "Salon Mara"
    assert data["ciudad"] == "Madrid"
    assert "branding" in data
    assert "bot" in data
    assert "landing" in data
    assert "widget_web" in data


def test_api_salon_incluye_equipo(client):
    """El endpoint expone el equipo de estilistas activos."""
    r = client.get("/api/salon")
    assert r.status_code == 200
    equipo = r.json().get("equipo") or []
    nombres = [e["nombre"] for e in equipo]
    assert "Mara" in nombres
    assert "Lucia" in nombres
    assert "Diego" in nombres


def test_health_endpoint_responde(client):
    """GET /health responde con 200 o 503 (segun estado de deps)."""
    r = client.get("/health")
    assert r.status_code in (200, 503)


# ════════════════════════════════════════════════════════════════════
# 2. peluqueria_data (loader del YAML)
# ════════════════════════════════════════════════════════════════════

def test_peluqueria_data_carga_salon():
    from core.peluqueria_data import SALON
    assert SALON["nombre"] == "Salon Mara"
    assert SALON["ciudad"] == "Madrid"
    assert SALON["telefono"].startswith("+34")


def test_peluqueria_data_horarios_parseados():
    from core.peluqueria_data import HORARIOS
    # Lunes y domingo cerrados (lista vacia)
    assert HORARIOS[0] == []
    assert HORARIOS[6] == []
    # Sabado: una franja
    assert len(HORARIOS[5]) == 1


def test_estilistas_activos_3():
    from core.peluqueria_data import estilistas_activos
    activos = estilistas_activos()
    nombres = [e["nombre"] for e in activos]
    assert {"Mara", "Lucia", "Diego"}.issubset(set(nombres))


def test_horario_dia_legible():
    from core.peluqueria_data import horario_dia_legible
    txt_lunes = horario_dia_legible(0)
    assert "cerrado" in txt_lunes
    txt_martes = horario_dia_legible(1)
    assert "10:00-20:00" in txt_martes


# ════════════════════════════════════════════════════════════════════
# 3. servicios.py
# ════════════════════════════════════════════════════════════════════

def test_validar_servicios_validos():
    from core.servicios import validar_y_resolver_servicios
    res = validar_y_resolver_servicios(["Corte mujer"])
    assert not res["nombres_invalidos"]
    assert len(res["servicios_validos"]) == 1
    assert res["servicios_validos"][0]["especialidad"] == "corte_mujer"
    assert res["duracion_total_min"] == 45


def test_validar_servicios_combinacion():
    from core.servicios import validar_y_resolver_servicios
    res = validar_y_resolver_servicios(["Corte mujer", "Coloracion raiz"])
    assert len(res["servicios_validos"]) == 2
    assert res["duracion_total_min"] == 45 + 75
    assert "color" in res["especialidades_requeridas"]
    assert "corte_mujer" in res["especialidades_requeridas"]


def test_validar_servicios_invalidos():
    from core.servicios import validar_y_resolver_servicios
    res = validar_y_resolver_servicios(["Servicio que no existe"])
    assert res["nombres_invalidos"] == ["Servicio que no existe"]
    assert res["servicios_validos"] == []


def test_servicios_legibles_categoria():
    from core.peluqueria_data import servicios_legibles
    txt = servicios_legibles(categoria="corte")
    assert "Corte mujer" in txt
    assert "Corte hombre" in txt


# ════════════════════════════════════════════════════════════════════
# 4. estilistas.py
# ════════════════════════════════════════════════════════════════════

def test_esta_disponible_sin_citas():
    """Sin citas previas en BD, el estilista esta libre."""
    from core.estilistas import esta_disponible
    assert esta_disponible("mara", "2026-12-15", "10:00", "11:00") is True


def test_buscar_estilista_disponible_compatibilidad():
    from core.estilistas import buscar_estilista_disponible
    res = buscar_estilista_disponible(
        especialidades_requeridas=["corte_hombre", "barba"],
        fecha="2026-12-15",
        hora_inicio="10:00",
        hora_fin="10:45",
    )
    assert res["ok"] is True
    assert res["estilista"]["id_yaml"] == "diego"


def test_buscar_estilista_no_compatible():
    """Una especialidad inexistente no encuentra estilista."""
    from core.estilistas import buscar_estilista_disponible
    res = buscar_estilista_disponible(
        especialidades_requeridas=["depilacion_laser"],
        fecha="2026-12-15",
        hora_inicio="10:00",
        hora_fin="10:45",
    )
    assert res["ok"] is False
    assert res["razon"] == "ningun_estilista_compatible"


# ════════════════════════════════════════════════════════════════════
# 5. citas.py
# ════════════════════════════════════════════════════════════════════

def test_consultar_disponibilidad_servicios_invalidos():
    from core.citas import consultar_disponibilidad
    res = consultar_disponibilidad(
        fecha="2026-12-15",
        hora_inicio="10:00",
        servicios=["Servicio que no existe"],
    )
    assert res["status"] == "servicios_invalidos"


def test_consultar_disponibilidad_fuera_horario_lunes():
    """Lunes (cerrado) debe devolver fuera_de_horario."""
    from core.citas import consultar_disponibilidad
    from datetime import date, timedelta
    hoy = date.today()
    # Buscar el proximo lunes (al menos 7 dias por delante)
    delta = (7 - hoy.weekday()) % 7
    if delta < 7:
        delta += 7
    lunes = hoy + timedelta(days=delta)
    res = consultar_disponibilidad(
        fecha=lunes.isoformat(),
        hora_inicio="11:00",
        servicios=["Corte mujer"],
    )
    assert res["status"] == "fuera_de_horario"


def test_consultar_disponibilidad_disponible_martes():
    """Martes a las 11:00 con corte mujer: debe devolver disponible."""
    from core.citas import consultar_disponibilidad
    from datetime import date, timedelta
    hoy = date.today()
    # Buscar un martes futuro suficiente para superar antelacion minima
    delta = (1 - hoy.weekday()) % 7
    if delta < 2:
        delta += 7
    martes = hoy + timedelta(days=delta)
    res = consultar_disponibilidad(
        fecha=martes.isoformat(),
        hora_inicio="11:00",
        servicios=["Corte mujer"],
    )
    assert res["status"] == "disponible", res
    assert "estilista_nombre" in res
    assert res["duracion_total_min"] == 45


def test_agendar_cita_falta_nombre():
    from core.citas import agendar_cita
    res = agendar_cita({
        "telefono": "+34600000000",
        "fecha": "2026-12-15",
        "hora_inicio": "11:00",
        "servicios": ["Corte mujer"],
    })
    assert res["status"] == "error"
    assert "nombre" in res["mensaje"].lower()


def test_agendar_cita_falta_servicios():
    from core.citas import agendar_cita
    res = agendar_cita({
        "nombre": "Marta",
        "telefono": "+34600000000",
        "fecha": "2026-12-15",
        "hora_inicio": "11:00",
        "servicios": [],
    })
    assert res["status"] == "error"
    assert "servicios" in res["mensaje"].lower()


def test_buscar_citas_sin_filtros_da_error():
    from core.citas import buscar_citas
    res = buscar_citas(telefono=None, nombre=None)
    assert res["status"] == "error"


def test_buscar_citas_devuelve_estructura(fakes):
    """Sin citas en BD el endpoint devuelve {total: 0, citas: []}."""
    from core.citas import buscar_citas
    fakes["supabase"].set_data("citas", [])
    res = buscar_citas(telefono="+34600000000")
    assert res["status"] == "ok"
    assert res["total"] == 0


# ════════════════════════════════════════════════════════════════════
# 6. clientes.py
# ════════════════════════════════════════════════════════════════════

def test_upsert_cliente_creado(fakes):
    """Sin existente, upsert crea fila nueva."""
    from core.clientes import upsert_cliente
    fakes["supabase"].set_data("clientes", [])
    res = upsert_cliente(
        telefono="+34600000000",
        nombre="Marta Soler",
        canal_origen="whatsapp",
    )
    assert res["status"] == "creado"


def test_upsert_cliente_sin_identificador():
    """Sin telefono ni email, devuelve sin_identificador."""
    from core.clientes import upsert_cliente
    res = upsert_cliente(telefono=None, email=None)
    assert res["status"] == "sin_identificador"


# ════════════════════════════════════════════════════════════════════
# 7. escalacion.py
# ════════════════════════════════════════════════════════════════════

def test_escalar_a_humano_datos_insuficientes():
    """Sin nombre ni telefono, no escala."""
    from core.escalacion import escalar_a_humano
    res = escalar_a_humano({
        "motivo": "queja_o_enfado",
        "contexto": "Esta enfadado.",
    })
    assert res["status"] == "datos_insuficientes"
    assert "nombre" in res["faltantes"]


def test_escalar_a_humano_ok(fakes):
    """Con nombre y telefono valido, escala correctamente."""
    from core.escalacion import escalar_a_humano
    fakes["supabase"].set_data("clientes", [])
    res = escalar_a_humano(
        {
            "motivo": "cliente_lo_pide",
            "contexto": "Quiere hablar con Mara directamente.",
            "nombre": "Marta Soler",
            "telefono": "+34600000000",
        },
        canal_origen="whatsapp",
    )
    assert res["status"] == "ok"
    assert res["escalacion_id"]


# ════════════════════════════════════════════════════════════════════
# 8. guardrails.py
# ════════════════════════════════════════════════════════════════════

def test_guardrail_detecta_agendar_cita_alucinada():
    from core.guardrails import detectar_alucinacion
    reply = "¡Listo Marta! Cita agendada para el viernes a las 18:00."
    tool_alucinada = detectar_alucinacion(reply, tools_ejecutadas_ok=set())
    assert tool_alucinada == "agendar_cita"


def test_guardrail_detecta_cancelar_cita_alucinada():
    from core.guardrails import detectar_alucinacion
    reply = "Hecho, cita cancelada sin problema."
    tool_alucinada = detectar_alucinacion(reply, tools_ejecutadas_ok=set())
    assert tool_alucinada == "cancelar_cita"


def test_guardrail_no_alucina_si_tool_ok():
    from core.guardrails import detectar_alucinacion
    reply = "Cita agendada para el viernes."
    tool_alucinada = detectar_alucinacion(
        reply, tools_ejecutadas_ok={"agendar_cita"}
    )
    assert tool_alucinada is None


def test_guardrail_recovery_para_tool():
    from core.guardrails import reply_recovery_para
    msg = reply_recovery_para("agendar_cita")
    assert msg
    assert "cita" in msg.lower()


# ════════════════════════════════════════════════════════════════════
# 9. memory.py
# ════════════════════════════════════════════════════════════════════

def test_normalizar_telefono():
    from core.memory import _normalizar_telefono
    assert _normalizar_telefono("+34 600 00 00 00") == "+34600000000"
    assert _normalizar_telefono("whatsapp:+34600000000") == "+34600000000"


# ════════════════════════════════════════════════════════════════════
# 10. lang_detect.py
# ════════════════════════════════════════════════════════════════════

def test_detectar_idioma_castellano_corto():
    from core.lang_detect import detectar_idioma
    assert detectar_idioma("hola") == "es"


def test_detectar_idioma_ingles_saludo():
    from core.lang_detect import detectar_idioma
    assert detectar_idioma("hello") == "en"


# ════════════════════════════════════════════════════════════════════
# 11. Webhooks (smoke)
# ════════════════════════════════════════════════════════════════════

def test_chatbot_web_chat_endpoint(client):
    """POST /web/chat devuelve session_id + reply."""
    r = client.post("/web/chat", json={"message": "hola"})
    assert r.status_code == 200
    data = r.json()
    assert "session_id" in data
    assert "reply" in data
    assert data["reply"]


def test_chatbot_whatsapp_twilio_endpoint(client):
    """POST /whatsapp (form-data Twilio) responde TwiML."""
    r = client.post(
        "/whatsapp",
        data={"Body": "hola", "From": "whatsapp:+34600000000", "ProfileName": "Test"},
    )
    assert r.status_code == 200
    assert "Response" in r.text or "Message" in r.text


def test_chatbot_whatsapp_meta_verify(client):
    """GET /whatsapp/meta sin token configurado responde 403."""
    r = client.get(
        "/whatsapp/meta",
        params={
            "hub_mode": "subscribe",
            "hub_verify_token": "invalid",
            "hub_challenge": "1234",
        },
    )
    assert r.status_code in (200, 403)


def test_landing_webhook_cita_nueva(client):
    """POST /supabase/webhook/cita-nueva con record valido."""
    r = client.post(
        "/supabase/webhook/cita-nueva",
        json={
            "type": "INSERT",
            "table": "citas",
            "record": {
                "id": "cita-test-1",
                "nombre": "Marta Soler",
                "telefono": "+34600000000",
                "fecha": "2026-12-15",
                "hora_inicio": "11:00",
                "hora_fin": "11:45",
                "estilista_id_yaml": "lucia",
                "canal_origen": "web",
                "estado": "confirmada",
                "created_at": "2026-04-20T10:00:00Z",
            },
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_landing_webhook_cita_modificada_sin_cambios(client):
    """UPDATE sin cambios relevantes se ignora sin email."""
    r = client.post(
        "/supabase/webhook/cita-modificada",
        json={
            "type": "UPDATE",
            "table": "citas",
            "record": {"id": "x", "fecha": "2026-12-15", "hora_inicio": "11:00"},
            "old_record": {"id": "x", "fecha": "2026-12-15", "hora_inicio": "11:00"},
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


def test_admin_listar_citas_empty(client):
    """GET /admin/api/citas con BD vacia devuelve {total: 0}."""
    r = client.get("/admin/api/citas?desde=2026-04-01&hasta=2026-04-30")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["citas"] == []


def test_admin_stats_empty(client):
    """GET /admin/api/stats devuelve metricas en cero."""
    r = client.get("/admin/api/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["kpis"]["citas_hoy"] == 0
    assert "por_canal" in data
    assert "por_estilista" in data


def test_admin_ical_sin_token_503(client):
    """GET /admin/ical/citas.ics sin ICAL_FEED_TOKEN configurado -> 503."""
    r = client.get("/admin/ical/citas.ics?token=foo")
    assert r.status_code in (404, 503)


# ════════════════════════════════════════════════════════════════════
# 12. Vapi tools
# ════════════════════════════════════════════════════════════════════

def _vapi_payload(tool_name: str, arguments: Any, telefono: str = "+34600000000") -> dict:
    return {
        "message": {
            "type": "tool-calls",
            "toolCalls": [{
                "id": "tc-test-1",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            }],
            "call": {
                "id": "vapi-call-test-1",
                "customer": {"number": telefono},
            },
        }
    }


def test_vapi_consultar_horario(client):
    r = client.post(
        "/vapi/tool/consultar_horario",
        json=_vapi_payload("consultar_horario", {}),
    )
    assert r.status_code == 200
    res = r.json()
    assert "results" in res
    assert res["results"][0]["toolCallId"] == "tc-test-1"


def test_vapi_consultar_servicios(client):
    r = client.post(
        "/vapi/tool/consultar_servicios",
        json=_vapi_payload("consultar_servicios", {"categoria": "corte"}),
    )
    assert r.status_code == 200
    res = r.json()
    assert res["results"][0]["result"]
    assert "Corte" in res["results"][0]["result"]


def test_vapi_consultar_historial_sin_telefono(client):
    """consultar_historial sin telefono devuelve bloque de fecha."""
    r = client.post(
        "/vapi/tool/consultar_historial",
        json=_vapi_payload("consultar_historial", {}, telefono=""),
    )
    assert r.status_code == 200
    txt = r.json()["results"][0]["result"]
    assert "FECHA DE HOY" in txt


def test_vapi_server_url_assistant_request(client):
    """assistant-request devuelve dict (sin overrides cuando no hay historial)."""
    r = client.post(
        "/vapi/server-url",
        json={
            "message": {
                "type": "assistant-request",
                "call": {"customer": {"number": "+34600000000"}},
            }
        },
    )
    assert r.status_code == 200


# ════════════════════════════════════════════════════════════════════
# 13. calendario.py (iCal)
# ════════════════════════════════════════════════════════════════════

def test_generar_ics_feed_estructura():
    from core.calendario import generar_ics_feed
    citas = [{
        "id": "c1",
        "fecha": "2026-12-15",
        "hora_inicio": "11:00",
        "hora_fin": "11:45",
        "nombre": "Marta",
        "telefono": "+34600000000",
        "estilista_id_yaml": "lucia",
        "estado": "confirmada",
        "canal_origen": "web",
        "servicios_str": "Corte mujer",
    }]
    ics = generar_ics_feed(
        citas,
        nombre_salon="Salon Mara",
        direccion_salon="C/ Espiritu Santo 34",
    )
    assert "BEGIN:VCALENDAR" in ics
    assert "END:VCALENDAR" in ics
    assert "BEGIN:VEVENT" in ics
    assert "Marta" in ics
    assert "Salon Mara" in ics
