"""
Router FastAPI del panel de administracion del salon.

Endpoints:
  - GET  /admin                               -> sirve el HTML del panel.
  - GET  /admin/api/citas                     -> lista de citas en un rango (FullCalendar).
  - POST /admin/api/citas/{id}/cancelar       -> cancela una cita.
  - GET  /admin/api/stats                     -> metricas agregadas.
  - GET  /admin/ical/citas.ics                -> feed iCal (RFC 5545).
  - GET  /admin/api/ical/info                 -> URL del feed iCal.

Proteccion: password simple via header X-Admin-Password. Se valida contra
la variable ADMIN_PASSWORD del .env.
"""
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Query
from fastapi.responses import FileResponse, Response

from core.config import supabase
from core.logger import get_logger
from core.peluqueria_data import estilista_por_id_yaml

log = get_logger(__name__)

router = APIRouter()

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()
ICAL_FEED_TOKEN = os.environ.get("ICAL_FEED_TOKEN", "").strip()

_ICAL_DIAS_PASADOS = 1
_ICAL_DIAS_FUTUROS = 90

_DASHBOARD_HTML = os.path.join(os.path.dirname(__file__), "dashboard.html")


def _check_password(header_value: Optional[str]) -> None:
    """Valida el password del header. 401 si no coincide."""
    if not ADMIN_PASSWORD:
        return
    if not header_value or header_value != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid admin password")


def _cargar_servicios_de_cita(cita_id: str) -> list:
    if not cita_id:
        return []
    try:
        res = (
            supabase.table("cita_servicios")
            .select("*")
            .eq("cita_id", cita_id)
            .order("orden", desc=False)
            .execute()
        )
        return res.data or []
    except Exception:
        return []


@router.get("/admin")
async def admin_dashboard():
    """Sirve el HTML del panel."""
    return FileResponse(_DASHBOARD_HTML, media_type="text/html")


