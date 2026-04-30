"""
Proveedor de mensajeria Twilio (WhatsApp).

Encapsula el SDK de Twilio. Mientras estemos en sandbox, los destinatarios
deben haber hecho 'join <codigo>' previamente. En produccion, con un numero
WhatsApp Business API real, esa limitacion desaparece.

Variables de entorno:
  - TWILIO_ACCOUNT_SID
  - TWILIO_AUTH_TOKEN
  - TWILIO_WHATSAPP_NUMBER  (ej: 'whatsapp:+14155238886')
"""
import html as html_mod
import os
from typing import Optional

from core.logger import get_logger

from .base import MessagingProvider, MensajeEntrante

log = get_logger(__name__)

try:
    from twilio.rest import Client
    from twilio.base.exceptions import TwilioRestException
    _TWILIO_AVAILABLE = True
except ImportError:
    _TWILIO_AVAILABLE = False


class TwilioProvider(MessagingProvider):
    name = "twilio"

    def __init__(self):
        self.account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
        self.auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
        self.from_number = os.environ.get("TWILIO_WHATSAPP_NUMBER", "").strip()
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not _TWILIO_AVAILABLE:
            log.warning("Paquete 'twilio' no instalado. pip install twilio.")
            return None
        if not (self.account_sid and self.auth_token):
            log.warning("TWILIO_ACCOUNT_SID o TWILIO_AUTH_TOKEN no configurados en .env.")
            return None
        self._client = Client(self.account_sid, self.auth_token)
        return self._client

    # ───────────────────────────────────────────────────────────────
    def enviar(self, telefono: str, mensaje: str) -> dict:
        if not telefono or not mensaje:
            return {"ok": False, "id": None, "error": "Faltan telefono o mensaje."}

        client = self._get_client()
        if client is None:
            return {"ok": False, "id": None, "error": "Twilio no configurado correctamente."}

        if not self.from_number:
            return {"ok": False, "id": None, "error": "TWILIO_WHATSAPP_NUMBER no configurado."}

        # Normalizar destinatario al formato whatsapp:
        destino = telefono.strip()
        if not destino.startswith("whatsapp:"):
            if not destino.startswith("+"):
                destino = "+" + destino
            destino = f"whatsapp:{destino}"

        # Normalizar remitente
        origen = self.from_number
        if not origen.startswith("whatsapp:"):
            origen = f"whatsapp:{origen}"

        try:
            message = client.messages.create(from_=origen, to=destino, body=mensaje)
            return {"ok": True, "id": message.sid, "error": None}
        except TwilioRestException as e:
            return {"ok": False, "id": None, "error": f"Twilio error {e.code}: {e.msg}"}
        except Exception as e:
            return {"ok": False, "id": None, "error": str(e)}

    # ───────────────────────────────────────────────────────────────
    def parsear_entrante(self, payload) -> MensajeEntrante:
        """
        payload aqui es un dict con los campos que Twilio manda como form-data
        al webhook (Body, From, ProfileName, MessageSid, ...).
        """
        if not isinstance(payload, dict):
            raise ValueError("Payload Twilio debe ser dict de form-data.")

        texto = (payload.get("Body") or "").strip()
        telefono_raw = payload.get("From") or ""
        # Twilio manda 'whatsapp:+34600...', quitamos el prefijo.
        telefono = telefono_raw.replace("whatsapp:", "").strip()

        return MensajeEntrante(
            telefono=telefono,
            texto=texto,
            profile_name=(payload.get("ProfileName") or "").strip(),
            proveedor=self.name,
            mensaje_id=payload.get("MessageSid"),
            raw=payload,
        )

    # ───────────────────────────────────────────────────────────────
    def responder_webhook_sincrono(self, texto_respuesta: str) -> Optional[dict]:
        """
        Twilio espera TwiML en la respuesta del mismo POST.
        """
        safe = html_mod.escape(texto_respuesta or "")
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Response>\n'
            f'    <Message>{safe}</Message>\n'
            '</Response>'
        )
        return {"body": twiml, "media_type": "application/xml"}
