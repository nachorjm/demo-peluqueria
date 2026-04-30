"""
Generador de feed iCal (RFC 5545) para que el dueno del restaurante
suscriba sus reservas al calendario de su movil (issue #58).

El feed se sirve dinamicamente en /admin/ical/reservas.ics y el dueno
lo anade UNA VEZ a Google Calendar / Apple Calendar / Outlook como
"calendario por suscripcion". A partir de ahi:
- Las reservas nuevas aparecen como eventos automaticamente.
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
from typing import Iterable, Optional


# ════════════════════════════════════════════════════════════════════
# Constantes
# ════════════════════════════════════════════════════════════════════

# VTIMEZONE Europe/Madrid completo. Necesario para que iOS / macOS
# Calendar muestren las horas correctamente con cambio de hora europeo.
# Las reglas son las oficiales de la Union Europea (CEST/CET).
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

# Duracion default de una reserva en minutos cuando no hay hora_fin
# explicita en BD. 90 min es el estandar de la mayoria de restaurantes.
_DURACION_DEFAULT_MIN = 90

# PRODID identifica al generador. RFC pide formato -//Vendor//Product//Lang.
_PRODID = "-//Alnora IA//Demo Restaurante iCal Feed//ES"


# ════════════════════════════════════════════════════════════════════
# Helpers de formato iCal
# ════════════════════════════════════════════════════════════════════

def _escape_text(s: Optional[str]) -> str:
    """
    Escapa caracteres reservados en TEXT segun RFC 5545:
    - Backslash      -> \\\\
    - Coma           -> \\,
    - Punto y coma   -> \\;
    - Newline        -> \\n
    """
    if not s:
        return ""
    out = str(s)
    out = out.replace("\\", "\\\\")
    out = out.replace(",", "\\,")
    out = out.replace(";", "\\;")
    out = out.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return out


def _fold_line(line: str) -> str:
    """
    iCal exige lineas <=75 octetos. Si pasa, hay que partir y empezar
    cada continuacion con un espacio (line folding RFC 5545 sec 3.1).
    Trabajamos en bytes UTF-8 para no romper caracteres multi-byte.
    """
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    pieces = []
    i = 0
    primero = True
    while i < len(raw):
        # Cortar en limite seguro de UTF-8 sin partir code points.
        chunk_size = 75 if primero else 74  # un espacio menos en las continuaciones
        end = min(i + chunk_size, len(raw))
        # Retroceder si caemos en medio de un caracter multibyte
        while end > i and (raw[end - 1] & 0xC0) == 0x80:
            end -= 1
        if end == i:  # sanity guard
            end = min(i + chunk_size, len(raw))
        chunk = raw[i:end].decode("utf-8", errors="replace")
        pieces.append(("" if primero else " ") + chunk)
        i = end
        primero = False
    return "\r\n".join(pieces)


def _fmt_dt_local(d: date, hora_str: str) -> str:
    """
    Formatea fecha + hora a la forma iCal floating-local con TZID:
    YYYYMMDDTHHMMSS (sin Z, porque el TZID se especifica aparte).
    Acepta hora "HH:MM" o "HH:MM:SS".
    """
    h = (hora_str or "21:00").split(".")[0]
    parts = h.split(":")
    hh = int(parts[0]) if parts and parts[0].isdigit() else 21
    mm = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    ss = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    return f"{d.strftime('%Y%m%d')}T{hh:02d}{mm:02d}{ss:02d}"


def _fmt_dt_utc(dt: datetime) -> str:
    """Formato UTC para DTSTAMP, LAST-MODIFIED: YYYYMMDDTHHMMSSZ."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _parsear_fecha(s: Optional[str]) -> Optional[date]:
    """ISO YYYY-MM-DD -> date. None si invalido."""
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _parsear_iso_dt(s: Optional[str]) -> Optional[datetime]:
    """ISO 8601 (con o sin Z, con o sin offset) -> datetime aware."""
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
    """
    Reduce un texto a un slug ASCII apto para usar en el dominio del UID
    (ej: "Casa Lola" -> "casalola"). Solo letras y digitos.
    """
    if not s:
        return "restaurante"
    nfd = unicodedata.normalize("NFD", str(s))
    sin_tildes = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    limpio = re.sub(r"[^a-zA-Z0-9]", "", sin_tildes).lower()
    return limpio or "restaurante"


# ════════════════════════════════════════════════════════════════════
# Generacion del feed
# ════════════════════════════════════════════════════════════════════

