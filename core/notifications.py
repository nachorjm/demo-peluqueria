"""
Utilidades de notificacion por email via Resend para Salon Mara.

Se usa para avisar al duenno/encargado cuando ocurren eventos
importantes:
  - Nueva cita creada por cualquier canal (web, whatsapp, voz).
  - Cita modificada o cancelada.
  - Escalacion al humano (queja, servicio no disponible, etc.).

Configuracion:
  - RESEND_API_KEY en .env (obtener en https://resend.com).
  - RESEND_FROM: email del remitente (por defecto el dominio de prueba
    de Resend hasta que verifiquemos el del salon).
  - NOTIFICATIONS_TO: email del duenno que recibe los avisos.
"""
import os
from typing import Optional

import resend

from core import peluqueria_data as _pd
from core.peluqueria_data import (
    SALON,
    email_from_address,
    email_logo_url,
    estilista_por_id_yaml,
)


RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
NOTIFICATIONS_TO = os.environ.get("NOTIFICATIONS_TO", "").strip()

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY


# ────────────────────────────────────────────────────────────────────
# Helpers de branding email
# ────────────────────────────────────────────────────────────────────

_DEFAULT_PALETA_EMAIL = {
    "accent": "#7A1F1F",
    "accent_soft": "#FAF7F2",
    "border": "#E7DFD2",
    "text": "#2A2118",
    "muted": "#8A7B66",
}


def _paleta_email() -> dict:
    """
    Devuelve la paleta a usar en los emails al duenno. Cada color cae a
    su default neutro si el YAML no lo define. Lee LANDING via _pd.LANDING
    para que monkeypatches en tests funcionen.
    """
    colores = _pd.LANDING.get("colores", {}) or {}
    return {
        "accent": colores.get("accent") or _DEFAULT_PALETA_EMAIL["accent"],
        "accent_soft": colores.get("cream") or _DEFAULT_PALETA_EMAIL["accent_soft"],
        "border": _DEFAULT_PALETA_EMAIL["border"],
        "text": colores.get("text") or _DEFAULT_PALETA_EMAIL["text"],
        "muted": _DEFAULT_PALETA_EMAIL["muted"],
    }


def _logo_html() -> str:
    """Devuelve el <img> del logo si esta configurado, o cadena vacia."""
    url = (_pd.EMAILS_CFG.get("logo_url") or "").strip()
    if not url:
        return ""
    return (
        f'<div style="text-align:center;margin-bottom:24px;">'
        f'<img src="{url}" alt="{SALON.get("nombre", "")}" '
        f'style="max-height:48px;max-width:200px;" />'
        f'</div>'
    )


def send_email(
    subject: str,
    html: str,
    to: Optional[str] = None,
    text: Optional[str] = None,
) -> dict:
    """Envia un email via Resend."""
    if not RESEND_API_KEY:
        return {"ok": False, "id": None, "error": "RESEND_API_KEY no configurada en el .env."}

    destinatario = to or NOTIFICATIONS_TO
    if not destinatario:
        return {"ok": False, "id": None, "error": "No se ha indicado destinatario."}

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


# ────────────────────────────────────────────────────────────────────
# Helpers especificos de citas
# ────────────────────────────────────────────────────────────────────

def _nombre_estilista_de_cita(cita: dict) -> str:
    """Resuelve el nombre publico del estilista a partir del id_yaml."""
    e = estilista_por_id_yaml(cita.get("estilista_id_yaml") or "")
    if e:
        return e.get("nombre") or cita.get("estilista_id_yaml") or "?"
    return cita.get("estilista_id_yaml") or "?"


def _servicios_legibles(servicios: list) -> str:
    """Convierte filas de cita_servicios en texto plano: 'Corte mujer, Color raiz'."""
    if not servicios:
        return "(sin servicios)"
    return ", ".join(s.get("servicio_nombre") or "?" for s in servicios)


def _precio_total(servicios: list) -> str:
    """Total en euros de la lista de servicios. Devuelve '38.00€'."""
    total = sum(float(s.get("precio_eur") or 0) for s in servicios)
    return f"{total:.2f}€"


# ════════════════════════════════════════════════════════════════════
# NOTIFICACION: nueva cita confirmada
# ════════════════════════════════════════════════════════════════════

