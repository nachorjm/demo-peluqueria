# CLAUDE.md — Pautas para el repo demo-peluqueria

> **Lee este archivo al empezar cualquier sesion.** Resume el estado del proyecto, la arquitectura y las reglas que NO se deben romper.

---

## 1. Que es este repo

Demo de **chatbot + agente telefonico para una PELUQUERIA**. Fork manual de la plantilla "AlnoraIA" (sin historial git), adaptada al dominio de salones de belleza/peluqueria a partir de la rama demo-restaurante.

Proposito: el comercial de Alnora IA usa esta demo para ensenar a clientes potenciales del sector peluqueria/estetica (en visita fisica o por llamada) como seria un sistema multi-canal de IA aplicado a su negocio: agendar citas, consulta de servicios, horarios, alergias a tintes, atencion telefonica.

---

## 2. Salon demo

Salon Mara (peluqueria unisex ficticia en Malasana, Madrid). **Todos los datos
especificos viven en `config/peluqueria.yaml`** — nombre, servicios, horarios,
estilistas, colores de marca, telefono, direccion, CORS. Editar ese fichero
basta para adaptar el repo a otra peluqueria.

El fichero `core/peluqueria_data.py` es solo un loader del YAML y expone
constantes (`SALON`, `BOT`, `LANDING`, `WIDGET_WEB`, `HORARIOS`, `SERVICIOS`,
`ESTILISTAS`, etc.) y helpers para que el resto del codigo no se entere del
formato.

Plantilla para nuevos clientes: `config/peluqueria.example.yaml`.

---

## 3. Stack y servicios externos

Identico a la plantilla Alnora, con cuentas SEPARADAS:

| Servicio | Configuracion |
|---|---|
| **FastAPI + uvicorn** | Hosting en Railway (proyecto independiente). |
| **Supabase** | Proyecto INDEPENDIENTE del de Alnora y de demo-restaurante. |
| **Anthropic Claude** | `claude-haiku-4-5`. Misma API key que Alnora. |
| **Vapi** | Assistant NUEVO ("Mara"). Voz Azure `es-ES-ElviraNeural`, distinta de Ximena (Kara/Alnora) y Lola (demo-restaurante). |
| **Twilio** | Cuenta NUEVA con sandbox propio. Palabra clave actual: `join toy-dish` (distinta de `join produce-go` de Casa Lola). |
| **Resend** | Misma cuenta, mismo destinatario. Cuando haya dominio del salon, dominio nuevo. |

URLs/IDs concretos del entorno actual:

| Recurso | Valor |
|---|---|
| Supabase project ref | `eoeinoilkklmiqcybwnb` |
| Supabase URL | `https://eoeinoilkklmiqcybwnb.supabase.co` |
| Railway public URL | `https://web-production-e8a8c.up.railway.app` |
| Vapi assistant id | guardado en `.setup-artifacts/vapi_assistant_result.json` (gitignored) |

---

## 3.5 Estructura del repo

```
demo-peluqueria/
├── server.py                     # entry FastAPI: monta todos los routers
├── index.html                    # landing dinamica (lee /api/salon)
├── Procfile                      # arranque Railway
├── requirements.txt              # deps produccion (incluye pyyaml)
│
├── config/
│   ├── peluqueria.yaml           # ← fuente unica de verdad del cliente
│   └── peluqueria.example.yaml   # plantilla para nuevos clientes
│
├── core/                         # logica compartida por los 3 canales
│   ├── peluqueria_data.py        # loader del YAML + helpers
│   ├── config.py                 # carga .env + clientes Anthropic/Supabase
│   ├── logger.py                 # setup_logging + get_logger
│   ├── health.py                 # chequeos de dependencias (/health)
│   ├── memory.py / clientes.py / citas.py / estilistas.py / servicios.py
│   ├── escalacion.py / notifications.py / whatsapp_out.py
│   ├── calendario.py / prompts.py / lang_detect.py / guardrails.py
│   └── messaging/                # provider pattern (Twilio + Meta stub)
│
├── chatbot_whatsapp/             # /whatsapp y /whatsapp/meta
├── chatbot_web/                  # /web/chat
├── agente_telefonico/            # /vapi/tool/* y /vapi/server-url
├── landing/                      # /supabase/webhook/cita-nueva, cita-modificada
├── admin/                        # /admin + dashboard.html
├── health/                       # /health
│
├── scripts/                      # crons de Railway (CLI con print() OK)
│
├── tests/
│   ├── conftest.py               # fakes: Supabase, Claude, Resend, Twilio
│   └── test_smoke.py             # smoke tests (rapidos, mockeados)
│
├── supabase/migrations/          # migracion inicial consolidada (8 tablas)
└── .github/workflows/tests.yml   # CI: smoke tests Python 3.12
```

