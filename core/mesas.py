"""
Modelo de mesas y algoritmo de asignacion (rediseno aforo, issue post #6).

Sustituye el modelo "aforo total = X personas" por mesas fisicas con
capacidad individual. Una reserva ocupa una o varias mesas en un rango
horario; cualquier combinacion de mesas libres sirve si la suma de
capacidades cubre el grupo.

Algoritmo de asignacion:
  1. Buscar mesa simple libre con capacidad >= num_personas. Si hay,
     asignar la mas ajustada (menor capacidad >= N).
  2. Si no, greedy descendente: ordenar mesas libres por capacidad
     descendente y tomar las necesarias hasta sumar >= N.
  3. Si la suma no llega, devolver "lleno".

Duracion por defecto:
  - comida: 105 min (1h45)
  - cena:   120 min (2h)
  - extra arroz: +30 min (si en notas/peticiones aparece "arroz" o "paella")
"""
from datetime import datetime, time as dtime, timedelta
from typing import List, Optional

from core.config import supabase
from core.logger import get_logger

log = get_logger(__name__)


# ════════════════════════════════════════════════════════════════════
# Duracion de la reserva
# ════════════════════════════════════════════════════════════════════

DURACION_MIN_POR_TURNO = {
    "comida": 105,   # 1h45
    "cena":   120,   # 2h
}
EXTRA_MIN_SI_ARROZ = 30


def calcular_hora_fin(hora_inicio: str, turno: str, lleva_arroz: bool = False) -> str:
    """
    Calcula la hora de fin de una reserva.

    Args:
        hora_inicio: 'HH:MM'
        turno: 'comida' | 'cena'
        lleva_arroz: True si la reserva incluye arroz/paella (notas/menciones).

    Returns:
        'HH:MM' de cuando se libera la mesa.
    """
    base = DURACION_MIN_POR_TURNO.get(turno, 120)
    extra = EXTRA_MIN_SI_ARROZ if lleva_arroz else 0
    duracion = base + extra

    h, m = hora_inicio.split(":")[:2]
    inicio = datetime(2000, 1, 1, int(h), int(m))
    fin = inicio + timedelta(minutes=duracion)
    return fin.strftime("%H:%M")


def lleva_arroz(notas: Optional[str], ocasion: Optional[str] = None) -> bool:
    """Heuristica simple: detecta arroz/paella en notas u ocasion."""
    texto = " ".join(filter(None, [notas, ocasion])).lower()
    return any(k in texto for k in ("arroz", "paella", "senyoret", "a banda", "negro"))


# ════════════════════════════════════════════════════════════════════
# Cargar inventario de mesas
# ════════════════════════════════════════════════════════════════════

