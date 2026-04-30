"""
Smoke tests — verifican que cada endpoint y tool responde sin explotar.

NO prueban semantica fina ni que Claude conteste "bien" — solo que:
  - el endpoint devuelve 200,
  - el payload tiene la forma correcta,
  - la aplicacion no revienta con errores de import, tipo o integracion.

Todos los servicios externos (Claude, Supabase, Resend, Twilio) estan
mockeados en conftest.py.
"""
from datetime import date, timedelta


def _proxima_fecha_abierta(min_dias: int = 14) -> str:
    """
    Devuelve la fecha (ISO) del primer dia ABIERTO en Casa Lola desde
    hoy+min_dias. Casa Lola cierra los lunes (weekday 0). Si la fecha
    base cae en lunes, avanza al martes.

    Antes: `_FECHA_FUTURA = today + 14 dias` calculaba directo, lo que
    cuando hoy era lunes daba otro lunes 14 dias despues -> dia cerrado
    -> tests rotos. Bug que solo se manifestaba 1 de cada 7 dias.
    """
    d = date.today() + timedelta(days=min_dias)
    while d.weekday() == 0:  # lunes en Casa Lola = cerrado
        d += timedelta(days=1)
    return d.isoformat()


def _proximo_lunes() -> str:
    """Proximo lunes (dia cerrado en Casa Lola). Para tests de
    rechazo por dia cerrado."""
    hoy = date.today()
    dias_hasta_lunes = (7 - hoy.weekday()) % 7 or 7
    return (hoy + timedelta(days=dias_hasta_lunes)).isoformat()


# Fecha futura usable: garantiza dia abierto (no lunes).
_FECHA_FUTURA = _proxima_fecha_abierta(min_dias=14)
_FECHA_LUNES_FUTURO = _proximo_lunes()


# ═══════════════════════════════════════════════════════════════════
# Root / salud del servidor
# ═══════════════════════════════════════════════════════════════════
def test_root_responde(client):
    """GET / sirve la landing HTML."""
    r = client.get("/")
    assert r.status_code == 200
    assert "Casa Lola" in r.text
    assert r.headers["content-type"].startswith("text/html")


def test_api_status_responde(client):
    """GET /api/status devuelve el JSON de salud."""
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "endpoints" in data


# ═══════════════════════════════════════════════════════════════════
# Pagina /demo comercial (issue #61 reformulada)
# ═══════════════════════════════════════════════════════════════════
def test_demo_endpoint_responde_html(client):
    """
    GET /demo devuelve la pagina demo.html con HTML completo y los
    numeros de WhatsApp / Vapi inyectados como window.__DEMO_CONFIG.
    """
    r = client.get("/demo")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    # Estructura HTML basica
    assert "<!doctype html>" in r.text.lower() or "<!DOCTYPE html>" in r.text
    # Marca Alnora visible
    assert "Alnora IA" in r.text
    # Las 3 secciones de canales presentes
    assert "Chat web" in r.text
    assert "WhatsApp" in r.text
    assert "Llamada" in r.text


def test_demo_inyecta_window_demo_config(client, monkeypatch):
    """
    El endpoint inyecta window.__DEMO_CONFIG con los valores de las
    env vars TWILIO_WHATSAPP_NUMBER, TWILIO_SANDBOX_KEYWORD,
    VAPI_PHONE_NUMBER. El prefijo "whatsapp:" se quita del numero
    Twilio para que se muestre como numero de telefono normal.
    """
    monkeypatch.setenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
    monkeypatch.setenv("TWILIO_SANDBOX_KEYWORD", "join produce-go")
    monkeypatch.setenv("VAPI_PHONE_NUMBER", "+34911234567")

    r = client.get("/demo")
    assert r.status_code == 200
    assert "window.__DEMO_CONFIG" in r.text
    assert "+14155238886" in r.text
    # El prefijo whatsapp: NO debe aparecer en la pagina
    assert "whatsapp:+14155238886" not in r.text
    assert "join produce-go" in r.text
    assert "+34911234567" in r.text


def test_demo_aguanta_env_vars_vacias(client, monkeypatch):
    """
    Si VAPI_PHONE_NUMBER no esta configurada, la pagina sigue
    cargando sin romper. El JS del frontend cae al mensaje
    "Pidelo al comercial".
    """
    monkeypatch.delenv("VAPI_PHONE_NUMBER", raising=False)
    monkeypatch.delenv("TWILIO_SANDBOX_KEYWORD", raising=False)
    r = client.get("/demo")
    assert r.status_code == 200
    assert "window.__DEMO_CONFIG" in r.text
    assert '"vapi_numero": ""' in r.text


def test_demo_link_panel_admin_visible(client):
    """
    La pagina demo enlaza al panel admin para que el comercial pueda
    ensenar al cliente la vista del duenno.
    """
    r = client.get("/demo")
    assert r.status_code == 200
    assert 'href="/admin"' in r.text


def test_api_restaurante_devuelve_config_publica(client):
    """
    GET /api/restaurante (issue #11) devuelve los datos publicos del
    restaurante para que la landing y el panel admin se autoconfiguren.
    Leidos del YAML config/restaurante.yaml.
    """
    r = client.get("/api/restaurante")
    assert r.status_code == 200
    data = r.json()
    # Campos clave que el frontend necesita
    assert data["nombre"]  # no vacio
    assert data["ciudad"]
    assert "direccion" in data
    assert "telefono" in data
    assert "email" in data
    # Branding con paleta de colores
    assert "branding" in data
    assert "colores" in data["branding"]
    # Colores minimos que el HTML aplica como CSS vars
    for clave in ("bg", "cream", "accent", "gold", "text"):
        assert clave in data["branding"]["colores"]


# ═══════════════════════════════════════════════════════════════════
# Branding modular por canal (issue #55)
# ═══════════════════════════════════════════════════════════════════
def test_api_restaurante_expone_bloques_modulares(client):
    """
    /api/restaurante debe devolver los nuevos bloques `bot`, `landing`
    y `widget_web` ademas del legacy `branding`. Esto permite al
    frontend configurar el chat widget y la landing por separado.
    """
    r = client.get("/api/restaurante")
    assert r.status_code == 200
    data = r.json()
    # Bloques nuevos (issue #55)
    assert "bot" in data
    assert "landing" in data
    assert "widget_web" in data
    # widget_web siempre tiene defaults graceful (avatar, mensaje, colores)
    assert data["widget_web"].get("avatar_emoji")
    assert data["widget_web"].get("mensaje_bienvenida")
    colores_widget = data["widget_web"].get("colores", {})
    for clave in ("burbuja_bot", "burbuja_usuario", "fondo"):
        assert clave in colores_widget, f"falta color {clave} en widget_web"
    # landing expone favicon/og_image/logo (vacios o no, pero presentes)
    for clave in ("favicon", "og_image", "logo", "colores"):
        assert clave in data["landing"]


def test_widget_web_config_hereda_si_yaml_vacio(fakes, monkeypatch):
    """
    Cliente que NO rellena widget_web en su YAML debe seguir teniendo
    valores funcionales (avatar 💬, mensaje generico, colores
    heredados de landing.colores o defaults neutros). Sin reventar.
    """
    from core import restaurante_data as rd
    monkeypatch.setattr(rd, "WIDGET_WEB", {})
    cfg = rd.widget_web_config()
    assert cfg["avatar_emoji"]  # default 💬
    assert cfg["mensaje_bienvenida"]  # default generico con nombre del bot
    assert cfg["colores"]["burbuja_bot"]
    assert cfg["colores"]["burbuja_usuario"]
    assert cfg["colores"]["fondo"]


def test_landing_config_hereda_si_yaml_vacio(fakes, monkeypatch):
    """
    Cliente sin bloque landing (solo WA) debe poder llamar al endpoint
    sin que reviente. Devuelve strings vacios para imagenes (el
    frontend no inyecta los tags si vacios).
    """
    from core import restaurante_data as rd
    monkeypatch.setattr(rd, "LANDING", {})
    cfg = rd.landing_config()
    assert cfg["favicon"] == ""
    assert cfg["og_image"] == ""
    assert cfg["logo"] == ""
    assert cfg["slogan"] == ""
    assert cfg["tagline"] == ""
    assert cfg["colores"] == {}


def test_nombre_bot_devuelve_default_si_no_configurado(fakes, monkeypatch):
    """Sin bloque bot en YAML, nombre_bot() devuelve 'asistente'."""
    from core import restaurante_data as rd
    monkeypatch.setattr(rd, "BOT", {})
    assert rd.nombre_bot() == "asistente"
    assert rd.nombre_bot(fallback="bot") == "bot"


def test_nombre_bot_devuelve_yaml_si_configurado(fakes, monkeypatch):
    """Con bot.nombre = 'Lola', nombre_bot() devuelve 'Lola'."""
    from core import restaurante_data as rd
    monkeypatch.setattr(rd, "BOT", {"nombre": "Lola"})
    assert rd.nombre_bot() == "Lola"


def test_email_from_address_prioridad_yaml_sobre_env(fakes, monkeypatch):
    """
    Orden de prioridad: emails.from_address (YAML) > RESEND_FROM env >
    fallback "<nombre> <onboarding@resend.dev>".
    """
    from core import restaurante_data as rd
    # 1. YAML tiene prioridad
    monkeypatch.setattr(rd, "EMAILS_CFG", {"from_address": "Yaml <yaml@test.com>"})
    monkeypatch.setenv("RESEND_FROM", "Env <env@test.com>")
    assert rd.email_from_address() == "Yaml <yaml@test.com>"
    # 2. Sin YAML, usa env var
    monkeypatch.setattr(rd, "EMAILS_CFG", {})
    assert rd.email_from_address() == "Env <env@test.com>"
    # 3. Sin nada, fallback Resend
    monkeypatch.delenv("RESEND_FROM", raising=False)
    addr = rd.email_from_address()
    assert "onboarding@resend.dev" in addr
    assert rd.RESTAURANTE.get("nombre", "") in addr


def test_email_logo_html_vacio_si_no_configurado(fakes, monkeypatch):
    """Sin emails.logo_url, _logo_html() devuelve ''. El email no incluye logo pero no rompe."""
    from core import notifications as core_notif
    from core import restaurante_data as rd
    monkeypatch.setattr(rd, "EMAILS_CFG", {})
    assert core_notif._logo_html() == ""