---

## 4. Tablas Supabase

Schema consolidado en `supabase/migrations/0001_initial_schema.sql` (NO hay
seed de estilistas: viven en YAML).

- `clientes` — CRM unificado del salon. id, nombre, telefono (UNIQUE), email,
  alergias, notas, canal_origen ∈ {web, whatsapp, voz, escalacion},
  ultima_interaccion, created_at.
- `citas` — id, cliente_id (FK), nombre, telefono, fecha, hora_inicio,
  hora_fin, estilista_id_yaml (string que referencia un estilista del YAML),
  alergias, notas, estado ∈ {confirmada, cancelada, completada},
  motivo_cancelacion, canal_origen, created_at, updated_at.
- `cita_servicios` — relacion M-N: cada fila es un servicio de una cita
  (snapshot de precio y duracion al agendar para que no cambien
  retroactivamente al editar el YAML).
- `whatsapp_conversaciones` — historial por telefono (clave con prefijo
  `whatsapp:`).
- `web_conversaciones` — historial por session_id.
- `llamadas_voz` — transcripciones + resumenes Vapi.
- `escalaciones` — con traza de email (resend_message_id, email_status,
  email_error). Motivos adaptados a peluqueria
  (`servicio_no_disponible`, `caso_complejo`, etc.).
- `seguimientos_pendientes` — handoff voz->WhatsApp con `pregunta_pendiente`
  enum (servicio, fecha_y_hora, estilista, confirmacion, nombre, alergias,
  otro).

Cuando toques schema: **usar siempre `apply_migration`** con nombre en
snake_case, nunca `execute_sql` para DDL.

---

## 5. Tools del salon

10 tools en total. Las primeras 8 viven en `chatbot_whatsapp/tools.py:TOOLS`
y se reutilizan en web y voz. Las 2 ultimas solo existen en voz.

| Tool | Descripcion | Canales |
|---|---|---|
| `agendar_cita` | **Crea** una cita. Requiere nombre, telefono, fecha, hora_inicio y servicios (lista de nombres exactos del catalogo). Opcional: estilista_preferido, alergias, notas. La duracion total se calcula sumando duracion_min de cada servicio. | web, wa, voz |
| `modificar_cita` | **Modifica IN-PLACE** una cita por `id_cita` (lo da `buscar_citas`). UPDATE puro: conserva id y alergias salvo que se sobreescriban. **NUNCA** usar `cancelar_cita + agendar_cita` para "mover" — eso crea duplicados y emails confusos. | web, wa, voz |
| `buscar_citas` | Devuelve citas futuras por telefono y/o nombre. Pensada para iniciar el flujo de cancelacion/modificacion. | web, wa, voz |
| `consultar_disponibilidad` | Hueco para fecha + hora + servicios. Opcional: estilista_preferido. | web, wa, voz |
| `cancelar_cita` | Cancela por id_cita o por (telefono + fecha). Llamala SOLO tras `buscar_citas` con confirmacion del cliente. Pide `nombre_confirmacion` como verificacion de identidad cuando no es el mismo canal+telefono. | web, wa, voz |
| `consultar_servicios` | Devuelve el catalogo completo o una categoria (corte, color, peinados, tratamientos, barba). Filtro por especialidad opcional. **Datos en YAML**. | web, wa, voz |
| `consultar_horario` | Devuelve horario, opcional por dia. **Datos en YAML**. | web, wa, voz |
| `escalar_a_humano` | Pasa el caso al duenno/encargado por email (Resend). Motivos: cliente_lo_pide, queja_o_enfado, servicio_no_disponible, caso_complejo, datos_no_capturados, otro. | web, wa, voz |
| `consultar_historial` | Reconocer cliente recurrente por telefono (lee `llamadas_voz`). Devuelve tambien fecha de hoy + tabla de 14 dias para resolver fechas relativas. Invocar SIEMPRE al inicio de cada llamada. | solo voz |
| `derivar_a_whatsapp` | Handoff voz->WhatsApp cuando el agente no puede capturar un dato por voz (alergias largas, nombre dificil, lista de servicios tecnicos). | solo voz |

---

## 6. Reglas estrictas (heredadas de la plantilla Alnora)

### Idioma y tono
- **Castellano peninsular** siempre. Jamas latinoamericano ("computadora", "celular", "carro"). Si "ordenador", "movil", "coche".
- Tutea al cliente por defecto.
- Tono: cercano, calido y resolutivo, como una jefa de salon con experiencia.

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
- Las credenciales son DISTINTAS a las de Alnora y a las de demo-restaurante
  (Supabase nuevo, Twilio nuevo, Vapi assistant nuevo).