def notificar_nueva_cita(cita: dict, servicios: Optional[list] = None) -> dict:
    """
    Envia un email al duenno cuando se crea una cita nueva.

    Args:
        cita: dict con campos de la tabla `citas`.
        servicios: lista de filas de `cita_servicios` (opcional, si se
                   pasa se incluyen en el cuerpo).
    """
    nombre = cita.get("nombre") or "(sin nombre)"
    telefono = cita.get("telefono") or "(no indicado)"
    fecha = cita.get("fecha") or "?"
    hora_inicio = (cita.get("hora_inicio") or "")[:5] or "?"
    hora_fin = (cita.get("hora_fin") or "")[:5] or "?"
    estilista = _nombre_estilista_de_cita(cita)
    alergias = cita.get("alergias") or "(ninguna indicada)"
    notas = cita.get("notas") or "(sin notas)"
    canal = cita.get("canal_origen") or "?"
    created = cita.get("created_at") or ""

    servicios_txt = _servicios_legibles(servicios or [])
    precio_txt = _precio_total(servicios or [])

    subject = (
        f"📅 Nueva cita — {nombre} ({fecha} {hora_inicio}, {estilista})"
    )

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
      Nueva cita en {SALON['nombre']}
    </h1>
    <p style="margin:0 0 24px 0;color:{p['muted']};font-size:14px;">
      Acaba de entrar una cita por el canal <strong>{canal}</strong>.
    </p>

    <table style="width:100%;border-collapse:collapse;font-size:15px;">
      <tr><td style="padding:8px 0;color:{p['muted']};width:140px;">Cliente</td>
          <td style="padding:8px 0;color:{p['text']};"><strong>{nombre}</strong></td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};">Telefono</td>
          <td style="padding:8px 0;color:{p['text']};">{telefono}</td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};">Fecha</td>
          <td style="padding:8px 0;color:{p['text']};"><strong>{fecha} de {hora_inicio} a {hora_fin}</strong></td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};">Estilista</td>
          <td style="padding:8px 0;color:{p['text']};">{estilista}</td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};">Servicios</td>
          <td style="padding:8px 0;color:{p['text']};">{servicios_txt}</td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};">Total estimado</td>
          <td style="padding:8px 0;color:{p['text']};">{precio_txt}</td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};">Alergias / sensibilidades</td>
          <td style="padding:8px 0;color:{p['text']};">{alergias}</td></tr>
      <tr><td style="padding:8px 0;color:{p['muted']};vertical-align:top;">Notas</td>
          <td style="padding:8px 0;color:{p['text']};white-space:pre-wrap;">{notas}</td></tr>
    </table>

    <p style="margin:24px 0 0 0;color:{p['muted']};font-size:12px;border-top:1px solid {p['border']};padding-top:16px;">
      Recibido {created} · {SALON['nombre']}
    </p>
  </div>
