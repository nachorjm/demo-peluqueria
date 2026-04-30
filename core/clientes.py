"""
CRM unificado del restaurante: upsert_cliente.

La tabla `clientes` es la vista unica de cualquier cliente que entre por
cualquier canal del restaurante:

    web          -> formulario de la landing y chatbot web
    whatsapp     -> chatbot de WhatsApp
    voz          -> agente telefonico (Vapi)
    escalacion   -> agente telefonico tras escalar al duenno

La clave de identificacion es el TELEFONO normalizado (formato +34XXXXXXXXX).
A diferencia de la plantilla Alnora (que identificaba por email), aqui el
telefono es el dato natural: en hosteleria casi nadie da el email pero
casi todos dan el telefono para confirmar la reserva.

Si no hay telefono (caso raro: cliente de la web que solo dejo email),
se rastrea aun asi pero en una fila con telefono NULL — tipico solo del
canal web.

Uso:
    from core.clientes import upsert_cliente
    upsert_cliente(
        telefono="+34600000000",
        nombre="Marta Soler",
        canal_origen="whatsapp",
        email="marta@ejemplo.com",
        alergias="frutos secos",
        notas="Pidio mesa terraza si llueve no",
    )
"""
from datetime import datetime, timezone
from typing import Optional

from core.config import supabase
from core.logger import get_logger
from core.memory import _normalizar_telefono

log = get_logger(__name__)


CANALES_VALIDOS = {"web", "whatsapp", "voz", "escalacion"}


def upsert_cliente(
    telefono: Optional[str],
    nombre: Optional[str] = None,
    canal_origen: str = "web",
    email: Optional[str] = None,
    alergias: Optional[str] = None,
    notas: Optional[str] = None,
) -> dict:
    """
    Upsert por telefono (normalizado) en la tabla clientes.

    Si el telefono ya existe: actualiza solo los campos que aporten
    informacion nueva y refresca `ultima_interaccion`.

    Si no existe: inserta nueva fila con el canal_origen indicado.

    Si no hay telefono (None o ""): inserta SOLO si hay email (caso web).
    Si tampoco hay email, devuelve status 'sin_identificador'.

    Returns:
        dict con {"status": "creado|actualizado|sin_identificador|error",
                  "id": ..., "mensaje": ...}
    """
    tel_limpio = _normalizar_telefono(telefono or "")
    email_limpio = (email or "").strip().lower() or None

    if not tel_limpio and not email_limpio:
        return {
            "status": "sin_identificador",
            "id": None,
            "mensaje": "No hay telefono ni email, no se inserta en clientes.",
        }

    if canal_origen not in CANALES_VALIDOS:
        canal_origen = "web"

    try:
        existente = None

        if tel_limpio:
            res = (
                supabase.table("clientes")
                .select("*")
                .eq("telefono", tel_limpio)
                .limit(1)
                .execute()
            )
            if res.data:
                existente = res.data[0]

        # Fallback: si no encontramos por telefono pero hay email, miramos por email.
        if not existente and email_limpio:
            res = (
                supabase.table("clientes")
                .select("*")
                .ilike("email", email_limpio)
                .limit(1)
                .execute()
            )
            if res.data:
                existente = res.data[0]

        ahora = datetime.now(timezone.utc).isoformat()

        if existente:
            updates = {"ultima_interaccion": ahora}
            nuevos = {
                "nombre": nombre,
                "telefono": tel_limpio or None,
                "email": email_limpio,
                "alergias": alergias,
                "notas": notas,
            }
            for campo, valor in nuevos.items():
                if valor and valor != existente.get(campo):
                    updates[campo] = valor

            # canal_origen se actualiza si el cliente entra por canal nuevo,
            # salvo si ya estaba marcado como 'escalacion' (mas grave, no
            # lo pisamos con un hola posterior).
            if (
                existente.get("canal_origen") != "escalacion"
                and canal_origen != existente.get("canal_origen")
            ):
                updates["canal_origen"] = canal_origen

            supabase.table("clientes").update(updates).eq("id", existente["id"]).execute()

            return {
                "status": "actualizado",
                "id": existente["id"],
                "mensaje": (
                    f"Cliente {tel_limpio or email_limpio} actualizado "
                    f"(canal {canal_origen})."
                ),
            }

        # Inserta nuevo
        registro = {
            "telefono": tel_limpio or None,
            "nombre": nombre or "(sin nombre)",
            "email": email_limpio,
            "alergias": alergias,
            "notas": notas,
            "canal_origen": canal_origen,
            "ultima_interaccion": ahora,
        }
        ins = supabase.table("clientes").insert(registro).execute()
        new_id = ins.data[0]["id"] if ins.data else None

        return {
            "status": "creado",
            "id": new_id,
            "mensaje": (
                f"Cliente {tel_limpio or email_limpio} creado en CRM "
                f"(canal {canal_origen})."
            ),
        }

    except Exception as e:
        log.error("Error en upsert_cliente: %s", e, exc_info=True)
        return {"status": "error", "id": None, "mensaje": str(e)}
