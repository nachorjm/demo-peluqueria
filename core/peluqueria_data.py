"""Datos de la peluqueria - LOADER del YAML de config.

Todo lo especifico del cliente (Salon Mara o cualquier otra peluqueria)
vive en `config/peluqueria.yaml`. Este modulo lo carga al importar y
expone constantes y helpers para que el resto del codigo no se entere
del formato del YAML.

Para clonar el repo a una nueva peluqueria: editar el YAML, no este
archivo. Ver `config/peluqueria.example.yaml` para la plantilla.

Especialidades validas (vocabulario controlado):
    'corte_mujer', 'corte_hombre', 'corte_nino', 'barba', 'color',
    'mechas', 'peinado', 'brushing', 'novias', 'tratamiento'
"""
import os
import sys
from typing import Dict, List, Optional

import yaml


# ════════════════════════════════════════════════════════════════════
# Carga del YAML al importar
# ════════════════════════════════════════════════════════════════════

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_CONFIG_PATH = os.path.join(_ROOT, "config", "peluqueria.yaml")


def _cargar_config() -> dict:
    """Carga el YAML. Si no existe, aborta: sin config no hay app."""
    if not os.path.exists(_CONFIG_PATH):
        sys.stderr.write(
            f"ERROR: no se encuentra config/peluqueria.yaml en {_CONFIG_PATH}.\n"
            "Copia config/peluqueria.example.yaml y edita los valores.\n"
        )
        sys.exit(1)
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        sys.stderr.write(f"ERROR: config/peluqueria.yaml invalido: {e}\n")
        sys.exit(1)


_CFG = _cargar_config()


# ════════════════════════════════════════════════════════════════════
# Datos basicos del salon
# ════════════════════════════════════════════════════════════════════

SALON: Dict = dict(_CFG.get("salon", {}))

# ────────────────────────────────────────────────────────────────────
# Bloques modulares por canal
# ────────────────────────────────────────────────────────────────────

BOT: Dict = dict(_CFG.get("bot", {}) or {})
LANDING: Dict = dict(_CFG.get("landing", {}) or {})
WIDGET_WEB: Dict = dict(_CFG.get("widget_web", {}) or {})
EMAILS_CFG: Dict = dict(_CFG.get("emails", {}) or {})

# Compat para HTML viejo que ya leia BRANDING (campos planos).
BRANDING: Dict = {
    "colores": LANDING.get("colores", {}),
    "slogan": LANDING.get("slogan", ""),
    "tagline": LANDING.get("tagline", ""),
    "welcome_chat": (
        WIDGET_WEB.get("mensaje_bienvenida")
        or f"Hola, soy el asistente de {SALON.get('nombre', 'el salon')}. ¿En que te ayudo?"
    ),
}

GOOGLE_REVIEW_URL: str = _CFG.get("google_review_url", "") or ""
CORS_ORIGINS_DEFAULT: List[str] = list(_CFG.get("cors_origins", []) or [])


# ────────────────────────────────────────────────────────────────────
# Helpers con defaults graceful
# ────────────────────────────────────────────────────────────────────

def nombre_bot(fallback: str = "asistente") -> str:
    """Nombre del bot del YAML. Si no esta, devuelve 'asistente'."""
    return (BOT.get("nombre") or fallback).strip()


def descripcion_bot(fallback: str = "") -> str:
    """Descripcion 1 linea del bot. Default: 'asistente de <salon>'."""
    desc = BOT.get("descripcion")
    if desc:
        return str(desc).strip()
    nombre_salon = SALON.get("nombre", "el salon")
    return fallback or f"asistente de {nombre_salon}"


