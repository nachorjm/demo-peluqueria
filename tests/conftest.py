"""
Fixtures globales para los smoke tests.

OBJETIVO: que los tests NO gasten dinero ni ensucien la BD de produccion.
Para conseguirlo:

1. Antes de cualquier import del proyecto, ponemos variables de entorno
   DUMMY para que `core/config.py` no haga sys.exit al no encontrarlas.

2. Un fixture `autouse=True` monkeypatchea:
     - core.config.supabase  -> FakeSupabase
     - core.config.claude    -> FakeClaude
     - core.notifications.send_email   -> no-op
     - core.whatsapp_out.enviar_whatsapp -> no-op
     - core.messaging.get_provider     -> FakeProvider

3. TODOS los modulos que ya importaron `supabase`/`claude` por nombre
   directo se parchean tambien (porque `from core.config import supabase`
   crea una referencia local en ese modulo).
"""
import os
import sys

# ───────────────────────────────────────────────────────────────────
# 1. ENV vars dummy ANTES de cualquier import del proyecto
# ───────────────────────────────────────────────────────────────────
os.environ["ANTHROPIC_API_KEY"] = "sk-test-dummy"
os.environ["SUPABASE_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "sb_secret_test_dummy"
os.environ["RESEND_API_KEY"] = "re_test_dummy"
os.environ["NOTIFICATIONS_TO"] = "test@example.com"
os.environ["TWILIO_ACCOUNT_SID"] = "ACtest"
os.environ["TWILIO_AUTH_TOKEN"] = "test_token"
os.environ["TWILIO_WHATSAPP_NUMBER"] = "whatsapp:+14155238886"

os.environ["SUPABASE_WEBHOOK_SECRET"] = ""
os.environ["ADMIN_PASSWORD"] = ""

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


import pytest


# ───────────────────────────────────────────────────────────────────
# 2. Fakes
# ───────────────────────────────────────────────────────────────────
class _FakeQuery:
    """Query encadenable falsa."""
    def __init__(self, supabase_ref, table):
        self._sb = supabase_ref
        self._table = table
        self._op = None
        self._payload = None
        self._delete_filters = []

    def select(self, *a, **kw): return self
    def insert(self, data, *a, **kw):
        self._op = "insert"
        self._payload = data
        return self
    def update(self, data, *a, **kw):
        self._op = "update"
        self._payload = data
        return self
    def delete(self, *a, **kw):
        self._op = "delete"
        return self
    def eq(self, *a, **kw): return self
    def ilike(self, *a, **kw): return self
    def neq(self, *a, **kw): return self
    def gte(self, *a, **kw): return self
    def lte(self, *a, **kw): return self
    def lt(self, *a, **kw): return self
    def gt(self, *a, **kw): return self
    def is_(self, *a, **kw): return self
    def in_(self, *a, **kw): return self
    def order(self, *a, **kw): return self
    def limit(self, *a, **kw): return self
    def single(self, *a, **kw): return self

    @property
    def not_(self): return self

    def execute(self):
        class _Resp:
            pass
        r = _Resp()
        if self._op == "insert":
            payload = self._payload
            if isinstance(payload, list):
                r.data = [{**row, "id": f"fake-{self._table}-{i}",
                           "created_at": "2026-04-20T10:00:00Z"}
                          for i, row in enumerate(payload)]
            else:
                r.data = [{**payload, "id": f"fake-{self._table}-0",
                           "created_at": "2026-04-20T10:00:00Z"}]
            return r
        if self._op == "update":
            r.data = [{"id": f"fake-{self._table}-0", **(self._payload or {})}]
            return r
        if self._op == "delete":
            r.data = []
            return r
        # select y resto
        r.data = list(self._sb.tables.get(self._table, []))
        return r


class FakeSupabase:
    """Mock minimo de supabase-py con .table(...).<query>().execute()."""
    def __init__(self):
        self.tables = {}

    def set_data(self, tablename, rows):
        self.tables[tablename] = rows

    def table(self, name):
        return _FakeQuery(self, name)


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text="Respuesta falsa del test."):
        self.content = [_FakeTextBlock(text)]
        self.stop_reason = "end_turn"


class FakeClaude:
    """Mock de anthropic.Anthropic que devuelve siempre texto fijo."""
    def __init__(self):
        self.messages = self
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse()


