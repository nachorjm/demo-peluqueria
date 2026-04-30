"""
Utilidades de notificacion por email via Resend para Casa Lola.

Se usa para avisar al dueño/encargado cuando ocurren eventos
importantes:
  - Nueva reserva creada por cualquier canal (web, whatsapp, voz).
  - Escalacion al humano (queja, grupo grande, evento privado, etc.).

Configuracion:
  - RESEND_API_KEY en .env (obtener en https://resend.com).
  - RESEND_FROM: email del remitente (por defecto el dominio de prueba
    de Resend hasta que verifiquemos el del restaurante).
  - NOTIFICATIONS_TO: email del dueño que recibe los avisos.
"""
import os
from typing import Optional

import resend

from core import restaurante_data as _rd
from core.restaurante_data import (
    RESTAURANTE,
    email_from_address,
    email_logo_url,
)


# Configuracion (se lee del entorno al importar)
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
NOTIFICATIONS_TO = os.environ.get("NOTIFICATIONS_TO", "").strip()

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY


# ────────────────────────────────────────────────────────────────────
# Helpers de branding email (issue #55)
# ────────────────────────────────────────────────────────────────────
# Antes los emails tenian colores Casa Lola hardcoded. Ahora cogen
# los del YAML (landing.colores) con fallback a una paleta neutra,
# para que cada cliente reciba emails con SU marca.

_DEFAULT_PALETA_EMAIL = {
    "accent": "#7A1F1F",      # rojo cabecera
    "accent_soft": "#FAF7F2", # fondo claro
    "border": "#E7DFD2",      # bordes y separadores
    "text": "#2A2118",        # texto principal
    "muted": "#8A7B66",       # texto secundario
}


def _paleta_email() -> dict:
    """
    Devuelve la paleta a usar en los emails al duenno. Cada color cae a
    su default neutro si el YAML no lo define.

    Lee LANDING via _rd.LANDING (acceso por modulo) para que los tests
    puedan monkeypatchear restaurante_data.LANDING y se respete.
    """
    colores = _rd.LANDING.get("colores", {}) or {}
    return {
        "accent": colores.get("accent") or _DEFAULT_PALETA_EMAIL["accent"],
        "accent_soft": colores.get("cream") or _DEFAULT_PALETA_EMAIL["accent_soft"],
        "border": _DEFAULT_PALETA_EMAIL["border"],  # neutro siempre
        "text": colores.get("text") or _DEFAULT_PALETA_EMAIL["text"],
        "muted": _DEFAULT_PALETA_EMAIL["muted"],   # neutro siempre
    }


def _logo_html() -> str:
    """Devuelve el <img> del logo si esta configurado, o cadena vacia."""
    # Igual que _paleta_email: leemos via modulo para que el monkeypatch
    # de tests sobre restaurante_data.EMAILS_CFG funcione.
    url = (_rd.EMAILS_CFG.get("logo_url") or "").strip()
    if not url:
        return ""
    return (
        f'<div style="text-align:center;margin-bottom:24px;">'
        f'<img src="{url}" alt="{RESTAURANTE.get("nombre", "")}" '
        f'style="max-height:48px;max-width:200px;" />'
        f'</div>'
    )


def send_email(
    subject: str,
    html: str,
    to: Optional[str] = None,
    text: Optional[str] = None,
) -> dict:
    """
    Envia un email via Resend.

    Returns:
        dict con {"ok": bool, "id": str | None, "error": str | None}
    """
    if not RESEND_API_KEY:
        return {
            "ok": False,
            "id": None,
            "error": "RESEND_API_KEY no configurada en el .env.",
        }

    destinatario = to or NOTIFICATIONS_TO
    if not destinatario:
        return {
            "ok": False,
            "id": None,
            "error": "No se ha indicado destinatario (NOTIFICATIONS_TO o argumento 'to').",
        }

    try:
        payload = {
            "from": email_from_address(),
            "to": [destinatario],
            "subject": subject,
            "html": html,
        }
        if text:
            payload["text"] = text

        response = resend.Emails.send(payload)
        email_id = response.get("id") if isinstance(response, dict) else None
        return {"ok": True, "id": email_id, "error": None}

    except Exception as e:
        return {"ok": False, "id": None, "error": str(e)}


