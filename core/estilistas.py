"""
Disponibilidad de estilistas / barberos.

Modelo: cada estilista solo puede estar en UNA cita a la vez. Una cita
ocupa el rango [hora_inicio, hora_fin] de un estilista concreto. Para
saber si un estilista esta libre, consultamos la tabla `citas` con
estado='confirmada' del mismo estilista_id_yaml en la misma fecha y
miramos solapamientos.

El catalogo de estilistas vive en config/peluqueria.yaml (no en BD).
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from core.config import supabase
from core.logger import get_logger
from core.peluqueria_data import (
    ESTILISTAS,
    estilistas_activos,
    estilistas_para_especialidad,
    estilista_por_id_yaml,
    estilista_por_nombre,
)

log = get_logger(__name__)


# ════════════════════════════════════════════════════════════════════
# Aritmetica de horarios
# ════════════════════════════════════════════════════════════════════

def sumar_minutos(hora_hhmm: str, minutos: int) -> str:
    """'10:30' + 45 -> '11:15'."""
    h, m = hora_hhmm.split(":")[:2]
    base = datetime(2000, 1, 1, int(h), int(m))
    return (base + timedelta(minutes=minutos)).strftime("%H:%M")


def _solapan(a_inicio: str, a_fin: str, b_inicio: str, b_fin: str) -> bool:
    """True si dos rangos horarios HH:MM se solapan (no adyacentes)."""
    return a_inicio < b_fin and b_inicio < a_fin


# ════════════════════════════════════════════════════════════════════
# Citas ocupadas de un estilista en un dia
# ════════════════════════════════════════════════════════════════════

def _citas_confirmadas_de(
    estilista_id_yaml: str,
    fecha: str,
    excluir_cita_id: Optional[str] = None,
) -> List[Dict]:
    """
    Citas confirmadas de un estilista en una fecha. Excluye una cita
    concreta si se pasa `excluir_cita_id` (util para `modificar_cita`).
    """
    try:
        q = (
            supabase.table("citas")
            .select("id, hora_inicio, hora_fin")
            .eq("estilista_id_yaml", estilista_id_yaml)
            .eq("fecha", fecha)
            .eq("estado", "confirmada")
        )
        if excluir_cita_id:
            q = q.neq("id", excluir_cita_id)
        res = q.execute()
        return res.data or []
    except Exception as e:
        log.warning("Error consultando citas estilista %s: %s", estilista_id_yaml, e)
        return []


def esta_disponible(
    estilista_id_yaml: str,
    fecha: str,
    hora_inicio: str,
    hora_fin: str,
    excluir_cita_id: Optional[str] = None,
) -> bool:
    """
    True si el estilista no tiene ninguna cita confirmada que solape
    el rango [hora_inicio, hora_fin] en `fecha`.
    """
    citas = _citas_confirmadas_de(estilista_id_yaml, fecha, excluir_cita_id)
    for c in citas:
        h_ini = (c.get("hora_inicio") or "")[:5]
        h_fin = (c.get("hora_fin") or "")[:5]
        if not h_ini or not h_fin:
            continue
        if _solapan(hora_inicio, hora_fin, h_ini, h_fin):
            return False
    return True


# ════════════════════════════════════════════════════════════════════
# Resolucion de estilistas
# ════════════════════════════════════════════════════════════════════

def resolver_estilista(
    nombre_o_id: Optional[str],
) -> Optional[Dict]:
    """
    Acepta nombre publico ("Mara", "Lucia") o id_yaml ("mara", "lucia")
    y devuelve el dict del estilista, o None si no existe o esta inactivo.
    """
    if not nombre_o_id:
        return None
    txt = str(nombre_o_id).strip()
    e = estilista_por_nombre(txt) or estilista_por_id_yaml(txt)
    if e and e.get("activa", True):
        return e
    return None


def estilistas_compatibles_con_especialidades(
    especialidades_requeridas: List[str],
) -> List[Dict]:
    """
    Estilistas activos que dominan TODAS las especialidades de la lista.
    Si la lista esta vacia, devuelve todos los estilistas activos.
    """
    if not especialidades_requeridas:
        return estilistas_activos()
    candidatos = []
    for e in estilistas_activos():
        especialidades_e = set(e.get("especialidades") or [])
        if all(esp in especialidades_e for esp in especialidades_requeridas):
            candidatos.append(e)
    return candidatos


def buscar_estilista_disponible(
    especialidades_requeridas: List[str],
    fecha: str,
    hora_inicio: str,
    hora_fin: str,
    estilista_preferido: Optional[str] = None,
    excluir_cita_id: Optional[str] = None,
) -> Dict:
    """
    Busca un estilista que (a) sepa hacer las especialidades pedidas y
    (b) este libre en el rango horario.

    Si `estilista_preferido` (nombre o id_yaml) se pasa, intenta primero
    con ese; si no esta libre o no domina las especialidades, devuelve
    `incompatible` o `ocupado` segun aplique.

    Si no hay preferencia, recorre los compatibles en el orden del YAML
    y devuelve el primero libre.

    Returns:
        {"ok": True, "estilista": dict, "razon": "preferido_libre" | "asignado_libre"}
        {"ok": False, "razon": "preferido_no_compatible" | "preferido_ocupado" |
                                "ningun_estilista_compatible" | "todos_ocupados",
         "estilistas_compatibles": [...]}
    """
    compatibles = estilistas_compatibles_con_especialidades(especialidades_requeridas)
    if not compatibles:
        return {
            "ok": False,
            "razon": "ningun_estilista_compatible",
            "mensaje": (
                f"Ningun estilista activo domina la combinacion {especialidades_requeridas}. "
                f"Pasalo al duenno con escalar_a_humano (motivo servicio_no_disponible)."
            ),
            "estilistas_compatibles": [],
        }

    # Si hay preferencia, validar primero esa
    if estilista_preferido:
        pref = resolver_estilista(estilista_preferido)
        if not pref:
            return {
                "ok": False,
                "razon": "preferido_no_existe",
                "mensaje": f"No tenemos a '{estilista_preferido}' en el equipo.",
                "estilistas_compatibles": [c["nombre"] for c in compatibles],
            }
        if pref not in compatibles:
            return {
                "ok": False,
                "razon": "preferido_no_compatible",
                "mensaje": (
                    f"{pref['nombre']} no realiza ese tipo de servicio. "
                    f"Disponibles para esto: "
                    f"{', '.join(c['nombre'] for c in compatibles)}."
                ),
                "estilistas_compatibles": [c["nombre"] for c in compatibles],
            }
        if esta_disponible(pref["id_yaml"], fecha, hora_inicio, hora_fin, excluir_cita_id):
            return {"ok": True, "estilista": pref, "razon": "preferido_libre"}
        return {
            "ok": False,
            "razon": "preferido_ocupado",
            "mensaje": (
                f"{pref['nombre']} ya tiene una cita en ese horario. "
                f"Sugiere otra hora o cambiar de estilista."
            ),
            "estilistas_compatibles": [c["nombre"] for c in compatibles],
        }

    # Sin preferencia: primer compatible libre
    for e in compatibles:
        if esta_disponible(e["id_yaml"], fecha, hora_inicio, hora_fin, excluir_cita_id):
            return {"ok": True, "estilista": e, "razon": "asignado_libre"}

    return {
        "ok": False,
        "razon": "todos_ocupados",
        "mensaje": (
            f"Ningun estilista compatible esta libre en {fecha} a las {hora_inicio}. "
            f"Sugiere otra hora o dia."
        ),
        "estilistas_compatibles": [c["nombre"] for c in compatibles],
    }


# ════════════════════════════════════════════════════════════════════
# Listado legible para prompts y mensajes
# ════════════════════════════════════════════════════════════════════

def equipo_legible() -> str:
    """
    Listado plano del equipo activo: 'Mara (duenna y colorista),
    Lucia (estilista), Diego (barbero)'.
    """
    activos = estilistas_activos()
    partes = []
    for e in activos:
        rol = e.get("rol") or ""
        if rol:
            partes.append(f"{e['nombre']} ({rol.lower()})")
        else:
            partes.append(e["nombre"])
    return ", ".join(partes)
