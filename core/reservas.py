"""
Logica compartida de reservas entre los 3 canales (web, whatsapp, voz).

Centralizamos aqui:
  - reservar_mesa: crea o actualiza reserva en `reservas` y mirror en `clientes`.
  - consultar_disponibilidad: comprueba aforo restante por turno.
  - cancelar_reserva: marca reserva como 'cancelada'.

Cada canal tiene su modulo `tools.py` que llama a estas funciones con su
propio `canal_origen`. Asi cualquier mejora a la logica afecta a los 3.
"""
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Optional

from core.config import supabase
from core.clientes import upsert_cliente
from core.logger import get_logger
from core.memory import _normalizar_telefono

log = get_logger(__name__)
from core.restaurante_data import (
    AFORO_MAX_POR_TURNO,
    ANTELACION_MAXIMA_DIAS,
    ANTELACION_MINIMA_HORAS,
    GRUPO_GRANDE_DESDE,
    HORARIOS,
)
from core.mesas import (
    asignar_mesas,
    calcular_hora_fin,
    cargar_mesas_activas,
    lleva_arroz,
    mesas_legibles,
    mesas_ocupadas,
)


# ─── Helpers de validacion de fecha/hora ────────────────────────────
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


def _turno_de(hora: dtime, dia_semana: int) -> Optional[str]:
    """
    Dado una hora y dia de semana (0..6), devuelve el identificador del
    turno ('comida' o 'cena') o None si la hora cae fuera de horario.

    Para simplificar la demo: si hay 2 turnos ese dia, el primero es
    'comida' y el segundo es 'cena'. Si solo hay uno, es 'comida'.
    """
    turnos = HORARIOS.get(dia_semana, [])
    if not turnos:
        return None
    nombres = ["comida", "cena"]
    for i, (apertura, cierre) in enumerate(turnos):
        a = _parsear_hora(apertura)
        c = _parsear_hora(cierre)
        if a and c and a <= hora <= c:
            return nombres[i] if i < len(nombres) else f"turno{i}"
    return None


def _validar_fecha_hora(fecha_str: str, hora_str: str) -> dict:
    """
    Valida que la fecha + hora caigan dentro de horario y no sean pasado.

    Returns:
        {"ok": True, "fecha": dt, "hora": time, "dia_semana": int, "turno": str}
        o {"ok": False, "mensaje": "..."}
    """
    fecha = _parsear_fecha(fecha_str)
    if not fecha:
        return {"ok": False, "mensaje": f"Fecha invalida '{fecha_str}'. Formato esperado: YYYY-MM-DD."}

    hora = _parsear_hora(hora_str)
    if not hora:
        return {"ok": False, "mensaje": f"Hora invalida '{hora_str}'. Formato esperado: HH:MM."}

    ahora = datetime.now()
    fecha_hora_completa = datetime.combine(fecha.date(), hora)
    if fecha_hora_completa < ahora:
        return {"ok": False, "mensaje": f"La fecha y hora ({fecha_str} {hora_str}) ya han pasado."}

    # Antelacion MINIMA configurable por restaurante (issue #65).
    # Si el restaurante exige al menos N horas de antelacion, rechazamos
    # las reservas que caen en una ventana mas corta.
    if ANTELACION_MINIMA_HORAS > 0:
        margen_minimo = ahora + timedelta(hours=ANTELACION_MINIMA_HORAS)
        if fecha_hora_completa < margen_minimo:
            return {
                "ok": False,
                "mensaje": (
                    f"Necesitamos al menos {ANTELACION_MINIMA_HORAS}h de "
                    f"antelacion para preparar la mesa. La hora mas cercana "
                    f"disponible seria {margen_minimo.strftime('%H:%M')} del "
                    f"{margen_minimo.date().isoformat()}."
                ),
                "tipo": "antelacion_minima",
            }

    # Antelacion MAXIMA configurable por restaurante (issue #65).
    # Algunos restaurantes solo aceptan reservas hasta N dias por delante
    # (gestion de aforo, calendarios temporales, etc.).
    if ANTELACION_MAXIMA_DIAS > 0:
        limite_maximo = (ahora + timedelta(days=ANTELACION_MAXIMA_DIAS)).date()
        if fecha.date() > limite_maximo:
            return {
                "ok": False,
                "mensaje": (
                    f"Aceptamos reservas hasta {ANTELACION_MAXIMA_DIAS} dias "
                    f"por delante. La fecha mas lejana posible seria "
                    f"{limite_maximo.isoformat()}."
                ),
                "tipo": "antelacion_maxima",
            }

    dia_semana = fecha.weekday()
    turno = _turno_de(hora, dia_semana)
    if not turno:
        # Restaurante cerrado o fuera de horario
        from core.restaurante_data import horario_dia_legible
        return {
            "ok": False,
            "mensaje": (
                f"A esa hora el restaurante esta cerrado. "
                f"Horario de ese dia: {horario_dia_legible(dia_semana)}."
            ),
        }

    return {
        "ok": True,
        "fecha": fecha.date().isoformat(),
        "hora": hora.strftime("%H:%M"),
        "dia_semana": dia_semana,
        "turno": turno,
    }


