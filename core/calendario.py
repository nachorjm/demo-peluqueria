"""
Generador de feed iCal (RFC 5545) para que el duenno del salon
suscriba sus citas al calendario de su movil.

El feed se sirve dinamicamente en /admin/ical/citas.ics y el duenno
lo anade UNA VEZ a Google Calendar / Apple Calendar / Outlook como
"calendario por suscripcion". A partir de ahi:
- Las citas nuevas aparecen como eventos automaticamente.
- Las modificaciones se reflejan (mismo UID).
- Las cancelaciones se marcan con STATUS:CANCELLED y desaparecen.

NO requiere OAuth ni credenciales del cliente. Token en query string
(unico por instalacion, generado al onboarding y guardado en env).

Generamos el .ics a mano sin librerias para no anadir deps. iCal es
texto plano con lineas terminadas en CRLF (\r\n) y line folding al
pasar de 75 caracteres. Implementacion siguiendo RFC 5545.
"""
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, List, Optional


# ════════════════════════════════════════════════════════════════════
# Constantes
# ════════════════════════════════════════════════════════════════════

# VTIMEZONE Europe/Madrid completo. Necesario para que iOS / macOS
# Calendar muestren las horas correctamente con cambio de hora europeo.
_VTIMEZONE_MADRID = (
    "BEGIN:VTIMEZONE\r\n"
    "TZID:Europe/Madrid\r\n"
    "BEGIN:DAYLIGHT\r\n"
    "TZOFFSETFROM:+0100\r\n"
    "TZOFFSETTO:+0200\r\n"
    "TZNAME:CEST\r\n"
    "DTSTART:19700329T020000\r\n"
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU\r\n"
    "END:DAYLIGHT\r\n"
    "BEGIN:STANDARD\r\n"
    "TZOFFSETFROM:+0200\r\n"
    "TZOFFSETTO:+0100\r\n"
    "TZNAME:CET\r\n"
    "DTSTART:19701025T030000\r\n"
    "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU\r\n"
    "END:STANDARD\r\n"
    "END:VTIMEZONE\r\n"
)

# Duracion default cuando no hay hora_fin explicita en BD.
# 30 min cubre un corte basico; el resto de servicios siempre traeran
# hora_fin calculada desde la suma de duraciones.
_DURACION_DEFAULT_MIN = 30

_PRODID = "-//Alnora IA//Demo Peluqueria iCal Feed//ES"


# ════════════════════════════════════════════════════════════════════
# Helpers de formato iCal
# ════════════════════════════════════════════════════════════════════

def _escape_text(s: Optional[str]) -> str:
    """Escapa caracteres reservados en TEXT segun RFC 5545."""
    if not s:
        return ""
    out = str(s)
    out = out.replace("\\", "\\\\")
    out = out.replace(",", "\\,")
    out = out.replace(";", "\\;")
    out = out.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return out


def _fold_line(line: str) -> str:
    """iCal exige lineas <=75 octetos. Line folding RFC 5545 sec 3.1."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    pieces = []
    i = 0
    primero = True
    while i < len(raw):
        chunk_size = 75 if primero else 74
        end = min(i + chunk_size, len(raw))
        while end > i and (raw[end - 1] & 0xC0) == 0x80:
            end -= 1
        if end == i:
            end = min(i + chunk_size, len(raw))
        chunk = raw[i:end].decode("utf-8", errors="replace")
        pieces.append(("" if primero else " ") + chunk)
        i = end
        primero = False
    return "\r\n".join(pieces)


def _fmt_dt_local(d: date, hora_str: str) -> str:
    """YYYYMMDDTHHMMSS sin Z (TZID se especifica aparte)."""
    h = (hora_str or "10:00").split(".")[0]
    parts = h.split(":")
    hh = int(parts[0]) if parts and parts[0].isdigit() else 10
    mm = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    ss = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    return f"{d.strftime('%Y%m%d')}T{hh:02d}{mm:02d}{ss:02d}"


def _fmt_dt_utc(dt: datetime) -> str:
    """YYYYMMDDTHHMMSSZ para DTSTAMP / LAST-MODIFIED."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _parsear_fecha(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _parsear_iso_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        v = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _slug_dominio(s: str) -> str:
    """'Salon Mara' -> 'salonmara'. Default 'salon' si vacio."""
    if not s:
        return "salon"
    nfd = unicodedata.normalize("NFD", str(s))
    sin_tildes = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    limpio = re.sub(r"[^a-zA-Z0-9]", "", sin_tildes).lower()
    return limpio or "salon"


# ════════════════════════════════════════════════════════════════════
# Generacion del feed
# ════════════════════════════════════════════════════════════════════