def widget_web_config() -> Dict:
    """Config del widget chat con defaults graceful (avatar y colores)."""
    colores_widget = WIDGET_WEB.get("colores", {}) or {}
    colores_landing = LANDING.get("colores", {}) or {}
    return {
        "avatar_emoji": WIDGET_WEB.get("avatar_emoji") or "💬",
        "mensaje_bienvenida": (
            WIDGET_WEB.get("mensaje_bienvenida")
            or f"Hola, soy {nombre_bot()}. ¿En que te ayudo?"
        ),
        "colores": {
            "burbuja_bot": (
                colores_widget.get("burbuja_bot")
                or colores_landing.get("cream")
                or "#F5F5F5"
            ),
            "burbuja_usuario": (
                colores_widget.get("burbuja_usuario")
                or colores_landing.get("accent")
                or "#1976D2"
            ),
            "fondo": (
                colores_widget.get("fondo")
                or "#FFFFFF"
            ),
        },
    }


def landing_config() -> Dict:
    """Config de la landing con defaults graceful."""
    colores = LANDING.get("colores", {}) or {}
    return {
        "colores": colores,
        "slogan": LANDING.get("slogan", "") or "",
        "tagline": LANDING.get("tagline", "") or "",
        "favicon": LANDING.get("favicon", "") or "",
        "og_image": LANDING.get("og_image", "") or "",
        "logo": LANDING.get("logo", "") or "",
    }


def email_from_address() -> str:
    """Remitente de los emails al duenno."""
    yaml_from = (EMAILS_CFG.get("from_address") or "").strip()
    if yaml_from:
        return yaml_from
    env_from = os.environ.get("RESEND_FROM", "").strip()
    if env_from:
        return env_from
    return f"{SALON.get('nombre', 'Peluqueria')} <onboarding@resend.dev>"


def email_logo_url() -> str:
    """URL del logo para incrustar en emails. Vacio = sin logo."""
    return (EMAILS_CFG.get("logo_url") or "").strip()


# ════════════════════════════════════════════════════════════════════
# Politica de antelacion de citas
# ════════════════════════════════════════════════════════════════════

_cit = _CFG.get("citas", {}) or {}
ANTELACION_MINIMA_HORAS: int = int(_cit.get("antelacion_minima_horas", 0) or 0)
ANTELACION_MAXIMA_DIAS: int = int(_cit.get("antelacion_maxima_dias", 0) or 0)


# ════════════════════════════════════════════════════════════════════
# Horarios
# ════════════════════════════════════════════════════════════════════

DIAS_NOMBRE = {
    0: "lunes", 1: "martes", 2: "miercoles", 3: "jueves",
    4: "viernes", 5: "sabado", 6: "domingo",
}
_NOMBRE_A_IDX = {v: k for k, v in DIAS_NOMBRE.items()}


def _parsear_horarios(yaml_horarios: dict) -> dict:
    """Convierte el horario del YAML al dict {0..6 -> [(apertura, cierre), ...]}."""
    resultado = {i: [] for i in range(7)}
    if not yaml_horarios:
        return resultado
    for nombre_dia, turnos in yaml_horarios.items():
        idx = _NOMBRE_A_IDX.get(str(nombre_dia).lower())
        if idx is None:
            continue
        resultado[idx] = [tuple(t) for t in (turnos or []) if len(t) == 2]
    return resultado


HORARIOS: Dict[int, List] = _parsear_horarios(_CFG.get("horarios", {}))


def horario_dia_legible(dia_semana: int) -> str:
    """Devuelve 'martes: 10:00-20:00' o 'lunes: cerrado'."""
    turnos = HORARIOS.get(dia_semana, [])
    nombre = DIAS_NOMBRE.get(dia_semana, "?")
    if not turnos:
        return f"{nombre}: cerrado"
    partes = [f"{a}-{c}" for a, c in turnos]
    return f"{nombre}: " + " y ".join(partes)


def horario_completo_legible() -> str:
    """Devuelve los 7 dias en una sola cadena multilinea."""
    return "\n".join(horario_dia_legible(d) for d in range(7))


# ════════════════════════════════════════════════════════════════════
# Estilistas (barberos / peluqueros)
# ════════════════════════════════════════════════════════════════════

# Lista de dicts: id_yaml, nombre, rol, especialidades (list[str]), activa.
ESTILISTAS: List[Dict] = list(_CFG.get("estilistas", []) or [])