def cargar_mesas_activas() -> List[dict]:
    """Devuelve todas las mesas activas ordenadas por capacidad ascendente."""
    try:
        res = (
            supabase.table("mesas")
            .select("*")
            .eq("activa", True)
            .order("capacidad", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as e:
        log.warning("Error cargando mesas: %s", e)
        return []


# ════════════════════════════════════════════════════════════════════
# Mesas ocupadas en un rango horario
# ════════════════════════════════════════════════════════════════════

def _solapan(a_inicio: str, a_fin: str, b_inicio: str, b_fin: str) -> bool:
    """True si dos rangos horarios HH:MM se solapan (no adyacentes)."""
    return a_inicio < b_fin and b_inicio < a_fin


def mesas_ocupadas(fecha: str, hora_inicio: str, hora_fin: str,
                   excluir_reserva_id: Optional[str] = None) -> set:
    """
    Devuelve el set de mesa_ids ocupadas en `fecha` que solapan con
    el rango [hora_inicio, hora_fin). Excluye una reserva concreta si
    se pasa (util al modificar una reserva existente).
    """
    try:
        res = (
            supabase.table("reservas")
            .select("id, hora, hora_fin, mesas_asignadas")
            .eq("fecha", fecha)
            .eq("estado", "confirmada")
            .execute()
        )
        ocupadas = set()
        for r in (res.data or []):
            if excluir_reserva_id and r.get("id") == excluir_reserva_id:
                continue
            r_inicio = (r.get("hora") or "00:00")[:5]
            r_fin = (r.get("hora_fin") or "")[:5]
            if not r_fin:
                # Reservas viejas sin hora_fin: asumir 2h por defecto.
                r_fin = calcular_hora_fin(r_inicio, "cena")
            if _solapan(hora_inicio, hora_fin, r_inicio, r_fin):
                for mid in (r.get("mesas_asignadas") or []):
                    ocupadas.add(mid)
        return ocupadas
    except Exception as e:
        log.warning("Error consultando mesas ocupadas: %s", e)
        return set()


# ════════════════════════════════════════════════════════════════════
# Algoritmo de asignacion
# ════════════════════════════════════════════════════════════════════

def asignar_mesas(fecha: str, hora_inicio: str, hora_fin: str,
                  num_personas: int,
                  excluir_reserva_id: Optional[str] = None) -> dict:
    """
    Intenta asignar mesa(s) para `num_personas` en el rango dado.

    `excluir_reserva_id` se usa al modificar una reserva existente: las
    mesas ocupadas por esa misma reserva se consideran libres durante
    la reasignacion (la reserva esta cambiando, no es un duplicado).

    Returns:
        {"ok": True, "mesas": [mesa_dict, ...], "capacidad_total": int}
        o {"ok": False, "razon": "lleno" | "sin_mesas" | ...,
           "mesas_libres_total": int, "capacidad_libre_total": int}
    """
    inventario = cargar_mesas_activas()
    if not inventario:
        return {"ok": False, "razon": "sin_mesas"}

    ocupadas = mesas_ocupadas(fecha, hora_inicio, hora_fin,
                              excluir_reserva_id=excluir_reserva_id)
    libres = [m for m in inventario if m["id"] not in ocupadas]

    if not libres:
        return {"ok": False, "razon": "lleno",
                "mesas_libres_total": 0, "capacidad_libre_total": 0}

    # 1. Buscar mesa simple mas ajustada
    candidatas_simples = sorted(
        [m for m in libres if m["capacidad"] >= num_personas],
        key=lambda m: m["capacidad"],
    )
    if candidatas_simples:
        elegida = candidatas_simples[0]
        return {"ok": True, "mesas": [elegida], "capacidad_total": elegida["capacidad"]}

    # 2. Greedy descendente: tomar las mas grandes hasta cubrir
    libres_desc = sorted(libres, key=lambda m: m["capacidad"], reverse=True)
    elegidas = []
    suma = 0
    for m in libres_desc:
        if suma >= num_personas:
            break
        elegidas.append(m)
        suma += m["capacidad"]

    if suma >= num_personas:
        return {"ok": True, "mesas": elegidas, "capacidad_total": suma}

    # 3. No cabe ni juntando todo
    capacidad_libre_total = sum(m["capacidad"] for m in libres)
    return {
        "ok": False,
        "razon": "lleno",
        "mesas_libres_total": len(libres),
        "capacidad_libre_total": capacidad_libre_total,
    }


# ════════════════════════════════════════════════════════════════════
# Helpers para mostrar
# ════════════════════════════════════════════════════════════════════

def mesas_legibles(mesa_ids: List[str]) -> str:
    """Convierte una lista de IDs de mesa a 'M7+M8' (legible)."""
    if not mesa_ids:
        return ""
    try:
        res = (
            supabase.table("mesas")
            .select("nombre")
            .in_("id", mesa_ids)
            .execute()
        )
        nombres = sorted([m["nombre"] for m in (res.data or [])])
        return "+".join(nombres)
    except Exception:
        return f"({len(mesa_ids)} mesas)"