def _vevent_de_cita(
    cita: dict,
    *,
    location: str,
    uid_dominio: str,
    duracion_default_min: int,
    ahora_utc: datetime,
    estilista_resolver=None,
) -> Optional[str]:
    """
    Construye un VEVENT a partir de una fila de la tabla `citas`.
    Devuelve None si la cita no tiene fecha valida.

    Args:
        estilista_resolver: callable opcional que recibe id_yaml y
            devuelve el dict del estilista (para mostrar nombre publico).
            Si None, se muestra el id_yaml tal cual.
    """
    fecha = _parsear_fecha(cita.get("fecha"))
    if fecha is None:
        return None

    hora_inicio = (cita.get("hora_inicio") or "10:00")[:5]
    dtstart_local = _fmt_dt_local(fecha, hora_inicio)

    hora_fin = (cita.get("hora_fin") or "")[:5]
    if hora_fin:
        dtend_local = _fmt_dt_local(fecha, hora_fin)
    else:
        try:
            partes = hora_inicio.split(":")
            hh = int(partes[0]) if partes else 10
            mm = int(partes[1]) if len(partes) > 1 else 0
            base = datetime(fecha.year, fecha.month, fecha.day, hh, mm)
            fin_dt = base + timedelta(minutes=duracion_default_min)
            if fin_dt.date() != fecha:
                fin_dt = datetime(fecha.year, fecha.month, fecha.day, 23, 59)
            dtend_local = _fmt_dt_local(fecha, f"{fin_dt.hour:02d}:{fin_dt.minute:02d}")
        except (ValueError, TypeError):
            dtend_local = _fmt_dt_local(fecha, "23:00")

    nombre = (cita.get("nombre") or "Cita sin nombre").strip()
    canal = (cita.get("canal_origen") or "").strip()
    estado = (cita.get("estado") or "confirmada").lower()

    # Resolver nombre del estilista
    id_yaml = cita.get("estilista_id_yaml") or ""
    estilista_nombre = id_yaml
    if estilista_resolver and id_yaml:
        e = estilista_resolver(id_yaml)
        if e:
            estilista_nombre = e.get("nombre") or id_yaml

    # Servicios: pueden venir embebidos en la cita o no. La capa que
    # llama (admin webhook) los une previamente como "servicios_str".
    servicios_str = cita.get("servicios_str") or cita.get("servicios") or ""
    if isinstance(servicios_str, list):
        servicios_str = ", ".join(str(s) for s in servicios_str if s)

    # SUMMARY: marcas visibles para escanear de un vistazo en el movil
    if estado == "cancelada":
        summary_extra = f" — {servicios_str}" if servicios_str else ""
        summary = f"[CANCELADA] {nombre} ({estilista_nombre}){summary_extra}"
        ical_status = "CANCELLED"
    else:
        summary_extra = f" — {servicios_str}" if servicios_str else ""
        summary = f"{nombre} ({estilista_nombre}){summary_extra}"
        ical_status = "CONFIRMED"

    desc_partes: List[str] = []
    if cita.get("telefono"):
        desc_partes.append(f"Telefono: {cita['telefono']}")
    if estilista_nombre:
        desc_partes.append(f"Estilista: {estilista_nombre}")
    if servicios_str:
        desc_partes.append(f"Servicios: {servicios_str}")
    if cita.get("alergias"):
        desc_partes.append(f"Alergias: {cita['alergias']}")
    if cita.get("notas"):
        desc_partes.append(f"Notas: {cita['notas']}")
    if canal:
        canal_legible = {
            "web": "Chat web",
            "whatsapp": "WhatsApp",
            "voz": "Telefono (Mara)",
            "escalacion": "Escalada al equipo",
        }.get(canal, canal)
        desc_partes.append(f"Canal: {canal_legible}")
    description = "\\n".join(_escape_text(p) for p in desc_partes)

    # UID estable por cita: si la cita se modifica, el evento se
    # actualiza en el calendario en lugar de duplicarse.
    uid = f"cita-{cita.get('id', 'sin-id')}@{uid_dominio}"

    last_mod_dt = (
        _parsear_iso_dt(cita.get("updated_at"))
        or _parsear_iso_dt(cita.get("created_at"))
        or ahora_utc
    )
    sequence = int(last_mod_dt.timestamp() // 60)

    lineas = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_fmt_dt_utc(ahora_utc)}",
        f"LAST-MODIFIED:{_fmt_dt_utc(last_mod_dt)}",
        f"SEQUENCE:{sequence}",
        f"DTSTART;TZID=Europe/Madrid:{dtstart_local}",
        f"DTEND;TZID=Europe/Madrid:{dtend_local}",
        f"SUMMARY:{_escape_text(summary)}",
        f"LOCATION:{_escape_text(location)}",
        f"DESCRIPTION:{description}",
        f"STATUS:{ical_status}",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]
    return "\r\n".join(_fold_line(l) for l in lineas) + "\r\n"


def generar_ics_feed(
    citas: Iterable[dict],
    *,
    nombre_salon: str,
    direccion_salon: str,
    duracion_default_min: int = _DURACION_DEFAULT_MIN,
    ahora_utc: Optional[datetime] = None,
    estilista_resolver=None,
) -> str:
    """
    Construye el feed iCal completo (VCALENDAR) a partir de una lista
    de citas (filas de la tabla `citas` de Supabase).

    Args:
        citas: iterable de dicts con campos id, fecha, hora_inicio,
            hora_fin, nombre, telefono, estilista_id_yaml, alergias,
            notas, canal_origen, estado, servicios_str, created_at,
            updated_at.
        nombre_salon: titulo del calendario que ve el duenno.
        direccion_salon: para LOCATION de cada evento.
        duracion_default_min: cuando no hay hora_fin en BD. Default 30.
        ahora_utc: para tests deterministas.
        estilista_resolver: callable id_yaml -> dict para mostrar nombre
            publico en lugar del id.
    """
    if ahora_utc is None:
        ahora_utc = datetime.now(timezone.utc)

    uid_dominio = _slug_dominio(nombre_salon) + ".alnora.es"
    cal_name = f"Citas — {nombre_salon}"

    cabecera = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{_PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_text(cal_name)}",
        f"X-WR-CALDESC:{_escape_text('Citas del salon en tiempo real.')}",
        "X-WR-TIMEZONE:Europe/Madrid",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    cabecera_str = "\r\n".join(_fold_line(l) for l in cabecera) + "\r\n"

    eventos_str = "".join(
        _vevent_de_cita(
            c,
            location=direccion_salon,
            uid_dominio=uid_dominio,
            duracion_default_min=duracion_default_min,
            ahora_utc=ahora_utc,
            estilista_resolver=estilista_resolver,
        ) or ""
        for c in citas
    )

    return cabecera_str + _VTIMEZONE_MADRID + eventos_str + "END:VCALENDAR\r\n"