# ───────────────────────────────────────────────────────────────────
# 3. Fixtures
# ───────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _isolate_external_services(monkeypatch):
    """
    Parchea supabase, claude, resend y twilio en TODOS los modulos que
    ya los importaron por nombre directo.
    """
    from core import config as core_config
    from core import notifications as core_notifications
    from core import whatsapp_out as core_whatsapp_out
    from core import memory as core_memory
    from core import clientes as core_clientes
    from core import citas as core_citas
    from core import estilistas as core_estilistas
    from core import escalacion as core_escalacion
    from core import health as core_health
    from chatbot_whatsapp import tools as wa_tools
    from chatbot_whatsapp import webhook as wa_webhook
    from chatbot_web import tools as web_tools
    from chatbot_web import webhook as web_webhook
    from agente_telefonico import tools as voz_tools
    from agente_telefonico import webhook as voz_webhook
    from landing import webhook as landing_webhook
    from admin import webhook as admin_webhook

    # core/config.py hace load_dotenv(override=True), que pisa las env
    # vars dummy si el repo tiene un .env real. Forzamos los secretos.
    monkeypatch.setattr(landing_webhook, "WEBHOOK_SECRET", "", raising=False)
    monkeypatch.setattr(admin_webhook, "ADMIN_PASSWORD", "", raising=False)

    fake_sb = FakeSupabase()
    fake_cl = FakeClaude()

    # Parchear en todos los modulos donde se uso "from core.config import supabase/claude"
    for mod in (core_config, core_notifications, core_memory,
                core_clientes, core_citas, core_estilistas,
                core_escalacion, core_health,
                wa_tools, wa_webhook, web_tools, web_webhook,
                voz_tools, voz_webhook, landing_webhook, admin_webhook):
        if hasattr(mod, "supabase"):
            monkeypatch.setattr(mod, "supabase", fake_sb, raising=False)
        if hasattr(mod, "claude"):
            monkeypatch.setattr(mod, "claude", fake_cl, raising=False)

    # Silenciar Resend y Twilio
    def _fake_send_email(*a, **kw):
        return {"ok": True, "id": "fake-email-id", "error": None}

    monkeypatch.setattr(core_notifications, "send_email", _fake_send_email, raising=True)

    def _fake_enviar_whatsapp(*a, **kw):
        return {"ok": True, "sid": "fake-twilio-sid", "error": None}

    monkeypatch.setattr(core_whatsapp_out, "enviar_whatsapp", _fake_enviar_whatsapp, raising=True)
    monkeypatch.setattr(voz_tools, "enviar_whatsapp", _fake_enviar_whatsapp, raising=True)

    # Neutralizar el provider de mensajeria
    from core import messaging as core_messaging
    from core.messaging import twilio_provider as tw_prov
    from core.messaging import meta_provider as meta_prov

    class _FakeProvider:
        name = "fake"
        def enviar(self, telefono, mensaje):
            return {"ok": True, "id": "fake-msg-id", "error": None}
        def parsear_entrante(self, payload):
            from core.messaging.base import MensajeEntrante
            return MensajeEntrante(
                telefono="+34600000000", texto=str(payload)[:50],
                profile_name="", proveedor="fake", mensaje_id="fake",
                raw=payload,
            )
        def responder_webhook_sincrono(self, texto):
            return {"body": f"<Response><Message>{texto}</Message></Response>",
                    "media_type": "application/xml"}

    fake_prov = _FakeProvider()
    monkeypatch.setattr(core_messaging, "get_provider", lambda *a, **kw: fake_prov, raising=True)
    import core.whatsapp_out as wo
    monkeypatch.setattr(wo, "get_provider", lambda *a, **kw: fake_prov, raising=True)

    # MetaProvider.enviar para que /whatsapp/meta no toque red
    monkeypatch.setattr(meta_prov.MetaProvider, "enviar",
                        lambda self, telefono, mensaje: {"ok": True, "id": "fake", "error": None},
                        raising=True)

    yield {
        "supabase": fake_sb,
        "claude": fake_cl,
    }


@pytest.fixture
def client(_isolate_external_services):
    """TestClient de FastAPI montando el server.py real."""
    from fastapi.testclient import TestClient
    from server import app
    return TestClient(app)


@pytest.fixture
def fakes(_isolate_external_services):
    """Acceso directo a los fakes desde un test si quiere precargar datos."""
    return _isolate_external_services