# ════════════════════════════════════════════════════════════════════
# NOTIFICACION: nueva reserva confirmada
# ════════════════════════════════════════════════════════════════════
def notificar_nueva_reserva(reserva: dict) -> dict:
    """
    Envia un email al dueño cuando se crea una reserva nueva.

    Args:
        reserva: dict con campos de la tabla `reservas`:
                 id, nombre, telefono, fecha, hora, num_personas,
                 alergias, ocasion_especial, notas, canal_origen,
                 created_at.
    """
    nombre = reserva.get("nombre") or "(sin nombre)"
    telefono = reserva.get("telefono") or "(no indicado)"
    fecha = reserva.get("fecha") or "?"
    hora = reserva.get("hora") or "?"
    num_personas = reserva.get("num_personas") or "?"
    alergias = reserva.get("alergias") or "(ninguna indicada)"
    ocasion = reserva.get("ocasion_especial") or "(no)"
    notas = reserva.get("notas") or "(sin notas)"
    canal = reserva.get("canal_origen") or "?"
    created = reserva.get("created_at") or ""

    subject = f"📅 Nueva reserva — {nombre} ({fecha} {hora}, {num_personas}p)"

    p = _paleta_email()
    logo = _logo_html()
    html = f"""
<!doctype html>
<html lang="es">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:24px;background:{p['accent_soft']};color:{p['text']};font-family:Georgia,serif;">
  <div style="max-width:560px;margin:0 auto;background:#FFFFFF;border:1px solid {p['border']};border-radius:12px;padding:32px;">
    {logo}
    <h1 style="margin:0 0 8px 0;font-size:22px;color:{p['accent']};">
      Nueva reserva en {RESTAURANTE['nombre']}
    </h1>
    <p style="margin:0 0 24px 0;color:{p['muted']};font-size:14px;">
      Acaba de entrar una reserva por el canal <strong>{canal}</strong>.
    </p>

    <table style="width:100%;border-collapse:collapse;font-size:15px;">
      <tr><td style="padding:8px 0;color:{p['muted']};width:140px;">Nombre</td>
          <td style="padding:8px 0;color:{p['text']};"><strong>{nombre}</strong></td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};">Telefono</td>
          <td style="padding:8px 0;color:{p['text']};">{telefono}</td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};">Fecha</td>
          <td style="padding:8px 0;color:{p['text']};"><strong>{fecha} a las {hora}</strong></td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};">Comensales</td>
          <td style="padding:8px 0;color:{p['text']};">{num_personas}</td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};">Alergias</td>
          <td style="padding:8px 0;color:{p['text']};">{alergias}</td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};">Ocasion</td>
          <td style="padding:8px 0;color:{p['text']};">{ocasion}</td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};vertical-align:top;">Notas</td>
          <td style="padding:8px 0;color:{p['text']};white-space:pre-wrap;">{notas}</td></tr>
    </table>

    <p style="margin:24px 0 0 0;color:{p['muted']};font-size:12px;border-top:1px solid {p['border']};padding-top:16px;">
      Recibido {created} · {RESTAURANTE['nombre']}
    </p>
  </div>
</body>
</html>
""".strip()

    text_plano = (
        f"Nueva reserva en {RESTAURANTE['nombre']}\n"
        f"---------------------------------------\n"
        f"Canal:     {canal}\n"
        f"Nombre:    {nombre}\n"
        f"Telefono:  {telefono}\n"
        f"Fecha:     {fecha} a las {hora}\n"
        f"Comensales:{num_personas}\n"
        f"Alergias:  {alergias}\n"
        f"Ocasion:   {ocasion}\n"
        f"Notas:     {notas}\n"
        f"\nRecibido: {created}\n"
    )

    return send_email(subject=subject, html=html, text=text_plano)


# ════════════════════════════════════════════════════════════════════
# NOTIFICACION: caso escalado al dueño/encargado
# ════════════════════════════════════════════════════════════════════
MOTIVO_LABELS = {
    "cliente_lo_pide":      "El cliente ha pedido hablar con un humano",
    "queja_o_enfado":       "Cliente molesto o queja",
    "grupo_grande":         "Reserva de grupo grande (11+ personas)",
    "evento_privado":       "Solicitud de evento privado",
    "caso_complejo":        "Caso complejo fuera del ambito del bot",
    "datos_no_capturados":  "No se pudieron capturar datos clave",
    "otro":                 "Otro motivo",
}


def notificar_escalacion(escalacion: dict) -> dict:
    """
    Envia email al dueño cuando el bot escala un caso.

    Args:
        escalacion: dict con id, telefono, motivo, contexto, datos_cliente,
                    vapi_call_id, created_at.
    """
    telefono = escalacion.get("telefono") or "(desconocido)"
    motivo = escalacion.get("motivo") or "otro"
    motivo_legible = MOTIVO_LABELS.get(motivo, motivo)
    contexto = escalacion.get("contexto") or "(sin contexto)"
    fecha = escalacion.get("created_at") or ""
    vapi_call_id = escalacion.get("vapi_call_id") or "-"

    datos = escalacion.get("datos_cliente") or {}
    nombre = datos.get("nombre") or "(no recogido)"
    email_cliente = datos.get("email") or "(no recogido)"

    subject = f"⚠️ Atencion necesaria — {nombre} ({motivo})"

    p = _paleta_email()
    logo = _logo_html()
    html = f"""
<!doctype html>
<html lang="es">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:24px;background:{p['accent_soft']};color:{p['text']};font-family:Georgia,serif;">
  <div style="max-width:580px;margin:0 auto;background:#FFFFFF;border:1px solid {p['border']};border-radius:12px;padding:32px;">
    {logo}
    <div style="display:inline-block;background:#FEE7C7;color:#7A4500;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:600;margin-bottom:12px;">
      ATENCION NECESARIA
    </div>
    <h1 style="margin:0 0 8px 0;font-size:22px;color:{p['accent']};">
      Caso derivado por el bot de {RESTAURANTE['nombre']}
    </h1>
    <p style="margin:0 0 24px 0;color:{p['muted']};font-size:14px;">
      El asistente ha derivado este caso. Conviene contactar al cliente cuanto antes.
    </p>

    <table style="width:100%;border-collapse:collapse;font-size:15px;">
      <tr><td style="padding:8px 0;color:{p['muted']};width:140px;">Motivo</td>
          <td style="padding:8px 0;color:{p['text']};"><strong>{motivo_legible}</strong></td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};vertical-align:top;">Contexto</td>
          <td style="padding:8px 0;color:{p['text']};white-space:pre-wrap;">{contexto}</td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};">Telefono</td>
          <td style="padding:8px 0;color:{p['text']};"><strong>{telefono}</strong></td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};">Nombre</td>
          <td style="padding:8px 0;color:{p['text']};">{nombre}</td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};">Email</td>
          <td style="padding:8px 0;color:{p['text']};">{email_cliente}</td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};">Vapi Call ID</td>
          <td style="padding:8px 0;color:{p['muted']};font-size:11px;font-family:monospace;">{vapi_call_id}</td></tr>
    </table>

    <p style="margin:24px 0 0 0;color:{p['muted']};font-size:12px;border-top:1px solid {p['border']};padding-top:16px;">
      Recibido {fecha} · Bot de {RESTAURANTE['nombre']}
    </p>
  </div>
</body>
</html>
""".strip()

    text_plano = (
        f"Caso derivado por el bot de {RESTAURANTE['nombre']}\n"
        f"--------------------------------------------\n"
        f"Motivo:    {motivo_legible}\n"
        f"Contexto:  {contexto}\n"
        f"Telefono:  {telefono}\n"
        f"Nombre:    {nombre}\n"
        f"Email:     {email_cliente}\n"
        f"Call ID:   {vapi_call_id}\n"
        f"\nRecibido: {fecha}\n"
    )

    return send_email(subject=subject, html=html, text=text_plano)