def test_email_logo_html_con_url(fakes, monkeypatch):
    """Con emails.logo_url, _logo_html() devuelve un <img>."""
    from core import notifications as core_notif
    from core import restaurante_data as rd
    monkeypatch.setattr(rd, "EMAILS_CFG", {"logo_url": "https://test.com/logo.png"})
    html = core_notif._logo_html()
    assert "<img" in html
    assert "https://test.com/logo.png" in html


def test_paleta_email_hereda_de_landing_colores(fakes, monkeypatch):
    """
    El email del duenno usa landing.colores.accent y .cream para el
    branding, con fallback a defaults neutros si no estan.
    """
    from core import notifications as core_notif
    from core import restaurante_data as rd
    monkeypatch.setattr(rd, "LANDING", {"colores": {"accent": "#FF0000", "cream": "#EEEEEE"}})
    p = core_notif._paleta_email()
    assert p["accent"] == "#FF0000"
    assert p["accent_soft"] == "#EEEEEE"
    # Sin landing, defaults
    monkeypatch.setattr(rd, "LANDING", {})
    p = core_notif._paleta_email()
    assert p["accent"] == "#7A1F1F"  # default neutro


def test_prompt_usa_nombre_bot_si_configurado(fakes):
    """
    Si bot.nombre = 'Lola', el prompt empieza con 'Eres Lola, asistente
    virtual de Casa Lola...'. Sin nombre_bot configurado, vuelve al
    patron generico 'Eres el asistente virtual de Casa Lola...'.

    Casa Lola tiene bot.nombre = 'Lola' en su YAML, asi que el prompt
    debe incluir 'Eres Lola'.
    """
    from core.prompts import prompt_web
    p = prompt_web()
    # Casa Lola tiene bot.nombre = "Lola" en su YAML
    assert "Eres Lola, asistente virtual de Casa Lola" in p


# ═══════════════════════════════════════════════════════════════════
# Health check (issue #13)
# ═══════════════════════════════════════════════════════════════════
def test_health_endpoint_responde_healthy(client, monkeypatch):
    """
    GET /health con todos los servicios OK debe devolver 200 y
    status="healthy". Mockeamos los 4 checks para que el test sea
    determinista en cualquier entorno (en CI las env vars dummy de
    Twilio no pasarian la validacion de longitud).
    """
    from core import health as core_health

    monkeypatch.setattr(core_health, "check_supabase",
                        lambda: {"status": "ok", "latency_ms": 10})
    monkeypatch.setattr(core_health, "check_anthropic",
                        lambda: {"status": "ok", "latency_ms": 20})
    monkeypatch.setattr(core_health, "check_twilio",
                        lambda: {"status": "ok"})
    monkeypatch.setattr(core_health, "check_resend",
                        lambda: {"status": "ok"})

    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    assert "checks" in data
    assert data["checks"]["supabase"]["status"] == "ok"
    assert data["checks"]["anthropic"]["status"] == "ok"
    assert data["checks"]["twilio"]["status"] == "ok"
    assert data["checks"]["resend"]["status"] == "ok"
    assert "timestamp" in data


def test_health_endpoint_devuelve_503_si_critica_falla(client, monkeypatch):
    """
    Si supabase (critica) falla, status debe ser "down" y HTTP 503.
    """
    from core import health as core_health

    def _fake_check_supabase():
        return {"status": "fail", "latency_ms": 5, "error": "boom"}

    monkeypatch.setattr(core_health, "check_supabase", _fake_check_supabase)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "down"


# ═══════════════════════════════════════════════════════════════════
# Bugs detectados en la ronda de QA manual (post deploy plantilla)
# ═══════════════════════════════════════════════════════════════════
def test_normalizar_asteriscos_dobles_wa():
    """
    Bug QA: el modelo a veces devuelve **negrita markdown estandar** en
    respuestas largas (carta por categorias). WhatsApp solo renderiza
    negrita con UN asterisco (*asi*), asi que el backend normaliza.
    """
    from chatbot_whatsapp.webhook import _normalizar_asteriscos_wa

    entrada = "**Entrantes:**\n- Esgarraet\n- Coca de tomate"
    salida = _normalizar_asteriscos_wa(entrada)
    assert "**" not in salida
    assert "*Entrantes:*" in salida

    # No toca si ya estan bien puestos
    assert _normalizar_asteriscos_wa("*Viernes 24 a las 21:00*") == "*Viernes 24 a las 21:00*"

    # Tolera saltos de linea dentro
    entrada2 = "**linea1\nlinea2**"
    salida2 = _normalizar_asteriscos_wa(entrada2)
    assert salida2 == "*linea1\nlinea2*"

    # No toca asteriscos aislados o impares
    entrada3 = "esto es *normal* y ** aislado"
    assert _normalizar_asteriscos_wa(entrada3) == "esto es *normal* y ** aislado"


def test_lang_detect_no_cambia_por_nombre_propio_corto():
    """
    Bug QA: "me llamo Marta Ruiz" (4 palabras) se detectaba como italiano
    por el nombre propio "Marta". El bot respondia en italiano. Ahora:
    - Si el historial es mayoritariamente espanol, se exige mas confianza
      para cambiar. Una frase con nombre propio no deberia alterar el flujo.
    """
    from core.lang_detect import detectar_idioma

    historial_espanol = [
        {"role": "user", "content": "Hola, quiero anular mi reserva"},
        {"role": "assistant", "content": "Voy a ayudarte con la anulacion"},
        {"role": "user", "content": "Ha habido un problema con la fecha"},
    ]
    # "me llamo Marta Ruiz" en medio de flujo espanol -> sigue espanol
    assert detectar_idioma("me llamo Marta Ruiz", historial=historial_espanol) == "es"


def test_lang_detect_si_acepta_ingles_claro_con_historial_espanol():
    """
    El fix no debe bloquear cambios legitimos. Si el cliente escribe
    una frase inequivocamente en ingles con >=4 palabras, se respeta.
    """
    from core.lang_detect import detectar_idioma

    historial = [
        {"role": "user", "content": "Hola buenos dias"},
        {"role": "assistant", "content": "Hola, en que te ayudo?"},
    ]
    # Frase inglesa clara con alta confianza -> se respeta
    assert detectar_idioma(
        "Hi, can I book a table for two tonight please?",
        historial=historial,
    ) == "en"


def test_lang_detect_frase_corta_no_cambia_idioma():
    """
    Frases <4 palabras no activan langdetect (ruido). Se mantiene default.
    """
    from core.lang_detect import detectar_idioma

    assert detectar_idioma("me llamo Marta") == "es"  # 3 palabras
    assert detectar_idioma("sí confirmo ahora") == "es"  # 3 palabras (no cambia)


def test_lang_detect_ola_no_dispara_portugues(fakes):
    """
    QA round 2: "ola, somos 20 personas para una cena el sabado a las 22:00"
    se detectaba como portugues por el saludo "ola" (error tipografico
    espanol comun de "hola" sin h). Ahora "ola" sin tilde NO es saludo
    inequivoco de pt; solo "olá" con tilde lo es.
    """
    from core.lang_detect import detectar_idioma

    # El mensaje completo esta claramente en espanol -> debe detectar es
    frase = "ola, somos 20 personas para una cena el sabado a las 22:00"
    idioma = detectar_idioma(frase)
    assert idioma == "es", f"Esperaba 'es', obtuve '{idioma}'"

    # "olá" con tilde SI es pt inequivoco y manda si el mensaje es corto
    assert detectar_idioma("olá") == "pt"


def test_normalizar_telefono_espanol_sin_prefijo():
    """
    QA round 3 (issue #35): telefonos ES sin prefijo se guardaban tal cual,
    generando duplicados en BD (mismo cliente con `611223344` y `+34611223344`
    como dos registros distintos). Ahora 9 digitos empezando por 6/7/9
    reciben `+34` automatico.
    """
    from core.memory import _normalizar_telefono

    # Movil ES sin prefijo -> anade +34
    assert _normalizar_telefono("611223344") == "+34611223344"
    assert _normalizar_telefono("722334455") == "+34722334455"
    assert _normalizar_telefono("911122233") == "+34911122233"

    # Con prefijo ya -> no toca
    assert _normalizar_telefono("+34611223344") == "+34611223344"

    # Extranjero con prefijo -> no toca
    assert _normalizar_telefono("+447700900123") == "+447700900123"
    assert _normalizar_telefono("+33612345678") == "+33612345678"

    # Prefijo de canal + movil ES -> quita prefijo, anade +34
    assert _normalizar_telefono("whatsapp:611223344") == "+34611223344"
    assert _normalizar_telefono("whatsapp:+34611223344") == "+34611223344"
    assert _normalizar_telefono("voz:611223344") == "+34611223344"

    # Espacios y guiones -> se limpian
    assert _normalizar_telefono("611 22 33 44") == "+34611223344"
    assert _normalizar_telefono("611-22-33-44") == "+34611223344"

    # Numeros cortos o formato raro -> se devuelven tal cual
    assert _normalizar_telefono("123456") == "123456"
    assert _normalizar_telefono("") == ""
    # Empieza por digito que NO es movil ES (ej. 1, 2, 3, 4, 5) -> no toca
    assert _normalizar_telefono("112345678") == "112345678"


def test_prompts_usan_utf8_sin_ascii_substitutes():
    """
    QA round 3 (issue #37 punto 5): strings de prompts usaban "duenno",
    "manana", "espanol" en ASCII y el modelo los reproducia al cliente.
    Ahora deben usar UTF-8 con ñ donde corresponda.
    """
    from core.prompts import prompt_web, prompt_whatsapp, prompt_voz_estatico

    for nombre, getter in [
        ("web", prompt_web),
        ("whatsapp", prompt_whatsapp),
        ("voz", prompt_voz_estatico),
    ]:
        p = getter()
        # No debe haber "duenno" sueltos (con doble n)
        # (aceptamos que aparezca en subcadenas de palabras legitimas, pero
        # no como palabra completa)
        import re
        for palabra_mala in [r"\bduenno\b", r"\bmanana\b", r"\bespanol\b",
                              r"\bcumpleanos\b"]:
            matches = re.findall(palabra_mala, p, flags=re.IGNORECASE)
            assert not matches, (
                f"prompt_{nombre}: encontrada '{palabra_mala}' "
                f"(debe estar en UTF-8 con ñ)"
            )


def test_bloque_fecha_no_impone_limite_14_dias():
    """
    QA round 3 (issue #36): el bloque de fecha decia "PROXIMOS 14 DIAS"
    y el bot lo interpretaba como limite de reserva. Ahora debe dejar
    claro que la tabla es solo AYUDA, no limite.
    """
    from core.prompts import bloque_fecha_actual
    bloque = bloque_fecha_actual()
    # Debe incluir explicitamente que NO es un limite
    assert "NO es un límite" in bloque or "NO es un limite" in bloque
    # Y debe mencionar que se puede reservar con mas antelacion
    assert "PUEDEN reservar" in bloque or "pueden reservar" in bloque.lower()


