"""
Router FastAPI del panel de administracion del restaurante.

Endpoints:
  - GET  /admin                              -> sirve el HTML del panel (dashboard).
  - GET  /admin/api/reservas                 -> lista de reservas en un rango JSON.
  - POST /admin/api/reservas/{id}/cancelar   -> cancela una reserva.
  - GET  /admin/api/stats                    -> metricas agregadas para la pestania de estadisticas.

Proteccion: password simple via header X-Admin-Password. Se valida contra
la variable ADMIN_PASSWORD del .env. Es una demo, no sistema de auth real.
"""
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Query
from fastapi.responses import FileResponse, Response

from core.config import supabase
from core.logger import get_logger

log = get_logger(__name__)

router = APIRouter()

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()

# Token para el feed iCal del dueno (issue #58). Se genera UNA vez al
# onboarding y se guarda en Railway como env var. Si esta vacio, el
# endpoint /admin/ical/reservas.ics devuelve 503.
ICAL_FEED_TOKEN = os.environ.get("ICAL_FEED_TOKEN", "").strip()

# Cuantos dias hacia atras incluir en el feed iCal. Permite al dueno
# revisar al dia siguiente las reservas de ayer si las consulta por la
# manana. 1 dia es suficiente para ese caso de uso.
_ICAL_DIAS_PASADOS = 1

# Cuantos dias hacia adelante incluir en el feed iCal. 90 dias = ~3
# meses, suficiente para planificacion media. Limita el tamano del .ics
# si el restaurante acumula muchisimas reservas.
_ICAL_DIAS_FUTUROS = 90

_DASHBOARD_HTML = os.path.join(os.path.dirname(__file__), "dashboard.html")


def _check_password(header_value: Optional[str]) -> None:
    """Valida el password del header. 401 si no coincide."""
    if not ADMIN_PASSWORD:
        # Fallback para desarrollo: si no hay password configurado,
        # dejamos pasar todo. En produccion NO dejar asi.
        return
    if not header_value or header_value != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid admin password")


@router.get("/admin")
async def admin_dashboard():
    """Sirve el HTML del panel. El HTML pide la password al cargar."""
    return FileResponse(_DASHBOARD_HTML, media_type="text/html")


@router.get("/admin/api/reservas")
async def admin_listar_reservas(
    desde: str = Query(..., description="Fecha inicio YYYY-MM-DD"),
    hasta: str = Query(..., description="Fecha fin YYYY-MM-DD"),
    incluir_canceladas: bool = Query(False, description="Si true, incluye canceladas en gris"),
    x_admin_password: Optional[str] = Header(default=None, alias="X-Admin-Password"),
):
    """
    Devuelve reservas en el rango [desde, hasta] en formato FullCalendar.
    Por defecto excluye las canceladas (pasa `incluir_canceladas=true`
    para obtenerlas tambien, en gris).
    """
    _check_password(x_admin_password)

    try:
        q = (
            supabase.table("reservas")
            .select("*")
            .gte("fecha", desde)
            .lte("fecha", hasta)
            .order("fecha", desc=False)
        )
        if not incluir_canceladas:
            q = q.neq("estado", "cancelada")
        res = q.execute()
        filas = res.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    # Resolver nombres de mesas en una sola query (en lugar de N).
    todas_mesas_ids = set()
    for r in filas:
        for mid in (r.get("mesas_asignadas") or []):
            todas_mesas_ids.add(mid)

    nombre_por_mesa = {}
    if todas_mesas_ids:
        try:
            res_mesas = (
                supabase.table("mesas")
                .select("id, nombre")
                .in_("id", list(todas_mesas_ids))
                .execute()
            )
            nombre_por_mesa = {m["id"]: m["nombre"] for m in (res_mesas.data or [])}
        except Exception as e:
            log.warning("No se pudieron resolver nombres de mesas: %s", e)

    # Transformar a formato que FullCalendar entiende
    eventos = []
    for r in filas:
        fecha = r.get("fecha")
        hora = (r.get("hora") or "21:00").split(".")[0]
        if len(hora) == 5:
            hora += ":00"
        inicio_iso = f"{fecha}T{hora}"

        # Hora de fin: usar la real si esta guardada, sino estimar.
        hora_fin_real = (r.get("hora_fin") or "").split(".")[0]
        if hora_fin_real and len(hora_fin_real) >= 5:
            if len(hora_fin_real) == 5:
                hora_fin_real += ":00"
            fin_iso = f"{fecha}T{hora_fin_real}"
        else:
            turno = r.get("turno", "cena")
            hora_h = int(hora[:2])
            fin_h = min(hora_h + (3 if turno == "cena" else 2), 23)
            fin_iso = f"{fecha}T{fin_h:02d}:{hora[3:5]}:00"

        color_por_canal = {
            "web": "#2E86AB",
            "whatsapp": "#1F9650",
            "voz": "#7D3C98",
            "escalacion": "#C0392B",
        }
        color = color_por_canal.get(r.get("canal_origen"), "#6B5E4A")

        if r.get("estado") == "cancelada":
            color = "#9E9E9E"
        elif r.get("estado") == "no_show":
            color = "#D4A24C"  # naranja/oro para llamar la atencion del duenno

        # Resolver nombres de mesas asignadas
        mesa_ids = r.get("mesas_asignadas") or []
        nombres_mesas = sorted(filter(None, (nombre_por_mesa.get(mid) for mid in mesa_ids)))
        mesa_str = "+".join(nombres_mesas) if nombres_mesas else None

        # Anadir mesa al titulo del evento si la hay
        title = f"{r.get('nombre', '?')} ({r.get('num_personas', '?')}p)"
        if mesa_str:
            title += f" · {mesa_str}"

        eventos.append({
            "id": r.get("id"),
            "title": title,
            "start": inicio_iso,
            "end": fin_iso,
            "backgroundColor": color,
            "borderColor": color,
            "extendedProps": {
                "telefono": r.get("telefono"),
                "num_personas": r.get("num_personas"),
                "turno": r.get("turno"),
                "mesa": mesa_str,
                "alergias": r.get("alergias"),
                "ocasion_especial": r.get("ocasion_especial"),
                "notas": r.get("notas"),
                "canal_origen": r.get("canal_origen"),
                "estado": r.get("estado"),
                "created_at": r.get("created_at"),
            },
        })

    return {"reservas": eventos, "total": len(eventos)}


