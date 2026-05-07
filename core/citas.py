"""
Logica compartida de citas entre los 3 canales (web, whatsapp, voz).

Centralizamos aqui:
  - consultar_disponibilidad: comprueba si hay estilista libre para
    una franja con los servicios pedidos.
  - agendar_cita: crea cita + cita_servicios + mirror cliente.
  - modificar_cita: UPDATE in-place de una cita.
  - buscar_citas: lista citas del cliente para los flujos cancelar/modificar.
  - cancelar_cita: marca como cancelada con verificacion de identidad.
  - historial_cliente_resumen: contexto del cliente para personalizar saludo.

Cada canal tiene su modulo `tools.py` que llama a estas funciones con
su propio `canal_origen`. Asi cualquier mejora a la logica afecta a
los 3 canales por igual.
"""
import unicodedata
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Dict, List, Optional

from core.config import supabase
from core.clientes import upsert_cliente
from core.logger import get_logger
from core.memory import _normalizar_telefono
from core.peluqueria_data import (
    ANTELACION_MAXIMA_DIAS,
    ANTELACION_MINIMA_HORAS,
    HORARIOS,
    horario_dia_legible,
)
from core.servicios import validar_y_resolver_servicios
from core.estilistas import (
    buscar_estilista_disponible,
    estilista_por_id_yaml,
    sumar_minutos,
)

log = get_logger(__name__)


# ════════════════════════════════════════════════════════════════════
# Helpers de validacion de fecha/hora
# ════════════════════════════════════════════════════════════════════

def _parsear_fecha(fecha_str: str) -> Optional[datetime]:
    """Acepta 'YYYY-MM-DD'. Devuelve datetime o None si invalido."""
    try:
        return datetime.strptime(fecha_str.strip(), "%Y-%m-%d")
    except (ValueError, AttributeError):
        return None


def _parsear_hora(hora_str: str) -> Optional[dtime]:
    """Acepta 'HH:MM'. Devuelve time o None si invalido."""
    try:
        return datetime.strptime(hora_str.strip(), "%H:%M").time()
    except (ValueError, AttributeError):
        return None


def _en_horario(hora_inicio: dtime, hora_fin: dtime, dia_semana: int) -> bool:
    """
    True si TODO el rango [hora_inicio, hora_fin] cae dentro de algun
    turno del dia. Si el dia no tiene turnos, falso.
    """
    turnos = HORARIOS.get(dia_semana, [])
    if not turnos:
        return False
    for apertura, cierre in turnos:
        a = _parsear_hora(apertura)
        c = _parsear_hora(cierre)
        if not a or not c:
            continue
        if a <= hora_inicio and hora_fin <= c:
            return True
    return False


