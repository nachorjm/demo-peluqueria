"""
Interfaz abstracta comun para proveedores de mensajeria.

Cualquier proveedor (Twilio, Meta Cloud API, Telegram, Instagram DM...)
implementa esta interfaz. El resto del codigo depende SOLO de esta
interfaz, nunca del SDK concreto.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class MensajeEntrante:
    """
    Representacion normalizada de un mensaje entrante, independiente
    del canal por el que haya llegado.

    Atributos:
        telefono: numero del remitente en formato '+34...' (sin prefijo 'whatsapp:').
        texto: cuerpo del mensaje.
        profile_name: nombre que el usuario tiene puesto en la app
                      (WhatsApp lo envia; otros canales pueden dejar '').
        proveedor: nombre corto del proveedor ('twilio', 'meta', ...).
        mensaje_id: id del mensaje en el canal (por si queremos rastreo).
        raw: payload original por si hace falta algo especifico.
    """
    telefono: str
    texto: str
    profile_name: str = ""
    proveedor: str = "desconocido"
    mensaje_id: Optional[str] = None
    raw: Optional[dict] = None


class MessagingProvider:
    """
    Clase base abstracta que todo proveedor debe implementar.

    name: identificador corto ('twilio', 'meta').
    """
    name: str = "base"

    def enviar(self, telefono: str, mensaje: str) -> dict:
        """
        Envia un mensaje al telefono indicado.

        Args:
            telefono: formato '+34600000000' (sin prefijos especificos).
            mensaje: texto a enviar.

        Returns:
            dict con {"ok": bool, "id": str|None, "error": str|None}
        """
        raise NotImplementedError

    def parsear_entrante(self, payload) -> MensajeEntrante:
        """
        Convierte el payload del webhook (form-data de Twilio, JSON de Meta,
        etc.) a un MensajeEntrante normalizado.

        Args:
            payload: lo que haya recibido el endpoint FastAPI. Para Twilio
                     es un dict con 'Body', 'From', 'ProfileName'. Para Meta
                     es el JSON con estructura entry[].changes[].value.messages[].

        Returns:
            MensajeEntrante con los campos rellenos. Si no hay mensaje
            parseable, lanzar ValueError.
        """
        raise NotImplementedError

    def responder_webhook_sincrono(self, texto_respuesta: str) -> Optional[dict]:
        """
        Algunos proveedores esperan la respuesta en el mismo request
        (Twilio espera TwiML; Meta NO espera nada).

        Si el proveedor usa respuesta sincrona, devuelve dict con:
            {"body": str, "media_type": str}
        Si usa respuesta async (Meta), devuelve None y el handler
        debe llamar a .enviar(...) como un POST separado.
        """
        return None
