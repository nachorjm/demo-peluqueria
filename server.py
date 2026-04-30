"""
Servidor principal FastAPI — backend unificado de los canales del
restaurante (chatbot WhatsApp, chatbot web, agente telefonico Vapi y
landing). El nombre, branding y datos del restaurante vienen de
`config/restaurante.yaml` (issue #11).

Arranque:
    python -m uvicorn server:app --reload --port 8000
"""
import os
import sys

# Forzar UTF-8 en stdout/stderr. En Windows, la consola por defecto usa
# CP1252 y los `print()` con emojis (logs del codigo) revientan con
# UnicodeEncodeError. errors='replace' evita el crash si llega un caracter
# que aun asi no se puede codificar.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from core.logger import setup_logging

# Configurar logging ANTES de importar routers, para que cualquier log de
# import (ej. config.py rechazando arranque) salga con formato estructurado.
setup_logging()

from chatbot_whatsapp.webhook import router as chatbot_router
from chatbot_web.webhook import router as chatbot_web_router
from agente_telefonico.webhook import router as agente_router
from landing.webhook import router as landing_router
from admin.webhook import router as admin_router
from health.webhook import router as health_router
from core.restaurante_data import (
    BOT,
    BRANDING,
    CORS_ORIGINS_DEFAULT,
    GOOGLE_REVIEW_URL,
    RESTAURANTE,
    landing_config,
    widget_web_config,
)


app = FastAPI(title=f"{RESTAURANTE['nombre']} - Backend unificado")


# ─── CORS ────────────────────────────────────────────────────────────
# Por defecto se usan los `cors_origins` del YAML del restaurante. En
# produccion se puede sobrescribir con la env var CORS_ORIGINS (lista
# separada por comas) para no editar el YAML.
_default_origins = ",".join(CORS_ORIGINS_DEFAULT)
CORS_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", _default_origins).split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(chatbot_router, tags=["chatbot-whatsapp"])
app.include_router(chatbot_web_router, tags=["chatbot-web"])
app.include_router(agente_router, tags=["agente-telefonico"])
app.include_router(landing_router, tags=["landing"])
app.include_router(admin_router, tags=["admin"])
app.include_router(health_router, tags=["health"])

# Static files (favicon, OG image, logo) — issue #55. Solo se monta si
# existe el directorio. Cliente que no tenga branding visual y solo
# use chatbot WA puede no tener `static/` en absoluto.
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


_INDEX_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
_DEMO_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo.html")


@app.get("/")
def root():
    """Sirve la landing del restaurante."""
    return FileResponse(_INDEX_HTML, media_type="text/html")


@app.get("/demo", response_class=HTMLResponse)
def pagina_demo():
    """
    Pagina comercial pensada para que el equipo de Alnora ensene a
    clientes potenciales como funciona el sistema multicanal.

    Lee `demo.html` y le inyecta `window.__DEMO_CONFIG` con los
    numeros reales (Twilio sandbox + Vapi) que el comercial usa
    para que el cliente pueda probar en vivo. Esos numeros vienen
    de las env vars TWILIO_WHATSAPP_NUMBER, TWILIO_SANDBOX_KEYWORD
    y VAPI_PHONE_NUMBER.

    Si alguna no esta configurada, la seccion correspondiente cae a
    un mensaje "Pidelo al comercial" sin romper la pagina.
    """
    if not os.path.exists(_DEMO_HTML):
        return HTMLResponse(
            "<h1>Pagina demo no disponible</h1>"
            "<p>El archivo demo.html no esta presente en el deploy.</p>",
            status_code=503,
        )

    # Numero WA: env var "whatsapp:+14155238886" -> "+1 415 523 8886"
    wa_raw = os.environ.get("TWILIO_WHATSAPP_NUMBER", "").strip()
    wa_numero = wa_raw.replace("whatsapp:", "").strip() if wa_raw else ""
    wa_keyword = os.environ.get("TWILIO_SANDBOX_KEYWORD", "").strip()
    vapi_numero = os.environ.get("VAPI_PHONE_NUMBER", "").strip()

    with open(_DEMO_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    # Inyeccion segura: usamos json.dumps para escapar cualquier comilla
    # o caracter raro en los valores. NO interpolar strings sueltos.
    import json
    config = {
        "wa_numero": wa_numero,
        "wa_keyword": wa_keyword,
        "vapi_numero": vapi_numero,
    }
    inject = (
        f"<script>window.__DEMO_CONFIG = {json.dumps(config)};</script>"
    )
    # Inyectar justo antes del </head>
    html = html.replace("</head>", f"{inject}\n</head>", 1)

    return HTMLResponse(content=html)


@app.get("/api/restaurante")
def api_restaurante():
    """
    Datos publicos del restaurante para que el frontend (landing y panel
    admin) se autoconfigure: nombre, contacto, branding (colores, textos)
    y urls externas. El cliente clona el repo, edita config/restaurante.yaml
    y este endpoint ya expone todo lo que el HTML necesita (issue #11).

    Tras issue #55: ademas expone bloques separados `landing` y
    `widget_web` con defaults graceful, para que clientes que solo
    embeben el widget no necesiten rellenar el bloque landing
    (y viceversa).

    El campo `branding` se mantiene por compatibilidad con codigo
    viejo del frontend; codigo nuevo debe leer landing/widget_web/bot.
    """
    return {
        "nombre": RESTAURANTE.get("nombre", ""),
        "tipo": RESTAURANTE.get("tipo", ""),
        "ciudad": RESTAURANTE.get("ciudad", ""),
        "barrio": RESTAURANTE.get("barrio", ""),
        "anno_fundacion": RESTAURANTE.get("anno_fundacion"),
        "direccion": RESTAURANTE.get("direccion", ""),
        "telefono": RESTAURANTE.get("telefono", ""),
        "email": RESTAURANTE.get("email", ""),
        "web": RESTAURANTE.get("web", ""),
        "branding": BRANDING,                    # legacy, no romper
        "bot": BOT,                              # nuevo (issue #55)
        "landing": landing_config(),             # nuevo (issue #55)
        "widget_web": widget_web_config(),       # nuevo (issue #55)
        "google_review_url": GOOGLE_REVIEW_URL,
    }


@app.get("/api/status")
def api_status():
    return {
        "status": "ok",
        "service": f"{RESTAURANTE['nombre']} backend",
        "endpoints": {
            "chatbot_whatsapp": ["POST /whatsapp", "POST /whatsapp/meta"],
            "chatbot_web": ["POST /web/chat"],
            "agente": [
                "POST /vapi/tool/reservar_mesa",
                "POST /vapi/tool/consultar_disponibilidad",
                "POST /vapi/tool/cancelar_reserva",
                "POST /vapi/tool/buscar_reservas",
                "POST /vapi/tool/modificar_reserva",
                "POST /vapi/tool/consultar_carta",
                "POST /vapi/tool/consultar_horario",
                "POST /vapi/tool/consultar_historial",
                "POST /vapi/tool/escalar_a_humano",
                "POST /vapi/tool/derivar_a_whatsapp",
                "POST /vapi/server-url",
            ],
            "landing": [
                "POST /supabase/webhook/reserva-nueva",
                "POST /supabase/webhook/reserva-modificada",
                "GET /demo",
            ],
            "admin": [
                "GET /admin",
                "GET /admin/api/reservas",
                "POST /admin/api/reservas/{id}/cancelar",
                "GET /admin/api/stats",
                "GET /admin/api/ical/info",
                "GET /admin/ical/reservas.ics",
            ],
            "health": [
                "GET /health",
            ],
        },
    }
