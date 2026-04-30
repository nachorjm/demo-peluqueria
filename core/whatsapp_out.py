"""
Envio de mensajes WhatsApp salientes.

DELEGADO en core.messaging (patron Adapter): el proveedor concreto
(Twilio hoy, Meta Cloud API manana) se elige via la env var
`MESSAGING_PROVIDER`. Esta funcion se mantiene por compatibilidad con
codigo existente que la importaba, pero internamente solo es un
wrapper sobre get_provider().enviar(...).

Se usa principalmente desde el agente telefonico (handoff voz->WhatsApp)
para retomar la conversacion por texto cuando Kara no pudo capturar
algun dato por voz (tipicamente el email).
"""
from core.messaging import get_provider


def enviar_whatsapp(telefono: str, mensaje: str) -> dict:
    """
    Envia un mensaje WhatsApp a un numero.

    Args:
        telefono: numero del destinatario en formato '+34...' (sin prefijo
                  'whatsapp:'; el provider lo normaliza si hace falta).
        mensaje: texto del mensaje.

    Returns:
        dict con {"ok": bool, "sid": str|None, "error": str|None}
        (sid es el alias legacy del id del mensaje en Twilio).
    """
    provider = get_provider()
    r = provider.enviar(telefono=telefono, mensaje=mensaje)
    # Mantener la clave legacy 'sid' ademas de 'id'
    return {
        "ok": r.get("ok", False),
        "sid": r.get("id"),
        "error": r.get("error"),
    }