def test_escalar_a_humano_valida_datos_minimos(fakes):
    """
    QA round 2: el bot escalaba dos veces (email duplicado) porque la
    tool creaba fila en BD aunque faltara nombre/telefono. Ahora la tool
    devuelve 'datos_insuficientes' en esos casos sin tocar BD ni mandar
    email. El bot debe pedir los datos faltantes y reintentar.
    """
    from core.escalacion_restaurante import escalar_a_humano

    # Sin nombre ni telefono -> bloqueado
    r = escalar_a_humano(
        input_data={"motivo": "grupo_grande", "contexto": "20 personas sabado"},
        telefono=None,  # sin telefono de canal (como web)
        canal_origen="web",
    )
    assert r["status"] == "datos_insuficientes"
    assert "nombre" in r["faltantes"]
    assert "telefono" in r["faltantes"]

    # Con nombre pero sin telefono en web -> sigue bloqueado
    r = escalar_a_humano(
        input_data={
            "motivo": "grupo_grande",
            "contexto": "20 personas sabado",
            "nombre": "Luis Garcia",
        },
        telefono=None,
        canal_origen="web",
    )
    assert r["status"] == "datos_insuficientes"
    assert "telefono" in r["faltantes"]
    assert "nombre" not in r["faltantes"]

    # Con nombre y telefono -> pasa la validacion (el resto depende de BD/email mockeados)
    r = escalar_a_humano(
        input_data={
            "motivo": "grupo_grande",
            "contexto": "20 personas sabado",
            "nombre": "Luis Garcia",
            "telefono": "+34611223344",
        },
        canal_origen="web",
    )
    assert r["status"] != "datos_insuficientes"

    # En whatsapp/voz el telefono viene del canal: con nombre + canal_tel -> pasa
    r = escalar_a_humano(
        input_data={
            "motivo": "grupo_grande",
            "contexto": "20 personas sabado",
            "nombre": "Luis Garcia",
        },
        telefono="+34611223344",
        canal_origen="whatsapp",
    )
    assert r["status"] != "datos_insuficientes"


# ═══════════════════════════════════════════════════════════════════
# Chatbot WhatsApp
# ═══════════════════════════════════════════════════════════════════
def test_whatsapp_acepta_mensaje(client):
    r = client.post(
        "/whatsapp",
        data={
            "Body": "Hola, queria reservar para el viernes",
            "From": "whatsapp:+34600000000",
            "ProfileName": "Smoke Tester",
        },
    )
    assert r.status_code == 200
    assert "<Response>" in r.text
    assert "<Message>" in r.text


def test_whatsapp_funciona_sin_profile_name(client):
    r = client.post(
        "/whatsapp",
        data={"Body": "hola", "From": "whatsapp:+34600000001"},
    )
    assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════
# Endpoints Meta Cloud API
# ═══════════════════════════════════════════════════════════════════
def test_meta_verify_rechaza_token_invalido(client):
    r = client.get(
        "/whatsapp/meta",
        params={
            "hub_mode": "subscribe",
            "hub_verify_token": "token_que_no_coincide",
            "hub_challenge": "12345",
        },
    )
    assert r.status_code == 403


def test_meta_verify_acepta_token_correcto(client, monkeypatch):
    monkeypatch.setenv("META_VERIFY_TOKEN", "secreto_smoke")
    r = client.get(
        "/whatsapp/meta",
        params={
            "hub_mode": "subscribe",
            "hub_verify_token": "secreto_smoke",
            "hub_challenge": "98765",
        },
    )
    assert r.status_code == 200
    assert r.text == "98765"


def test_meta_webhook_acepta_mensaje_entrante(client):
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "34600000000",
                        "id": "wamid.smoke",
                        "type": "text",
                        "text": {"body": "Hola desde Meta"},
                    }],
                    "contacts": [{"profile": {"name": "Smoke Meta"}}],
                }
            }]
        }]
    }
    r = client.post("/whatsapp/meta", json=payload)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_meta_webhook_ignora_notificaciones_sin_mensaje(client):
    payload = {"entry": [{"changes": [{"value": {"statuses": [{"id": "x"}]}}]}]}
    r = client.post("/whatsapp/meta", json=payload)
    assert r.status_code == 200
    assert r.json().get("status") == "ignored"


# ═══════════════════════════════════════════════════════════════════
# Chatbot Web
# ═══════════════════════════════════════════════════════════════════
def test_web_chat_devuelve_reply(client):
    r = client.post("/web/chat", json={"message": "hola"})
    assert r.status_code == 200
    data = r.json()
    assert "reply" in data
    assert "session_id" in data
    assert len(data["session_id"]) > 0


def test_web_chat_respeta_session_id(client):
    r = client.post(
        "/web/chat",
        json={"message": "hola", "session_id": "sess-smoke-123"},
    )
    assert r.status_code == 200
    assert r.json()["session_id"] == "sess-smoke-123"


def test_web_chat_rechaza_mensaje_vacio(client):
    r = client.post("/web/chat", json={"message": ""})
    assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════
# Agente de voz (Vapi) — endpoints por tool
# ═══════════════════════════════════════════════════════════════════
def _vapi_payload(function_name, arguments=None, telefono="+34600000000"):
    """Helper: construye un payload tipico de Vapi tool-calls."""
    return {
        "message": {
            "type": "tool-calls",
            "toolCallList": [
                {
                    "id": f"call_smoke_{function_name}",
                    "function": {
                        "name": function_name,
                        "arguments": arguments or {},
                    },
                }
            ],
            "call": {
                "id": "vapi_call_smoke_123",
                "customer": {"number": telefono},
            },
        }
    }