### Supabase
- **RLS activado** en todas las tablas.
- Sin policies para anon: todo el acceso pasa por el backend FastAPI con
  service_role. Los advisors marcaran "RLS enabled but no policies" — es
  intencional.

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
- Tras ejecutar `agendar_cita`, si la tool devuelve OK -> confirmar al cliente con texto natural.

### Flujos de cancelacion y modificacion
Los dos flujos arrancan IGUAL: `buscar_citas` primero. NUNCA interrogar al cliente con telefono+fecha+nombre uno a uno.

- **Cancelar**: `buscar_citas` -> mostrar cita -> confirmacion del cliente -> `cancelar_cita(id_cita=...)`.
- **Modificar** (mover fecha/hora, cambiar servicios, estilista, alergias...): `buscar_citas` -> mostrar cita -> proponer cambio -> confirmacion -> `modificar_cita(id_cita=..., fecha=..., ...)` UNA sola vez.
- En WA/voz: `buscar_citas` usa el telefono del canal (no se pide al cliente).
- En web: hay que pedir nombre + telefono al cliente porque no hay tel del canal.

### Guardrail anti-alucinacion (`core/guardrails.py`)
Categorias separadas: `agendar_cita` (creacion: "Cita agendada", "apuntada para..."), `cancelar_cita` ("cancelada sin problema", "anulada", "Hecho, cancelada"), `modificar_cita` ("cita movida/cambiada/modificada al X"), `escalar_a_humano`, `derivar_a_whatsapp`. Cada una con su propio recovery message.

Si el bot afirma una accion sin que la tool correspondiente este en `tools_ok`, se hace 1 auto-retry inyectando un aviso + reglas duras. Si tras retry sigue sin ejecutarse, se sustituye el reply por el recovery (texto que pide datos al cliente para reintentar).

`_ESTADOS_EXITO_POR_TOOL` en los webhooks define que `status` cuenta como exito por tool. Solo si la tool devuelve uno de esos estados se anade a `tools_ok`.

### Datos del salon
- Servicios, horarios, estilistas, branding, contacto, CORS origins, Google
  Review URL — todo en `config/peluqueria.yaml`.
  `core/peluqueria_data.py` lo carga al arranque y expone `SALON`, `BOT`,
  `LANDING`, `WIDGET_WEB`, `HORARIOS`, `SERVICIOS`, `ESTILISTAS`,
  `GOOGLE_REVIEW_URL`, `CORS_ORIGINS_DEFAULT`, ademas de helpers
  (`nombre_bot()`, `email_from_address()`, `email_logo_url()`, etc.).
- Los HTML (`index.html`, `admin/dashboard.html`) leen `GET /api/salon`
  al cargar y se repintan: textos, colores CSS, titulos, href de tel/mail/maps.
  Para marcar un nodo como dinamico: `data-r="nombre"`, `data-r-tpl="{nombre}..."`,
  `data-r-href-tel="telefono"`, `data-r-href-mail="email"`, `data-r-href-maps="direccion"`.
- Los datos viven en codigo (YAML), NO en BD. Demo siempre disponible
  aunque Supabase este caido.

### Branding modular por canal
El YAML se reorganizo en bloques OPCIONALES por canal para facilitar
onboarding de clientes que solo quieren parte del producto. Estructura:

| Bloque YAML | Cuando rellenarlo | Si vacio |
|---|---|---|
| `salon:` | Siempre | n/a |
| `bot:` | Siempre que use cualquier canal IA | Prompts caen a "asistente" generico |
| `landing:` | Solo si usa la landing Salon Mara completa (GET /) | La landing carga sin colores ni imagenes personalizados |
| `widget_web:` | Solo si embede el widget chat | El widget hereda colores de `landing.colores`, avatar default 💬 |
| `emails:` | Recomendado siempre | Usa env var RESEND_FROM o fallback Resend, sin logo |

Onboarding rapido segun lo que el cliente quiera:

- **Solo WA**: `salon` + `bot` + `horarios` + `citas` (politica antelacion) +
  `servicios` + `estilistas` + `emails`. Borrar `landing` y `widget_web`.
- **Widget en su web**: anade `widget_web` (colores propios si su web tiene paleta distinta).
- **Landing completa**: anade `landing` + sube 3 imagenes a `static/branding/`.

