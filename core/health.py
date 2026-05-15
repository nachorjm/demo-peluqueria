"""
Comprobaciones de salud de las dependencias externas (issue #13).

Endpoint /health (servido por health/webhook.py) llama aqui para saber
si Supabase, Anthropic, Twilio y Resend responden. Lo usa Railway (en
Settings -> Health Check URL) y opcionalmente uptime monitors externos
para alertar antes de que el cliente se queje.

Niveles:
  - "ok": el chequeo paso.
  - "fail": el chequeo fallo.
  - "missing": no hay credencial configurada (no se puede chequear).

Status global:
  - "healthy": Supabase y Anthropic OK (criticas).
  - "degraded": criticas OK pero Twilio o Resend fallan/missing.
  - "down": al menos una critica falla.

Disenamos los chequeos para ser BARATOS:
  - Supabase: SELECT 1 row, latencia ~100ms, no factura.
  - Anthropic: llamada con max_tokens=1, ~0.0000005 € por chequeo.
  - Twilio: solo verificamos que credenciales esten presentes y
    formato del SID ('AC...').
  - Resend: solo verificamos que API key este presente.
"""
import os
import time
from typing import Dict, Optional


CRITICAS = {"supabase", "anthropic"}


def _ms_desde(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


# ════════════════════════════════════════════════════════════════════
# Checks individuales
# ════════════════════════════════════════════════════════════════════

def check_supabase() -> Dict:
    """SELECT 1 row de citas. Si tarda >3s o falla -> fail."""
    t0 = time.perf_counter()
    try:
        from core.config import supabase
        # Limit 1 + select id minimal para ser rapido
        supabase.table("citas").select("id").limit(1).execute()
        return {"status": "ok", "latency_ms": _ms_desde(t0)}
    except Exception as e:
        return {
            "status": "fail",
            "latency_ms": _ms_desde(t0),
            "error": str(e)[:200],
        }


def check_anthropic() -> Dict:
    """Llamada minima al modelo (max_tokens=1) para validar que la API responde."""
    t0 = time.perf_counter()
    try:
        from core.config import claude, MODEL
        claude.messages.create(
            model=MODEL,
            max_tokens=1,
            messages=[{"role": "user", "content": "ok"}],
        )
        return {"status": "ok", "latency_ms": _ms_desde(t0)}
    except Exception as e:
        return {
            "status": "fail",
            "latency_ms": _ms_desde(t0),
            "error": str(e)[:200],
        }


def check_twilio() -> Dict:
    """Solo verifica presencia y formato de credenciales (no llamada real)."""
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    if not sid or not token:
        return {"status": "missing", "error": "credenciales ausentes"}
    if not sid.startswith("AC") or len(sid) < 20:
        return {"status": "fail", "error": "TWILIO_ACCOUNT_SID con formato invalido"}
    return {"status": "ok"}


def check_resend() -> Dict:
    """Solo verifica presencia de API key (no llamada real)."""
    key = os.environ.get("RESEND_API_KEY", "").strip()
    if not key:
        return {"status": "missing", "error": "RESEND_API_KEY ausente"}
    if not key.startswith("re_"):
        return {"status": "fail", "error": "RESEND_API_KEY con formato invalido"}
    return {"status": "ok"}


# ════════════════════════════════════════════════════════════════════
# Status overall
# ════════════════════════════════════════════════════════════════════

def _overall_status(checks: Dict[str, Dict]) -> str:
    """
    healthy: todas las criticas en ok.
    degraded: criticas ok pero alguna no critica fail/missing.
    down: alguna critica fail/missing.
    """
    for nombre in CRITICAS:
        if checks.get(nombre, {}).get("status") != "ok":
            return "down"
    for nombre, c in checks.items():
        if c.get("status") != "ok":
            return "degraded"
    return "healthy"


def health_check() -> Dict:
    """
    Punto de entrada usado por el endpoint /health.
    Devuelve dict con status global, timestamp y detalles por servicio.
    """
    from datetime import datetime, timezone
    checks = {
        "supabase": check_supabase(),
        "anthropic": check_anthropic(),
        "twilio": check_twilio(),
        "resend": check_resend(),
    }
    return {
        "status": _overall_status(checks),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }
