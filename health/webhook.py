"""
Router FastAPI del endpoint /health (issue #13).

GET /health: comprueba salud de Supabase, Anthropic, Twilio, Resend y
devuelve JSON con status overall + detalles. Codigo HTTP:
  - 200 si healthy o degraded.
  - 503 Service Unavailable si down (alguna critica falla).

Sin auth (los health checks externos / Railway lo llaman sin credenciales).
"""
from fastapi import APIRouter, Response

from core.health import health_check


router = APIRouter()


@router.get("/health")
async def health(response: Response):
    """Devuelve el estado de las dependencias externas. Para uptime monitors."""
    resultado = health_check()
    if resultado["status"] == "down":
        response.status_code = 503
    return resultado