@router.post("/admin/api/reservas/{reserva_id}/cancelar")
async def admin_cancelar_reserva(
    reserva_id: str,
    x_admin_password: Optional[str] = Header(default=None, alias="X-Admin-Password"),
):
    """Cancela una reserva desde el panel y dispara matching de lista de espera."""
    _check_password(x_admin_password)

    try:
        # Leer la reserva ANTES de cancelarla, para tener fecha+turno+hora
        # disponibles para el matching de lista de espera.
        prev = (
            supabase.table("reservas")
            .select("fecha, hora, turno")
            .eq("id", reserva_id)
            .limit(1)
            .execute()
        )
        if not prev.data:
            raise HTTPException(status_code=404, detail="Reserva no encontrada")
        reserva_prev = prev.data[0]

        res = (
            supabase.table("reservas")
            .update({
                "estado": "cancelada",
                "motivo_cancelacion": "cancelada_desde_panel",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", reserva_id)
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="Reserva no encontrada")

        # Disparar matching de lista de espera (issue #6). Best-effort.
        try:
            from core.lista_espera import procesar_cancelacion
            procesar_cancelacion(
                fecha=reserva_prev.get("fecha"),
                turno=reserva_prev.get("turno") or "cena",
                hora_libre=(reserva_prev.get("hora") or "21:00")[:5],
            )
        except Exception as e:
            log.warning("Lista espera matching fallo (admin): %s", e)

        return {"status": "ok", "reserva_id": reserva_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")


# ════════════════════════════════════════════════════════════════════
# Endpoint de estadisticas para el panel admin
# ════════════════════════════════════════════════════════════════════

_DIAS_SEMANA_ES = ["lunes", "martes", "miercoles", "jueves",
                   "viernes", "sabado", "domingo"]


@router.get("/admin/api/stats")
async def admin_stats(
    desde: Optional[str] = Query(None, description="Fecha inicio YYYY-MM-DD (default: -30 dias)"),
    hasta: Optional[str] = Query(None, description="Fecha fin YYYY-MM-DD (default: hoy)"),
    x_admin_password: Optional[str] = Header(default=None, alias="X-Admin-Password"),
):
    """
    Devuelve metricas agregadas de reservas para el dashboard.

    Incluye:
      - KPIs: reservas hoy / esta semana / este mes / comensales mes.
      - Distribucion por canal: web / whatsapp / voz / escalacion.
      - Distribucion por turno y dia semana: matriz para detectar hora pico.
      - Evolucion diaria en el rango: reservas por dia.
      - Tasa de cancelacion.
    """
    _check_password(x_admin_password)

    hoy = date.today()
    if not desde:
        desde = (hoy - timedelta(days=30)).isoformat()
    if not hasta:
        hasta = hoy.isoformat()

    try:
        res = (
            supabase.table("reservas")
            .select("fecha, hora, turno, num_personas, canal_origen, estado, created_at")
            .gte("fecha", desde)
            .lte("fecha", hasta)
            .execute()
        )
        filas = res.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    confirmadas = [r for r in filas if r.get("estado") != "cancelada"]
    canceladas = [r for r in filas if r.get("estado") == "cancelada"]

    # ─── KPIs ──────────────────────────────────────────────────────
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    inicio_mes = hoy.replace(day=1)

    def _en_rango(r, ini, fin):
        f = r.get("fecha")
        return f and ini.isoformat() <= f <= fin.isoformat()

    reservas_hoy = [r for r in confirmadas if r.get("fecha") == hoy.isoformat()]
    reservas_semana = [r for r in confirmadas if _en_rango(r, inicio_semana, hoy + timedelta(days=6 - hoy.weekday()))]
    reservas_mes = [r for r in confirmadas if _en_rango(r, inicio_mes, hoy)]

    kpis = {
        "reservas_hoy": len(reservas_hoy),
        "comensales_hoy": sum(r.get("num_personas", 0) for r in reservas_hoy),
        "reservas_semana": len(reservas_semana),
        "reservas_mes": len(reservas_mes),
        "comensales_mes": sum(r.get("num_personas", 0) for r in reservas_mes),
        "tasa_cancelacion_pct": (
            round(100 * len(canceladas) / max(len(filas), 1), 1)
        ),
    }

    # ─── Por canal ─────────────────────────────────────────────────
    por_canal_counter = defaultdict(int)
    for r in confirmadas:
        por_canal_counter[r.get("canal_origen") or "desconocido"] += 1
    por_canal = [{"canal": k, "total": v} for k, v in por_canal_counter.items()]

    # ─── Por dia de la semana y turno ──────────────────────────────
    por_dia_turno = {d: {"comida": 0, "cena": 0} for d in _DIAS_SEMANA_ES}
    for r in confirmadas:
        try:
            dt = datetime.strptime(r.get("fecha", ""), "%Y-%m-%d").date()
            dia = _DIAS_SEMANA_ES[dt.weekday()]
            turno = r.get("turno", "cena")
            if turno in por_dia_turno[dia]:
                por_dia_turno[dia][turno] += 1
        except (ValueError, TypeError):
            continue
    por_dia_turno_list = [
        {"dia": d, "comida": por_dia_turno[d]["comida"], "cena": por_dia_turno[d]["cena"]}
        for d in _DIAS_SEMANA_ES
    ]

    # ─── Evolucion diaria en el rango ─────────────────────────────
    por_dia_counter = defaultdict(int)
    for r in confirmadas:
        f = r.get("fecha")
        if f:
            por_dia_counter[f] += 1
    por_dia = []
    try:
        d0 = datetime.strptime(desde, "%Y-%m-%d").date()
        d1 = datetime.strptime(hasta, "%Y-%m-%d").date()
        cursor = d0
        while cursor <= d1:
            k = cursor.isoformat()
            por_dia.append({"fecha": k, "total": por_dia_counter.get(k, 0)})
            cursor += timedelta(days=1)
    except ValueError:
        por_dia = [{"fecha": k, "total": v} for k, v in sorted(por_dia_counter.items())]

    return {
        "rango": {"desde": desde, "hasta": hasta},
        "kpis": kpis,
        "por_canal": por_canal,
        "por_dia_turno": por_dia_turno_list,
        "por_dia": por_dia,
        "total_reservas_rango": len(filas),
        "total_confirmadas_rango": len(confirmadas),
    }


# ════════════════════════════════════════════════════════════════════
# Feed iCal para el calendario del duenno (issue #58)
# ════════════════════════════════════════════════════════════════════

@router.get("/admin/ical/reservas.ics")
async def admin_ical_feed(
    token: str = Query(..., description="Token unico del feed (env ICAL_FEED_TOKEN)"),
):
    """
    Devuelve un feed iCal (RFC 5545) con las reservas del restaurante.

    El duenno suscribe esta URL UNA vez en su Google Calendar / Apple
    Calendar / Outlook como "calendario por suscripcion" y a partir de
    ese momento ve sus reservas en el movil sin entrar al panel.

    Refresh real:
      - Apple Calendar: respeta REFRESH-INTERVAL (1h).
      - Google Calendar: refresca cada ~4-12h, no se puede forzar.
      - Outlook: ~3h.

    Auth: token unico via query string. Razon: los clientes de
    calendario no soportan headers custom al suscribirse, asi que el
    standard de la industria es ?token=. El token debe ser largo y no
    adivinable (>=32 chars). Se configura como env var ICAL_FEED_TOKEN.

    Si el token es invalido devolvemos 404 en lugar de 401 para no
    revelar que el endpoint existe (defensa en profundidad).
    """
    if not ICAL_FEED_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Feed iCal no configurado. Define ICAL_FEED_TOKEN en el entorno.",
        )
    if token != ICAL_FEED_TOKEN:
        # 404 deliberado: no revelar que el endpoint existe a quien
        # mete tokens al azar.
        raise HTTPException(status_code=404, detail="Not found")

    hoy = date.today()
    desde = (hoy - timedelta(days=_ICAL_DIAS_PASADOS)).isoformat()
    hasta = (hoy + timedelta(days=_ICAL_DIAS_FUTUROS)).isoformat()

    try:
        res = (
            supabase.table("reservas")
            .select(
                "id, fecha, hora, hora_fin, nombre, num_personas, telefono, "
                "turno, alergias, ocasion_especial, notas, canal_origen, "
                "estado, mesas_asignadas, created_at, updated_at"
            )
            .gte("fecha", desde)
            .lte("fecha", hasta)
            .order("fecha", desc=False)
            .execute()
        )
        reservas = res.data or []
    except Exception as e:
        log.error("[ical] Error leyendo reservas de Supabase: %s", e)
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    # Import tardio para no acoplar admin/webhook.py a core/calendario
    # ni a core/restaurante_data en el modulo. Permite que los tests
    # que no usen ical no carguen el YAML.
    from core.calendario import generar_ics_feed
    from core.restaurante_data import RESTAURANTE

    nombre = RESTAURANTE.get("nombre", "Restaurante")
    direccion = RESTAURANTE.get("direccion", "")

    ics = generar_ics_feed(
        reservas,
        nombre_restaurante=nombre,
        direccion_restaurante=direccion,
    )

    log.info("[ical] Feed servido: %d reservas (%s a %s)", len(reservas), desde, hasta)

    # text/calendar es el MIME oficial. charset=utf-8 explicito porque
    # algunos clientes (Outlook clasico) interpretan latin-1 por defecto.
    # Cache-Control corto para que clients que polean no peguen al DB
    # de mas.
    return Response(
        content=ics,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="reservas.ics"',
            "Cache-Control": "private, max-age=600",  # 10 min
        },
    )


@router.get("/admin/api/ical/info")
async def admin_ical_info(
    request_url_base: Optional[str] = Query(None, description="Base URL para construir el link (ej. https://...)"),
    x_admin_password: Optional[str] = Header(default=None, alias="X-Admin-Password"),
):
    """
    Helper para el panel admin: devuelve el estado del feed iCal y la
    URL completa para suscribirse (con token incluido). El front la
    pinta tras pulsar 'Sincronizar al calendario'.

    NO revela el token a quien no haya pasado el ADMIN_PASSWORD.
    """
    _check_password(x_admin_password)

    if not ICAL_FEED_TOKEN:
        return {
            "configurado": False,
            "mensaje": (
                "Feed iCal no configurado. Pidele al equipo tecnico que defina "
                "ICAL_FEED_TOKEN en las variables de entorno (Railway)."
            ),
            "url": None,
        }

    base = (request_url_base or "").rstrip("/")
    url_relativa = f"/admin/ical/reservas.ics?token={ICAL_FEED_TOKEN}"
    url_completa = f"{base}{url_relativa}" if base else url_relativa

    return {
        "configurado": True,
        "url": url_completa,
        "instrucciones": {
            "google_calendar": (
                "En Google Calendar (web): rueda > Configuracion > Anadir calendario > "
                "Desde URL > pega la URL > Anadir calendario."
            ),
            "apple_calendar": (
                "En iPhone: Ajustes > Calendario > Cuentas > Anadir cuenta > Otra > "
                "Anadir calendario suscrito > pega la URL."
            ),
            "outlook": (
                "En Outlook (web): Calendario > Anadir calendario > Suscribir desde web > "
                "pega la URL > Importar."
            ),
        },
    }