</body>
</html>
""".strip()

    text_plano = (
        f"Nueva cita en {SALON['nombre']}\n"
        f"---------------------------------------\n"
        f"Canal:     {canal}\n"
        f"Cliente:   {nombre}\n"
        f"Telefono:  {telefono}\n"
        f"Fecha:     {fecha} de {hora_inicio} a {hora_fin}\n"
        f"Estilista: {estilista}\n"
        f"Servicios: {servicios_txt}\n"
        f"Total:     {precio_txt}\n"
        f"Alergias:  {alergias}\n"
        f"Notas:     {notas}\n"
        f"\nRecibido: {created}\n"
    )

    return send_email(subject=subject, html=html, text=text_plano)


# ════════════════════════════════════════════════════════════════════
# NOTIFICACION: caso escalado al duenno
# ════════════════════════════════════════════════════════════════════

MOTIVO_LABELS = {
    "cliente_lo_pide":       "El cliente ha pedido hablar con un humano",
    "queja_o_enfado":        "Cliente molesto o queja",
    "servicio_no_disponible":"Pide un servicio que no esta en el catalogo",
    "caso_complejo":         "Caso complejo fuera del ambito del bot",
    "datos_no_capturados":   "No se pudieron capturar datos clave",
    "otro":                  "Otro motivo",
}


def notificar_escalacion(escalacion: dict) -> dict:
    """Envia email al duenno cuando el bot escala un caso."""
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
      Caso derivado por el bot de {SALON['nombre']}
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
      Recibido {fecha} · Bot de {SALON['nombre']}
    </p>
  </div>
</body>
</html>
""".strip()

    text_plano = (
        f"Caso derivado por el bot de {SALON['nombre']}\n"
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
# NOTIFICACION: cita modificada o cancelada
# ════════════════════════════════════════════════════════════════════

CAMPOS_RELEVANTES_CAMBIO = (
    "fecha",
    "hora_inicio",
    "hora_fin",
    "estilista_id_yaml",
    "estado",
    "alergias",
    "notas",
)

_ETIQUETAS_CAMPO = {
    "fecha": "Fecha",
    "hora_inicio": "Hora inicio",
    "hora_fin": "Hora fin",
    "estilista_id_yaml": "Estilista",
    "estado": "Estado",
    "alergias": "Alergias",
    "notas": "Notas",
}


def _diff_cita(old: dict, new: dict) -> list:
    """Cambios entre old y new sobre campos relevantes de citas."""
    if not old or not new:
        return []
    diff = []
    for campo in CAMPOS_RELEVANTES_CAMBIO:
        ov = old.get(campo)
        nv = new.get(campo)
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


def _resolver_estilista_label(id_yaml: Optional[str]) -> str:
    """Convierte un id_yaml en el nombre publico para mostrar."""
    if not id_yaml:
        return "(ninguno)"
    e = estilista_por_id_yaml(id_yaml)
    return e.get("nombre") if e else id_yaml


def notificar_cambio_cita(old: dict, new: dict) -> dict:
    """
    Envia email al duenno cuando una cita cambia (UPDATE) o se cancela.
    Distingue visualmente entre cancelacion (rojo) y modificacion
    (naranja) para no confundir al duenno con una cita nueva.
    """
    diff = _diff_cita(old, new)
    if not diff:
        return {"ok": True, "id": None, "error": None, "skipped": True}

    nombre = new.get("nombre") or old.get("nombre") or "(sin nombre)"
    fecha_new = new.get("fecha") or "?"
    hora_new = (new.get("hora_inicio") or "")[:5] or "?"
    canal = new.get("canal_origen") or old.get("canal_origen") or "?"
    cita_id = new.get("id") or old.get("id") or "?"

    cancelacion = _es_cancelacion(old, new)
    if cancelacion:
        tono_color = "#991B1B"
        tono_fondo = "#FEF2F2"
        titulo = f"Cita CANCELADA — {nombre}"
        subject = f"❌ Cita CANCELADA — {nombre} ({fecha_new} {hora_new})"
        intro = (
            f"La cita de <strong>{nombre}</strong> ha sido "
            f"<strong style='color:{tono_color};'>cancelada</strong> "
            f"por el canal <strong>{canal}</strong>."
        )
        intro_txt = f"La cita de {nombre} ha sido CANCELADA (canal: {canal})."
    else:
        tono_color = "#B45309"
        tono_fondo = "#FFFBEB"
        titulo = f"Cita MODIFICADA — {nombre}"
        subject = f"✏️ Cita MODIFICADA — {nombre} ({fecha_new} {hora_new})"
        intro = (
            f"La cita de <strong>{nombre}</strong> ha sido "
            f"<strong style='color:{tono_color};'>modificada</strong> "
            f"por el canal <strong>{canal}</strong>."
        )
        intro_txt = f"La cita de {nombre} ha sido MODIFICADA (canal: {canal})."

    filas_html = []
    for campo, ov, nv in diff:
        etiqueta = _ETIQUETAS_CAMPO.get(campo, campo)
        if campo == "estilista_id_yaml":
            ov_str = _resolver_estilista_label(ov)
            nv_str = _resolver_estilista_label(nv)
        else:
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
      Cita ID: {cita_id} · {SALON['nombre']}
    </p>
  </div>
</body>
</html>
""".strip()

    lineas_texto = []
    for campo, ov, nv in diff:
        etiqueta = _ETIQUETAS_CAMPO.get(campo, campo)
        if campo == "estilista_id_yaml":
            ov_str = _resolver_estilista_label(ov)
            nv_str = _resolver_estilista_label(nv)
        else:
            ov_str = "(vacio)" if ov in (None, "") else str(ov)
            nv_str = "(vacio)" if nv in (None, "") else str(nv)
        lineas_texto.append(f"  {etiqueta}: {ov_str} -> {nv_str}")
    text_plano = (
        f"{intro_txt}\n"
        f"---------------------------------------\n"
        f"Cambios:\n" + "\n".join(lineas_texto) + "\n"
        f"\nCita ID: {cita_id}\n"
    )

    return send_email(subject=subject, html=html, text=text_plano)