# ════════════════════════════════════════════════════════════════════
# NOTIFICACION: reserva modificada o cancelada (issue #31)
# ════════════════════════════════════════════════════════════════════

# Campos cuyos cambios SI disparan email. Los demas (updated_at,
# recordatorio_enviado_at, mesas_asignadas, etc) se consideran internos
# y no generan email.
CAMPOS_RELEVANTES_CAMBIO = (
    "fecha",
    "hora",
    "num_personas",
    "estado",
    "alergias",
    "ocasion_especial",
    "notas",
)

# Etiquetas humanas por campo (para el email).
_ETIQUETAS_CAMPO = {
    "fecha": "Fecha",
    "hora": "Hora",
    "num_personas": "Comensales",
    "estado": "Estado",
    "alergias": "Alergias",
    "ocasion_especial": "Ocasion",
    "notas": "Notas",
}


def _diff_reserva(old: dict, new: dict) -> list:
    """
    Calcula cambios entre old y new sobre los campos relevantes.
    Devuelve lista de tuplas (campo, old_val, new_val). Vacia si no
    hay cambios significativos.
    """
    if not old or not new:
        return []
    diff = []
    for campo in CAMPOS_RELEVANTES_CAMBIO:
        ov = old.get(campo)
        nv = new.get(campo)
        # Normalizar None vs "" para no marcar diff espurio
        ov_norm = "" if ov is None else ov
        nv_norm = "" if nv is None else nv
        if ov_norm != nv_norm:
            diff.append((campo, ov, nv))
    return diff


def _es_cancelacion(old: dict, new: dict) -> bool:
    """True si el cambio es una transicion a estado=cancelada."""
    old_estado = (old or {}).get("estado")
    new_estado = (new or {}).get("estado")
    return old_estado != "cancelada" and new_estado == "cancelada"


