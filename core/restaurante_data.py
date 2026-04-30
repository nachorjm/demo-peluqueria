"""Datos del restaurante — LOADER del YAML de config (issue #11).

Antes este modulo tenia los datos de Casa Lola hardcodeados en Python.
Ahora todo vive en `config/restaurante.yaml` y este modulo simplemente
lo carga al importar y expone las mismas variables de siempre. La API
publica NO cambia: el resto del codigo sigue haciendo
`from core.restaurante_data import RESTAURANTE, CARTA, HORARIOS, ...`
sin tocar nada.

Para clonar el repo a un nuevo restaurante: editar el YAML, no este
archivo. Ver `config/restaurante.example.yaml` para la plantilla.

Alergenos validos (vocabulario controlado):
    'gluten', 'lacteos', 'huevo', 'pescado', 'crustaceos', 'moluscos',
    'frutos_secos', 'soja', 'apio', 'mostaza', 'sesamo', 'sulfitos',
    'altramuces', 'cacahuetes'
"""
import os
import sys
from typing import Dict, List, Optional

import yaml


# ════════════════════════════════════════════════════════════════════
# Carga del YAML al importar
# ════════════════════════════════════════════════════════════════════

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_CONFIG_PATH = os.path.join(_ROOT, "config", "restaurante.yaml")


def _cargar_config() -> dict:
    """Carga el YAML. Si no existe, aborta: sin config no hay app."""
    if not os.path.exists(_CONFIG_PATH):
        sys.stderr.write(
            f"ERROR: no se encuentra config/restaurante.yaml en {_CONFIG_PATH}.\n"
            "Copia config/restaurante.example.yaml y edita los valores.\n"
        )
        sys.exit(1)
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        sys.stderr.write(f"ERROR: config/restaurante.yaml invalido: {e}\n")
        sys.exit(1)


_CFG = _cargar_config()


# ════════════════════════════════════════════════════════════════════
# Datos basicos
# ════════════════════════════════════════════════════════════════════

# Diccionario principal del restaurante (nombre, ciudad, contacto...).
# Toda la logica que mencione al restaurante usa RESTAURANTE['nombre'].
RESTAURANTE: Dict = dict(_CFG.get("restaurante", {}))

# ────────────────────────────────────────────────────────────────────
# Bloques modulares introducidos en issue #55 (branding por canal).
#
# Cada bloque del YAML es OPCIONAL salvo `bot`. Si no esta, se usa
# un dict vacio y el resto del codigo aplica sus defaults. Asi un
# cliente que solo quiere chatbot WA no necesita rellenar `landing`
# ni `widget_web`.
# ────────────────────────────────────────────────────────────────────

# Identidad del bot (nombre, descripcion). Se usa en los prompts de
# los 3 canales (web, WA, voz). Si no hay nombre, los prompts caen
# a "asistente" generico (sin romper).
BOT: Dict = dict(_CFG.get("bot", {}) or {})

# Configuracion de la landing publica (la que sirve GET /). Solo
# relevante si el cliente usa nuestra landing. Cliente con web propia
# y solo widget embebido: este bloque puede estar vacio.
LANDING: Dict = dict(_CFG.get("landing", {}) or {})

# Configuracion del widget chat embebido. Solo relevante si el cliente
# usa el widget (en nuestra landing o embebido en su web).
WIDGET_WEB: Dict = dict(_CFG.get("widget_web", {}) or {})

# Configuracion de los emails al duenno (Resend). Si vacio, hereda
# de las env vars y usa branding default.
EMAILS_CFG: Dict = dict(_CFG.get("emails", {}) or {})

# ────────────────────────────────────────────────────────────────────
# COMPAT: BRANDING legacy
# ────────────────────────────────────────────────────────────────────
# Antes de la reorganizacion modular (issue #55), todo vivia bajo
# `branding:`. Codigo viejo (admin/dashboard.html, /api/restaurante)
# todavia espera `BRANDING['colores']`, `BRANDING['welcome_chat']`,
# etc. Lo recreamos uniendo los nuevos bloques para no romper
# compatibilidad. Codigo nuevo debe leer LANDING / WIDGET_WEB
# directamente.
BRANDING: Dict = {
    **dict(_CFG.get("branding", {}) or {}),  # YAML viejo si alguien lo conserva
    "colores": LANDING.get("colores", {}),
    "slogan": LANDING.get("slogan", ""),
    "tagline": LANDING.get("tagline", ""),
    "welcome_chat": (
        WIDGET_WEB.get("mensaje_bienvenida")
        or f"Hola, soy el asistente de {RESTAURANTE.get('nombre', 'el restaurante')}. ¿En que te ayudo?"
    ),
}