def test_vapi_consultar_carta(client):
    payload = _vapi_payload("consultar_carta", arguments={"categoria": "arroces"})
    r = client.post("/vapi/tool/consultar_carta", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert "results" in body
    assert "Paella" in body["results"][0]["result"]


def test_vapi_consultar_horario_dia(client):
    payload = _vapi_payload("consultar_horario", arguments={"dia": "lunes"})
    r = client.post("/vapi/tool/consultar_horario", json=payload)
    assert r.status_code == 200
    assert "cerrado" in r.json()["results"][0]["result"].lower()


def test_vapi_consultar_horario_completo(client):
    payload = _vapi_payload("consultar_horario", arguments={})
    r = client.post("/vapi/tool/consultar_horario", json=payload)
    assert r.status_code == 200
    assert "lunes" in r.json()["results"][0]["result"].lower()
    assert "domingo" in r.json()["results"][0]["result"].lower()


def test_vapi_consultar_disponibilidad(client):
    payload = _vapi_payload(
        "consultar_disponibilidad",
        arguments={"fecha": _FECHA_FUTURA, "hora": "21:00", "num_personas": 4},
    )
    r = client.post("/vapi/tool/consultar_disponibilidad", json=payload)
    assert r.status_code == 200
    # Con la fake supabase no hay reservas previas -> "disponible"
    msg = r.json()["results"][0]["result"].lower()
    assert "disponible" in msg or "hay sitio" in msg or "quedan" in msg


def test_vapi_reservar_mesa(client):
    payload = _vapi_payload(
        "reservar_mesa",
        arguments={
            "nombre": "Smoke Test",
            "telefono": "+34600000000",
            "fecha": _FECHA_FUTURA,
            "hora": "21:00",
            "num_personas": 4,
        },
    )
    r = client.post("/vapi/tool/reservar_mesa", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["results"][0]["toolCallId"] == "call_smoke_reservar_mesa"


def test_vapi_reservar_mesa_grupo_grande(client):
    """Grupo de 11+ debe rechazar y derivar al duenno."""
    payload = _vapi_payload(
        "reservar_mesa",
        arguments={
            "nombre": "Smoke Grupo",
            "telefono": "+34600000000",
            "fecha": _FECHA_FUTURA,
            "hora": "21:00",
            "num_personas": 15,
        },
    )
    r = client.post("/vapi/tool/reservar_mesa", json=payload)
    assert r.status_code == 200
    msg = r.json()["results"][0]["result"].lower()
    assert "grupo" in msg or "11" in msg or "escalar" in msg


def test_vapi_cancelar_reserva_inexistente(client):
    payload = _vapi_payload(
        "cancelar_reserva",
        arguments={"telefono": "+34600000000", "fecha": _FECHA_FUTURA},
    )
    r = client.post("/vapi/tool/cancelar_reserva", json=payload)
    assert r.status_code == 200
    # Con fake supabase vacia -> no_encontrada
    assert "encontrado" in r.json()["results"][0]["result"].lower()


def test_vapi_consultar_historial(client):
    payload = _vapi_payload("consultar_historial")
    r = client.post("/vapi/tool/consultar_historial", json=payload)
    assert r.status_code == 200
    assert isinstance(r.json()["results"][0]["result"], str)


def test_vapi_escalar_a_humano(client):
    payload = _vapi_payload(
        "escalar_a_humano",
        arguments={
            "motivo": "cliente_lo_pide",
            "contexto": "Cliente quiere hablar con el duenno por evento privado.",
            "nombre": "Smoke",
        },
    )
    r = client.post("/vapi/tool/escalar_a_humano", json=payload)
    assert r.status_code == 200
    assert "toolCallId" in r.json()["results"][0]


def test_vapi_escalar_sin_contexto_da_error_educado(client):
    payload = _vapi_payload(
        "escalar_a_humano",
        arguments={"motivo": "otro"},
    )
    r = client.post("/vapi/tool/escalar_a_humano", json=payload)
    assert r.status_code == 200
    assert "contexto" in body_result_lower(r)


def test_vapi_derivar_a_whatsapp(client):
    payload = _vapi_payload(
        "derivar_a_whatsapp",
        arguments={
            "pregunta_pendiente": "alergias",
            "datos_parciales": {"nombre": "Smoke"},
            "contexto": "No pudo capturar alergias por voz.",
        },
    )
    r = client.post("/vapi/tool/derivar_a_whatsapp", json=payload)
    assert r.status_code == 200
    assert "results" in r.json()


def test_vapi_server_url_assistant_request(client):
    payload = {
        "message": {
            "type": "assistant-request",
            "call": {"customer": {"number": "+34600000000"}},
        }
    }
    r = client.post("/vapi/server-url", json=payload)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_vapi_server_url_end_of_call(client):
    payload = {
        "message": {
            "type": "end-of-call-report",
            "call": {"id": "smoke-call-1", "customer": {"number": "+34600000000"}},
            "messages": [{"role": "user", "content": "hola"}],
            "durationSeconds": 30,
            "endedReason": "customer-ended-call",
            "cost": 0.05,
        }
    }
    r = client.post("/vapi/server-url", json=payload)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


# ═══════════════════════════════════════════════════════════════════
# Landing — webhook de reservas de Supabase
# ═══════════════════════════════════════════════════════════════════
def test_landing_reserva_webhook_acepta_insert(client):
    payload = {
        "type": "INSERT",
        "table": "reservas",
        "record": {
            "id": "fake-reserva-1",
            "nombre": "Marta",
            "telefono": "+34600000000",
            "fecha": _FECHA_FUTURA,
            "hora": "21:00",
            "num_personas": 4,
            "estado": "confirmada",
            "canal_origen": "web",
        },
    }
    r = client.post("/supabase/webhook/reserva-nueva", json=payload)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_landing_reserva_webhook_ignora_otra_tabla(client):
    payload = {"type": "INSERT", "table": "clientes", "record": {}}
    r = client.post("/supabase/webhook/reserva-nueva", json=payload)
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


# ═══════════════════════════════════════════════════════════════════
# Webhook UPDATE: reserva modificada / cancelada (issue #31)
# ═══════════════════════════════════════════════════════════════════
def test_landing_reserva_modificada_acepta_cambio_relevante(client):
    """
    Cliente cambia fecha de una reserva -> email al dueño con subject
    diferenciado (Reserva MODIFICADA).
    """
    payload = {
        "type": "UPDATE",
        "table": "reservas",
        "record": {
            "id": "abc-123",
            "nombre": "Marta Ruiz",
            "telefono": "+34600111222",
            "fecha": "2026-05-24",
            "hora": "21:00",
            "num_personas": 4,
            "estado": "confirmada",
            "canal_origen": "web",
        },
        "old_record": {
            "id": "abc-123",
            "nombre": "Marta Ruiz",
            "telefono": "+34600111222",
            "fecha": "2026-05-23",  # ← cambiaba de dia
            "hora": "21:00",
            "num_personas": 4,
            "estado": "confirmada",
            "canal_origen": "web",
        },
    }
    r = client.post("/supabase/webhook/reserva-modificada", json=payload)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_landing_reserva_modificada_ignora_cambios_internos(client):
    """
    Si solo cambian campos internos (updated_at, recordatorio_enviado_at,
    mesas_asignadas), no se envia email.
    """
    base = {
        "id": "abc-123",
        "nombre": "Marta",
        "telefono": "+34600111222",
        "fecha": "2026-05-24",
        "hora": "21:00",
        "num_personas": 4,
        "estado": "confirmada",
        "canal_origen": "web",
        "alergias": None,
        "ocasion_especial": None,
        "notas": None,
    }
    payload = {
        "type": "UPDATE",
        "table": "reservas",
        "record": {**base, "updated_at": "2026-04-24T10:00:00Z",
                   "recordatorio_enviado_at": "2026-04-24T10:00:00Z"},
        "old_record": base,
    }
    r = client.post("/supabase/webhook/reserva-modificada", json=payload)
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


def test_landing_reserva_modificada_detecta_cancelacion(client):
    """
    Cancelación: estado pasa de confirmada a cancelada -> email tipo
    "Reserva CANCELADA".
    """
    base = {
        "id": "abc-123",
        "nombre": "Marta",
        "telefono": "+34600111222",
        "fecha": "2026-05-24",
        "hora": "21:00",
        "num_personas": 4,
        "canal_origen": "web",
    }
    payload = {
        "type": "UPDATE",
        "table": "reservas",
        "record": {**base, "estado": "cancelada"},
        "old_record": {**base, "estado": "confirmada"},
    }
    r = client.post("/supabase/webhook/reserva-modificada", json=payload)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_notificar_cambio_reserva_diff_correcto():
    """
    Verifica directamente la funcion de diff sin pasar por HTTP.
    """
    from core.notifications import _diff_reserva, _es_cancelacion
    old = {"fecha": "2026-05-23", "hora": "21:00", "num_personas": 4,
           "estado": "confirmada", "alergias": None}
    new = {"fecha": "2026-05-24", "hora": "21:30", "num_personas": 4,
           "estado": "confirmada", "alergias": None}
    diff = _diff_reserva(old, new)
    campos = {c for c, _, _ in diff}
    assert campos == {"fecha", "hora"}
    assert not _es_cancelacion(old, new)

    # Cancelacion
    old2 = {"estado": "confirmada"}
    new2 = {"estado": "cancelada"}
    assert _es_cancelacion(old2, new2)

    # Cambio solo en campo irrelevante (ej. mesas_asignadas) -> diff vacio
    old3 = {"fecha": "2026-05-24", "mesas_asignadas": ["m1"]}
    new3 = {"fecha": "2026-05-24", "mesas_asignadas": ["m2"]}
    assert _diff_reserva(old3, new3) == []


# ═══════════════════════════════════════════════════════════════════
# Buscar reservas (issue #33) — tool nueva para flujo de cancelacion
# ═══════════════════════════════════════════════════════════════════
def test_buscar_reservas_sin_parametros_devuelve_error(fakes):
    from core.reservas import buscar_reservas
    r = buscar_reservas(telefono=None, nombre=None)
    assert r["status"] == "error"
    assert r["total"] == 0
    assert r["reservas"] == []


def test_buscar_reservas_por_telefono_devuelve_filtrado(fakes):
    """
    Test de integracion con FakeSupabase. El fake acepta cualquier query
    y devuelve lo que le inyectemos con set_data.
    """
    from core.reservas import buscar_reservas
    # Inyectamos 1 reserva futura del telefono que vamos a buscar
    fakes["supabase"].set_data("reservas", [
        {"id": "r1", "nombre": "Marta Ruiz", "telefono": "+34600111222",
         "fecha": "2030-01-01", "hora": "21:00:00", "num_personas": 4,
         "estado": "confirmada", "turno": "cena"},
    ])
    r = buscar_reservas(telefono="+34600111222")
    assert r["status"] == "ok"
    # No asertamos sobre total concreto porque el FakeQuery es permisivo,
    # pero si sobre que devuelve estructura correcta
    assert isinstance(r["reservas"], list)
    if r["reservas"]:
        res = r["reservas"][0]
        assert "telefono" not in res, "No debemos filtrar telefono al cliente"
        assert "mesas_asignadas" not in res, "No debemos filtrar mesas al cliente"
        assert "id" in res
        assert "fecha" in res
        assert "nombre" in res


def test_buscar_reservas_nombre_ilike(fakes):
    from core.reservas import buscar_reservas
    fakes["supabase"].set_data("reservas", [])
    r = buscar_reservas(nombre="Marta")
    assert r["status"] == "ok"
    # Solo verifica que la funcion acepta el parametro sin error


def test_buscar_reservas_rechaza_strings_vacios(fakes):
    """
    QA round 3 emergency: buscar_reservas con telefono="" o nombre=""
    (o ambos vacios) NO debe devolver todas las reservas. Hard guard.
    """
    from core.reservas import buscar_reservas
    # Ambos vacios
    r = buscar_reservas(telefono="", nombre="")
    assert r["status"] == "error"
    # Solo whitespace
    r = buscar_reservas(telefono="   ", nombre="  ")
    assert r["status"] == "error"
    # None ambos
    r = buscar_reservas()
    assert r["status"] == "error"
    # Nombre muy corto, sin telefono -> error (demasiado ambiguo)
    r = buscar_reservas(telefono="", nombre="a")
    assert r["status"] == "error"


def test_guardrail_modificar_reserva_atrapa_aluciaciones(fakes):
    """
    Variantes de afirmacion de modificacion ("tu reserva esta movida")
    deben atraparse en la categoria `modificar_reserva` (no en
    reservar_mesa). Si modificar_reserva esta en tools_ok, no dispara.
    """
    from core.guardrails import detectar_alucinacion

    frases_alucinacion = [
        "Tu reserva está movida al 23 de junio a las 21:00.",
        "¡Listo! Tu reserva está cambiada al viernes 24.",
        "He movido tu reserva al sábado.",
        "La he cambiado al 10 de mayo.",
        "Te la paso al martes 5.",
        "Tu reserva ya está actualizada.",
        "Perfecto, reserva modificada al 23 de junio.",
        "Te la muevo al 15 de julio.",
    ]
    for reply in frases_alucinacion:
        r = detectar_alucinacion(reply, set())
        assert r == "modificar_reserva", (
            f"No atrapa alucinacion: '{reply}' -> {r}"
        )

    # Si modificar_reserva esta en tools_ok, no debe disparar
    for reply in frases_alucinacion:
        r = detectar_alucinacion(reply, {"modificar_reserva"})
        assert r != "modificar_reserva", (
            f"Falso positivo con tool ok: '{reply}' -> {r}"
        )

    # Frases de consulta/informacion que NO deben activar
    frases_ok = [
        "Si quieres, puedes modificarla hasta 2h antes.",
        "Tu reserva se puede actualizar llamando al restaurante.",
        "Cuando quieras mover la reserva, escríbeme.",
        "¿Quieres que te lo cambie?",
    ]
    for reply in frases_ok:
        r = detectar_alucinacion(reply, set())
        assert r is None, f"Falso positivo: '{reply}' -> {r}"


def test_modificar_reserva_sin_id_devuelve_error(fakes):
    """
    modificar_reserva requiere id_reserva. Si no se pasa, devuelve error
    y guia al bot a usar buscar_reservas primero.
    """
    from core.reservas import modificar_reserva
    r = modificar_reserva({"fecha": "2030-01-01"})
    assert r["status"] == "error"
    assert "id_reserva" in r["mensaje"]
    assert "buscar_reservas" in r["mensaje"]


def test_historial_cliente_resumen_vacio(fakes):
    """
    QA round 4 (issue #3): historial_cliente_resumen sin datos devuelve
    estructura "vacia" sin error y sin marcar es_recurrente.
    """
    from core.reservas import historial_cliente_resumen
    fakes["supabase"].set_data("reservas", [])
    r = historial_cliente_resumen("+34611111111")
    assert r["es_recurrente"] is False
    assert r["num_visitas_pasadas"] == 0
    assert r["ultima_visita"] is None
    assert r["reservas_futuras"] == []
    assert r["tiene_no_show_reciente"] is False


def test_historial_cliente_resumen_telefono_vacio_no_hace_query(fakes):
    """Si el telefono es '' o None, devuelve vacio sin tocar BD."""
    from core.reservas import historial_cliente_resumen
    r = historial_cliente_resumen("")
    assert r["es_recurrente"] is False
    r = historial_cliente_resumen(None)
    assert r["es_recurrente"] is False


def test_prompt_wa_tiene_plantilla_resumen_fija(fakes):
    """
    QA round 4 (issue #3): el prompt WA debe incluir la plantilla fija
    del resumen con emojis estructurados (📅 👥 📞) para que Claude no
    invente formato cada vez.
    """
    from core.prompts import prompt_whatsapp
    p = prompt_whatsapp()
    # Plantilla fija
    assert "PLANTILLA FIJA DE RESUMEN DE RESERVA" in p
    # Emojis obligatorios mencionados como tales
    assert "📅" in p
    assert "👥" in p
    # Regla de longitud
    assert "MAXIMO 4 lineas" in p
    # Despedidas variadas (5 variantes V1-V5, regla no repetir)
    assert "DESPEDIDAS VARIADAS" in p
    assert "V1:" in p and "V5:" in p
    # Cliente recurrente
    assert "CLIENTE RECURRENTE" in p
    # Manejo de errores
    assert "Manejo de errores de tool" in p


def test_antelacion_minima_rechaza_reserva_demasiado_proxima(fakes, monkeypatch):
    """
    Issue #65: si el restaurante exige antelacion minima (ej. 2h) y el
    cliente pide para dentro de 30 min, la validacion debe rechazar
    con mensaje claro y tipo='antelacion_minima'.
    """
    from core import reservas as core_reservas
    monkeypatch.setattr(core_reservas, "ANTELACION_MINIMA_HORAS", 2)
    from datetime import datetime, timedelta
    en_30_min = datetime.now() + timedelta(minutes=30)
    r = core_reservas._validar_fecha_hora(
        en_30_min.date().isoformat(),
        en_30_min.strftime("%H:%M"),
    )
    assert r["ok"] is False
    assert r.get("tipo") == "antelacion_minima"
    assert "antelacion" in r["mensaje"].lower() or "preparar" in r["mensaje"].lower()


def test_antelacion_maxima_rechaza_reserva_demasiado_lejana(fakes, monkeypatch):
    """
    Issue #65: si el restaurante limita reservas a ej. 30 dias, una
    reserva para dentro de 200 dias debe rechazarse con tipo
    'antelacion_maxima'.
    """
    from core import reservas as core_reservas
    monkeypatch.setattr(core_reservas, "ANTELACION_MAXIMA_DIAS", 30)
    from datetime import date, timedelta
    en_200_dias = date.today() + timedelta(days=200)
    r = core_reservas._validar_fecha_hora(en_200_dias.isoformat(), "21:00")
    assert r["ok"] is False
    assert r.get("tipo") == "antelacion_maxima"
    assert "30" in r["mensaje"]


def test_antelacion_defaults_cero_no_rechazan_nada(fakes, monkeypatch):
    """
    Defaults (ambos a 0): comportamiento sin regresion. Una reserva
    para dentro de 5 minutos pasa la validacion de antelacion (sigue
    fallando por estar fuera de horario o por algo distinto, pero el
    campo `tipo` no debe ser de antelacion).
    """
    from core import reservas as core_reservas
    monkeypatch.setattr(core_reservas, "ANTELACION_MINIMA_HORAS", 0)
    monkeypatch.setattr(core_reservas, "ANTELACION_MAXIMA_DIAS", 0)
    from datetime import date, timedelta
    en_14_dias = (date.today() + timedelta(days=14))
    while en_14_dias.weekday() == 0:  # evitar lunes (cerrado)
        en_14_dias += timedelta(days=1)
    r = core_reservas._validar_fecha_hora(en_14_dias.isoformat(), "21:00")
    # Debe ser ok (dentro de horario, defaults sin limite de antelacion)
    assert r["ok"] is True


def test_bloque_politica_antelacion_vacio_si_ambos_a_cero(fakes, monkeypatch):
    """Si ambos campos son 0, no se inyecta nada al prompt (default Casa Lola)."""
    from core import prompts as core_prompts
    monkeypatch.setattr(core_prompts, "ANTELACION_MINIMA_HORAS", 0)
    monkeypatch.setattr(core_prompts, "ANTELACION_MAXIMA_DIAS", 0)
    bloque = core_prompts.bloque_politica_antelacion()
    assert bloque == ""


def test_bloque_politica_antelacion_aparece_si_hay_minimo(fakes, monkeypatch):
    """Con antelacion minima > 0, el bloque debe aparecer e instar a parar."""
    from core import prompts as core_prompts
    monkeypatch.setattr(core_prompts, "ANTELACION_MINIMA_HORAS", 2)
    monkeypatch.setattr(core_prompts, "ANTELACION_MAXIMA_DIAS", 0)
    bloque = core_prompts.bloque_politica_antelacion()
    assert "POLITICA DE ANTELACION" in bloque
    assert "MINIMO: 2h" in bloque
    assert "MAXIMO" not in bloque  # no se menciona si esta a 0
    assert "PARA INMEDIATAMENTE" in bloque


def test_bloque_politica_antelacion_aparece_si_hay_maximo(fakes, monkeypatch):
    """Con antelacion maxima > 0, el bloque debe aparecer."""
    from core import prompts as core_prompts
    monkeypatch.setattr(core_prompts, "ANTELACION_MINIMA_HORAS", 0)
    monkeypatch.setattr(core_prompts, "ANTELACION_MAXIMA_DIAS", 90)
    bloque = core_prompts.bloque_politica_antelacion()
    assert "POLITICA DE ANTELACION" in bloque
    assert "MAXIMO: 90 dias" in bloque
    assert "MINIMO" not in bloque  # no se menciona si esta a 0


def test_prompt_wa_resumen_pregunta_alergias_antes_de_confirmar(fakes):
    """
    Bug QA (Ernesto, 25 abril): cuando el cliente da los datos de un
    tiron y nunca menciona alergias, el bot mete "🌿 Sin alergias" en
    el resumen y cierra con "¿Confirmas?" pelado, sin dar al cliente
    la oportunidad de añadir una alergia tardia o celebracion.

    El cierre del resumen WA debe seguir el mismo patron que el web:
    pregunta proactiva por alergias/celebracion + "dime *si* y la apunto".
    """
    from core.prompts import prompt_whatsapp
    p = prompt_whatsapp()
    # La plantilla DEBE incluir la pregunta proactiva
    assert "¿Quieres añadir alguna alergia, celebracion o nota?" in p
    # Cierre con "dime *si* y la apunto" (mismo patron que el web)
    assert "dime *si* y la apunto" in p
    # NO debe quedar la plantilla vieja con "¿Confirmas?" pelado como
    # cierre del bloque de resumen.
    assert "Cierre siempre \"¿Confirmas?\"" not in p


def test_construir_contexto_cliente_recurrente_vacio_devuelve_string_vacio(fakes):
    """
    QA round 4 (issue #3): si el cliente no tiene historial, no se inyecta
    contexto al prompt (no contamina el saludo de cliente nuevo).
    """
    from chatbot_whatsapp.webhook import construir_contexto_cliente_recurrente
    fakes["supabase"].set_data("reservas", [])
    bloque = construir_contexto_cliente_recurrente("whatsapp:+34611111111")
    assert bloque == ""


def test_prompt_incluye_validacion_temprana_de_hora(fakes):
    """
    Bug QA (test web 13:00): el bot pedia todos los datos antes de
    validar la hora contra el horario. Ahora el prompt debe incluir
    una regla explicita (paso 2.5) que obligue a validar fecha y hora
    EN CUANTO las reciba, antes de pedir nombre/telefono/etc.

    Aplica a los 3 canales (web, WA, voz via FLUJO_RESERVA_COMUN).
    """
    from core.prompts import prompt_web, prompt_whatsapp, prompt_voz_estatico
    for prompt_fn, nombre in [
        (prompt_web, "web"),
        (prompt_whatsapp, "whatsapp"),
        (prompt_voz_estatico, "voz"),
    ]:
        p = prompt_fn()
        # Regla nueva
        assert "VALIDACION TEMPRANA" in p, f"falta en {nombre}"
        # Las dos comprobaciones que tiene que hacer el bot
        assert "dia de la semana esta ABIERTO" in p, f"falta check (a) en {nombre}"
        assert "dentro de alguno de los turnos" in p, f"falta check (b) en {nombre}"
        # Instruccion dura de no seguir pidiendo datos
        assert "PARA INMEDIATAMENTE" in p, f"falta regla de parada en {nombre}"
        # Ejemplo concreto con la hora fallida real del bug
        assert "EJEMPLO MAL #12" in p, f"falta ejemplo #12 en {nombre}"
        assert "13:00" in p, f"falta caso concreto en {nombre}"


def test_prompt_sigue_incluyendo_el_horario_legible(fakes):
    """
    El bloque 'DATOS_RESTAURANTE' debe seguir inyectando el horario
    legible en los prompts. Sin eso, la regla de validacion temprana
    no tendria contra que comparar.
    """
    from core.prompts import prompt_web, prompt_whatsapp
    for prompt_fn in (prompt_web, prompt_whatsapp):
        p = prompt_fn()
        # Las 2 franjas de Casa Lola aparecen textualmente en el prompt
        assert "13:30" in p
        assert "20:30" in p
        # Los 7 dias aparecen
        for dia in ("martes", "miercoles", "jueves", "viernes", "sabado", "domingo"):
            assert dia in p


def test_modificar_reserva_no_encontrada(fakes):
    """Si el id no existe en BD, status=no_encontrada."""
    from core.reservas import modificar_reserva
    fakes["supabase"].set_data("reservas", [])
    r = modificar_reserva({"id_reserva": "no-existe-123", "fecha": "2030-01-01"})
    assert r["status"] == "no_encontrada"


def test_guardrail_cancelar_reserva_atrapa_variantes_cortas(fakes):
    """
    QA round 3 emergency: "Entendido, cancelada sin problema" se escapaba
    del regex del guardrail y la alucinacion de cancelacion pasaba sin
    atrapar. Ampliado el regex. Este test cubre las variantes nuevas.
    """
    from core.guardrails import detectar_alucinacion

    frases_alucinacion = [
        "Entendido, cancelada sin problema.",
        "Perfecto, cancelada ya.",
        "Hecho, cancelada sin mas.",
        "Listo, cancelada correctamente.",
        "Vale, anulada sin problema.",
        "Tu reserva ha sido anulada sin problema.",
        "Anulada, cuando quieras volver.",
        "Reserva anulada, ¡hasta pronto!",
    ]
    for reply in frases_alucinacion:
        r = detectar_alucinacion(reply, set())
        assert r == "cancelar_reserva", (
            f"No atrapa alucinacion: '{reply}' -> {r}"
        )

    # Frases que NO deben activar (no son afirmaciones de accion hecha)
    frases_ok = [
        "Si quieres cancelar tu reserva, dime el nombre.",
        "Anular una reserva requiere el nombre exacto.",
        "Puedes anular hasta 2h antes del turno.",
    ]
    for reply in frases_ok:
        r = detectar_alucinacion(reply, set())
        assert r != "cancelar_reserva", (
            f"Falso positivo: '{reply}' -> {r}"
        )


# ═══════════════════════════════════════════════════════════════════
# CRM unificado del restaurante
# ═══════════════════════════════════════════════════════════════════
def test_upsert_cliente_sin_telefono_ni_email_no_inserta(fakes):
    from core.clientes import upsert_cliente
    r = upsert_cliente(telefono=None, nombre="test", canal_origen="whatsapp")
    assert r["status"] == "sin_identificador"


def test_upsert_cliente_crea_cuando_no_existe(fakes):
    from core.clientes import upsert_cliente
    r = upsert_cliente(
        telefono="+34600000000",
        nombre="Marta",
        canal_origen="whatsapp",
    )
    assert r["status"] == "creado"
    assert r["id"]


def test_upsert_cliente_actualiza_cuando_existe(fakes):
    from core.clientes import upsert_cliente
    fakes["supabase"].set_data("clientes", [{
        "id": "existing-id",
        "telefono": "+34600000000",
        "nombre": "Viejo",
        "canal_origen": "web",
    }])
    r = upsert_cliente(
        telefono="+34600000000",
        nombre="Viejo",
        canal_origen="whatsapp",
    )
    assert r["status"] == "actualizado"
    assert r["id"] == "existing-id"


# ═══════════════════════════════════════════════════════════════════
# Logica de reservas (fechas, horarios, validaciones)
# ═══════════════════════════════════════════════════════════════════
def test_reservar_fecha_pasada_falla(fakes):
    from core.reservas import reservar_mesa
    r = reservar_mesa({
        "nombre": "Smoke",
        "telefono": "+34600000000",
        "fecha": "2020-01-01",
        "hora": "21:00",
        "num_personas": 2,
    })
    assert r["status"] == "error"
    assert "pasado" in r["mensaje"].lower()


def test_reservar_horario_cerrado_falla(fakes):
    """Lunes 03:00: el restaurante esta cerrado."""
    from core.reservas import reservar_mesa
    r = reservar_mesa({
        "nombre": "Smoke",
        "telefono": "+34600000000",
        "fecha": _FECHA_LUNES_FUTURO,
        "hora": "03:00",
        "num_personas": 2,
    })
    assert r["status"] == "error"
    assert "cerrado" in r["mensaje"].lower()


def test_reservar_sin_telefono_falla(fakes):
    from core.reservas import reservar_mesa
    r = reservar_mesa({
        "nombre": "Smoke",
        "fecha": _FECHA_FUTURA,
        "hora": "21:00",
        "num_personas": 2,
    })
    assert r["status"] == "error"
    assert "telefono" in r["mensaje"].lower()


def test_reservar_grupo_grande_escala(fakes):
    from core.reservas import reservar_mesa
    r = reservar_mesa({
        "nombre": "Smoke Grupo",
        "telefono": "+34600000000",
        "fecha": _FECHA_FUTURA,
        "hora": "21:00",
        "num_personas": 20,  # supera GRUPO_GRANDE_DESDE (17) tras modelo de mesas
    })
    assert r["status"] == "grupo_grande"


# ═══════════════════════════════════════════════════════════════════
# Carta y horarios estaticos
# ═══════════════════════════════════════════════════════════════════
def test_carta_filtro_vegetariano_devuelve_platos(fakes):
    from core.restaurante_data import carta_legible
    texto = carta_legible(filtro_alergeno="vegetariano")
    assert "Verduras" in texto or "verduras" in texto.lower()


def test_carta_filtro_sin_gluten_excluye_croquetas(fakes):
    from core.restaurante_data import carta_legible
    texto = carta_legible(categoria="entrantes", filtro_alergeno="sin_gluten")
    assert "Croquetas" not in texto


def test_horario_lunes_dice_cerrado(fakes):
    from core.restaurante_data import horario_dia_legible
    assert "cerrado" in horario_dia_legible(0).lower()  # 0 = lunes


def test_horario_viernes_tiene_dos_turnos(fakes):
    from core.restaurante_data import horario_dia_legible
    txt = horario_dia_legible(4)  # 4 = viernes
    assert "13:30" in txt and "20:30" in txt


# ═══════════════════════════════════════════════════════════════════
# Guardrails genericos (issues #20, #22) y seguridad cancelaciones (#18)
# ═══════════════════════════════════════════════════════════════════
def test_guardrail_detecta_alucinacion_reservar(fakes):
    from core.guardrails import detectar_alucinacion
    assert detectar_alucinacion("¡Listo! Mesa reservada para el viernes.", set()) == "reservar_mesa"
    assert detectar_alucinacion("Reserva confirmada, te espero.", set()) == "reservar_mesa"
    # Variante "anotada" (caso real Antonio 10p)
    assert detectar_alucinacion(
        "Antonio, ya tengo tu reserva anotada para 10 personas el viernes.",
        set(),
    ) == "reservar_mesa"


def test_guardrail_detecta_alucinacion_cancelar(fakes):
    from core.guardrails import detectar_alucinacion
    assert detectar_alucinacion("Reserva cancelada, gracias por avisar.", set()) == "cancelar_reserva"
    assert detectar_alucinacion("He cancelado tu reserva.", set()) == "cancelar_reserva"


def test_guardrail_detecta_alucinacion_escalar(fakes):
    from core.guardrails import detectar_alucinacion
    # Escenario real del bug #22 (Marina, ascenso)
    assert detectar_alucinacion(
        "El equipo de Casa Lola te llamará pronto al 633445566 para organizar todo.",
        set(),
    ) == "escalar_a_humano"
    assert detectar_alucinacion("Aviso al equipo y te contactarán pronto.", set()) == "escalar_a_humano"


def test_guardrail_normaliza_tildes(fakes):
    """'contactarán' con tilde debe detectarse igual que 'contactaran'."""
    from core.guardrails import detectar_alucinacion
    con_tilde = "Te contactarán pronto al 600333444."
    sin_tilde = "Te contactaran pronto al 600333444."
    assert detectar_alucinacion(con_tilde, set()) == "escalar_a_humano"
    assert detectar_alucinacion(sin_tilde, set()) == "escalar_a_humano"
    # Patron extra del fix reciente:
    assert detectar_alucinacion(
        "Para un grupo de 10 personas necesito que hables directamente con el equipo.",
        set(),
    ) == "escalar_a_humano"


def test_guardrail_detecta_alucinacion_derivar_whatsapp(fakes):
    from core.guardrails import detectar_alucinacion
    assert detectar_alucinacion("Te mando un whatsapp ahora con los datos.", set()) == "derivar_a_whatsapp"


def test_guardrail_no_falso_positivo_si_tool_ejecutada(fakes):
    from core.guardrails import detectar_alucinacion
    assert detectar_alucinacion("¡Listo! Mesa reservada.", {"reservar_mesa"}) is None
    assert detectar_alucinacion("Reserva cancelada.", {"cancelar_reserva"}) is None
    assert detectar_alucinacion("El equipo te llamara pronto.", {"escalar_a_humano"}) is None


def test_guardrail_no_falso_positivo_en_pregunta(fakes):
    from core.guardrails import detectar_alucinacion
    # Frases informativas no deben disparar.
    assert detectar_alucinacion("¿Quieres reservar mesa?", set()) is None
    assert detectar_alucinacion("Para reservar necesito tu nombre.", set()) is None
    assert detectar_alucinacion("¿Cuando quieres cancelar la reserva?", set()) is None
    assert detectar_alucinacion("Si quieres puedes llamar al equipo en el 96 312 34 56.", set()) is None


def test_guardrail_historial_evita_falso_positivo_pregunta_pasiva(fakes):
    """
    Issue #49: tras una reserva confirmada en turnos previos, si el
    cliente pregunta de forma pasiva ("¿la has reservado?") y el bot
    responde afirmativamente sin volver a llamar a la tool, el
    guardrail NO debe disparar porque la tool ya se ejecuto antes.
    """
    from core.guardrails import detectar_alucinacion
    historial = [
        {"role": "user", "content": "Hola, quiero reservar para el viernes a las 21h, 4 personas"},
        {"role": "assistant", "content": "Perfecto, dame nombre y telefono"},
        {"role": "user", "content": "Marta Ruiz, 600111222"},
        {"role": "assistant", "content": "¡Listo, Marta! Mesa reservada para el viernes a las 21h."},
        {"role": "user", "content": "vale gracias"},
        {"role": "assistant", "content": "A ti. ¿Algo mas en lo que pueda ayudarte?"},
    ]
    # Turno actual: cliente pregunta pasivamente, bot reafirma sin tool
    reply_actual = "Si, ya esta reservada. Te espero el viernes a las 21h."
    # SIN historial dispararia falso positivo
    assert detectar_alucinacion(reply_actual, set()) == "reservar_mesa"
    # CON historial no debe disparar (la tool ya esta afirmada antes)
    assert detectar_alucinacion(reply_actual, set(), historial=historial) is None


def test_guardrail_historial_no_oculta_alucinacion_real(fakes):
    """
    Caso negativo: si el bot afirma una reserva por PRIMERA vez y el
    historial NO contiene ninguna afirmacion previa de reserva, el
    guardrail SIGUE disparando. El historial solo debe perdonar tools
    ya afirmadas, no enmascarar alucinaciones nuevas.
    """
    from core.guardrails import detectar_alucinacion
    historial = [
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Hola, ¿en que puedo ayudarte?"},
        {"role": "user", "content": "Quiero reservar para el sabado"},
        {"role": "assistant", "content": "¿Para cuantas personas y a que hora?"},
    ]
    reply_actual = "Listo, mesa reservada para el sabado."
    assert detectar_alucinacion(reply_actual, set(), historial=historial) == "reservar_mesa"


def test_guardrail_historial_diferencia_categorias(fakes):
    """
    Una afirmacion previa de RESERVAR no debe perdonar una alucinacion
    de CANCELAR. Cada categoria se rastrea por separado.
    """
    from core.guardrails import detectar_alucinacion
    historial = [
        {"role": "assistant", "content": "¡Listo! Mesa reservada para el viernes."},
        {"role": "user", "content": "perfecto"},
        {"role": "assistant", "content": "Te espero."},
    ]
    # Bot afirma cancelacion sin tool y sin historial de cancelacion
    reply_actual = "He cancelado tu reserva."
    assert detectar_alucinacion(reply_actual, set(), historial=historial) == "cancelar_reserva"


def test_guardrail_historial_none_es_compatible(fakes):
    """
    El parametro historial es opcional. Sin pasarlo, el comportamiento
    es identico a la version anterior.
    """
    from core.guardrails import detectar_alucinacion
    # Mismo input que test_guardrail_detecta_alucinacion_reservar
    assert detectar_alucinacion("¡Listo! Mesa reservada para el viernes.", set()) == "reservar_mesa"
    assert detectar_alucinacion("¡Listo! Mesa reservada.", {"reservar_mesa"}) is None
    # Pasando historial=None explicito tambien
    assert detectar_alucinacion("Mesa reservada.", set(), historial=None) == "reservar_mesa"
    assert detectar_alucinacion("Mesa reservada.", set(), historial=[]) == "reservar_mesa"


def test_guardrail_historial_ignora_content_no_string(fakes):
    """
    El historial puede contener mensajes assistant con content como
    lista de bloques (tool_use). El guardrail debe ignorarlos sin
    romper.
    """
    from core.guardrails import detectar_alucinacion
    historial = [
        {"role": "user", "content": "reserva para el viernes"},
        # content como lista (caso real durante tool_use)
        {"role": "assistant", "content": [{"type": "tool_use", "id": "x", "name": "reservar_mesa", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]},
        {"role": "assistant", "content": "Mesa reservada para el viernes."},
    ]
    reply_actual = "Si, ya esta reservada."
    # No debe disparar (hay afirmacion en el ultimo assistant string)
    assert detectar_alucinacion(reply_actual, set(), historial=historial) is None


def test_guardrail_recovery_distinto_por_tool(fakes):
    from core.guardrails import reply_recovery_para
    rec_reservar = reply_recovery_para("reservar_mesa")
    rec_cancelar = reply_recovery_para("cancelar_reserva")
    rec_escalar = reply_recovery_para("escalar_a_humano")
    # Cada uno menciona su accion correspondiente
    assert "reserva" in rec_reservar.lower()
    assert "anular" in rec_cancelar.lower() or "cancelar" in rec_cancelar.lower()
    assert "equipo" in rec_escalar.lower() or "duen" in rec_escalar.lower()


def test_cancelar_reserva_sin_verificar_identidad_pide_nombre(fakes):
    """Issue #18: cancelar sin nombre_confirmacion ni canal/tel coincidentes
    debe devolver verificacion_pendiente."""
    from core.reservas import cancelar_reserva
    # Simula reserva existente de otra persona
    fakes["supabase"].set_data("reservas", [{
        "id": "r1", "nombre": "Marta Ruiz", "telefono": "+34600111222",
        "fecha": _FECHA_FUTURA, "hora": "21:00", "turno": "cena",
        "num_personas": 4, "canal_origen": "whatsapp",
        "estado": "confirmada",
    }])
    # Otro cliente desde web (sin tel ni nombre_confirmacion) intenta cancelar
    r = cancelar_reserva(
        {"telefono": "+34600111222", "fecha": _FECHA_FUTURA},
        telefono_canal=None, canal_actual="web",
    )
    assert r["status"] == "verificacion_pendiente"


def test_cancelar_reserva_con_nombre_correcto_funciona(fakes):
    """Con nombre_confirmacion correcto, la cancelacion procede."""
    from core.reservas import cancelar_reserva
    fakes["supabase"].set_data("reservas", [{
        "id": "r1", "nombre": "Marta Ruiz", "telefono": "+34600111222",
        "fecha": _FECHA_FUTURA, "hora": "21:00", "turno": "cena",
        "num_personas": 4, "canal_origen": "web",
        "estado": "confirmada",
    }])
    r = cancelar_reserva(
        {"telefono": "+34600111222", "fecha": _FECHA_FUTURA,
         "nombre_confirmacion": "marta ruiz"},
        telefono_canal=None, canal_actual="web",
    )
    assert r["status"] == "cancelada"


def test_cancelar_reserva_mismo_canal_mismo_tel_no_pide_nombre(fakes):
    """Si la reserva es de WhatsApp y cancelas desde WhatsApp con mismo tel,
    no hace falta nombre_confirmacion (el canal ya verifica)."""
    from core.reservas import cancelar_reserva
    fakes["supabase"].set_data("reservas", [{
        "id": "r1", "nombre": "Marta Ruiz", "telefono": "+34600111222",
        "fecha": _FECHA_FUTURA, "hora": "21:00", "turno": "cena",
        "num_personas": 4, "canal_origen": "whatsapp",
        "estado": "confirmada",
    }])
    r = cancelar_reserva(
        {"fecha": _FECHA_FUTURA},
        telefono_canal="+34600111222", canal_actual="whatsapp",
    )
    assert r["status"] == "cancelada"


# ═══════════════════════════════════════════════════════════════════
# Recordatorios automaticos (issue #5)
# ═══════════════════════════════════════════════════════════════════
def test_recordatorio_si_marca_confirmado(fakes):
    """Cliente responde 'si' al recordatorio -> reserva queda confirmada."""
    from core.recordatorios import procesar_respuesta_recordatorio
    reserva = {"id": "r1", "nombre": "Marta", "estado": "confirmada"}
    r = procesar_respuesta_recordatorio(reserva, "si")
    assert r is not None
    assert "esperamos" in r.lower()


def test_recordatorio_no_cancela_reserva(fakes):
    """Cliente responde 'no' al recordatorio -> reserva queda cancelada."""
    from core.recordatorios import procesar_respuesta_recordatorio
    reserva = {"id": "r1", "nombre": "Marta", "estado": "confirmada"}
    r = procesar_respuesta_recordatorio(reserva, "no puedo")
    assert r is not None
    assert "anulada" in r.lower() or "cancelada" in r.lower()


def test_recordatorio_texto_libre_devuelve_none(fakes):
    """Cliente escribe texto libre -> sigue al flujo normal del bot."""
    from core.recordatorios import procesar_respuesta_recordatorio
    reserva = {"id": "r1", "nombre": "Marta", "estado": "confirmada"}
    r = procesar_respuesta_recordatorio(reserva, "puedo cambiar la hora?")
    assert r is None


def test_recordatorios_pendientes_filtra_correctamente(fakes):
    """Solo trae reservas confirmadas sin recordatorio aun."""
    from core.recordatorios import reservas_pendientes_de_recordatorio
    fakes["supabase"].set_data("reservas", [
        {"id": "r1", "estado": "confirmada", "fecha": _FECHA_FUTURA, "telefono": "+34600000000"},
    ])
    pendientes = reservas_pendientes_de_recordatorio(date.fromisoformat(_FECHA_FUTURA))
    assert len(pendientes) == 1


# ═══════════════════════════════════════════════════════════════════
# Lista de espera (issue #6)
# ═══════════════════════════════════════════════════════════════════
def test_apuntar_lista_espera_crea_registro(fakes):
    from core.lista_espera import apuntar_en_lista_espera
    r = apuntar_en_lista_espera({
        "nombre": "Marta",
        "telefono": "+34600111222",
        "fecha": _FECHA_FUTURA,
        "hora": "21:00",
        "num_personas": 4,
    }, canal_origen="web")
    assert r["status"] == "ok"
    assert r["lista_id"]


def test_apuntar_lista_espera_falta_datos(fakes):
    from core.lista_espera import apuntar_en_lista_espera
    r = apuntar_en_lista_espera({"telefono": "+34600000000"})
    assert r["status"] == "error"


def test_lista_espera_si_acepta_crea_reserva(fakes):
    from core.lista_espera import procesar_respuesta_oferta
    candidato = {
        "id": "c1",
        "nombre": "Marta",
        "telefono": "+34600111222",
        "fecha": _FECHA_FUTURA,
        "hora_preferida": "21:00",
        "num_personas": 4,
    }
    respuesta = procesar_respuesta_oferta(candidato, "si")
    assert respuesta is not None
    assert "esperamos" in respuesta.lower() or "mesa" in respuesta.lower()


def test_lista_espera_no_marca_rechazado(fakes):
    from core.lista_espera import procesar_respuesta_oferta
    candidato = {
        "id": "c1",
        "nombre": "Marta",
        "telefono": "+34600111222",
        "fecha": _FECHA_FUTURA,
        "hora_preferida": "21:00",
        "turno": "cena",
        "num_personas": 4,
    }
    respuesta = procesar_respuesta_oferta(candidato, "no")
    assert respuesta is not None
    assert "quitamos" in respuesta.lower() or "gracias" in respuesta.lower()


def test_lista_espera_texto_libre_devuelve_none(fakes):
    from core.lista_espera import procesar_respuesta_oferta
    candidato = {"id": "c1", "nombre": "Marta", "fecha": _FECHA_FUTURA}
    assert procesar_respuesta_oferta(candidato, "¿cuanto cuesta el menu?") is None


# ═══════════════════════════════════════════════════════════════════
# Encuestas post-visita (issue #7)
# ═══════════════════════════════════════════════════════════════════
def test_encuesta_alta_redirige_a_google(fakes):
    from core.encuestas import procesar_respuesta_encuesta
    reserva = {"id": "r1", "nombre": "Marta", "telefono": "+34600111222"}
    r = procesar_respuesta_encuesta(reserva, "5")
    assert r is not None
    assert "google" in r.lower() or "resena" in r.lower() or "review" in r.lower()


def test_encuesta_baja_pide_comentario(fakes):
    from core.encuestas import procesar_respuesta_encuesta
    reserva = {"id": "r1", "nombre": "Marta", "telefono": "+34600111222"}
    r = procesar_respuesta_encuesta(reserva, "2")
    assert r is not None
    assert "mejor" in r.lower() or "comentario" in r.lower() or "duenno" in r.lower()


def test_encuesta_palabra_5_funciona(fakes):
    from core.encuestas import procesar_respuesta_encuesta
    reserva = {"id": "r1", "nombre": "Marta", "telefono": "+34600111222"}
    r = procesar_respuesta_encuesta(reserva, "cinco")
    assert r is not None
    assert "google" in r.lower() or "resena" in r.lower()


def test_encuesta_texto_libre_devuelve_none(fakes):
    """Texto libre sin valoracion ni feedback previo -> None."""
    from core.encuestas import procesar_respuesta_encuesta
    reserva = {"id": "r1", "nombre": "Marta", "telefono": "+34600111222"}
    r = procesar_respuesta_encuesta(reserva, "puedo cambiar mi proxima reserva?")
    assert r is None


# ═══════════════════════════════════════════════════════════════════
# Multi-idioma (issue #9)
# ═══════════════════════════════════════════════════════════════════
def test_lang_detect_ingles_largo(fakes):
    from core.lang_detect import detectar_idioma
    assert detectar_idioma("Hi, do you have a table for 4 tomorrow night?") == "en"


def test_lang_detect_frances(fakes):
    from core.lang_detect import detectar_idioma
    assert detectar_idioma("Bonjour, est-ce que vous avez une table pour deux ce soir") == "fr"


def test_lang_detect_saludos_cortos(fakes):
    """'hello', 'bonjour'... saludos no ambiguos sí cuentan aunque sean 1 palabra."""
    from core.lang_detect import detectar_idioma
    assert detectar_idioma("hello") == "en"
    assert detectar_idioma("Hi!") == "en"
    assert detectar_idioma("bonjour") == "fr"
    assert detectar_idioma("ciao") == "it"
    assert detectar_idioma("hallo") == "de"


def test_lang_detect_palabras_neutras_devuelve_default(fakes):
    """'ok', '5', etc. no indican idioma -> default es."""
    from core.lang_detect import detectar_idioma
    assert detectar_idioma("ok") == "es"
    assert detectar_idioma("5") == "es"


def test_lang_detect_espanol_natural(fakes):
    from core.lang_detect import detectar_idioma
    assert detectar_idioma("hola, quiero reservar mesa para el viernes") == "es"


def test_bloque_idioma_vacio_para_espanol(fakes):
    """Si el cliente escribe en espanol no anadimos bloque al prompt."""
    from core.lang_detect import bloque_idioma_para_prompt
    assert bloque_idioma_para_prompt("es") == ""


def test_bloque_idioma_para_ingles_pide_responder_ingles(fakes):
    from core.lang_detect import bloque_idioma_para_prompt
    bloque = bloque_idioma_para_prompt("en")
    assert "English" in bloque
    assert "ingles" in bloque.lower()


# ═══════════════════════════════════════════════════════════════════
# No-show pasivo (issue #10)
# ═══════════════════════════════════════════════════════════════════
def test_no_show_marca_reserva_candidata(fakes):
    """Reserva con hora pasada hace >30 min se marca como no_show."""
    from core.no_show import marcar_no_show
    reserva = {
        "id": "r1",
        "nombre": "Ana",
        "fecha": _FECHA_FUTURA,
        "hora": "21:00",
        "turno": "cena",
        "num_personas": 4,
    }
    r = marcar_no_show(reserva)
    assert r["ok"] is True


def test_no_show_detector_devuelve_resumen(fakes):
    """El detector siempre devuelve dict con keys correctas, no crashea."""
    from core.no_show import detectar_y_marcar_no_shows
    r = detectar_y_marcar_no_shows()
    assert "total_candidatos" in r
    assert "marcados" in r
    assert isinstance(r["detalle"], list)


# ═══════════════════════════════════════════════════════════════════
# Feed iCal del duenno (issue #58)
# ═══════════════════════════════════════════════════════════════════
def test_ical_generador_devuelve_vcalendar_valido(fakes):
    """
    El generador devuelve un .ics con cabecera VCALENDAR, VTIMEZONE
    Europe/Madrid, y al menos un VEVENT bien formado por reserva.
    """
    from core.calendario import generar_ics_feed

    reservas = [{
        "id": "abc-123",
        "fecha": "2026-05-10",
        "hora": "21:00",
        "nombre": "Marta Ruiz",
        "num_personas": 4,
        "telefono": "+34600111222",
        "turno": "cena",
        "alergias": "gluten",
        "estado": "confirmada",
        "canal_origen": "whatsapp",
        "created_at": "2026-04-24T10:00:00Z",
    }]
    ics = generar_ics_feed(
        reservas,
        nombre_restaurante="Casa Lola",
        direccion_restaurante="Calle Sevilla 5, Valencia",
    )
    # Estructura basica
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert ics.rstrip().endswith("END:VCALENDAR")
    assert "VERSION:2.0" in ics
    assert "PRODID:" in ics
    # VTIMEZONE Europe/Madrid (DST CEST/CET)
    assert "BEGIN:VTIMEZONE\r\nTZID:Europe/Madrid" in ics
    # VEVENT con campos clave
    assert "BEGIN:VEVENT" in ics and "END:VEVENT" in ics
    assert "DTSTART;TZID=Europe/Madrid:20260510T210000" in ics
    assert "Marta Ruiz" in ics
    assert "(4p)" in ics
    assert "STATUS:CONFIRMED" in ics
    # UID estable y con dominio del restaurante
    assert "UID:reserva-abc-123@" in ics
    assert "casalola" in ics.lower()
    # LOCATION con la direccion
    assert "Calle Sevilla 5" in ics
    # CRLF (no LF solo) — requisito de RFC 5545
    assert "\r\n" in ics
    # No deben quedar lineas de >75 octetos sin foldear
    for linea in ics.split("\r\n"):
        # Las continuaciones empiezan por espacio, no las contamos
        if linea.startswith(" "):
            continue
        assert len(linea.encode("utf-8")) <= 75, f"Linea sin foldear: {linea[:80]!r}"


def test_ical_cancelada_marca_status_cancelled(fakes):
    """Reserva cancelada debe llevar STATUS:CANCELLED para que el cliente
    de calendario la elimine del calendario del duenno."""
    from core.calendario import generar_ics_feed

    reservas = [{
        "id": "x1",
        "fecha": "2026-05-15",
        "hora": "14:00",
        "nombre": "Pedro",
        "num_personas": 2,
        "estado": "cancelada",
    }]
    ics = generar_ics_feed(
        reservas, nombre_restaurante="Casa Lola",
        direccion_restaurante="C/ Test 1",
    )
    assert "STATUS:CANCELLED" in ics
    assert "[CANCELADA]" in ics


def test_ical_sin_token_configurado_devuelve_503(client, monkeypatch):
    """
    Si ICAL_FEED_TOKEN esta vacio en el entorno, el endpoint devuelve
    503 con mensaje claro (feature desactivada).
    """
    from admin import webhook as admin_webhook
    monkeypatch.setattr(admin_webhook, "ICAL_FEED_TOKEN", "", raising=False)
    r = client.get("/admin/ical/reservas.ics?token=loquesea")
    assert r.status_code == 503
    assert "no configurado" in r.json()["detail"].lower()


def test_ical_token_invalido_devuelve_404(client, monkeypatch):
    """
    Token invalido devuelve 404 (deliberado: no revela que el endpoint
    existe a quien mete tokens al azar).
    """
    from admin import webhook as admin_webhook
    monkeypatch.setattr(admin_webhook, "ICAL_FEED_TOKEN", "secreto-real-XXX", raising=False)
    r = client.get("/admin/ical/reservas.ics?token=otro-token")
    assert r.status_code == 404


def test_ical_token_valido_devuelve_calendar(client, monkeypatch, fakes):
    """
    Token valido devuelve 200, content-type text/calendar y un
    VCALENDAR completo aunque no haya reservas.
    """
    from admin import webhook as admin_webhook
    monkeypatch.setattr(admin_webhook, "ICAL_FEED_TOKEN", "token-valido-test", raising=False)
    # Sin reservas en el fake (tabla vacia)
    fakes["supabase"].set_data("reservas", [])

    r = client.get("/admin/ical/reservas.ics?token=token-valido-test")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in r.text
    assert "END:VCALENDAR" in r.text


def test_ical_info_endpoint_oculta_token_si_no_configurado(client, monkeypatch):
    """
    /admin/api/ical/info devuelve configurado=false si no hay token,
    sin filtrar info sensible.
    """
    from admin import webhook as admin_webhook
    monkeypatch.setattr(admin_webhook, "ICAL_FEED_TOKEN", "", raising=False)
    r = client.get("/admin/api/ical/info")
    assert r.status_code == 200
    data = r.json()
    assert data["configurado"] is False
    assert data["url"] is None
    assert "mensaje" in data


def test_ical_info_endpoint_devuelve_url_si_configurado(client, monkeypatch):
    """
    Con token configurado devuelve URL completa con el token y las
    instrucciones por plataforma.
    """
    from admin import webhook as admin_webhook
    monkeypatch.setattr(admin_webhook, "ICAL_FEED_TOKEN", "abc123", raising=False)
    r = client.get("/admin/api/ical/info?request_url_base=https://demo.alnora.es")
    assert r.status_code == 200
    data = r.json()
    assert data["configurado"] is True
    assert data["url"] == "https://demo.alnora.es/admin/ical/reservas.ics?token=abc123"
    assert "google_calendar" in data["instrucciones"]
    assert "apple_calendar" in data["instrucciones"]
    assert "outlook" in data["instrucciones"]


def test_ical_escape_de_caracteres_reservados(fakes):
    """
    Comas, puntos y comas, backslashes y newlines en campos de texto
    deben escaparse correctamente segun RFC 5545.
    """
    from core.calendario import generar_ics_feed

    reservas = [{
        "id": "esc",
        "fecha": "2026-05-20",
        "hora": "20:00",
        "nombre": "Juan, Carlos",  # coma
        "num_personas": 3,
        "alergias": "gluten; lacteos",  # punto y coma
        "notas": "Mesa cerca\nde la ventana",  # newline
        "estado": "confirmada",
    }]
    ics = generar_ics_feed(
        reservas, nombre_restaurante="Casa Lola",
        direccion_restaurante="C/ Test 1",
    )
    # Coma escapada
    assert "Juan\\, Carlos" in ics
    # Punto y coma escapado
    assert "gluten\\; lacteos" in ics
    # Newline -> \n literal
    assert "Mesa cerca\\nde la ventana" in ics


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════
def body_result_lower(response) -> str:
    res = response.json().get("results", [])
    if not res:
        return ""
    content = res[0].get("result", "")
    return str(content).lower()