# ─── Calculo de capacidad libre (modelo de mesas) ──────────────────
def _capacidad_libre_en_rango(fecha: str, hora_inicio: str, hora_fin: str) -> int:
    """
    Suma de capacidades de las mesas LIBRES en el rango horario.
    Util para lista de espera (saber si cabe alguien tras una cancelacion).
    """
    inventario = cargar_mesas_activas()
    if not inventario:
        # Fallback al modelo viejo si la tabla mesas no esta poblada.
        return AFORO_MAX_POR_TURNO

    ocupadas = mesas_ocupadas(fecha, hora_inicio, hora_fin)
    return sum(m["capacidad"] for m in inventario if m["id"] not in ocupadas)


def _huecos_libres(fecha: str, turno: str) -> int:
    """
    Aproximacion del aforo libre para un turno entero. Usa la hora de
    inicio canonica del turno (13:30 comida, 21:00 cena) y suma las
    capacidades de las mesas libres para ese rango.

    Mantenido por compatibilidad: lista_espera y otros lo invocan asi.
    """
    hora_inicio = "13:30" if turno == "comida" else "21:00"
    hora_fin = calcular_hora_fin(hora_inicio, turno)
    return _capacidad_libre_en_rango(fecha, hora_inicio, hora_fin)


# ─── 1. Tool: consultar_disponibilidad ──────────────────────────────
def consultar_disponibilidad(
    fecha: str,
    hora: str,
    num_personas: int,
    turno_flexible: bool = False,
) -> dict:
    """
    Devuelve si hay sitio para num_personas en (fecha, hora). Si no hay
    y turno_flexible=True, sugiere el otro turno del mismo dia si hay hueco.
    """
    val = _validar_fecha_hora(fecha, hora)
    if not val["ok"]:
        return {"status": "error", "mensaje": val["mensaje"]}

    if num_personas < 1 or num_personas > 20:
        return {
            "status": "error",
            "mensaje": "El numero de personas debe estar entre 1 y 20.",
        }

    if num_personas >= GRUPO_GRANDE_DESDE:
        return {
            "status": "grupo_grande",
            "mensaje": (
                f"Para grupos de {GRUPO_GRANDE_DESDE} personas o mas hay que "
                f"hablar directamente con el restaurante. Llama a escalar_a_humano."
            ),
        }

    # Modelo de mesas: calculamos rango horario y consultamos asignacion.
    hora_fin = calcular_hora_fin(val["hora"], val["turno"])
    asignacion = asignar_mesas(val["fecha"], val["hora"], hora_fin, num_personas)

    if asignacion.get("ok"):
        nombres = "+".join(sorted(m["nombre"] for m in asignacion["mesas"]))
        cap = asignacion["capacidad_total"]
        return {
            "status": "disponible",
            "mensaje": (
                f"Hay sitio para {num_personas} personas el {val['fecha']} a "
                f"las {val['hora']} (turno {val['turno']}). "
                f"[INTERNO: mesa {nombres}, capacidad {cap}, no mencionar "
                f"al cliente]."
            ),
            "fecha": val["fecha"],
            "hora": val["hora"],
            "hora_fin": hora_fin,
            "turno": val["turno"],
            "mesas_propuestas": [m["id"] for m in asignacion["mesas"]],
        }

    # Sin sitio. Mirar el otro turno si se permite.
    if turno_flexible:
        otros_turnos = HORARIOS.get(val["dia_semana"], [])
        sugerencias = []
        for i, (apertura, _cierre) in enumerate(otros_turnos):
            nombre_turno = ["comida", "cena"][i] if i < 2 else f"turno{i}"
            if nombre_turno == val["turno"]:
                continue
            h_inicio_alt = apertura
            h_fin_alt = calcular_hora_fin(h_inicio_alt, nombre_turno)
            asign_alt = asignar_mesas(val["fecha"], h_inicio_alt, h_fin_alt, num_personas)
            if asign_alt.get("ok"):
                sugerencias.append(f"{nombre_turno} (a partir de {apertura})")
        if sugerencias:
            return {
                "status": "alternativa",
                "mensaje": (
                    f"En el turno de {val['turno']} no hay sitio para "
                    f"{num_personas}. Te valdria otro turno: {'; '.join(sugerencias)}."
                ),
                "fecha": val["fecha"],
                "alternativas": sugerencias,
            }

    return {
        "status": "lleno",
        "mensaje": (
            f"Lo siento, el {val['fecha']} a las {val['hora']} no hay mesa "
            f"libre para {num_personas} personas. Sugiere otro dia, otra "
            f"hora, o apuntar en lista de espera."
        ),
        "fecha": val["fecha"],
        "hora": val["hora"],
        "turno": val["turno"],
    }


