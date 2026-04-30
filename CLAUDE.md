# CLAUDE.md — Pautas para el repo demo-restaurante

> **Lee este archivo al empezar cualquier sesion.** Resume el estado del proyecto, la arquitectura y las reglas que NO se deben romper.

---

## 1. Que es este repo

Demo de **chatbot + agente telefonico para un RESTAURANTE**. Fork manual de la plantilla "AlnoraIA" (sin historial git).

Proposito: el comercial de Alnora IA usa esta demo para ensenar a clientes potenciales del sector restauracion (en visita fisica o por llamada) como seria un sistema multi-canal de IA aplicado a su negocio: reservas, consulta de carta, horarios, alergias, atencion telefonica.

---

## 2. Restaurante demo

Casa Lola (arroceria ficticia en Russafa, Valencia). **Todos los datos
especificos viven en `config/restaurante.yaml`** — nombre, carta, horarios,
colores de marca, telefono, direccion, CORS. Editar ese fichero basta
para adaptar el repo a otro cliente (issue #11, fase plantilla).

El fichero `core/restaurante_data.py` es solo un loader del YAML y
expone la misma API que antes (`RESTAURANTE`, `CARTA`, `HORARIOS`, etc)
para que el resto del codigo no se entere.

Plantilla para nuevos clientes: `config/restaurante.example.yaml`.

---

## 3. Stack y servicios externos

Identico a la plantilla Alnora, con cuentas SEPARADAS:

| Servicio | Configuracion |
|---|---|
| **FastAPI + uvicorn** | Hosting en Railway (proyecto independiente). |
| **Supabase** | Proyecto INDEPENDIENTE del de Alnora. URL y service role propias. |
| **Anthropic Claude** | `claude-haiku-4-5`. Misma API key que Alnora. |
| **Vapi** | Assistant NUEVO ("Lola"), NO el de Kara. Voz Azure femenina ES-ES distinta de Ximena. |
| **Twilio** | Cuenta NUEVA con sandbox propio (palabra clave distinta a la de Alnora). |
| **Resend** | Misma cuenta, mismo destinatario. Cuando haya dominio del restaurante, dominio nuevo. |

---

## 3.5 Estructura del repo

```
demo-restaurante/
├── server.py                     # entry FastAPI: monta todos los routers
├── index.html                    # landing dinamica (lee /api/restaurante)
├── Procfile                      # arranque Railway
├── requirements.txt              # deps produccion (incluye pyyaml)
│
├── config/
│   ├── restaurante.yaml          # ← fuente unica de verdad del cliente
│   └── restaurante.example.yaml  # plantilla para nuevos clientes
│
├── core/                         # logica compartida por los 3 canales
│   ├── restaurante_data.py       # loader del YAML (API compat legacy)
│   ├── config.py                 # carga .env + clientes Anthropic/Supabase
│   ├── logger.py                 # setup_logging + get_logger (issue #14)
│   ├── health.py                 # chequeos de dependencias (issue #13)
│   ├── memory.py / clientes.py / reservas.py / mesas.py
│   ├── lista_espera.py / recordatorios.py / encuestas.py / no_show.py
│   ├── escalacion_restaurante.py / notifications.py / whatsapp_out.py
│   ├── prompts.py / lang_detect.py / guardrails.py
│   └── messaging/                # provider pattern (Twilio + Meta stub)
│
├── chatbot_whatsapp/             # /whatsapp y /whatsapp/meta
├── chatbot_web/                  # /web/chat
├── agente_telefonico/            # /vapi/tool/* y /vapi/server-url
├── landing/                      # /supabase/webhook/reserva-nueva
├── admin/                        # /admin + dashboard.html
├── health/                       # /health
│
├── scripts/                      # crons de Railway (CLI con print() OK)
│   ├── enviar_recordatorios.py
│   ├── detectar_no_shows.py
│   ├── enviar_encuestas.py
│   └── run_evals.py
│
├── tests/
│   ├── conftest.py               # fakes: Supabase, Claude, Resend, Twilio
│   ├── test_smoke.py             # ~73 smoke tests (rapidos, mockeados)
│   ├── test_evals.py             # ~24 evals (marker @pytest.mark.eval, llama a Claude real)
│   └── eval_helpers.py
│
├── supabase/migrations/          # 6 migraciones SQL en orden
└── .github/workflows/tests.yml   # CI: smoke tests Python 3.12
```

---

## 4. Tablas Supabase

- `clientes` — CRM unificado del restaurante. Columnas: id, nombre, telefono (UNIQUE), email, alergias, notas, canal_origen ∈ {web, whatsapp, voz, escalacion}, ultima_interaccion, created_at.
- `reservas` — id, cliente_id (FK), fecha, hora, num_personas, alergias, ocasion_especial, notas, estado ∈ {confirmada, cancelada, completada}, canal_origen, created_at.
- `whatsapp_conversaciones` — historial por telefono.
- `web_conversaciones` — historial por session_id.
- `llamadas_voz` — transcripciones + resumenes estructurados.
- `escalaciones` — con traza de email (resend_message_id, email_status, email_error).
- `seguimientos_pendientes` — handoff voz->WhatsApp.

Cuando toques schema: **usar siempre `apply_migration`** con nombre en snake_case, nunca `execute_sql` para DDL.

---

## 5. Tools del restaurante

| Tool | Descripcion | Canales |
|---|---|---|
| `reservar_mesa` | **Crea** reserva. Upsert por (telefono, fecha, turno). Requiere nombre, telefono, fecha, hora, num_personas. Opcional: alergias, ocasion, notas. | web, wa, voz |
| `modificar_reserva` | **Modifica IN-PLACE** una reserva existente por `id_reserva` (lo da `buscar_reservas`). UPDATE puro: conserva id, alergias, etc. Reasigna mesas si cambia fecha/hora/personas. **NUNCA** usar `cancelar_reserva + reservar_mesa` para "mover" — eso crea duplicados. | web, wa, voz |
| `buscar_reservas` | Devuelve reservas futuras por telefono y/o nombre. Pensada para iniciar el flujo de cancelacion/modificacion (en lugar de pedir datos uno a uno). | web, wa, voz |
| `consultar_disponibilidad` | Hueco para fecha + hora + num_personas. Opcional: turno_flexible. | web, wa, voz |
| `cancelar_reserva` | Cancela por id_reserva o por (telefono + fecha). Llamala SOLO tras `buscar_reservas` con confirmacion del cliente. | web, wa, voz |
| `apuntar_lista_espera` | Apunta cliente en lista para fecha/turno lleno. | web, wa, voz |
| `consultar_carta` | Devuelve carta o categoria. Filtro alergeno opcional. **Datos en YAML** (`config/restaurante.yaml`). | web, wa, voz |
| `consultar_horario` | Devuelve horario, opcional por dia. **Datos en YAML**. | web, wa, voz |
| `escalar_a_humano` | Pasa el caso al dueño/encargado por email (Resend). **Valida datos minimos** (nombre + telefono): sin ellos devuelve `datos_insuficientes` sin enviar email. | web, wa, voz |
| `derivar_a_whatsapp` | Handoff voz->WhatsApp cuando el agente no puede capturar un dato por voz. | solo voz |
| `consultar_historial` | Reconocer cliente recurrente por telefono (lee `llamadas_voz`). | solo voz |

---

## 6. Reglas estrictas (heredadas de la plantilla Alnora)

### Idioma y tono
- **Castellano peninsular** siempre. Jamas latinoamericano ("computadora", "celular", "carro"). Si "ordenador", "movil", "coche".
- Tutea al cliente por defecto.
- Tono: cercano, calido y resolutivo, como una jefa de sala con experiencia.

### Codigo
- **No uses emojis** salvo en notificaciones a usuario final (emails de marca o prints de log donde ya existen).
- **Python 3.12** en produccion (Railway) pero el repo se prueba en **Python 3.9** local del usuario -> evita sintaxis `str | None`, usa `Optional[str]` de `typing`.
- **No crees archivos .md** salvo que el usuario lo pida explicitamente. Este CLAUDE.md es la excepcion.
- Comentarios en ASCII donde puedan, sin tildes.

### Tests
- **Antes de commitear cambios de codigo que toquen endpoints o tools, corre `pytest`**.
- Si algun test falla tras un refactor, **arregla antes de pushear**.
- Los tests estan mockeados (FakeSupabase, FakeClaude, FakeProvider) — no deben tocar red ni BD real.
- Si anades un endpoint nuevo o una tool, anade 1-2 smoke tests en `tests/test_smoke.py`.

### Evals (issue #12)
Suite separada que valida COMPORTAMIENTO del bot llamando a Claude
REAL. Vive en `tests/test_evals.py` con marker `@pytest.mark.eval`.

NO corren con `pytest` normal (excluidos por defecto en `pytest.ini`).
Para correrlos:
```
pytest -m eval                    # todos
pytest -m eval -k web             # solo web
python scripts/run_evals.py       # runner con UI mejorada
```

Requieren `ANTHROPIC_API_KEY` real en `.env` (no la dummy del conftest).
Si no esta, los evals se SKIPan automaticamente.

Coste: ~0.0001€ por eval con haiku. 25 evals ≈ 0.0025€ por corrida.

Cuando ATAQUES un prompt importante, corre los evals antes y despues:
- Antes: `pytest -m eval -v` y ve cuales fallan ya (baseline).
- Tras tu cambio: vuelve a correrlos. Si rompes alguno que antes pasaba,
  has introducido regresion.

Anadir un eval nuevo:
1. Edita `tests/test_evals.py`.
2. Sigue el patron existente con marker `@pytest.mark.eval`.
3. Usa los helpers de `tests/eval_helpers.py` (correr_eval_web,
   correr_eval_whatsapp, asserts).

Para voz (Lola/Vapi) los evals se haran aparte — ver issue #23.

### Git y flujo de PRs
- **No crear commits sin que el usuario lo pida**.
- **Branch protection activada en `main`**: no se puede pushear directo.
  Todo va por PR con el check "Smoke tests (Python 3.12)" en verde.
- Flujo: rama nueva -> commit -> push -> `gh pr create` -> esperar CI verde
  (~30s) -> notificar al usuario para merge. SIEMPRE esperar a ver CI en
  verde antes de pedir merge.
- Commits siempre con `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- Formato de commit: primera linea corta (`feat(...):`, `fix(...):`,
  `refactor(...):`), cuerpo explicando el **por que**.
- Nunca `git push --force` a `main` sin confirmacion explicita.
- Nunca `--no-verify` sin que lo pida el usuario.
- Pueden coexistir varias PRs abiertas; el usuario las mergea en el orden
  que le cuadre.

### Variables de entorno
- El `.env` real vive en la raiz del repo y en Railway (produccion).
- **Nunca** commitear un `.env`. Esta en `.gitignore`.
- Las credenciales son DISTINTAS a las de Alnora (Supabase nuevo, Twilio nuevo, Vapi assistant nuevo).

### Supabase
- **RLS activado** en todas las tablas.
- El frontend de la landing usa **publishable key**, el backend usa **service role**.

---

## 7. Convenciones internas

### Normalizacion de telefono
- Formato canonico: `+34XXXXXXXXX` (con `+`, sin espacios, sin prefijo de canal).
- Usa `core.memory._normalizar_telefono()` siempre que proceses un numero de cualquier fuente.
- En `whatsapp_conversaciones` y `seguimientos_pendientes`, la clave es el telefono **con prefijo `whatsapp:`** (legacy de la plantilla, no tocar). En `llamadas_voz` y `escalaciones` es el telefono limpio.

### Patron provider para WhatsApp
- `core/messaging/` es la abstraccion. Cualquier nuevo canal implementa `MessagingProvider`.
- El resto del codigo llama a `get_provider().enviar(...)` y `get_provider().parsear_entrante(...)`, nunca al SDK directamente.

### Tool use en chatbots
- Bucle de hasta 5 iteraciones.
- Tras ejecutar `reservar_mesa`, si la tool devuelve OK -> confirmar al cliente con texto natural.

### Flujos de cancelacion y modificacion (issue #33 + PR #45)
Los dos flujos arrancan IGUAL: `buscar_reservas` primero. NUNCA interrogar al cliente con telefono+fecha+nombre uno a uno.

- **Cancelar**: `buscar_reservas` -> mostrar reserva -> confirmacion del cliente -> `cancelar_reserva(id_reserva=...)`.
- **Modificar** (mover fecha/hora, cambiar personas, alergias...): `buscar_reservas` -> mostrar reserva -> proponer cambio -> confirmacion -> `modificar_reserva(id_reserva=..., fecha=..., ...)` UNA sola vez.
- En WA/voz: `buscar_reservas` usa el telefono del canal (no se pide al cliente).
- En web: hay que pedir nombre + telefono al cliente porque no hay tel del canal.

### Guardrail anti-alucinacion (`core/guardrails.py`)
Categorias separadas: `reservar_mesa` (creacion: "Mesa reservada", "apuntada para..."), `cancelar_reserva` ("cancelada sin problema", "anulada", "Hecho, cancelada"), `modificar_reserva` ("reserva movida/cambiada/modificada al X"), `escalar_a_humano`, `derivar_a_whatsapp`, `apuntar_lista_espera`. Cada una con su propio recovery message.

Si el bot afirma una accion sin que la tool correspondiente este en `tools_ok`, se hace 1 auto-retry inyectando un aviso + reglas duras. Si tras retry sigue sin ejecutarse, se sustituye el reply por el recovery (texto que pide datos al cliente para reintentar).

`_ESTADOS_EXITO_POR_TOOL` en los webhooks define que `status` cuenta como exito por tool. Solo si la tool devuelve uno de esos estados se anade a `tools_ok`.

### Datos del restaurante
- Carta, horarios, branding, contacto, CORS origins, Google Review URL —
  todo en `config/restaurante.yaml` (issue #11). `core/restaurante_data.py`
  lo carga al arranque y expone `RESTAURANTE`, `CARTA`, `HORARIOS`,
  `BRANDING`, `GOOGLE_REVIEW_URL`, `CORS_ORIGINS_DEFAULT`,
  `AFORO_MAX_POR_TURNO`, `GRUPO_GRANDE_DESDE`.
- Los HTML (`index.html`, `admin/dashboard.html`) leen `GET /api/restaurante`
  al cargar y se repintan: textos, colores CSS, titulos, href de tel/mail/maps.
  Para marcar un nodo como dinamico: `data-r="nombre"`, `data-r-tpl="{nombre}..."`,
  `data-r-href-tel="telefono"`, `data-r-href-mail="email"`, `data-r-href-maps="direccion"`.
- Los datos viven en codigo (YAML), NO en BD. Demo siempre disponible
  aunque Supabase este caido. Si un cliente quiere editar por panel,
  se migra a tabla en el futuro.

### Branding modular por canal (issue #55)
El YAML se reorganizo en bloques OPCIONALES por canal para facilitar
onboarding de clientes que solo quieren parte del producto. Estructura:

| Bloque YAML | Cuando rellenarlo | Si vacio |
|---|---|---|
| `restaurante:` | Siempre | n/a |
| `bot:` | Siempre que use cualquier canal IA | Prompts caen a "asistente" generico |
| `landing:` | Solo si usa la landing Casa Lola completa (GET /) | La landing carga sin colores ni imagenes personalizados |
| `widget_web:` | Solo si embede el widget chat (en nuestra landing o en su web) | El widget hereda colores de `landing.colores`, avatar default 💬 |
| `emails:` | Recomendado siempre | Usa env var RESEND_FROM o fallback Resend, sin logo |

Onboarding rapido segun lo que el cliente quiera:

- **Solo WA**: `restaurante` + `bot` + `horarios` + `capacidad` + `reservas` + `carta` + `emails`. Borrar `landing` y `widget_web`.
- **Widget en su web**: anade `widget_web` (colores propios si su web tiene paleta distinta).
- **Landing Casa Lola completa**: anade `landing` + sube 3 imagenes a `static/branding/`.

`core/restaurante_data.py` expone helpers con defaults graceful:
`nombre_bot()`, `descripcion_bot()`, `widget_web_config()`,
`landing_config()`, `email_from_address()`, `email_logo_url()`.

`/api/restaurante` devuelve los bloques nuevos (`bot`, `landing`,
`widget_web`) ademas de `branding` legacy (compat con codigo viejo
del frontend).

⚠️ **Voz (Vapi)**: el prompt vive estatico en el panel de Vapi. Cuando
edites `bot.nombre` en el YAML hay que **recopiar manualmente** el
output de `prompt_voz_estatico()` al panel de Vapi. No es automatizable.

⚠️ **Emails al duenno**: la URL del logo en `emails.logo_url` debe ser
ABSOLUTA (https://...). Las rutas relativas no funcionan en clientes
de correo.

### Logging estructurado (issue #14)
- Usa `from core.logger import get_logger; log = get_logger(__name__)`
  en cada modulo nuevo. **Nada de `print()`** en codigo de produccion.
- Scripts CLI (`scripts/*.py`) SI pueden usar `print()` (output decorativo).
- Niveles: `log.info` normal, `log.warning` error recuperable, `log.error`
  critico (con `exc_info=True` para incluir stack trace).
- Nivel configurable con env var `LOG_LEVEL` (default INFO).

### Health check (issue #13)
- `GET /health` devuelve status de Supabase, Anthropic, Twilio, Resend.
  200 healthy/degraded, 503 down. Railway lo usa como healthcheck path.
- Logica en `core/health.py`. Criticas: supabase + anthropic. Twilio y
  resend solo validan formato de credenciales (no llamada real).

---

## 8. Flujo de trabajo recomendado

1. **Entiende que quiere el usuario** — si algo no queda claro, pregunta antes de escribir codigo.
2. **Explora primero si el tema no es trivial** — usa Grep/Glob/Read antes de editar a ciegas.
3. **Escribe el cambio** — Edit o Write.
4. **Corre `pytest`** si tocaste codigo que afecta a endpoints o tools.
5. **Commit + push** SOLO si el usuario lo pide.
6. **Informa al usuario** con un resumen corto.

---

## 9. Origen de la plantilla

Repo madre: https://github.com/theGSM03/AlnoraIA

Si surgen mejoras genericas (provider Meta, tool nueva reutilizable, fix de patron core), avisar al usuario para portarlas con `git cherry-pick`.

NO modificar el repo Alnora desde aqui.

---

## 10. Estado actual

Infra y funcionalidad core:
- [x] `config/restaurante.yaml` como fuente de verdad, loader en `core/restaurante_data.py` (issue #11).
- [x] System prompts adaptados a los 3 canales (WA, web, voz) con `RESTAURANTE['nombre']` dinamico.
- [x] 8 tools del restaurante implementadas y testeadas.
- [x] Landing (`index.html`) y panel admin (`admin/dashboard.html`) dinamicos via `/api/restaurante`.
- [x] Supabase con 6 migraciones aplicadas + seed de mesas.
- [x] Vapi Assistant "Lola" configurado (voz Azure ES).
- [x] Twilio sandbox operativo (`+14155238886`).
- [x] Desplegado en Railway (`demo-restaurante-production.up.railway.app`).
- [x] Demo end-to-end funcionando en los 3 canales.

Calidad tecnica:
- [x] 94+ smoke tests + CI GitHub Actions en cada push (branch protection on).
- [x] Evals con Claude real (issue #12) — ~24 tests marker `@pytest.mark.eval`.
- [x] Logging estructurado con niveles + LOG_LEVEL configurable (issue #14).
- [x] `GET /health` con chequeos de Supabase/Anthropic/Twilio/Resend (issue #13).
- [x] Guardrails server-side anti-alucinacion (creacion + cancelacion + modificacion).
- [x] README comercial profesional (issue #16).
- [x] Plantillizacion via `config/restaurante.yaml` (issue #11).
- [x] Email diferenciado al duenno: nueva (verde) / modificada (naranja) / cancelada (rojo) (issue #31).
- [x] Tool `buscar_reservas` + flujo cancelacion por canal (issue #33).
- [x] Normalizacion telefonos ES sin +34 (issue #35).
- [x] Tool `modificar_reserva` UPDATE in-place — evita duplicados al mover (PR #45).

Pendiente:
- [ ] Mejorar prompt voz Lola (issue #2).
- [ ] Mejorar prompt WA pro (issue #3).
- [ ] Bugs de estilo en agente voz (issue #1).
- [ ] Migracion Twilio -> Meta Cloud API (issue #15, provider pattern listo).
- [ ] Evals de voz (issue #23).
- [ ] Rate limiting endpoints publicos.
- [ ] UptimeRobot externo sobre `/health` (issue #28) — para dia de demo real.
- [ ] Soporte delivery (issue #40, prioridad baja, ~15h).
- [ ] Screenshots README comercial (issue #25).
- [ ] Checklist visible de pruebas en panel (issue #21).

---

## 10.5 Sistema de labels en GitHub

Las issues llevan etiquetas para escanearlas rapido. Crear labels con `gh label create` en cualquier momento; las nuevas issues deben llevar siempre **al menos** un `area:*`, una `priority:*` y un tipo (`bug` / `enhancement` / `feat` / `documentation`).

**Area** (que parte del producto toca):
- `area:chatbot` — afecta a uno o varios chatbots
- `area:whatsapp` — solo WhatsApp
- `area:web` — solo chat web
- `area:voz` — agente Vapi (Lola)
- `area:landing` — landing publica + branding
- `area:panel-admin` — `/admin`
- `area:backend` — core, BD, emails, infra
- `area:plantilla` — onboarding nuevos clientes

**Prioridad**:
- `priority:high` (rojo) — hacer cuanto antes
- `priority:medium` (amarillo) — importante, no urgente
- `priority:low` (verde) — nice-to-have

Comando para crear label nuevo:
```bash
gh label create "area:nuevo" --color "1D76DB" --description "..." --force
```

Comando para etiquetar issue:
```bash
gh issue edit <N> --add-label "area:chatbot,priority:medium,bug"
```

Las PRs deben llevar las MISMAS etiquetas que las issues que cierran (o las equivalentes si no cierran ninguna). Asi el `gh pr list` y el `gh issue list` se cruzan visualmente.

---

## 10.6 Diagnostico backend desde la sesion

Para ver BD, logs y schema sin pedir al usuario que copie SQL:

**MCP de Supabase (`supabase-clover`)**: configurado con un PAT por cuenta del usuario. Si el `claude mcp list` dice "Connected", las tools `mcp__supabase-clover__*` estan disponibles tras un ToolSearch.

**Fallback con curl + API REST Management** (si el MCP no expone las tools en el agente):
```bash
curl -s -X POST "https://api.supabase.com/v1/projects/<PROJECT_REF>/database/query" \
  -H "Authorization: Bearer sbp_..." \
  -H "Content-Type: application/json" \
  -d '{"query":"SELECT ... FROM reservas LIMIT 5;"}'
```

El PROJECT_REF de demo-restaurante: `zmkzphvydevseijcsqzu`.
El PAT esta en `claude mcp get supabase-clover` -> Headers -> Bearer.

**Reproducir bugs en local apuntando a la BD de produccion**:
```bash
python -m uvicorn server:app --port 8765 --log-level info  # background
curl -X POST http://localhost:8765/web/chat -H "Content-Type: application/json" \
  -d '{"session_id":null,"message":"hola"}'
# Lee output del background con cat $TASK_OUTPUT
```
Util para diagnosticar si un bug es del codigo en main o de la version desplegada en Railway. Permite anadir logs temporales sin desplegar.

---

## 11. Cosas que el usuario ha dicho explicitamente

- Trabajamos en **castellano peninsular**.
- **No anunciar la preview en cada edicion** — evitar frases "visible en el panel de preview" tras cada Edit.
- **Correr los tests por defecto** tras cambios importantes. No esperar a que el usuario lo pida.
- **Plantilla reutilizable**: cuando se aplique una mejora generica (nueva tool, nuevo endpoint, refactor, fix), pensar si deberia portarse a la plantilla base (`config/restaurante.yaml` + codigo portable). Evitar dejar datos hardcodeados que obliguen a editarlos al clonar a otro cliente.
- **Siempre avisar de pendientes manuales** al terminar una tarea. Cuando algo no puedo hacer yo (configurar Railway, activar branch protection, crear cuenta en servicio externo), reportar al final del mensaje con formato:
  > **⚠️ Pendiente por tu parte:**
  > 1. Que hay que hacer
  > 2. Como se hace (panel + ruta + valores)
  > 3. Por que importa (que se rompe si no)
- **Explicar en lenguaje claro** los logros tras cerrar una issue importante (no solo "hecho"). El usuario valora entender QUE se ha ganado a nivel de producto/dia a dia, no solo que compilo.
- **PRs con CI verde antes de pedir merge**. Si CI falla, arreglar hasta que este verde. Nunca avisar de merge con tests en rojo.
- **Issues con etiquetas SIEMPRE**: cualquier issue nueva debe llevar al menos un `area:*`, una `priority:*` y un tipo (`bug` / `enhancement` / `feat` / `documentation`). Ver seccion 10.5.
- **Modificar reservas se hace IN-PLACE**: usar `modificar_reserva(id_reserva, ...)` nunca `cancelar + reservar_mesa`. Es regla de producto: el dueno no debe recibir 2-3 emails confusos por un cambio de fecha.
- **Nada de "como imaginaba" o tono condescendiente**: si el bot tiene que rechazar algo (lunes cerrado, fecha pasada), responde directo y amable, sin frases que insinuen que el cliente deberia haberlo sabido.
- **Confirmacion explicita antes de cada accion sensible**: reservar, cancelar, modificar, escalar — el bot SIEMPRE pide confirmacion ("¿Confirmas?") antes de tocar BD. No interpretes "perfecto, para el viernes 8, Eva, 691122334, confirmo" como confirmacion final si aun no diste el resumen.
- **Emails diferenciados por accion**: nueva reserva (verde), reserva modificada (naranja), reserva cancelada (rojo). Subjects con emoji distintivo. Configurado via webhook UPDATE en Supabase + funcion `notificar_cambio_reserva`.
- **Sesiones de QA largas**: el flujo es bateria de tests manual -> usuario reporta resultado por chat -> yo verifico backend (BD, conversaciones, emails) via curl/MCP -> diagnosticar y abrir PR de fix si hace falta. Tras cada PR mergeado: limpiar BD para no arrastrar datos de pruebas anteriores.