def _validar_franja(fecha_str: str, hora_inicio_str: str, duracion_min: int) -> Dict:
    """
    Valida fecha + hora_inicio + duracion. Calcula hora_fin y comprueba
    que la franja entera caiga dentro de horario.

    Returns:
        {"ok": True, "fecha": iso, "hora_inicio": "HH:MM", "hora_fin":
         "HH:MM", "dia_semana": int}
        o {"ok": False, "mensaje": "..."}
    """
    fecha = _parsear_fecha(fecha_str)
    if not fecha:
        return {"ok": False, "mensaje": f"Fecha invalida '{fecha_str}'. Formato esperado: YYYY-MM-DD."}

    hora_inicio = _parsear_hora(hora_inicio_str)
    if not hora_inicio:
        return {"ok": False, "mensaje": f"Hora invalida '{hora_inicio_str}'. Formato esperado: HH:MM."}

    if duracion_min <= 0:
        return {"ok": False, "mensaje": "La duracion total de los servicios debe ser positiva."}

    ahora = datetime.now()
    fecha_hora_completa = datetime.combine(fecha.date(), hora_inicio)
    if fecha_hora_completa < ahora:
        return {"ok": False, "mensaje": f"La fecha y hora ({fecha_str} {hora_inicio_str}) ya han pasado."}

    if ANTELACION_MINIMA_HORAS > 0:
        margen_minimo = ahora + timedelta(hours=ANTELACION_MINIMA_HORAS)
        if fecha_hora_completa < margen_minimo:
            return {
                "ok": False,
                "mensaje": (
                    f"Necesitamos al menos {ANTELACION_MINIMA_HORAS}h de "
                    f"antelacion para preparar producto si hace falta. La "
                    f"hora mas cercana posible seria "
                    f"{margen_minimo.strftime('%H:%M')} del "
                    f"{margen_minimo.date().isoformat()}."
                ),
                "tipo": "antelacion_minima",
            }

    if ANTELACION_MAXIMA_DIAS > 0:
        limite_maximo = (ahora + timedelta(days=ANTELACION_MAXIMA_DIAS)).date()
        if fecha.date() > limite_maximo:
            return {
                "ok": False,
                "mensaje": (
                    f"Aceptamos citas hasta {ANTELACION_MAXIMA_DIAS} dias "
                    f"por delante. La fecha mas lejana posible seria "
                    f"{limite_maximo.isoformat()}."
                ),
                "tipo": "antelacion_maxima",
            }

    dia_semana = fecha.weekday()
    hora_fin_str = sumar_minutos(hora_inicio.strftime("%H:%M"), duracion_min)
    hora_fin = _parsear_hora(hora_fin_str)
    if not hora_fin or not _en_horario(hora_inicio, hora_fin, dia_semana):
        return {
            "ok": False,
            "mensaje": (
                f"A esa hora la peluqueria esta cerrada o no cabe la "
                f"duracion completa ({duracion_min} min). Horario de ese "
                f"dia: {horario_dia_legible(dia_semana)}."
            ),
        }

    return {
        "ok": True,
        "fecha": fecha.date().isoformat(),
        "hora_inicio": hora_inicio.strftime("%H:%M"),
        "hora_fin": hora_fin_str,
        "dia_semana": dia_semana,
    }


# ════════════════════════════════════════════════════════════════════
# Helpers de servicios <-> BD
# ════════════════════════════════════════════════════════════════════

def _insertar_cita_servicios(cita_id: str, servicios_validos: List[Dict]) -> None:
    """Inserta filas en cita_servicios para cada servicio resuelto."""
    filas = []
    for i, s in enumerate(servicios_validos, start=1):
        filas.append({
            "cita_id": cita_id,
            "servicio_nombre": s["nombre"],
            "categoria": s.get("categoria"),
            "especialidad": s.get("especialidad"),
            "duracion_min": s["duracion_min"],
            "precio_eur": s["precio_eur"],
            "orden": i,
        })
    if filas:
        supabase.table("cita_servicios").insert(filas).execute()