def estilistas_activos() -> List[Dict]:
    """Solo los estilistas con activa=true."""
    return [e for e in ESTILISTAS if e.get("activa", True)]


def estilista_por_nombre(nombre: str) -> Optional[Dict]:
    """Busca un estilista por nombre (case-insensitive). None si no existe."""
    if not nombre:
        return None
    nombre_norm = nombre.strip().lower()
    for e in ESTILISTAS:
        if str(e.get("nombre", "")).strip().lower() == nombre_norm:
            return e
    return None


def estilista_por_id_yaml(id_yaml: str) -> Optional[Dict]:
    """Busca un estilista por su id estable del YAML."""
    if not id_yaml:
        return None
    for e in ESTILISTAS:
        if str(e.get("id_yaml", "")).strip() == id_yaml.strip():
            return e
    return None


def estilistas_para_especialidad(especialidad: str) -> List[Dict]:
    """Devuelve estilistas activos que dominan una especialidad."""
    return [
        e for e in estilistas_activos()
        if especialidad in (e.get("especialidades") or [])
    ]


# ════════════════════════════════════════════════════════════════════
# Catalogo de servicios
# ════════════════════════════════════════════════════════════════════

# Dict {categoria -> [servicio, ...]}. Cada servicio: nombre, precio,
# duracion_min, descripcion, especialidad.
SERVICIOS: Dict[str, List[Dict]] = dict(_CFG.get("servicios", {}) or {})


def todos_los_servicios() -> List[Dict]:
    """Lista plana de todos los servicios, anadiendo la categoria."""
    out = []
    for cat, lista in SERVICIOS.items():
        for s in lista:
            row = dict(s)
            row["categoria"] = cat
            out.append(row)
    return out


def servicio_por_nombre(nombre: str) -> Optional[Dict]:
    """Busca un servicio por nombre (case-insensitive). None si no existe."""
    if not nombre:
        return None
    nombre_norm = nombre.strip().lower()
    for s in todos_los_servicios():
        if str(s.get("nombre", "")).strip().lower() == nombre_norm:
            return s
    return None


def _formatear_servicio(s: dict) -> str:
    """Una linea: '- Nombre (28.00€, 45 min): descripcion.'"""
    precio = s.get("precio", 0)
    dur = s.get("duracion_min", 0)
    return f"- {s['nombre']} ({precio:.2f}€, {dur} min): {s['descripcion']}"


def servicios_legibles(
    categoria: Optional[str] = None,
    especialidad: Optional[str] = None,
) -> str:
    """
    Devuelve el catalogo como texto legible para que Claude lo lea/recorte.

    Args:
        categoria: una de SERVICIOS.keys() o None para todas.
        especialidad: filtra solo servicios de esa especialidad (ej. 'color').

    Returns:
        Texto multilinea con las categorias y servicios pedidos.
    """
    if categoria and categoria not in SERVICIOS:
        categorias_validas = ", ".join(SERVICIOS.keys())
        return (
            f"Categoria '{categoria}' no existe. Categorias validas: "
            f"{categorias_validas}."
        )

    categorias = [categoria] if categoria else list(SERVICIOS.keys())
    bloques = []
    total = 0

    for cat in categorias:
        lista = SERVICIOS[cat]
        if especialidad:
            lista = [s for s in lista if s.get("especialidad") == especialidad]
        if not lista:
            continue
        bloque = [f"\n## {cat.upper()}"]
        for s in lista:
            bloque.append(_formatear_servicio(s))
            total += 1
        bloques.append("\n".join(bloque))

    if total == 0:
        if especialidad:
            return (
                f"No hay servicios de especialidad '{especialidad}' en "
                f"{'la categoria ' + categoria if categoria else 'el catalogo'}."
            )
        return f"No hay servicios en la categoria '{categoria}'."

    cabecera = f"Servicios de {SALON['nombre']}"
    if categoria:
        cabecera += f" — categoria: {categoria}"
    if especialidad:
        cabecera += f" (especialidad: {especialidad})"
    return cabecera + "\n" + "\n".join(bloques)
