"""
Sistema de logging estructurado (issue #14).

Sustituye los `print()` esparcidos por todo el codigo por loggers reales
con niveles (DEBUG, INFO, WARNING, ERROR). Beneficios:

  - Filtrado por nivel en Railway (LOG_LEVEL env var).
  - Timestamps automaticos.
  - Stack traces completos en errores (exc_info=True).
  - Cada modulo tiene su propio sub-logger ("casalola.web",
    "casalola.whatsapp", etc) -> facil filtrar por canal.

USO en cada modulo:

    from core.logger import get_logger
    log = get_logger(__name__)

    log.info("Mensaje recibido: %s", texto[:120])
    log.warning("Error cargando historial: %s", e)
    log.error("Claude exploto", exc_info=True)

USO en entrypoints (server.py + scripts/*.py):

    from core.logger import setup_logging
    setup_logging()  # llamar UNA VEZ al arranque

Configuracion via env var LOG_LEVEL ("DEBUG", "INFO", "WARNING", "ERROR").
Por defecto: INFO.

Notas:
  - Emojis (❌ ⚠️ ✅ 📩) se mantienen en los mensajes — siguen siendo
    legibles en logs de Railway y ayudan al ojo a escanear rapido.
  - El fix de UTF-8 de server.py para Windows sigue valido (logging
    escribe a stdout y reusa el reconfigure).
"""
import logging
import os
import sys
from typing import Optional


_CONFIGURED = False


def setup_logging(level: Optional[str] = None) -> None:
    """
    Configura el logger root. Idempotente: llamarla varias veces no
    duplica handlers. Llamar UNA VEZ desde el entrypoint (server.py o
    cada script CLI).

    level: nivel a usar. Si None, lee LOG_LEVEL de env (default INFO).
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    # Resolver nivel: parametro > env var > INFO
    nivel_str = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    nivel = getattr(logging, nivel_str, logging.INFO)

    # Limpiamos handlers preexistentes (ej. uvicorn los pone) para evitar
    # logs duplicados.
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(nivel)

    # Silenciar libs ruidosas que escupen INFO/DEBUG en cada request.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """
    Devuelve un logger con nombre normalizado bajo "casalola.*".
    Acepta __name__ del modulo y lo recorta a algo legible:
       "chatbot_whatsapp.webhook" -> "casalola.whatsapp.webhook"
       "core.reservas"            -> "casalola.reservas"
       "agente_telefonico.tools"  -> "casalola.voz.tools"
    """
    # Mapping de prefijos largos a nombres cortos en logs.
    alias = {
        "chatbot_whatsapp": "whatsapp",
        "chatbot_web": "web",
        "agente_telefonico": "voz",
    }
    parts = name.split(".")
    if parts and parts[0] in alias:
        parts[0] = alias[parts[0]]
    if parts and parts[0] == "core":
        parts = parts[1:]  # "core.reservas" -> "reservas"
    nombre_legible = ".".join(parts) if parts else name
    return logging.getLogger(f"casalola.{nombre_legible}")
