"""
Capa de abstraccion de proveedores de mensajeria (WhatsApp y futuros canales).

Objetivo: que el resto del codigo (chatbot, tools, CRM) NO dependa del SDK
concreto de Twilio/Meta/Telegram/etc. Solo se hable con una interfaz comun
definida en `base.py`. Asi, el dia que migremos de Twilio a Meta Cloud API,
o anadamos Telegram o Instagram DM, cambia UNA variable de entorno.

Uso:
    from core.messaging import get_provider
    provider = get_provider()
    provider.enviar(telefono="+34600000000", mensaje="Hola")
    datos = provider.parsear_entrante(request_payload)

Seleccion de proveedor: env var `MESSAGING_PROVIDER` (default: 'twilio').
Valores soportados: 'twilio' | 'meta' (stub, pendiente implementar).
"""
import os

from .base import MessagingProvider, MensajeEntrante  # re-export


_cache: dict = {}


def get_provider(force_provider: str = None) -> MessagingProvider:
    """
    Devuelve la instancia singleton del provider configurado.

    Args:
        force_provider: si se pasa (p.ej. en tests), ignora la env var y usa ese.
    """
    name = (force_provider or os.environ.get("MESSAGING_PROVIDER", "twilio")).strip().lower()

    if name in _cache:
        return _cache[name]

    if name == "meta":
        from .meta_provider import MetaProvider
        instance = MetaProvider()
    else:
        # Default: Twilio
        from .twilio_provider import TwilioProvider
        instance = TwilioProvider()

    _cache[name] = instance
    return instance


def reset_cache():
    """Util para tests."""
    _cache.clear()