# ─── 2. Tool: reservar_mesa ─────────────────────────────────────────
def reservar_mesa(
    input_data: dict,
    telefono_canal: Optional[str] = None,
    canal_origen: str = "web",
) -> dict:
    """
    Crea una reserva.

    Politica anti-duplicado: si el mismo telefono ya tiene una reserva
    confirmada para la misma fecha + turno, se ACTUALIZA en lugar de
    crear otra (evita doble reserva por mismo cliente que insiste).

    Args (en input_data):
        nombre, telefono, fecha (YYYY-MM-DD), hora (HH:MM), num_personas (int),
        alergias (opcional), ocasion_especial (opcional), notas (opcional).

    `telefono_canal` es el telefono del canal (Twilio para wa, Vapi para
    voz). Si input_data trae telefono explicito, prevalece este ultimo.
    """
    nombre = (input_data.get("nombre") or "").strip()
    telefono_input = (input_data.get("telefono") or "").strip()
    telefono = _normalizar_telefono(telefono_input or telefono_canal or "")
    fecha_str = (input_data.get("fecha") or "").strip()
    hora_str = (input_data.get("hora") or "").strip()
    num_personas = input_data.get("num_personas")
    alergias = (input_data.get("alergias") or "").strip() or None
    ocasion = (input_data.get("ocasion_especial") or "").strip() or None
    notas = (input_data.get("notas") or "").strip() or None

    if not nombre:
        return {"status": "error", "mensaje": "Falta el nombre del cliente."}
    if not telefono:
        return {"status": "error", "mensaje": "Falta el telefono del cliente."}
    if not isinstance(num_personas, int) or num_personas < 1:
        return {"status": "error", "mensaje": "num_personas debe ser un entero >= 1."}

    val = _validar_fecha_hora(fecha_str, hora_str)
    if not val["ok"]:
        return {"status": "error", "mensaje": val["mensaje"]}

    if num_personas >= GRUPO_GRANDE_DESDE:
        return {
            "status": "grupo_grande",
            "mensaje": (
                f"Para grupos de {GRUPO_GRANDE_DESDE} personas o mas no puedo "
                f"reservar directamente. Hay que escalar al duenno (usa "
                f"escalar_a_humano con motivo 'grupo_grande')."
            ),
        }

    # Modelo de mesas: calculamos hora_fin segun turno + arroz.
    arroz = lleva_arroz(notas, ocasion)
    hora_fin = calcular_hora_fin(val["hora"], val["turno"], lleva_arroz=arroz)

    asignacion = asignar_mesas(val["fecha"], val["hora"], hora_fin, num_personas)
    if not asignacion.get("ok"):
        return {
            "status": "lleno",
            "mensaje": (
                f"No hay mesa libre para {num_personas} personas el "
                f"{val['fecha']} a las {val['hora']}. Sugiere otra hora, "
                f"otro dia, o apuntar en lista de espera."
            ),
        }
    mesas_asignadas = [m["id"] for m in asignacion["mesas"]]
    nombres_mesas = "+".join(sorted(m["nombre"] for m in asignacion["mesas"]))

    try:
        # Mirror cliente primero (asi tenemos cliente_id al insertar reserva).
        res_cli = upsert_cliente(
            telefono=telefono,
            nombre=nombre,
            canal_origen=canal_origen,
            alergias=alergias,
        )
        cliente_id = res_cli.get("id")

        # Anti-duplicado: misma reserva (telefono + fecha + turno + estado=confirmada)
        existentes = (
            supabase.table("reservas")
            .select("*")
            .eq("telefono", telefono)
            .eq("fecha", val["fecha"])
            .eq("turno", val["turno"])
            .eq("estado", "confirmada")
            .limit(1)
            .execute()
        )

        if existentes.data:
            ultima = existentes.data[0]
            updates = {}
            campos = {
                "nombre": nombre,
                "hora": val["hora"],
                "num_personas": num_personas,
                "alergias": alergias,
                "ocasion_especial": ocasion,
                "notas": notas,
            }
            for campo, valor in campos.items():
                if valor is not None and valor != ultima.get(campo):
                    updates[campo] = valor

            if not updates:
                return {
                    "status": "sin_cambios",
                    "reserva_id": ultima["id"],
                    "mensaje": (
                        f"Ya tienes una reserva el {val['fecha']} en el turno "
                        f"de {val['turno']} con esos datos (ID {ultima['id']}). "
                        f"Confirma al cliente que esta todo igual."
                    ),
                }

            updates["updated_at"] = datetime.now(timezone.utc).isoformat()
            supabase.table("reservas").update(updates).eq("id", ultima["id"]).execute()

            return {
                "status": "actualizada",
                "reserva_id": ultima["id"],
                "campos_actualizados": [c for c in updates if c != "updated_at"],
                "mensaje": (
                    f"Reserva existente ACTUALIZADA (ID {ultima['id']}, "
                    f"{val['fecha']} {val['hora']}, {num_personas} personas). "
                    f"Confirma al cliente con los datos nuevos."
                ),
            }

        registro = {
            "cliente_id": cliente_id,
            "nombre": nombre,
            "telefono": telefono,
            "fecha": val["fecha"],
            "hora": val["hora"],
            "hora_fin": hora_fin,
            "turno": val["turno"],
            "num_personas": num_personas,
            "alergias": alergias,
            "ocasion_especial": ocasion,
            "notas": notas,
            "estado": "confirmada",
            "canal_origen": canal_origen,
            "mesas_asignadas": mesas_asignadas,
        }
        ins = supabase.table("reservas").insert(registro).execute()
        reserva_id = ins.data[0]["id"] if ins.data else None

        return {
            "status": "creada",
            "reserva_id": reserva_id,
            "mesas_internas": nombres_mesas,  # info INTERNA para panel admin
            "mensaje": (
                f"Reserva confirmada para {nombre} el {val['fecha']} a las "
                f"{val['hora']} ({num_personas} personas, turno {val['turno']}). "
                f"ID {reserva_id}. [INTERNO: mesa {nombres_mesas}, no mencionar "
                f"al cliente]. Confirma al cliente y dile que recibira "
                f"recordatorio el dia anterior. NO menciones el codigo de mesa."
            ),
        }

    except Exception as e:
        return {
            "status": "error",
            "mensaje": f"No se pudo procesar la reserva: {str(e)}",
        }