⚠️ **Voz (Vapi)**: el prompt vive estatico en el panel de Vapi. Cuando
edites `bot.nombre` o el catalogo en el YAML hay que **recopiar manualmente**
el output de `prompt_voz_estatico()` al panel de Vapi (campo System Prompt
del assistant Mara). Para acelerarlo, en `.setup-artifacts/` hay scripts
que regeneran el prompt y reusan la API de Vapi.

⚠️ **Emails al duenno**: la URL del logo en `emails.logo_url` debe ser
ABSOLUTA (https://...). Las rutas relativas no funcionan en clientes
de correo.

### Logging estructurado
- Usa `from core.logger import get_logger; log = get_logger(__name__)`
  en cada modulo nuevo. **Nada de `print()`** en codigo de produccion.
- Scripts CLI (`scripts/*.py`) SI pueden usar `print()` (output decorativo).
- Niveles: `log.info` normal, `log.warning` error recuperable, `log.error`
  critico (con `exc_info=True` para incluir stack trace).
- Nivel configurable con env var `LOG_LEVEL` (default INFO).

### Health check
- `GET /health` devuelve status de Supabase, Anthropic, Twilio, Resend.
  200 healthy/degraded, 503 down. Railway lo usa como healthcheck path.
- Logica en `core/health.py`. Criticas: supabase + anthropic. Twilio y
  resend solo validan formato de credenciales (no llamada real).
- El check de Supabase consulta la tabla `citas` (NO `reservas`, que es
  resto de demo-restaurante: si vuelves a ver `reservas` en algun sitio
  del codigo, es bug).

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
Repo hermano: demo-restaurante (Casa Lola).

Si surgen mejoras genericas (provider Meta, tool nueva reutilizable, fix de
patron core), avisar al usuario para portarlas con `git cherry-pick`.

NO modificar los repos Alnora ni demo-restaurante desde aqui.

---

## 10. Estado actual (post-setup inicial)

Infra y funcionalidad core:
- [x] `config/peluqueria.yaml` como fuente de verdad, loader en `core/peluqueria_data.py`.
- [x] System prompts adaptados a los 3 canales (WA, web, voz) con datos del YAML dinamicos.
- [x] 10 tools del salon implementadas (8 comunes + 2 solo voz).
- [x] Landing (`index.html`), pagina `/demo` y panel admin (`admin/dashboard.html`) dinamicos via `/api/salon`.
- [x] Supabase con migracion inicial aplicada (8 tablas + RLS).
- [x] Vapi Assistant "Mara" configurado (voz Azure `es-ES-ElviraNeural`, 10 tools, serverUrl).
- [x] Twilio sandbox operativo (`+14155238886`, palabra clave `join toy-dish`).
- [x] Desplegado en Railway (`web-production-e8a8c.up.railway.app`), `/health` = healthy.
- [x] Webhooks Supabase configurados (cita-nueva + cita-modificada) y validados E2E.

Pendiente:
- [ ] Comprar numero Vapi y asignar a Mara → `VAPI_PHONE_NUMBER` en Railway.
- [ ] Rellenar `NOTIFICATIONS_TO` real en Railway para que lleguen emails de aviso.
- [ ] Migracion Twilio sandbox → numero Twilio propio del salon o Meta Cloud API.
- [ ] Mejorar prompt voz Mara con primeras pruebas de llamadas reales.
- [ ] Suite de evals para voz (cuando haya numero real).
- [ ] Rate limiting en endpoints publicos.
- [ ] UptimeRobot externo sobre `/health` antes del primer demo en cliente.

---

## 10.5 Sistema de labels en GitHub

Las issues y PRs llevan etiquetas para escanearlas rapido. Las nuevas issues
deben llevar siempre **al menos** un `area:*`, una `priority:*` y un tipo
(`bug` / `enhancement` / `feat` / `documentation`).

**Area** (que parte del producto toca):
- `area:chatbot` — afecta a uno o varios chatbots
- `area:whatsapp` — solo WhatsApp
- `area:web` — solo chat web
- `area:voz` — agente Vapi (Mara)
- `area:landing` — landing publica + branding
- `area:panel-admin` — `/admin`
- `area:backend` — core, BD, emails, infra
- `area:plantilla` — onboarding nuevos clientes

**Prioridad**:
- `priority:high` (rojo) — hacer cuanto antes
- `priority:medium` (amarillo) — importante, no urgente
- `priority:low` (verde) — nice-to-have

Comando para crear label nuevo (idempotente):
```bash
gh label create "area:nuevo" --color "1D76DB" --description "..." --force
```

Comando para etiquetar issue o PR:
```bash
gh issue edit <N> --add-label "area:chatbot,priority:medium,bug"
gh pr edit <N> --add-label "area:backend,priority:medium,bug"
```

Las PRs deben llevar las MISMAS etiquetas que las issues que cierran (o las equivalentes si no cierran ninguna).

---

## 10.6 Diagnostico backend desde la sesion

Para ver BD, logs y schema sin pedir al usuario que copie SQL:

**MCP de Supabase**: configurado con un PAT por cuenta del usuario. Si el
MCP esta conectado, las tools `apply_migration`, `execute_sql`,
`list_tables`, `get_advisors`, etc. estan disponibles tras un ToolSearch.

**Fallback con curl + API REST Management** (si el MCP no expone las tools):
```bash
curl -s -X POST "https://api.supabase.com/v1/projects/eoeinoilkklmiqcybwnb/database/query" \
  -H "Authorization: Bearer sbp_..." \
  -H "Content-Type: application/json" \
  -d '{"query":"SELECT * FROM citas LIMIT 5;"}'
```

PROJECT_REF de demo-peluqueria: `eoeinoilkklmiqcybwnb`.

**Reproducir bugs en local apuntando a la BD de produccion**:
```bash
python -m uvicorn server:app --port 8765 --log-level info  # background
curl -X POST http://localhost:8765/web/chat -H "Content-Type: application/json" \
  -d '{"session_id":null,"message":"hola"}'
```
Util para diagnosticar si un bug es del codigo en main o de la version desplegada en Railway. Permite anadir logs temporales sin desplegar.

**Verificar webhooks Supabase**: las respuestas HTTP de pg_net se guardan en
`net._http_response`. Tras un INSERT en `citas`, hacer:
```sql
SELECT status_code, content::text, created
FROM net._http_response
ORDER BY created DESC LIMIT 5;
```

---

## 11. Cosas que el usuario ha dicho explicitamente

- Trabajamos en **castellano peninsular**.
- **No anunciar la preview en cada edicion** — evitar frases "visible en el panel de preview" tras cada Edit.
- **Correr los tests por defecto** tras cambios importantes. No esperar a que el usuario lo pida.
- **Plantilla reutilizable**: cuando se aplique una mejora generica (nueva tool, nuevo endpoint, refactor, fix), pensar si deberia portarse a la plantilla base (`config/peluqueria.yaml` + codigo portable). Evitar dejar datos hardcodeados que obliguen a editarlos al clonar a otro cliente.
- **Siempre avisar de pendientes manuales** al terminar una tarea. Cuando algo no puedo hacer yo (configurar Railway, activar branch protection, crear cuenta en servicio externo), reportar al final del mensaje con formato:
  > **⚠️ Pendiente por tu parte:**
  > 1. Que hay que hacer
  > 2. Como se hace (panel + ruta + valores)
  > 3. Por que importa (que se rompe si no)
- **Explicar en lenguaje claro** los logros tras cerrar una issue importante (no solo "hecho"). El usuario valora entender QUE se ha ganado a nivel de producto/dia a dia, no solo que compilo.
- **PRs con CI verde antes de pedir merge**. Si CI falla, arreglar hasta que este verde. Nunca avisar de merge con tests en rojo.
- **Issues/PRs con etiquetas SIEMPRE**: al menos un `area:*`, una `priority:*` y un tipo (`bug` / `enhancement` / `feat` / `documentation`). Ver seccion 10.5.
- **Modificar citas se hace IN-PLACE**: usar `modificar_cita(id_cita, ...)` nunca `cancelar_cita + agendar_cita`. Es regla de producto: el dueno no debe recibir 2-3 emails confusos por un cambio de fecha.
- **Nada de "como imaginaba" o tono condescendiente**: si el bot tiene que rechazar algo (lunes cerrado, fecha pasada), responde directo y amable, sin frases que insinuen que el cliente deberia haberlo sabido.
- **Confirmacion explicita antes de cada accion sensible**: agendar, cancelar, modificar, escalar — el bot SIEMPRE pide confirmacion ("¿Confirmas?") antes de tocar BD. No interpretes "perfecto, viernes 8 con Lucia, confirmo" como confirmacion final si aun no diste el resumen.
- **Emails diferenciados por accion**: nueva cita (verde), cita modificada (naranja), cita cancelada (rojo). Subjects con emoji distintivo. Configurado via webhook UPDATE en Supabase + funcion `notificar_cambio_cita`.
- **Sesiones de QA largas**: el flujo es bateria de tests manual -> usuario reporta resultado por chat -> yo verifico backend (BD, conversaciones, emails) via curl/MCP -> diagnosticar y abrir PR de fix si hace falta. Tras cada PR mergeado: limpiar BD para no arrastrar datos de pruebas anteriores.