def notificar_cambio_reserva(old: dict, new: dict) -> dict:
    """
    Envia un email al dueño cuando una reserva CAMBIA (UPDATE) o se
    CANCELA desde cualquier canal. Distingue visual y textualmente entre
    cancelacion y modificacion para que el dueño no confunda un cambio
    con una reserva nueva (issue #31).

    Reglas:
        - Si solo hay cambios en campos internos (updated_at,
          recordatorio_enviado_at, mesas_asignadas), devuelve
          {"ok": True, "id": None, "error": None, "skipped": True}
          sin enviar email.
        - Si hay cancelacion (estado: confirmada -> cancelada), subject
          "Reserva CANCELADA" con cuerpo en rojo.
        - Si hay otro cambio relevante, subject "Reserva MODIFICADA"
          con cuerpo en naranja.

    Args:
        old: estado previo de la fila (viene del webhook Supabase
             como `old_record`).
        new: estado nuevo (viene como `record`).
    """
    diff = _diff_reserva(old, new)
    if not diff:
        return {"ok": True, "id": None, "error": None, "skipped": True}

    nombre = new.get("nombre") or old.get("nombre") or "(sin nombre)"
    fecha_new = new.get("fecha") or "?"
    hora_new = (new.get("hora") or "")[:5] or "?"
    num_new = new.get("num_personas") or "?"
    canal = new.get("canal_origen") or old.get("canal_origen") or "?"
    reserva_id = new.get("id") or old.get("id") or "?"

    cancelacion = _es_cancelacion(old, new)
    if cancelacion:
        tono_color = "#991B1B"  # rojo
        tono_fondo = "#FEF2F2"
        titulo = f"Reserva CANCELADA — {nombre}"
        subject = (
            f"❌ Reserva CANCELADA — {nombre} ({fecha_new} {hora_new}, {num_new}p)"
        )
        intro = (
            f"La reserva de <strong>{nombre}</strong> ha sido "
            f"<strong style='color:{tono_color};'>cancelada</strong> "
            f"por el canal <strong>{canal}</strong>."
        )
        intro_txt = f"La reserva de {nombre} ha sido CANCELADA (canal: {canal})."
    else:
        tono_color = "#B45309"  # naranja
        tono_fondo = "#FFFBEB"
        titulo = f"Reserva MODIFICADA — {nombre}"
        subject = (
            f"✏️ Reserva MODIFICADA — {nombre} ({fecha_new} {hora_new}, {num_new}p)"
        )
        intro = (
            f"La reserva de <strong>{nombre}</strong> ha sido "
            f"<strong style='color:{tono_color};'>modificada</strong> "
            f"por el canal <strong>{canal}</strong>."
        )
        intro_txt = f"La reserva de {nombre} ha sido MODIFICADA (canal: {canal})."

    # Tabla de cambios
    filas_html = []
    for campo, ov, nv in diff:
        etiqueta = _ETIQUETAS_CAMPO.get(campo, campo)
        ov_str = "(vacio)" if ov in (None, "") else str(ov)
        nv_str = "(vacio)" if nv in (None, "") else str(nv)
        filas_html.append(
            f"<tr>"
            f"<td style='padding:8px 0;color:#8A7B66;width:140px;'>{etiqueta}</td>"
            f"<td style='padding:8px 0;color:#991B1B;text-decoration:line-through;'>{ov_str}</td>"
            f"<td style='padding:8px 0;color:#2A2118;padding-left:12px;'>→ <strong>{nv_str}</strong></td>"
            f"</tr>"
        )
    tabla_html = "\n".join(filas_html)

    p = _paleta_email()
    logo = _logo_html()
    html = f"""
<!doctype html>
<html lang="es">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:24px;background:{tono_fondo};color:{p['text']};font-family:Georgia,serif;">
  <div style="max-width:600px;margin:0 auto;background:#FFFFFF;border:2px solid {tono_color};border-radius:12px;padding:32px;">
    {logo}
    <h1 style="margin:0 0 8px 0;font-size:22px;color:{tono_color};">{titulo}</h1>
    <p style="margin:0 0 24px 0;color:{p['muted']};font-size:14px;">{intro}</p>

    <h2 style="margin:0 0 12px 0;font-size:16px;color:{p['text']};">Cambios:</h2>
    <table style="width:100%;border-collapse:collapse;font-size:15px;">
      {tabla_html}
    </table>

    <p style="margin:24px 0 0 0;color:{p['muted']};font-size:12px;border-top:1px solid {p['border']};padding-top:16px;">
      Reserva ID: {reserva_id} · {RESTAURANTE['nombre']}
    </p>
  </div>
</body>
</html>
""".strip()

    lineas_texto = []
    for campo, ov, nv in diff:
        etiqueta = _ETIQUETAS_CAMPO.get(campo, campo)
        ov_str = "(vacio)" if ov in (None, "") else str(ov)
        nv_str = "(vacio)" if nv in (None, "") else str(nv)
        lineas_texto.append(f"  {etiqueta}: {ov_str} -> {nv_str}")
    text_plano = (
        f"{intro_txt}\n"
        f"---------------------------------------\n"
        f"Cambios:\n" + "\n".join(lineas_texto) + "\n"
        f"\nReserva ID: {reserva_id}\n"
    )

    return send_email(subject=subject, html=html, text=text_plano)
