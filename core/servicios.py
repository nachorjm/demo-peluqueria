"""
Helpers para resolver y validar servicios del catalogo YAML.

El catalogo de servicios vive en config/peluqueria.yaml y se carga via
core.peluqueria_data. Este modulo expone helpers para que las tools
puedan validar nombres aportados por el cliente y obtener metadatos
(precio, duracion, especialidad) en runtime.
"""
from typing import Dict, List, Optional

from core.peluqueria_data import (
    SERVICIOS,
    servicio_por_nombre,
    todos_los_servicios,
)


def validar_y_resolver_servicios(nombres_solicitados: List[str]) -> Dict:
    """
    Dada una lista de nombres de servicio que pide el cliente, devuelve
    un dict con:
        - servicios_validos: list[dict] con {nombre, categoria, especialidad,
          duracion_min, precio_eur} resueltos del YAML.
        - nombres_invalidos: list[str] con los que no encontramos.
        - duracion_total_min: int, suma de duraciones.
        - precio_total_eur: float, suma de precios.
        - especialidades_requeridas: list[str] unicas (para asignar
          estilista compatible).

    El match es case-insensitive y por nombre exacto. Si el cliente
    escribe "corte de mujer" pero en YAML es "Corte mujer", no matchea
    y va a `nombres_invalidos`. Las tools deben pedir al cliente que
    elija de la lista exacta antes de llamar aqui.
    """
    if not nombres_solicitados:
        return {
            "servicios_validos": [],
            "nombres_invalidos": [],
            "duracion_total_min": 0,
            "precio_total_eur": 0.0,
            "especialidades_requeridas": [],
        }

    validos: List[Dict] = []
    invalidos: List[str] = []
    especialidades_set = set()

    for raw in nombres_solicitados:
        if not raw:
            continue
        s = servicio_por_nombre(str(raw).strip())
        if not s:
            invalidos.append(str(raw).strip())
            continue
        validos.append({
            "nombre": s["nombre"],
            "categoria": s.get("categoria"),
            "especialidad": s.get("especialidad"),
            "duracion_min": int(s.get("duracion_min", 0)),
            "precio_eur": float(s.get("precio", 0)),
            "descripcion": s.get("descripcion", ""),
        })
        if s.get("especialidad"):
            especialidades_set.add(s["especialidad"])

    duracion_total = sum(v["duracion_min"] for v in validos)
    precio_total = sum(v["precio_eur"] for v in validos)

    return {
        "servicios_validos": validos,
        "nombres_invalidos": invalidos,
        "duracion_total_min": duracion_total,
        "precio_total_eur": round(precio_total, 2),
        "especialidades_requeridas": sorted(especialidades_set),
    }


def listado_breve_servicios() -> str:
    """
    Devuelve un listado plano y muy corto del catalogo, util para que el
    bot lo use como referencia cuando el cliente pida "que servicios teneis"
    sin filtros.

    Formato:
        "Corte mujer (28€, 45min) | Corte hombre (18€, 30min) | ..."
    """
    partes = []
    for s in todos_los_servicios():
        precio = s.get("precio", 0)
        dur = s.get("duracion_min", 0)
        partes.append(f"{s['nombre']} ({precio:.0f}€, {dur}min)")
    return " | ".join(partes)


def categorias_disponibles() -> List[str]:
    """Categorias presentes en el YAML."""
    return list(SERVICIOS.keys())


def servicio_existe(nombre: str) -> bool:
    """True si el nombre matchea un servicio del catalogo (case-insensitive)."""
    return servicio_por_nombre(nombre) is not None
