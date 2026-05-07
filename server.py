"""
Servidor principal FastAPI — backend unificado de los canales del salon
(chatbot WhatsApp, chatbot web, agente telefonico Vapi y landing).
El nombre, branding y datos del salon vienen de
`config/peluqueria.yaml`.

Arranque:
    python -m uvicorn server:app --reload --port 8000
"""
import os
import sys

# Forzar UTF-8 en stdout/stderr. En Windows, la consola por defecto usa
# CP1252 y los `print()` con emojis revientan con UnicodeEncodeError.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from core.logger import setup_logging

# Configurar logging ANTES de importar routers, para que cualquier log
# de import salga con formato estructurado.
setup_logging()

from chatbot_whatsapp.webhook import router as chatbot_router
from chatbot_web.webhook import router as chatbot_web_router
from agente_telefonico.webhook import router as agente_router
from landing.webhook import router as landing_router
from admin.webhook import router as admin_router
from health.webhook import router as health_router
from core.peluqueria_data import (
    BOT,
    BRANDING,
    CORS_ORIGINS_DEFAULT,
    GOOGLE_REVIEW_URL,
    SALON,
    estilistas_activos,
    landing_config,
    widget_web_config,
)


app = FastAPI(title=f"{SALON['nombre']} - Backend unificado")


# ─── CORS ────────────────────────────────────────────────────────────
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

# Static files (favicon, OG image, logo). Solo se monta si existe.
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


_INDEX_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
_DEMO_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo.html")


@app.get("/")
def root():
    """Sirve la landing del salon."""
    return FileResponse(_INDEX_HTML, media_type="text/html")


@app.get("/demo", response_class=HTMLResponse)
def pagina_demo():
    """
    Pagina comercial del sistema multicanal aplicado al salon.

    Lee `demo.html` y le inyecta `window.__DEMO_CONFIG` con los numeros
    reales (Twilio sandbox + Vapi) que el comercial usa para que el
    cliente pueda probar en vivo.
    """
    if not os.path.exists(_DEMO_HTML):
        return HTMLResponse(
            "<h1>Pagina demo no disponible</h1>"
            "<p>El archivo demo.html no esta presente en el deploy.</p>",
            status_code=503,
        )

    wa_raw = os.environ.get("TWILIO_WHATSAPP_NUMBER", "").strip()
    wa_numero = wa_raw.replace("whatsapp:", "").strip() if wa_raw else ""
    wa_keyword = os.environ.get("TWILIO_SANDBOX_KEYWORD", "").strip()
    vapi_numero = os.environ.get("VAPI_PHONE_NUMBER", "").strip()

    with open(_DEMO_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    import json
    config = {
        "wa_numero": wa_numero,
        "wa_keyword": wa_keyword,
        "vapi_numero": vapi_numero,
    }
    inject = (
        f"<script>window.__DEMO_CONFIG = {json.dumps(config)};</script>"
    )
    html = html.replace("</head>", f"{inject}\n</head>", 1)

    return HTMLResponse(content=html)


@app.get("/api/salon")
def api_salon():
    """
    Datos publicos del salon para que el frontend (landing y panel
    admin) se autoconfigure: nombre, contacto, branding, equipo y urls
    externas. El cliente clona el repo, edita config/peluqueria.yaml y
    este endpoint ya expone todo lo que el HTML necesita.
    """
    equipo = [
        {
            "id_yaml": e.get("id_yaml"),
            "nombre": e.get("nombre"),
            "rol": e.get("rol", ""),
            "especialidades": e.get("especialidades") or [],
        }
        for e in estilistas_activos()
    ]
    return {
        "nombre": SALON.get("nombre", ""),
        "tipo": SALON.get("tipo", ""),
        "ciudad": SALON.get("ciudad", ""),
        "barrio": SALON.get("barrio", ""),
        "anno_fundacion": SALON.get("anno_fundacion"),
        "direccion": SALON.get("direccion", ""),
        "telefono": SALON.get("telefono", ""),
        "email": SALON.get("email", ""),
        "web": SALON.get("web", ""),
        "branding": BRANDING,                    # legacy
        "bot": BOT,
        "landing": landing_config(),
        "widget_web": widget_web_config(),
        "google_review_url": GOOGLE_REVIEW_URL,
        "equipo": equipo,
    }


@app.get("/api/status")
def api_status():
    return {
        "status": "ok",
        "service": f"{SALON['nombre']} backend",
        "endpoints": {
            "chatbot_whatsapp": ["POST /whatsapp", "POST /whatsapp/meta"],
            "chatbot_web": ["POST /web/chat"],
            "agente": [
                "POST /vapi/tool/agendar_cita",
                "POST /vapi/tool/consultar_disponibilidad",
                "POST /vapi/tool/cancelar_cita",
                "POST /vapi/tool/buscar_citas",
                "POST /vapi/tool/modificar_cita",
                "POST /vapi/tool/consultar_servicios",
                "POST /vapi/tool/consultar_horario",
                "POST /vapi/tool/consultar_historial",
                "POST /vapi/tool/escalar_a_humano",
                "POST /vapi/tool/derivar_a_whatsapp",
                "POST /vapi/server-url",
            ],
            "landing": [
                "POST /supabase/webhook/cita-nueva",
                "POST /supabase/webhook/cita-modificada",
                "GET /demo",
            ],
            "admin": [
                "GET /admin",
                "GET /admin/api/citas",
                "POST /admin/api/citas/{id}/cancelar",
                "GET /admin/api/stats",
                "GET /admin/api/ical/info",
                "GET /admin/ical/citas.ics",
            ],
            "health": [
                "GET /health",
            ],
        },
    }