# ─── 2.5 Tool: modificar_reserva (UPDATE in-place) ──────────────────
def modificar_reserva(
    input_data: dict,
    telefono_canal: Optional[str] = None,
    canal_origen: str = "web",
) -> dict:
    """
    Actualiza una reserva existente IN-PLACE sin cancelarla ni crear
    duplicados. La fila conserva su `id`, `created_at` y los campos no
    modificados (alergias, ocasion, etc.).

    Pensada para el flujo "mover una reserva" (cambio de fecha/hora/personas).
    El bot debe usar esta tool en vez de `cancelar_reserva + reservar_mesa`,
    que generaba 2 emails y 2 filas distintas.

    Args (en input_data):
        id_reserva: ID de la reserva a modificar (obligatorio).
                    El bot lo obtiene de `buscar_reservas` previamente.
        fecha:      nueva fecha YYYY-MM-DD (opcional).
        hora:       nueva hora HH:MM (opcional).
        num_personas: nuevo numero de comensales (opcional).
        alergias:   nuevo valor (opcional).
        ocasion_especial: nuevo valor (opcional).
        notas:      nuevo valor (opcional).
        nombre:     nuevo nombre (opcional, raro).

    Si se cambia fecha/hora/num_personas, REASIGNA mesas. Si no hay
    sitio en la nueva combinacion, devuelve `lleno` SIN tocar la
    reserva original.

    No verifica identidad porque se asume que el bot ya hizo
    `buscar_reservas` (que filtra por telefono del canal o por
    nombre+telefono del cliente).

    Returns dict con:
        - status: 'actualizada' | 'sin_cambios' | 'lleno' | 'error' | 'no_encontrada'
        - reserva_id: el id (sin cambios, mismo de entrada)
        - campos_actualizados: lista de campos modificados
        - mensaje: texto para el bot
    """
    id_reserva = (input_data.get("id_reserva") or "").strip()
    if not id_reserva:
        return {
            "status": "error",
            "mensaje": (
                "Falta id_reserva. Ejecuta buscar_reservas primero "
                "para obtener el id de la reserva del cliente."
            ),
        }

    # Cargar reserva actual
    try:
        res = (
            supabase.table("reservas")
            .select("*")
            .eq("id", id_reserva)
            .limit(1)
            .execute()
        )
    except Exception as e:
        return {"status": "error", "mensaje": f"Error consultando reserva: {e}"}

    if not res.data:
        return {
            "status": "no_encontrada",
            "mensaje": f"No existe reserva con id {id_reserva}.",
        }
    actual = res.data[0]
    if actual.get("estado") == "cancelada":
        return {
            "status": "error",
            "mensaje": (
                "La reserva esta cancelada, no se puede modificar. "
                "Ofrece al cliente crear una nueva con reservar_mesa."
            ),
        }

    # Normalizar valores nuevos: solo aplicamos los que vengan no vacios
    cambios_solicitados = {}
    for campo in ("nombre", "fecha", "hora", "alergias",
                  "ocasion_especial", "notas"):
        v = input_data.get(campo)
        if v is None:
            continue
        v_str = str(v).strip()
        # alergias/ocasion/notas: "" se traduce a null para "quitarlo"
        if campo in ("alergias", "ocasion_especial", "notas") and v_str == "":
            cambios_solicitados[campo] = None
        elif v_str:
            cambios_solicitados[campo] = v_str
    if input_data.get("num_personas") is not None:
        try:
            cambios_solicitados["num_personas"] = int(input_data["num_personas"])
        except (TypeError, ValueError):
            return {"status": "error", "mensaje": "num_personas debe ser entero."}

    # Filtrar a los que realmente cambian respecto al estado actual
    cambios = {}
    for campo, nuevo in cambios_solicitados.items():
        actual_val = actual.get(campo)
        # Normalizar hora actual a HH:MM (la BD trae HH:MM:SS)
        if campo == "hora" and isinstance(actual_val, str):
            actual_val = actual_val[:5]
        if nuevo != actual_val:
            cambios[campo] = nuevo

    if not cambios:
        return {
            "status": "sin_cambios",
            "reserva_id": id_reserva,
            "mensaje": (
                f"La reserva {id_reserva} ya tiene esos datos. Nada que "
                f"cambiar. Confirma al cliente que sigue todo igual."
            ),
        }

    # Si cambia fecha, hora o num_personas -> recalcular mesas + turno
    fecha_nueva = cambios.get("fecha", actual["fecha"])
    hora_nueva = cambios.get("hora", actual["hora"])
    if isinstance(hora_nueva, str) and len(hora_nueva) > 5:
        hora_nueva = hora_nueva[:5]
    num_nueva = cambios.get("num_personas", actual["num_personas"])

    # Validar fecha+hora si han cambiado
    if "fecha" in cambios or "hora" in cambios:
        val = _validar_fecha_hora(fecha_nueva, hora_nueva)
        if not val["ok"]:
            return {"status": "error", "mensaje": val["mensaje"]}
        cambios["fecha"] = val["fecha"]
        cambios["hora"] = val["hora"]
        cambios["turno"] = val["turno"]
        # Recalcular hora_fin
        notas_efectivas = cambios.get("notas", actual.get("notas"))
        ocasion_efectiva = cambios.get("ocasion_especial", actual.get("ocasion_especial"))
        arroz = lleva_arroz(notas_efectivas, ocasion_efectiva)
        cambios["hora_fin"] = calcular_hora_fin(val["hora"], val["turno"], lleva_arroz=arroz)

    # Si cambia algo que afecta a la mesa, recalcular asignacion
    necesita_reasignar = bool({"fecha", "hora", "num_personas"} & set(cambios.keys()))
    if necesita_reasignar:
        if not isinstance(num_nueva, int) or num_nueva < 1:
            return {"status": "error", "mensaje": "num_personas debe ser entero >= 1."}
        if num_nueva >= GRUPO_GRANDE_DESDE:
            return {
                "status": "grupo_grande",
                "mensaje": (
                    f"Para grupos de {GRUPO_GRANDE_DESDE} o mas no se puede "
                    f"modificar directamente. Escala con escalar_a_humano."
                ),
            }
        # Buscar mesas libres en la nueva fecha/hora EXCLUYENDO la propia
        # reserva (si solo cambia num_personas misma fecha+hora, sus mesas
        # actuales pueden ya no servir).
        # Para simplificar: liberamos virtualmente la reserva actual
        # cancelandola en BD (NO! eso dispara webhook). Mejor: usamos
        # asignar_mesas con un parametro de exclusion. Como no existe
        # ese parametro, hacemos un truco: si cambia fecha o hora, la
        # vieja mesa queda libre automaticamente porque mesas_ocupadas
        # filtra por fecha+rango. Si solo cambia num_personas misma
        # fecha+hora, las mesas viejas siguen ocupadas por esta reserva,
        # asi que asignar_mesas dira "lleno" aunque podriamos reusar
        # parte. Edge case, lo tratamos en futuro.
        asignacion = asignar_mesas(
            cambios.get("fecha", actual["fecha"]),
            cambios.get("hora", actual["hora"][:5]),
            cambios.get("hora_fin", actual.get("hora_fin")),
            num_nueva,
            excluir_reserva_id=id_reserva,  # nuevo parametro (ver core/mesas.py)
        )
        if not asignacion.get("ok"):
            return {
                "status": "lleno",
                "mensaje": (
                    f"No hay mesa libre para {num_nueva} personas el "
                    f"{cambios.get('fecha', actual['fecha'])} a las "
                    f"{cambios.get('hora', actual['hora'][:5])}. "
                    f"La reserva original no se ha tocado. Sugiere otra "
                    f"hora/dia o lista de espera."
                ),
            }
        cambios["mesas_asignadas"] = [m["id"] for m in asignacion["mesas"]]

    # UPDATE final
    cambios["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table("reservas").update(cambios).eq("id", id_reserva).execute()
    except Exception as e:
        return {"status": "error", "mensaje": f"Error guardando cambios: {e}"}

    campos_publicos = [c for c in cambios if c not in ("updated_at", "mesas_asignadas", "hora_fin", "turno")]
    return {
        "status": "actualizada",
        "reserva_id": id_reserva,
        "campos_actualizados": campos_publicos,
        "mensaje": (
            f"Reserva {id_reserva} actualizada IN-PLACE. Campos cambiados: "
            f"{campos_publicos}. Confirma al cliente con los datos nuevos. "
            f"NO crees una reserva nueva ni canceles otra."
        ),
    }


# ─── 3. Tool: cancelar_reserva ──────────────────────────────────────
def buscar_reservas(
    telefono: Optional[str] = None,
    nombre: Optional[str] = None,
    solo_futuras: bool = True,
    limite: int = 10,
) -> dict:
    """
    Busca reservas que matcheen por telefono y/o nombre. Pensada para el
    flujo de cancelacion (issue #33): en vez de interrogar al cliente con
    telefono+fecha+nombre, el bot busca primero y muestra al cliente la(s)
    reserva(s) candidata(s) para confirmar cual anular.

    Args:
        telefono: telefono del cliente (normalizado, puede venir del canal
                  en WA/voz o pedido explicitamente en web).
        nombre:   nombre del cliente. Match fuzzy case-insensitive (ILIKE).
        solo_futuras: si True, solo devuelve reservas con fecha >= hoy.
        limite:   numero maximo de resultados (default 10).

    Returns:
        dict con keys:
          - status: 'ok' | 'error'
          - total: int, numero de reservas encontradas
          - reservas: list[dict] con campos resumidos (id, fecha, hora,
                      num_personas, nombre, estado). No incluye telefono
                      ni datos internos (mesas_asignadas) para no filtrar
                      info sensible del otro titular.
          - mensaje: texto opcional con error o matiz.

    Filtrado por canal:
        - WA/voz: tipicamente se llama con solo `telefono` (del canal).
          Devuelve las reservas asociadas a ese numero.
        - web: se llama con `nombre` + `telefono` (ambos aportados por el
          cliente). Mas seguro: solo si coinciden los dos.
        - Si solo hay `nombre` sin `telefono`: busqueda amplia por nombre.
          Menos seguro pero util si el cliente perdio el registro del
          telefono. El prompt decide cuando usar este modo.
    """
    # Normalizar strings vacios a None para que el filtro funcione bien
    tel_raw = (telefono or "").strip() if telefono else ""
    nom_raw = (nombre or "").strip() if nombre else ""
    if not tel_raw and not nom_raw:
        return {
            "status": "error",
            "total": 0,
            "reservas": [],
            "mensaje": (
                "Para buscar reservas necesito al menos un telefono o un "
                "nombre. Pide al cliente esos datos antes de reintentar."
            ),
        }
    # Seguridad: nombre de al menos 2 caracteres (un nombre suelto "a"
    # haria match con demasiadas reservas). Si es solo tel, pasa igual.
    if not tel_raw and len(nom_raw) < 2:
        return {
            "status": "error",
            "total": 0,
            "reservas": [],
            "mensaje": (
                "El nombre es demasiado corto para buscar. Pide al cliente "
                "el nombre completo o el telefono."
            ),
        }

    try:
        q = (
            supabase.table("reservas")
            .select("id, nombre, fecha, hora, num_personas, estado, turno")
            .neq("estado", "cancelada")
            .order("fecha", desc=False)
            .order("hora", desc=False)
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
            # ILIKE case-insensitive con wildcards
            q = q.ilike("nombre", f"%{nom_raw}%")

        res = q.execute()
        filas = res.data or []

        reservas_resumen = [
            {
                "id": r.get("id"),
                "nombre": r.get("nombre"),
                "fecha": r.get("fecha"),
                "hora": (r.get("hora") or "")[:5],
                "num_personas": r.get("num_personas"),
                "turno": r.get("turno"),
                "estado": r.get("estado"),
            }
            for r in filas
        ]

        return {
            "status": "ok",
            "total": len(reservas_resumen),
            "reservas": reservas_resumen,
        }
    except Exception as e:
        log.error("Error buscando reservas: %s", e, exc_info=True)
        return {
            "status": "error",
            "total": 0,
            "reservas": [],
            "mensaje": f"Error interno buscando reservas: {e}",
        }


def historial_cliente_resumen(telefono: str) -> dict:
    """
    Resumen del historial de un cliente para personalizar el saludo del
    bot (issue #3). Devuelve TODO en una consulta:

    - es_recurrente: True si tiene >= 1 reserva pasada confirmada o no_show.
    - num_visitas_pasadas: cuantas reservas pasadas confirmadas tiene.
    - ultima_visita: dict {fecha, num_personas, ocasion_especial, alergias}
                     de la mas reciente confirmada en el pasado, o None.
    - reservas_futuras: list[{id, fecha, hora, num_personas}] no canceladas
                       con fecha >= hoy. Maximo 3.
    - tiene_no_show_reciente: True si tiene un no_show en los ultimos 60 dias
                              (util para no asumir mucha familiaridad).

    Si telefono vacio o no hay datos, devuelve estructura "vacia" sin error.
    """
    tel_limpio = _normalizar_telefono(telefono)
    vacio = {
        "es_recurrente": False,
        "num_visitas_pasadas": 0,
        "ultima_visita": None,
        "reservas_futuras": [],
        "tiene_no_show_reciente": False,
    }
    if not tel_limpio:
        return vacio
    try:
        res = (
            supabase.table("reservas")
            .select("id, fecha, hora, num_personas, estado, alergias, "
                    "ocasion_especial, created_at")
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
    pasadas_confirmadas = []
    no_shows_recientes = 0
    futuras = []
    for r in filas:
        fecha = r.get("fecha") or ""
        estado = r.get("estado")
        if estado == "cancelada":
            continue
        if fecha < hoy:
            if estado == "confirmada":
                pasadas_confirmadas.append(r)
            elif estado == "no_show":
                # Detectar no_show de los ultimos 60 dias
                # (compar string YYYY-MM-DD funciona porque ordenado lex)
                from datetime import timedelta
                hace_60 = (datetime.now(timezone.utc).date() - timedelta(days=60)).isoformat()
                if fecha >= hace_60:
                    no_shows_recientes += 1
        elif fecha >= hoy:
            futuras.append({
                "id": r.get("id"),
                "fecha": fecha,
                "hora": (r.get("hora") or "")[:5],
                "num_personas": r.get("num_personas"),
            })

    ultima = pasadas_confirmadas[0] if pasadas_confirmadas else None
    ultima_dict = None
    if ultima:
        ultima_dict = {
            "nombre": ultima.get("nombre"),
            "fecha": ultima.get("fecha"),
            "num_personas": ultima.get("num_personas"),
            "ocasion_especial": ultima.get("ocasion_especial"),
            "alergias": ultima.get("alergias"),
        }

    # Nombre "preferido" para saludar: si hay reserva futura, usar el de la
    # reserva mas proxima (mas reciente intencion del cliente). Si no, el
    # de la ultima visita pasada.
    nombre_preferido = None
    if futuras:
        # Ordenado ASC por fecha en el query? No, el query usa DESC. Las
        # futuras estan al principio (mas lejanas). Tomamos la mas proxima
        # (la de fecha menor entre las futuras).
        prox_ordenadas = sorted(futuras, key=lambda r: r.get("fecha", ""))
        # Necesitamos el nombre que sigue en la fila original
        for r in filas:
            if r.get("id") == prox_ordenadas[0]["id"]:
                nombre_preferido = r.get("nombre")
                break
    if not nombre_preferido and ultima:
        nombre_preferido = ultima.get("nombre")

    return {
        "es_recurrente": len(pasadas_confirmadas) > 0,
        "num_visitas_pasadas": len(pasadas_confirmadas),
        "ultima_visita": ultima_dict,
        "reservas_futuras": futuras[:3],
        "tiene_no_show_reciente": no_shows_recientes > 0,
        "nombre_preferido": nombre_preferido,
    }


def _normalizar_nombre(nombre: Optional[str]) -> str:
    """Para comparar nombres ignorando mayusculas, tildes y espacios extras."""
    import unicodedata
    if not nombre:
        return ""
    nfd = unicodedata.normalize("NFD", nombre)
    sin_tildes = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return " ".join(sin_tildes.lower().split())


def cancelar_reserva(
    input_data: dict,
    telefono_canal: Optional[str] = None,
    canal_actual: str = "web",
) -> dict:
    """
    Cancela por id_reserva o por (telefono + fecha) con verificacion de
    identidad para evitar que terceros cancelen reservas ajenas (issue #18).

    Verificaciones de seguridad:
    1. Si la reserva fue por WhatsApp/voz, solo se puede cancelar si:
       - El telefono actual del canal coincide con el de la reserva, O
       - El cliente confirma el nombre exacto de la reserva.
    2. Si la reserva fue por web, solo se puede cancelar:
       - Confirmando el nombre exacto de la reserva (no podemos atar
         por session_id porque puede cambiar; el nombre es la prueba).

    Args en input_data:
        id_reserva (opt), telefono (opt), fecha (opt), motivo (opt),
        nombre_confirmacion (opt): nombre que el cliente nos da para
            verificar identidad.
    """
    id_reserva = (input_data.get("id_reserva") or "").strip() or None
    telefono_input = (input_data.get("telefono") or "").strip()
    telefono = _normalizar_telefono(telefono_input or telefono_canal or "")
    fecha_str = (input_data.get("fecha") or "").strip()
    motivo = (input_data.get("motivo") or "").strip() or None
    nombre_confirmacion = (input_data.get("nombre_confirmacion") or "").strip() or None

    if not id_reserva and not (telefono and fecha_str):
        return {
            "status": "error",
            "mensaje": (
                "Para cancelar necesito el ID de reserva, o bien telefono "
                "y fecha de la reserva."
            ),
        }

    try:
        # Buscar la reserva
        if id_reserva:
            res = (
                supabase.table("reservas")
                .select("*")
                .eq("id", id_reserva)
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
                supabase.table("reservas")
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
                    "No he encontrado una reserva confirmada con esos datos. "
                    "Comprueba los datos con el cliente o pasa el caso al duenno."
                ),
            }

        reserva = res.data[0]
        if reserva.get("estado") == "cancelada":
            return {
                "status": "ya_cancelada",
                "mensaje": (
                    f"La reserva (ID {reserva['id']}) ya estaba cancelada. "
                    f"Confirma al cliente que no figura."
                ),
            }

        # ─── VERIFICACION DE IDENTIDAD (issue #18) ─────────────────
        canal_reserva = reserva.get("canal_origen") or "web"
        tel_reserva = _normalizar_telefono(reserva.get("telefono") or "")
        tel_canal_norm = _normalizar_telefono(telefono_canal or "")

        # Caso 1: cancelacion desde el MISMO canal y MISMO telefono
        # del que se hizo la reserva (whatsapp/voz). Suficiente prueba.
        autorizada_por_canal = (
            canal_actual == canal_reserva
            and tel_canal_norm
            and tel_canal_norm == tel_reserva
        )

        # Caso 2: el cliente confirma el nombre exacto. Vale para todos
        # los canales y casos.
        autorizada_por_nombre = (
            nombre_confirmacion
            and _normalizar_nombre(nombre_confirmacion) == _normalizar_nombre(reserva.get("nombre"))
        )

        if not (autorizada_por_canal or autorizada_por_nombre):
            return {
                "status": "verificacion_pendiente",
                "mensaje": (
                    "Por seguridad necesito verificar tu identidad antes "
                    "de cancelar. Pidele al cliente que CONFIRME el NOMBRE "
                    "EXACTO con el que se hizo la reserva, y vuelve a "
                    "llamar a cancelar_reserva pasando ese nombre en el "
                    "campo 'nombre_confirmacion'."
                ),
            }

        updates = {
            "estado": "cancelada",
            "motivo_cancelacion": motivo,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        supabase.table("reservas").update(updates).eq("id", reserva["id"]).execute()

        # Notificar a lista de espera (issue #6): puede haber alguien
        # esperando esa fecha+turno. Best-effort, no bloquea la cancelacion.
        try:
            from core.lista_espera import procesar_cancelacion
            procesar_cancelacion(
                fecha=reserva.get("fecha"),
                turno=reserva.get("turno") or "cena",
                hora_libre=(reserva.get("hora") or "21:00")[:5],
            )
        except Exception as e:
            log.warning("Lista espera matching fallo: %s", e)

        return {
            "status": "cancelada",
            "reserva_id": reserva["id"],
            "mensaje": (
                f"Reserva cancelada (ID {reserva['id']}, era para el "
                f"{reserva.get('fecha')} a las {reserva.get('hora')}). "
                f"Confirma al cliente que la cancelacion ha quedado registrada."
            ),
        }

    except Exception as e:
        return {
            "status": "error",
            "mensaje": f"No se pudo cancelar la reserva: {str(e)}",
        }