# URL externa para enlace "deja tu resena" en Google. "" si aun no hay.
GOOGLE_REVIEW_URL: str = _CFG.get("google_review_url", "") or ""

# Dominios permitidos por CORS. El backend los lee desde aqui si no
# se fuerza via CORS_ORIGINS env var.
CORS_ORIGINS_DEFAULT: List[str] = list(_CFG.get("cors_origins", []) or [])


# ────────────────────────────────────────────────────────────────────
# Helpers con defaults graceful para lectura externa
# ────────────────────────────────────────────────────────────────────

def nombre_bot(fallback: str = "asistente") -> str:
    """Nombre del bot del YAML. Si no esta, devuelve 'asistente'."""
    return (BOT.get("nombre") or fallback).strip()


def descripcion_bot(fallback: str = "") -> str:
    """
    Descripcion 1 linea del bot. Default: 'asistente de <restaurante>'.
    Util para subtitulos del chat web y prompts.
    """
    desc = BOT.get("descripcion")
    if desc:
        return str(desc).strip()
    nombre_rest = RESTAURANTE.get("nombre", "el restaurante")
    return fallback or f"asistente de {nombre_rest}"


def widget_web_config() -> Dict:
    """
    Devuelve la config del widget chat con defaults graceful (avatar
    y colores). Lo consume /api/restaurante.
    """
    colores_widget = WIDGET_WEB.get("colores", {}) or {}
    colores_landing = LANDING.get("colores", {}) or {}
    return {
        "avatar_emoji": WIDGET_WEB.get("avatar_emoji") or "💬",
        "mensaje_bienvenida": (
            WIDGET_WEB.get("mensaje_bienvenida")
            or f"Hola, soy {nombre_bot()}. ¿En que te ayudo?"
        ),
        "colores": {
            # widget_web > landing > defaults neutros
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
    """
    Devuelve la config de la landing con defaults graceful.
    Lo consume /api/restaurante.
    """
    colores = LANDING.get("colores", {}) or {}
    return {
        "colores": colores,
        "slogan": LANDING.get("slogan", "") or "",
        "tagline": LANDING.get("tagline", "") or "",
        # Imagenes: ""  = el frontend NO inyecta el tag (sin link roto).
        "favicon": LANDING.get("favicon", "") or "",
        "og_image": LANDING.get("og_image", "") or "",
        "logo": LANDING.get("logo", "") or "",
    }


def email_from_address() -> str:
    """
    Remitente de los emails al duenno. Orden de prioridad:
      1. emails.from_address del YAML
      2. env var RESEND_FROM
      3. fallback: '<nombre restaurante> <onboarding@resend.dev>'
    """
    yaml_from = (EMAILS_CFG.get("from_address") or "").strip()
    if yaml_from:
        return yaml_from
    env_from = os.environ.get("RESEND_FROM", "").strip()
    if env_from:
        return env_from
    return f"{RESTAURANTE.get('nombre', 'Restaurante')} <onboarding@resend.dev>"


def email_logo_url() -> str:
    """URL del logo para incrustar en emails. Vacio = sin logo."""
    return (EMAILS_CFG.get("logo_url") or "").strip()


# ════════════════════════════════════════════════════════════════════
# Capacidad y reglas de aforo
# ════════════════════════════════════════════════════════════════════

_cap = _CFG.get("capacidad", {}) or {}
# Aforo total por turno (fallback informativo; disponibilidad real se
# calcula por mesas en core/mesas.py).
AFORO_MAX_POR_TURNO: int = int(_cap.get("aforo_max_por_turno", 50))
# A partir de N comensales, NO se reserva directamente: se escala al
# duenno con motivo "grupo_grande".
GRUPO_GRANDE_DESDE: int = int(_cap.get("grupo_grande_desde", 12))


# ════════════════════════════════════════════════════════════════════
# Politica de antelacion de reservas (issue #65)
# ════════════════════════════════════════════════════════════════════

_res = _CFG.get("reservas", {}) or {}
# Antelacion MINIMA en horas para hacer una reserva. 0 = sin minimo.
# Ejemplo: si vale 2, una reserva para dentro de 30 minutos es rechazada.
ANTELACION_MINIMA_HORAS: int = int(_res.get("antelacion_minima_horas", 0) or 0)
# Antelacion MAXIMA en dias para hacer una reserva. 0 = sin maximo.
# Ejemplo: si vale 90, una reserva para dentro de 200 dias es rechazada.
ANTELACION_MAXIMA_DIAS: int = int(_res.get("antelacion_maxima_dias", 0) or 0)


# ════════════════════════════════════════════════════════════════════
# Horarios
# ════════════════════════════════════════════════════════════════════

DIAS_NOMBRE = {
    0: "lunes", 1: "martes", 2: "miercoles", 3: "jueves",
    4: "viernes", 5: "sabado", 6: "domingo",
}
_NOMBRE_A_IDX = {v: k for k, v in DIAS_NOMBRE.items()}


def _parsear_horarios(yaml_horarios: dict) -> dict:
    """
    Convierte el horario del YAML (keys "lunes"... "domingo") al
    diccionario {0..6 -> [(apertura, cierre), ...]} que usa el resto
    del codigo (compat con la API previa).
    """
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
    """Devuelve string tipo 'martes: 13:30-16:00 y 20:30-23:30' o 'cerrado'."""
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
# Carta
# ════════════════════════════════════════════════════════════════════

# Cada plato: nombre, precio (eur), descripcion, alergenos, vegetariano.
# Algunos arroces tienen min_personas y tiempo_min.
CARTA: Dict[str, List[Dict]] = dict(_CFG.get("carta", {}) or {})


# ─── Filtros de alergenos ─────────────────────────────────────────
def _es_sin_gluten(plato: dict) -> bool:
    return "gluten" not in plato.get("alergenos", [])

def _es_sin_lactosa(plato: dict) -> bool:
    return "lacteos" not in plato.get("alergenos", [])

def _es_vegetariano(plato: dict) -> bool:
    return plato.get("vegetariano", False)

def _es_vegano(plato: dict) -> bool:
    return (
        plato.get("vegetariano", False)
        and not any(a in plato.get("alergenos", []) for a in ("lacteos", "huevo"))
    )

FILTROS_ALERGENO = {
    "sin_gluten": _es_sin_gluten,
    "sin_lactosa": _es_sin_lactosa,
    "vegetariano": _es_vegetariano,
    "vegano": _es_vegano,
}


# ─── Helpers de renderizado de carta ──────────────────────────────
def _formatear_plato(plato: dict) -> str:
    """Una linea: '- Nombre (12.00€): descripcion. [alergenos: gluten, huevo]'."""
    base = f"- {plato['nombre']} ({plato['precio']:.2f}€): {plato['descripcion']}"
    alergenos = plato.get("alergenos", [])
    if alergenos:
        base += f" [alergenos: {', '.join(alergenos)}]"
    return base


def carta_legible(
    categoria: Optional[str] = None,
    filtro_alergeno: Optional[str] = None,
) -> str:
    """
    Devuelve la carta como texto legible para que Claude la lea/recorte.

    Args:
        categoria: una de CARTA.keys() o None para todas.
        filtro_alergeno: clave de FILTROS_ALERGENO o None.

    Returns:
        Texto multilinea con las categorias y platos pedidos.
        Si no hay platos que cumplan el filtro, devuelve mensaje claro.
    """
    if categoria and categoria not in CARTA:
        categorias_validas = ", ".join(CARTA.keys())
        return (
            f"Categoria '{categoria}' no existe. Categorias validas: "
            f"{categorias_validas}."
        )

    filtro_fn = FILTROS_ALERGENO.get(filtro_alergeno) if filtro_alergeno else None
    if filtro_alergeno and not filtro_fn:
        filtros_validos = ", ".join(FILTROS_ALERGENO.keys())
        return (
            f"Filtro '{filtro_alergeno}' no existe. Filtros validos: "
            f"{filtros_validos}."
        )

    categorias = [categoria] if categoria else list(CARTA.keys())
    bloques = []
    total_platos = 0

    for cat in categorias:
        platos = CARTA[cat]
        if filtro_fn:
            platos = [p for p in platos if filtro_fn(p)]
        if not platos:
            continue
        bloque = [f"\n## {cat.upper()}"]
        for p in platos:
            bloque.append(_formatear_plato(p))
            total_platos += 1
        bloques.append("\n".join(bloque))

    if total_platos == 0:
        return (
            f"No hay platos que cumplan el filtro '{filtro_alergeno}' en "
            f"{'la categoria ' + categoria if categoria else 'la carta'}."
        )

    cabecera = f"Carta de {RESTAURANTE['nombre']}"
    if categoria:
        cabecera += f" — categoria: {categoria}"
    if filtro_alergeno:
        cabecera += f" (filtro: {filtro_alergeno})"
    return cabecera + "\n" + "\n".join(bloques)