@router.get("/admin/api/citas")
async def admin_listar_citas(
    desde: str = Query(..., description="Fecha inicio YYYY-MM-DD"),
    hasta: str = Query(..., description="Fecha fin YYYY-MM-DD"),
    incluir_canceladas: bool = Query(False, description="Si true, incluye canceladas en gris"),
    x_admin_password: Optional[str] = Header(default=None, alias="X-Admin-Password"),
):
    """Devuelve citas en el rango [desde, hasta] en formato FullCalendar."""
    _check_password(x_admin_password)

    try:
        q = (
            supabase.table("citas")
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

    # Cargar todos los servicios de las citas en una sola query (en lugar de N).
    cita_ids = [r["id"] for r in filas if r.get("id")]
    servicios_por_cita: dict = {}
    if cita_ids:
        try:
            res_serv = (
                supabase.table("cita_servicios")
                .select("cita_id, servicio_nombre, orden")
                .in_("cita_id", cita_ids)
                .order("orden", desc=False)
                .execute()
            )
            for s in (res_serv.data or []):
                servicios_por_cita.setdefault(s["cita_id"], []).append(
                    s.get("servicio_nombre") or "?"
                )
        except Exception as e:
            log.warning("No se pudieron cargar cita_servicios: %s", e)

    eventos = []
    for r in filas:
        fecha = r.get("fecha")
        hora_inicio = (r.get("hora_inicio") or "10:00").split(".")[0]
        if len(hora_inicio) == 5:
            hora_inicio += ":00"
        inicio_iso = f"{fecha}T{hora_inicio}"

        hora_fin_real = (r.get("hora_fin") or "").split(".")[0]
        if hora_fin_real and len(hora_fin_real) >= 5:
            if len(hora_fin_real) == 5:
                hora_fin_real += ":00"
            fin_iso = f"{fecha}T{hora_fin_real}"
        else:
            # Fallback: hora_inicio + 30 min si no hay hora_fin
            try:
                hh = int(hora_inicio[:2])
                mm = int(hora_inicio[3:5])
                base = datetime(2000, 1, 1, hh, mm) + timedelta(minutes=30)
                fin_iso = f"{fecha}T{base.strftime('%H:%M:%S')}"
            except Exception:
                fin_iso = inicio_iso

        color_por_canal = {
            "web": "#2E86AB",
            "whatsapp": "#1F9650",
            "voz": "#7D3C98",
            "escalacion": "#C0392B",
        }
        color = color_por_canal.get(r.get("canal_origen"), "#6B5E4A")
        if r.get("estado") == "cancelada":
            color = "#9E9E9E"

        # Resolver nombre publico del estilista
        est = estilista_por_id_yaml(r.get("estilista_id_yaml") or "")
        estilista_nombre = est["nombre"] if est else (r.get("estilista_id_yaml") or "?")

        servicios_list = servicios_por_cita.get(r.get("id"), [])
        servicios_str = ", ".join(servicios_list) if servicios_list else ""

        title_extra = f" — {servicios_str}" if servicios_str else ""
        title = f"{r.get('nombre', '?')} ({estilista_nombre}){title_extra}"

        eventos.append({
            "id": r.get("id"),
            "title": title,
            "start": inicio_iso,
            "end": fin_iso,
            "backgroundColor": color,
            "borderColor": color,
            "extendedProps": {
                "telefono": r.get("telefono"),
                "estilista": estilista_nombre,
                "estilista_id_yaml": r.get("estilista_id_yaml"),
                "servicios": servicios_list,
                "alergias": r.get("alergias"),
                "notas": r.get("notas"),
                "canal_origen": r.get("canal_origen"),
                "estado": r.get("estado"),
                "created_at": r.get("created_at"),
            },
        })

    return {"citas": eventos, "total": len(eventos)}


@router.post("/admin/api/citas/{cita_id}/cancelar")
async def admin_cancelar_cita(
    cita_id: str,
    x_admin_password: Optional[str] = Header(default=None, alias="X-Admin-Password"),
):
    """Cancela una cita desde el panel."""
    _check_password(x_admin_password)

    try:
        prev = (
            supabase.table("citas")
            .select("fecha, hora_inicio")
            .eq("id", cita_id)
            .limit(1)
            .execute()
        )
        if not prev.data:
            raise HTTPException(status_code=404, detail="Cita no encontrada")

        res = (
            supabase.table("citas")
            .update({
                "estado": "cancelada",
                "motivo_cancelacion": "cancelada_desde_panel",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", cita_id)
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="Cita no encontrada")

        return {"status": "ok", "cita_id": cita_id}
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
    """Devuelve metricas agregadas de citas para el dashboard."""
    _check_password(x_admin_password)

    hoy = date.today()
    if not desde:
        desde = (hoy - timedelta(days=30)).isoformat()
    if not hasta:
        hasta = hoy.isoformat()

    try:
        res = (
            supabase.table("citas")
            .select("id, fecha, hora_inicio, estilista_id_yaml, "
                    "canal_origen, estado, created_at")
            .gte("fecha", desde)
            .lte("fecha", hasta)
            .execute()
        )
        filas = res.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    confirmadas = [r for r in filas if r.get("estado") != "cancelada"]
    canceladas = [r for r in filas if r.get("estado") == "cancelada"]

    # ─── Cargar facturacion estimada (suma cita_servicios.precio_eur) ───
    cita_ids_conf = [r["id"] for r in confirmadas if r.get("id")]
    ingresos_estimados = 0.0
    if cita_ids_conf:
        try:
            res_serv = (
                supabase.table("cita_servicios")
                .select("cita_id, precio_eur")
                .in_("cita_id", cita_ids_conf)
                .execute()
            )
            for s in (res_serv.data or []):
                try:
                    ingresos_estimados += float(s.get("precio_eur") or 0)
                except (TypeError, ValueError):
                    continue
        except Exception as e:
            log.warning("No se pudo calcular ingresos estimados: %s", e)

    # ─── KPIs ──────────────────────────────────────────────────────
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    inicio_mes = hoy.replace(day=1)

    def _en_rango(r, ini, fin):
        f = r.get("fecha")
        return f and ini.isoformat() <= f <= fin.isoformat()

    citas_hoy = [r for r in confirmadas if r.get("fecha") == hoy.isoformat()]
    citas_semana = [r for r in confirmadas if _en_rango(r, inicio_semana, hoy + timedelta(days=6 - hoy.weekday()))]
    citas_mes = [r for r in confirmadas if _en_rango(r, inicio_mes, hoy)]

    kpis = {
        "citas_hoy": len(citas_hoy),
        "citas_semana": len(citas_semana),
        "citas_mes": len(citas_mes),
        "ingresos_estimados_rango_eur": round(ingresos_estimados, 2),
        "tasa_cancelacion_pct": (
            round(100 * len(canceladas) / max(len(filas), 1), 1)
        ),
    }

    # ─── Por canal ─────────────────────────────────────────────────
    por_canal_counter = defaultdict(int)
    for r in confirmadas:
        por_canal_counter[r.get("canal_origen") or "desconocido"] += 1
    por_canal = [{"canal": k, "total": v} for k, v in por_canal_counter.items()]

    # ─── Por estilista ─────────────────────────────────────────────
    por_estilista_counter = defaultdict(int)
    for r in confirmadas:
        id_yaml = r.get("estilista_id_yaml") or "desconocido"
        por_estilista_counter[id_yaml] += 1
    por_estilista = []
    for id_yaml, total in por_estilista_counter.items():
        e = estilista_por_id_yaml(id_yaml)
        por_estilista.append({
            "id_yaml": id_yaml,
            "nombre": e["nombre"] if e else id_yaml,
            "total": total,
        })

    # ─── Por dia de la semana ──────────────────────────────────────
    por_dia_semana = {d: 0 for d in _DIAS_SEMANA_ES}
    for r in confirmadas:
        try:
            dt = datetime.strptime(r.get("fecha", ""), "%Y-%m-%d").date()
            por_dia_semana[_DIAS_SEMANA_ES[dt.weekday()]] += 1
        except (ValueError, TypeError):
            continue
    por_dia_semana_list = [{"dia": d, "total": por_dia_semana[d]} for d in _DIAS_SEMANA_ES]

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
        "por_estilista": por_estilista,
        "por_dia_semana": por_dia_semana_list,
        "por_dia": por_dia,
        "total_citas_rango": len(filas),
        "total_confirmadas_rango": len(confirmadas),
    }


# ════════════════════════════════════════════════════════════════════
# Feed iCal para el calendario del duenno
# ════════════════════════════════════════════════════════════════════

@router.get("/admin/ical/citas.ics")
async def admin_ical_feed(
    token: str = Query(..., description="Token unico del feed (env ICAL_FEED_TOKEN)"),
):
    """Devuelve un feed iCal (RFC 5545) con las citas del salon."""
    if not ICAL_FEED_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Feed iCal no configurado. Define ICAL_FEED_TOKEN en el entorno.",
        )
    if token != ICAL_FEED_TOKEN:
        raise HTTPException(status_code=404, detail="Not found")

    hoy = date.today()
    desde = (hoy - timedelta(days=_ICAL_DIAS_PASADOS)).isoformat()
    hasta = (hoy + timedelta(days=_ICAL_DIAS_FUTUROS)).isoformat()

    try:
        res = (
            supabase.table("citas")
            .select(
                "id, fecha, hora_inicio, hora_fin, nombre, telefono, "
                "estilista_id_yaml, alergias, notas, canal_origen, "
                "estado, created_at, updated_at"
            )
            .gte("fecha", desde)
            .lte("fecha", hasta)
            .order("fecha", desc=False)
            .execute()
        )
        citas = res.data or []
    except Exception as e:
        log.error("[ical] Error leyendo citas de Supabase: %s", e)
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    # Cargar servicios y enriquecer cada cita con `servicios_str`
    cita_ids = [c["id"] for c in citas if c.get("id")]
    servicios_por_cita: dict = {}
    if cita_ids:
        try:
            res_s = (
                supabase.table("cita_servicios")
                .select("cita_id, servicio_nombre, orden")
                .in_("cita_id", cita_ids)
                .order("orden", desc=False)
                .execute()
            )
            for s in (res_s.data or []):
                servicios_por_cita.setdefault(s["cita_id"], []).append(
                    s.get("servicio_nombre") or "?"
                )
        except Exception as e:
            log.warning("[ical] No se pudieron cargar cita_servicios: %s", e)
    for c in citas:
        c["servicios_str"] = ", ".join(servicios_por_cita.get(c.get("id"), []))

    from core.calendario import generar_ics_feed
    from core.peluqueria_data import SALON

    nombre = SALON.get("nombre", "Peluqueria")
    direccion = SALON.get("direccion", "")

    ics = generar_ics_feed(
        citas,
        nombre_salon=nombre,
        direccion_salon=direccion,
        estilista_resolver=estilista_por_id_yaml,
    )

    log.info("[ical] Feed servido: %d citas (%s a %s)", len(citas), desde, hasta)

    return Response(
        content=ics,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="citas.ics"',
            "Cache-Control": "private, max-age=600",
        },
    )


@router.get("/admin/api/ical/info")
async def admin_ical_info(
    request_url_base: Optional[str] = Query(None, description="Base URL para construir el link"),
    x_admin_password: Optional[str] = Header(default=None, alias="X-Admin-Password"),
):
    """Helper para el panel admin: estado del feed iCal y URL completa."""
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
    url_relativa = f"/admin/ical/citas.ics?token={ICAL_FEED_TOKEN}"
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
