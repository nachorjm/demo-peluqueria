"""
Proveedor de mensajeria Meta Cloud API (WhatsApp Business Platform).

Estado: STUB pendiente de implementar cuando migremos (Issue #15).
La idea es rellenar esta clase cuando tengamos cuenta Meta for Developers
con la app de WhatsApp activa.

Endpoints de Meta:
  POST https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages
  (con Authorization: Bearer {META_ACCESS_TOKEN})

Webhook entrante (JSON):
  {
    "entry": [{
      "changes": [{
        "value": {
          "messages": [{
            "from": "34600000000",
            "id": "wamid.xxx",
            "text": {"body": "..."},
            "type": "text"
          }],
          "contacts": [{"profile": {"name": "Juan"}}]
        }
      }]
    }]
  }

Variables de entorno esperadas:
  - META_ACCESS_TOKEN
  - META_PHONE_NUMBER_ID
  - META_VERIFY_TOKEN   (para el handshake GET del webhook)
"""
import os
from typing import Optional

from .base import MessagingProvider, MensajeEntrante


class MetaProvider(MessagingProvider):
    name = "meta"

    def __init__(self):
        self.access_token = os.environ.get("META_ACCESS_TOKEN", "").strip()
        self.phone_number_id = os.environ.get("META_PHONE_NUMBER_ID", "").strip()
        self.api_version = os.environ.get("META_API_VERSION", "v20.0").strip()

    # ───────────────────────────────────────────────────────────────
    def enviar(self, telefono: str, mensaje: str) -> dict:
        # TODO(#15): implementar con httpx POST a graph.facebook.com
        return {
            "ok": False,
            "id": None,
            "error": "MetaProvider.enviar no implementado todavia (Issue #15).",
        }

    # ───────────────────────────────────────────────────────────────
    def parsear_entrante(self, payload) -> MensajeEntrante:
        """
        Parsea el JSON que envia Meta al webhook de mensajes.
        Si el payload no contiene un mensaje parseable (ej: notificaciones
        de estado), lanzar ValueError.
        """
        if not isinstance(payload, dict):
            raise ValueError("Payload Meta debe ser dict JSON.")

        try:
            entry = payload["entry"][0]
            change = entry["changes"][0]
            value = change["value"]
            messages = value.get("messages") or []
            if not messages:
                raise ValueError("Payload Meta sin 'messages' (probablemente notificacion de status).")
            msg = messages[0]

            telefono_raw = msg.get("from", "")
            # Meta envia sin '+'. Lo anadimos para homogeneizar.
            telefono = telefono_raw if telefono_raw.startswith("+") else f"+{telefono_raw}"

            texto = ""
            if msg.get("type") == "text":
                texto = msg.get("text", {}).get("body", "").strip()
            # TODO: soportar button, interactive, etc.

            contacts = value.get("contacts") or [{}]
            profile_name = contacts[0].get("profile", {}).get("name", "").strip()

            return MensajeEntrante(
                telefono=telefono,
                texto=texto,
                profile_name=profile_name,
                proveedor=self.name,
                mensaje_id=msg.get("id"),
                raw=payload,
            )
        except (KeyError, IndexError, TypeError) as e:
            raise ValueError(f"Payload Meta malformado: {e}")

    # ───────────────────────────────────────────────────────────────
    def responder_webhook_sincrono(self, texto_respuesta: str) -> Optional[dict]:
        """
        Meta NO espera respuesta en el mismo request. El endpoint devuelve
        200 OK y luego se llama a .enviar(...) de forma asincrona.
        """
        return None

    # ───────────────────────────────────────────────────────────────
    def verificar_webhook(self, hub_mode: str, hub_verify_token: str, hub_challenge: str) -> Optional[str]:
        """
        Handshake que Meta hace al configurar el webhook: GET con parametros
        hub.mode=subscribe, hub.verify_token=<nuestro token>, hub.challenge=<algo>.
        Si el token coincide, devolvemos el challenge para confirmar.
        """
        expected = os.environ.get("META_VERIFY_TOKEN", "").strip()
        if hub_mode == "subscribe" and hub_verify_token == expected and expected:
            return hub_challenge
        return None