def _cargar_servicios_de_cita(cita_id: str) -> List[Dict]:
    """Devuelve los servicios asociados a una cita ordenados."""
    try:
        res = (
            supabase.table("cita_servicios")
            .select("*")
            .eq("cita_id", cita_id)
            .order("orden", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as e:
        log.warning("Error cargando cita_servicios %s: %s", cita_id, e)
        return []


# ════════════════════════════════════════════════════════════════════
# 1. consultar_disponibilidad
# ════════════════════════════════════════════════════════════════════

def consultar_disponibilidad(
    fecha: str,
    hora_inicio: str,
    servicios: List[str],
    estilista_preferido: Optional[str] = None,
) -> Dict:
    """
    ¿Hay un estilista compatible y libre para los servicios pedidos en
    (fecha, hora_inicio)?

    Args:
        fecha: 'YYYY-MM-DD'
        hora_inicio: 'HH:MM'
        servicios: lista de nombres del catalogo (ej. ["Corte mujer"]).
        estilista_preferido: nombre o id_yaml. Opcional.

    Returns dict con `status`:
        - 'disponible': hay estilista libre. Incluye estilista_id_yaml,
          estilista_nombre, hora_fin, duracion_total_min, precio_total_eur.
        - 'servicios_invalidos': los nombres no matchean el catalogo.
        - 'fuera_de_horario': la franja completa no cabe en horario.
        - 'estilista_no_compatible' / 'estilista_ocupado' /
          'todos_ocupados': segun el caso.
        - 'error': error generico.
    """
    if not servicios:
        return {
            "status": "error",
            "mensaje": "Necesito saber que servicio quieres antes de comprobar disponibilidad.",
        }

    resol = validar_y_resolver_servicios(servicios)
    if resol["nombres_invalidos"]:
        return {
            "status": "servicios_invalidos",
            "mensaje": (
                f"No reconozco estos servicios: {resol['nombres_invalidos']}. "
                f"Dile al cliente la lista exacta del catalogo y vuelve a "
                f"intentarlo cuando elija."
            ),
            "nombres_invalidos": resol["nombres_invalidos"],
        }
    if not resol["servicios_validos"]:
        return {
            "status": "error",
            "mensaje": "No he podido resolver ningun servicio del catalogo.",
        }

    val = _validar_franja(fecha, hora_inicio, resol["duracion_total_min"])
    if not val["ok"]:
        return {
            "status": "fuera_de_horario",
            "mensaje": val["mensaje"],
        }

    busqueda = buscar_estilista_disponible(
        especialidades_requeridas=resol["especialidades_requeridas"],
        fecha=val["fecha"],
        hora_inicio=val["hora_inicio"],
        hora_fin=val["hora_fin"],
        estilista_preferido=estilista_preferido,
    )

    if not busqueda.get("ok"):
        return {
            "status": busqueda.get("razon", "no_disponible"),
            "mensaje": busqueda.get("mensaje", "No hay disponibilidad."),
            "estilistas_compatibles": busqueda.get("estilistas_compatibles", []),
        }

    e = busqueda["estilista"]
    return {
        "status": "disponible",
        "fecha": val["fecha"],
        "hora_inicio": val["hora_inicio"],
        "hora_fin": val["hora_fin"],
        "estilista_id_yaml": e["id_yaml"],
        "estilista_nombre": e["nombre"],
        "duracion_total_min": resol["duracion_total_min"],
        "precio_total_eur": resol["precio_total_eur"],
        "asignacion": busqueda.get("razon"),
        "mensaje": (
            f"Hay hueco con {e['nombre']} el {val['fecha']} de {val['hora_inicio']} "
            f"a {val['hora_fin']} para {[s['nombre'] for s in resol['servicios_validos']]}. "
            f"Total: {resol['precio_total_eur']:.2f}€."
        ),
    }


# ════════════════════════════════════════════════════════════════════
# 2. agendar_cita
# ════════════════════════════════════════════════════════════════════

def agendar_cita(
    input_data: Dict,
    telefono_canal: Optional[str] = None,
    canal_origen: str = "web",
) -> Dict:
    """
    Crea una cita.

    Args en input_data:
        nombre, telefono, fecha (YYYY-MM-DD), hora_inicio (HH:MM),
        servicios (list[str], nombres del catalogo),
        estilista_preferido (opt, nombre o id_yaml),
        alergias (opt), notas (opt).

    `telefono_canal` se usa si input_data no trae telefono explicito.
    """
    nombre = (input_data.get("nombre") or "").strip()
    telefono_input = (input_data.get("telefono") or "").strip()
    telefono = _normalizar_telefono(telefono_input or telefono_canal or "")
    fecha_str = (input_data.get("fecha") or "").strip()
    hora_inicio_str = (input_data.get("hora_inicio") or "").strip()
    servicios_in = input_data.get("servicios") or []
    estilista_preferido = (input_data.get("estilista_preferido") or "").strip() or None
    alergias = (input_data.get("alergias") or "").strip() or None
    notas = (input_data.get("notas") or "").strip() or None

    if not nombre:
        return {"status": "error", "mensaje": "Falta el nombre del cliente."}
    if not telefono:
        return {"status": "error", "mensaje": "Falta el telefono del cliente."}
    if not isinstance(servicios_in, list) or not servicios_in:
        return {
            "status": "error",
            "mensaje": "Falta la lista de servicios. Pasa una lista de nombres del catalogo.",
        }

    resol = validar_y_resolver_servicios(servicios_in)
    if resol["nombres_invalidos"]:
        return {
            "status": "servicios_invalidos",
            "mensaje": (
                f"Servicios no reconocidos: {resol['nombres_invalidos']}. "
                f"Pide al cliente la lista exacta y reintenta."
            ),
            "nombres_invalidos": resol["nombres_invalidos"],
        }
    if not resol["servicios_validos"]:
        return {"status": "error", "mensaje": "Lista de servicios vacia tras validacion."}

    val = _validar_franja(fecha_str, hora_inicio_str, resol["duracion_total_min"])
    if not val["ok"]:
        return {"status": "error", "mensaje": val["mensaje"]}

    busqueda = buscar_estilista_disponible(
        especialidades_requeridas=resol["especialidades_requeridas"],
        fecha=val["fecha"],
        hora_inicio=val["hora_inicio"],
        hora_fin=val["hora_fin"],
        estilista_preferido=estilista_preferido,
    )
    if not busqueda.get("ok"):
        return {
            "status": busqueda.get("razon", "no_disponible"),
            "mensaje": busqueda.get("mensaje", "No hay disponibilidad."),
            "estilistas_compatibles": busqueda.get("estilistas_compatibles", []),
        }
    estilista = busqueda["estilista"]

    try:
        # Mirror cliente primero (para tener cliente_id al insertar la cita)
        res_cli = upsert_cliente(
            telefono=telefono,
            nombre=nombre,
            canal_origen=canal_origen,
            alergias=alergias,
        )
        cliente_id = res_cli.get("id")

        # Anti-duplicado suave: misma cita (telefono + fecha + hora_inicio +
        # estilista + estado=confirmada). Si existe, actualizamos solo
        # alergias/notas. Para cambios mayores el bot debe usar
        # modificar_cita explicitamente.
        existentes = (
            supabase.table("citas")
            .select("*")
            .eq("telefono", telefono)
            .eq("fecha", val["fecha"])
            .eq("hora_inicio", val["hora_inicio"])
            .eq("estilista_id_yaml", estilista["id_yaml"])
            .eq("estado", "confirmada")
            .limit(1)
            .execute()
        )
        if existentes.data:
            ya = existentes.data[0]
            return {
                "status": "duplicada",
                "cita_id": ya["id"],
                "mensaje": (
                    f"Ya existe una cita confirmada con esos datos "
                    f"(ID {ya['id']}). Si el cliente quiere cambios usa "
                    f"modificar_cita; si no, confirma que ya esta agendada."
                ),
            }

        registro = {
            "cliente_id": cliente_id,
            "nombre": nombre,
            "telefono": telefono,
            "fecha": val["fecha"],
            "hora_inicio": val["hora_inicio"],
            "hora_fin": val["hora_fin"],
            "estilista_id_yaml": estilista["id_yaml"],
            "alergias": alergias,
            "notas": notas,
            "estado": "confirmada",
            "canal_origen": canal_origen,
        }
        ins = supabase.table("citas").insert(registro).execute()
        cita_id = ins.data[0]["id"] if ins.data else None
        if cita_id:
            _insertar_cita_servicios(cita_id, resol["servicios_validos"])

        nombres_servicios = [s["nombre"] for s in resol["servicios_validos"]]
        return {
            "status": "creada",
            "cita_id": cita_id,
            "estilista_nombre": estilista["nombre"],
            "servicios": nombres_servicios,
            "duracion_total_min": resol["duracion_total_min"],
            "precio_total_eur": resol["precio_total_eur"],
            "mensaje": (
                f"Cita confirmada para {nombre} el {val['fecha']} de "
                f"{val['hora_inicio']} a {val['hora_fin']} con "
                f"{estilista['nombre']}. Servicios: {nombres_servicios}. "
                f"Total estimado: {resol['precio_total_eur']:.2f}€. "
                f"ID {cita_id}."
            ),
        }

    except Exception as e:
        log.error("Error agendando cita: %s", e, exc_info=True)
        return {"status": "error", "mensaje": f"No se pudo agendar la cita: {str(e)}"}


# ════════════════════════════════════════════════════════════════════
# 3. modificar_cita (UPDATE in-place)
# ════════════════════════════════════════════════════════════════════

def modificar_cita(
    input_data: Dict,
    telefono_canal: Optional[str] = None,
    canal_origen: str = "web",
) -> Dict:
    """
    UPDATE in-place de una cita por id_cita. NO crea citas nuevas ni
    cancela la actual. Si cambian fecha/hora/servicios/estilista,
    recalcula la franja y reasigna estilista; si la nueva combinacion
    no cabe, devuelve estado de error y la cita original NO se toca.

    Args en input_data:
        id_cita: obligatorio. El bot lo obtiene de buscar_citas.
        fecha (opt), hora_inicio (opt), servicios (opt list[str]),
        estilista_preferido (opt), alergias (opt), notas (opt),
        nombre (opt).
    """
    id_cita = (input_data.get("id_cita") or "").strip()
    if not id_cita:
        return {
            "status": "error",
            "mensaje": (
                "Falta id_cita. Ejecuta buscar_citas primero para obtener "
                "el id de la cita del cliente."
            ),
        }

    try:
        res = (
            supabase.table("citas")
            .select("*")
            .eq("id", id_cita)
            .limit(1)
            .execute()
        )
    except Exception as e:
        return {"status": "error", "mensaje": f"Error consultando cita: {e}"}

    if not res.data:
        return {"status": "no_encontrada", "mensaje": f"No existe cita con id {id_cita}."}
    actual = res.data[0]
    if actual.get("estado") == "cancelada":
        return {
            "status": "error",
            "mensaje": (
                "La cita esta cancelada, no se puede modificar. Ofrece al "
                "cliente crear una nueva con agendar_cita."
            ),
        }

    # Recopilar cambios solicitados (solo los no vacios)
    cambios_in: Dict = {}
    for campo in ("nombre", "fecha", "hora_inicio", "alergias", "notas",
                  "estilista_preferido"):
        v = input_data.get(campo)
        if v is None:
            continue
        v_str = str(v).strip()
        if campo in ("alergias", "notas") and v_str == "":
            cambios_in[campo] = None
        elif v_str:
            cambios_in[campo] = v_str

    servicios_nuevos_in = input_data.get("servicios")
    cambian_servicios = isinstance(servicios_nuevos_in, list) and len(servicios_nuevos_in) > 0

    # Si cambian servicios, validamos
    if cambian_servicios:
        resol_nuevo = validar_y_resolver_servicios(servicios_nuevos_in)
        if resol_nuevo["nombres_invalidos"]:
            return {
                "status": "servicios_invalidos",
                "mensaje": (
                    f"Servicios no reconocidos: {resol_nuevo['nombres_invalidos']}. "
                    f"Pide al cliente la lista exacta y reintenta."
                ),
                "nombres_invalidos": resol_nuevo["nombres_invalidos"],
            }
        if not resol_nuevo["servicios_validos"]:
            return {"status": "error", "mensaje": "La lista de servicios nueva esta vacia."}

    # Calcular fecha/hora_inicio efectivas
    fecha_efectiva = cambios_in.get("fecha", actual["fecha"])
    hora_inicio_efectiva = cambios_in.get("hora_inicio", (actual.get("hora_inicio") or "")[:5])

    # Calcular duracion efectiva: si cambian servicios, suma nueva; si no,
    # mantener la duracion actual (hora_fin - hora_inicio).
    if cambian_servicios:
        duracion_efectiva = resol_nuevo["duracion_total_min"]
        especialidades_efectivas = resol_nuevo["especialidades_requeridas"]
    else:
        h_ini_curr = (actual.get("hora_inicio") or "")[:5]
        h_fin_curr = (actual.get("hora_fin") or "")[:5]
        try:
            h_ini_dt = datetime.strptime(h_ini_curr, "%H:%M")
            h_fin_dt = datetime.strptime(h_fin_curr, "%H:%M")
            duracion_efectiva = int((h_fin_dt - h_ini_dt).total_seconds() // 60)
        except Exception:
            duracion_efectiva = 30
        # Especialidades del estilista actual: leemos las de cita_servicios
        servicios_actuales = _cargar_servicios_de_cita(id_cita)
        especialidades_efectivas = sorted({
            s.get("especialidad") for s in servicios_actuales if s.get("especialidad")
        })

    # ¿Se necesita revalidar franja u re-buscar estilista?
    revalidar_franja = (
        "fecha" in cambios_in
        or "hora_inicio" in cambios_in
        or cambian_servicios
    )
    rebuscar_estilista = (
        revalidar_franja
        or "estilista_preferido" in cambios_in
    )

    cambios_db: Dict = {}
    if "nombre" in cambios_in:
        cambios_db["nombre"] = cambios_in["nombre"]
    if "alergias" in cambios_in:
        cambios_db["alergias"] = cambios_in["alergias"]
    if "notas" in cambios_in:
        cambios_db["notas"] = cambios_in["notas"]

    if revalidar_franja:
        val = _validar_franja(fecha_efectiva, hora_inicio_efectiva, duracion_efectiva)
        if not val["ok"]:
            return {"status": "error", "mensaje": val["mensaje"]}
        cambios_db["fecha"] = val["fecha"]
        cambios_db["hora_inicio"] = val["hora_inicio"]
        cambios_db["hora_fin"] = val["hora_fin"]
        fecha_busq = val["fecha"]
        hora_busq_ini = val["hora_inicio"]
        hora_busq_fin = val["hora_fin"]
    else:
        fecha_busq = actual["fecha"]
        hora_busq_ini = (actual.get("hora_inicio") or "")[:5]
        hora_busq_fin = (actual.get("hora_fin") or "")[:5]

    if rebuscar_estilista:
        estilista_pref = cambios_in.get("estilista_preferido") or actual.get("estilista_id_yaml")
        busqueda = buscar_estilista_disponible(
            especialidades_requeridas=especialidades_efectivas,
            fecha=fecha_busq,
            hora_inicio=hora_busq_ini,
            hora_fin=hora_busq_fin,
            estilista_preferido=estilista_pref,
            excluir_cita_id=id_cita,
        )
        if not busqueda.get("ok"):
            return {
                "status": busqueda.get("razon", "no_disponible"),
                "mensaje": busqueda.get("mensaje", "No hay disponibilidad."),
                "estilistas_compatibles": busqueda.get("estilistas_compatibles", []),
            }
        nuevo_estilista_id = busqueda["estilista"]["id_yaml"]
        if nuevo_estilista_id != actual.get("estilista_id_yaml"):
            cambios_db["estilista_id_yaml"] = nuevo_estilista_id

    if not cambios_db and not cambian_servicios:
        return {
            "status": "sin_cambios",
            "cita_id": id_cita,
            "mensaje": (
                f"La cita {id_cita} ya tiene esos datos. Confirma al "
                f"cliente que sigue todo igual."
            ),
        }

    cambios_db["updated_at"] = datetime.now(timezone.utc).isoformat()

    try:
        if cambios_db:
            supabase.table("citas").update(cambios_db).eq("id", id_cita).execute()
        if cambian_servicios:
            supabase.table("cita_servicios").delete().eq("cita_id", id_cita).execute()
            _insertar_cita_servicios(id_cita, resol_nuevo["servicios_validos"])
    except Exception as e:
        log.error("Error guardando cambios cita %s: %s", id_cita, e, exc_info=True)
        return {"status": "error", "mensaje": f"Error guardando cambios: {e}"}

    campos_publicos = [c for c in cambios_db if c not in ("updated_at",)]
    if cambian_servicios:
        campos_publicos.append("servicios")

    return {
        "status": "actualizada",
        "cita_id": id_cita,
        "campos_actualizados": campos_publicos,
        "mensaje": (
            f"Cita {id_cita} actualizada IN-PLACE. Campos cambiados: "
            f"{campos_publicos}. Confirma al cliente con los datos nuevos."
        ),
    }


# ════════════════════════════════════════════════════════════════════
# 4. buscar_citas
# ════════════════════════════════════════════════════════════════════

def buscar_citas(
    telefono: Optional[str] = None,
    nombre: Optional[str] = None,
    solo_futuras: bool = True,
    limite: int = 10,
) -> Dict:
    """
    Busca citas que matcheen por telefono y/o nombre. Pensada para los
    flujos de cancelar/modificar.
    """
    tel_raw = (telefono or "").strip() if telefono else ""
    nom_raw = (nombre or "").strip() if nombre else ""
    if not tel_raw and not nom_raw:
        return {
            "status": "error",
            "total": 0,
            "citas": [],
            "mensaje": (
                "Para buscar citas necesito al menos un telefono o un "
                "nombre. Pide al cliente esos datos antes de reintentar."
            ),
        }
    if not tel_raw and len(nom_raw) < 2:
        return {
            "status": "error",
            "total": 0,
            "citas": [],
            "mensaje": (
                "El nombre es demasiado corto para buscar. Pide al cliente "
                "el nombre completo o el telefono."
            ),
        }

    try:
        q = (
            supabase.table("citas")
            .select("id, nombre, fecha, hora_inicio, hora_fin, "
                    "estilista_id_yaml, estado")
            .neq("estado", "cancelada")
            .order("fecha", desc=False)
            .order("hora_inicio", desc=False)
            .limit(limite)
        )
        if solo_futuras:
            hoy_iso = datetime.now(timezone.utc).date().isoformat()
            q = q.gte("fecha", hoy_iso)
        if tel_raw:
            tel_limpio = _normalizar_telefono(tel_raw)
            if tel_limpio:
                q = q.eq("telefono", tel_limpio)
        if nom_raw:
            q = q.ilike("nombre", f"%{nom_raw}%")

        res = q.execute()
        filas = res.data or []

        citas_resumen: List[Dict] = []
        for r in filas:
            est = estilista_por_id_yaml(r.get("estilista_id_yaml") or "")
            servicios = _cargar_servicios_de_cita(r["id"])
            citas_resumen.append({
                "id": r.get("id"),
                "nombre": r.get("nombre"),
                "fecha": r.get("fecha"),
                "hora_inicio": (r.get("hora_inicio") or "")[:5],
                "hora_fin": (r.get("hora_fin") or "")[:5],
                "estilista": est["nombre"] if est else r.get("estilista_id_yaml"),
                "servicios": [s.get("servicio_nombre") for s in servicios],
                "estado": r.get("estado"),
            })

        return {
            "status": "ok",
            "total": len(citas_resumen),
            "citas": citas_resumen,
        }
    except Exception as e:
        log.error("Error buscando citas: %s", e, exc_info=True)
        return {
            "status": "error",
            "total": 0,
            "citas": [],
            "mensaje": f"Error interno buscando citas: {e}",
        }


# ════════════════════════════════════════════════════════════════════
# 5. cancelar_cita
# ════════════════════════════════════════════════════════════════════

def _normalizar_nombre(nombre: Optional[str]) -> str:
    """Para comparar nombres ignorando mayusculas, tildes y espacios."""
    if not nombre:
        return ""
    nfd = unicodedata.normalize("NFD", nombre)
    sin_tildes = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return " ".join(sin_tildes.lower().split())


def cancelar_cita(
    input_data: Dict,
    telefono_canal: Optional[str] = None,
    canal_actual: str = "web",
) -> Dict:
    """
    Cancela por id_cita o por (telefono + fecha) con verificacion de
    identidad para evitar que terceros cancelen citas ajenas.
    """
    id_cita = (input_data.get("id_cita") or "").strip() or None
    telefono_input = (input_data.get("telefono") or "").strip()
    telefono = _normalizar_telefono(telefono_input or telefono_canal or "")
    fecha_str = (input_data.get("fecha") or "").strip()
    motivo = (input_data.get("motivo") or "").strip() or None
    nombre_confirmacion = (input_data.get("nombre_confirmacion") or "").strip() or None

    if not id_cita and not (telefono and fecha_str):
        return {
            "status": "error",
            "mensaje": (
                "Para cancelar necesito el ID de cita, o bien telefono y "
                "fecha de la cita."
            ),
        }

    try:
        if id_cita:
            res = (
                supabase.table("citas")
                .select("*")
                .eq("id", id_cita)
                .limit(1)
                .execute()
            )
        else:
            fecha = _parsear_fecha(fecha_str)
            if not fecha:
                return {
                    "status": "error",
                    "mensaje": f"Fecha invalida '{fecha_str}'. Formato esperado: YYYY-MM-DD.",
                }
            res = (
                supabase.table("citas")
                .select("*")
                .eq("telefono", telefono)
                .eq("fecha", fecha.date().isoformat())
                .eq("estado", "confirmada")
                .limit(1)
                .execute()
            )

        if not res.data:
            return {
                "status": "no_encontrada",
                "mensaje": (
                    "No he encontrado una cita confirmada con esos datos. "
                    "Comprueba con el cliente o pasa el caso al duenno."
                ),
            }

        cita = res.data[0]
        if cita.get("estado") == "cancelada":
            return {
                "status": "ya_cancelada",
                "mensaje": (
                    f"La cita (ID {cita['id']}) ya estaba cancelada. "
                    f"Confirma al cliente que no figura."
                ),
            }

        # ─── VERIFICACION DE IDENTIDAD ─────────────────────────────
        canal_cita = cita.get("canal_origen") or "web"
        tel_cita = _normalizar_telefono(cita.get("telefono") or "")
        tel_canal_norm = _normalizar_telefono(telefono_canal or "")

        autorizada_por_canal = (
            canal_actual == canal_cita
            and tel_canal_norm
            and tel_canal_norm == tel_cita
        )
        autorizada_por_nombre = (
            nombre_confirmacion
            and _normalizar_nombre(nombre_confirmacion) == _normalizar_nombre(cita.get("nombre"))
        )

        if not (autorizada_por_canal or autorizada_por_nombre):
            return {
                "status": "verificacion_pendiente",
                "mensaje": (
                    "Por seguridad necesito verificar tu identidad antes "
                    "de cancelar. Pide al cliente que CONFIRME el NOMBRE "
                    "EXACTO con el que se hizo la cita y vuelve a llamar "
                    "a cancelar_cita pasando ese nombre en el campo "
                    "'nombre_confirmacion'."
                ),
            }

        updates = {
            "estado": "cancelada",
            "motivo_cancelacion": motivo,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        supabase.table("citas").update(updates).eq("id", cita["id"]).execute()

        return {
            "status": "cancelada",
            "cita_id": cita["id"],
            "mensaje": (
                f"Cita cancelada (ID {cita['id']}, era para el "
                f"{cita.get('fecha')} a las "
                f"{(cita.get('hora_inicio') or '')[:5]}). Confirma al "
                f"cliente que la cancelacion ha quedado registrada."
            ),
        }

    except Exception as e:
        log.error("Error cancelando cita: %s", e, exc_info=True)
        return {"status": "error", "mensaje": f"No se pudo cancelar la cita: {e}"}


# ════════════════════════════════════════════════════════════════════
# 6. historial_cliente_resumen
# ════════════════════════════════════════════════════════════════════

def historial_cliente_resumen(telefono: str) -> Dict:
    """
    Resumen del historial de un cliente para personalizar el saludo del
    bot. Incluye visitas pasadas, ultima visita y citas futuras.
    """
    tel_limpio = _normalizar_telefono(telefono)
    vacio = {
        "es_recurrente": False,
        "num_visitas_pasadas": 0,
        "ultima_visita": None,
        "citas_futuras": [],
        "nombre_preferido": None,
    }
    if not tel_limpio:
        return vacio
    try:
        res = (
            supabase.table("citas")
            .select("id, nombre, fecha, hora_inicio, estado, alergias, "
                    "estilista_id_yaml, created_at")
            .eq("telefono", tel_limpio)
            .order("fecha", desc=True)
            .limit(50)
            .execute()
        )
    except Exception as e:
        log.warning("Error consultando historial cliente: %s", e)
        return vacio

    filas = res.data or []
    if not filas:
        return vacio

    hoy = datetime.now(timezone.utc).date().isoformat()
    pasadas: List[Dict] = []
    futuras: List[Dict] = []
    for r in filas:
        fecha = r.get("fecha") or ""
        estado = r.get("estado")
        if estado == "cancelada":
            continue
        if fecha < hoy:
            if estado in ("confirmada", "completada"):
                pasadas.append(r)
        elif fecha >= hoy:
            est = estilista_por_id_yaml(r.get("estilista_id_yaml") or "")
            futuras.append({
                "id": r.get("id"),
                "fecha": fecha,
                "hora_inicio": (r.get("hora_inicio") or "")[:5],
                "estilista": est["nombre"] if est else r.get("estilista_id_yaml"),
            })

    ultima = pasadas[0] if pasadas else None
    ultima_dict = None
    if ultima:
        est_u = estilista_por_id_yaml(ultima.get("estilista_id_yaml") or "")
        ultima_dict = {
            "nombre": ultima.get("nombre"),
            "fecha": ultima.get("fecha"),
            "estilista": est_u["nombre"] if est_u else None,
            "alergias": ultima.get("alergias"),
        }

    nombre_preferido = None
    if futuras:
        prox_ordenadas = sorted(futuras, key=lambda r: r.get("fecha", ""))
        for r in filas:
            if r.get("id") == prox_ordenadas[0]["id"]:
                nombre_preferido = r.get("nombre")
                break
    if not nombre_preferido and ultima:
        nombre_preferido = ultima.get("nombre")

    return {
        "es_recurrente": len(pasadas) > 0,
        "num_visitas_pasadas": len(pasadas),
        "ultima_visita": ultima_dict,
        "citas_futuras": futuras[:3],
        "nombre_preferido": nombre_preferido,
    }