def _vevent_de_reserva(
    reserva: dict,
    *,
    location: str,
    uid_dominio: str,
    duracion_default_min: int,
    ahora_utc: datetime,
) -> Optional[str]:
    """
    Construye un VEVENT a partir de una fila de la tabla `reservas`.
    Devuelve None si la reserva no tiene fecha valida.
    """
    fecha = _parsear_fecha(reserva.get("fecha"))
    if fecha is None:
        return None

    hora = reserva.get("hora") or "21:00"
    dtstart_local = _fmt_dt_local(fecha, hora)

    # Hora de fin: usar hora_fin real si existe, si no estimar segun
    # turno o duracion default.
    hora_fin = reserva.get("hora_fin")
    if hora_fin:
        dtend_local = _fmt_dt_local(fecha, hora_fin)
    else:
        # Calcular fin con duracion default. Si pasa de medianoche se
        # corta a 23:59 para no rodar al dia siguiente (caso raro).
        try:
            h_str = (hora or "21:00").split(".")[0]
            partes = h_str.split(":")
            hh = int(partes[0]) if partes else 21
            mm = int(partes[1]) if len(partes) > 1 else 0
            base = datetime(fecha.year, fecha.month, fecha.day, hh, mm)
            fin_dt = base + timedelta(minutes=duracion_default_min)
            if fin_dt.date() != fecha:
                fin_dt = datetime(fecha.year, fecha.month, fecha.day, 23, 59)
            dtend_local = _fmt_dt_local(fecha, f"{fin_dt.hour:02d}:{fin_dt.minute:02d}")
        except (ValueError, TypeError):
            dtend_local = _fmt_dt_local(fecha, "23:00")

    nombre = (reserva.get("nombre") or "Reserva sin nombre").strip()
    num = reserva.get("num_personas") or "?"
    canal = (reserva.get("canal_origen") or "").strip()
    estado = (reserva.get("estado") or "confirmada").lower()

    # Marcas visuales en el SUMMARY: cancelada y no-show son los que
    # mas conviene ver de un vistazo en el calendario del movil.
    if estado == "cancelada":
        summary = f"[CANCELADA] {nombre} ({num}p)"
        ical_status = "CANCELLED"
    elif estado == "no_show":
        summary = f"[NO-SHOW] {nombre} ({num}p)"
        ical_status = "CONFIRMED"
    else:
        summary = f"{nombre} ({num}p)"
        ical_status = "CONFIRMED"

    # DESCRIPTION: bloque completo con todos los datos para que el
    # dueno tenga contexto sin abrir el panel.
    desc_partes = []
    if reserva.get("telefono"):
        desc_partes.append(f"Telefono: {reserva['telefono']}")
    if reserva.get("turno"):
        desc_partes.append(f"Turno: {reserva['turno']}")
    if reserva.get("alergias"):
        desc_partes.append(f"Alergias: {reserva['alergias']}")
    if reserva.get("ocasion_especial"):
        desc_partes.append(f"Ocasion: {reserva['ocasion_especial']}")
    if reserva.get("notas"):
        desc_partes.append(f"Notas: {reserva['notas']}")
    if canal:
        canal_legible = {
            "web": "Chat web",
            "whatsapp": "WhatsApp",
            "voz": "Telefono (Lola)",
            "escalacion": "Escalada al equipo",
        }.get(canal, canal)
        desc_partes.append(f"Canal: {canal_legible}")
    if reserva.get("mesas_asignadas"):
        # Lista de UUIDs; el dueno no los necesita pero deja constancia
        # de cuantas mesas hay agrupadas.
        n_mesas = len(reserva["mesas_asignadas"])
        if n_mesas > 1:
            desc_partes.append(f"Mesas agrupadas: {n_mesas}")
    description = "\\n".join(_escape_text(p) for p in desc_partes)

    # UID estable por reserva: si la reserva se modifica, el evento se
    # actualiza en el calendario del dueno en lugar de duplicarse.
    uid = f"reserva-{reserva.get('id', 'sin-id')}@{uid_dominio}"

    # LAST-MODIFIED: si hay updated_at, lo usamos; si no, created_at;
    # si tampoco, ahora.
    last_mod_dt = (
        _parsear_iso_dt(reserva.get("updated_at"))
        or _parsear_iso_dt(reserva.get("created_at"))
        or ahora_utc
    )

    # SEQUENCE: incremento monotono para que clients respeten el update.
    # Sin tabla de versiones, usamos timestamp UNIX truncado a minutos
    # del updated_at: cada modificacion da un valor mayor al anterior.
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
        # TRANSPARENT: la reserva no marca al dueno como ocupado en otros
        # calendarios si los tiene compartidos; es informativo.
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]
    return "\r\n".join(_fold_line(l) for l in lineas) + "\r\n"


def generar_ics_feed(
    reservas: Iterable[dict],
    *,
    nombre_restaurante: str,
    direccion_restaurante: str,
    duracion_default_min: int = _DURACION_DEFAULT_MIN,
    ahora_utc: Optional[datetime] = None,
) -> str:
    """
    Construye el feed iCal completo (VCALENDAR) a partir de una lista
    de reservas (filas de la tabla `reservas` de Supabase, cada una
    como dict con sus campos).

    Args:
        reservas: iterable de dicts con campos id, fecha, hora, nombre,
            num_personas, telefono, turno, alergias, ocasion_especial,
            notas, canal_origen, estado, mesas_asignadas, hora_fin,
            created_at, updated_at.
        nombre_restaurante: para el X-WR-CALNAME (titulo del calendario
            que ve el dueno en su movil).
        direccion_restaurante: para el campo LOCATION de cada evento.
        duracion_default_min: duracion estimada cuando no hay hora_fin
            en la reserva. Default 90 min.
        ahora_utc: para tests deterministas. Default datetime.now(utc).

    Returns:
        String con el iCal completo, listo para devolver con
        Content-Type text/calendar.
    """
    if ahora_utc is None:
        ahora_utc = datetime.now(timezone.utc)

    uid_dominio = _slug_dominio(nombre_restaurante) + ".alnora.es"
    cal_name = f"Reservas — {nombre_restaurante}"

    cabecera = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{_PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_text(cal_name)}",
        f"X-WR-CALDESC:{_escape_text('Reservas del restaurante en tiempo real.')}",
        "X-WR-TIMEZONE:Europe/Madrid",
        # Refresh hint: 1 hora. Apple Calendar lo respeta; Google ignora
        # y refresca cada ~4-12h.
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    cabecera_str = "\r\n".join(_fold_line(l) for l in cabecera) + "\r\n"

    eventos_str = "".join(
        _vevent_de_reserva(
            r,
            location=direccion_restaurante,
            uid_dominio=uid_dominio,
            duracion_default_min=duracion_default_min,
            ahora_utc=ahora_utc,
        ) or ""
        for r in reservas
    )

    return cabecera_str + _VTIMEZONE_MADRID + eventos_str + "END:VCALENDAR\r\n"
