# Salon Mara — Demo de gestión inteligente de citas

> **Salon Mara** es una peluquería ficticia (unisex en Malasaña, Madrid)
> que enseña en directo qué puede hacer un sistema multicanal de IA en
> un salón. Web, WhatsApp y teléfono unificados; panel de la dueña con
> calendario en vivo; asignación automática de estilista por
> compatibilidad y disponibilidad. La clienta pide cita por donde quiera
> y a la dueña le llega todo a un solo sitio.

[![Tests](https://github.com/nachorjm/demo-peluqueria/actions/workflows/tests.yml/badge.svg)](https://github.com/nachorjm/demo-peluqueria/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![Stack](https://img.shields.io/badge/Stack-Anthropic%20%C2%B7%20Supabase%20%C2%B7%20Vapi%20%C2%B7%20Twilio-7c3aed)](#stack)

---

## Demo en vivo

| Pieza | Enlace |
|---|---|
| **Landing + chatbot web** | _(pendiente de despliegue)_ |
| **Panel de la dueña** | `/admin` (pedir contraseña) |
| **WhatsApp sandbox** | _(pendiente de configurar Twilio nuevo)_ |
| **Llamada telefónica (Mara)** | _(pendiente de configurar Vapi nuevo)_ |

---

## Qué problema resuelve

Una peluquería pequeña pierde citas todos los días por:

- **El teléfono suena mientras Mara está haciendo mechas** y nadie lo coge → la clienta se va a la competencia.
- **La web no tiene chat**, la clienta tiene que llamar o cuadrar horarios por DM.
- **WhatsApp se acumula sin atender**, mensajes a las 23h que nadie ve.
- **Asignar estilista a mano** con una hoja en la recepción es un caos cuando 3 clientas piden corte+color a la vez.
- **El equipo no sabe** qué huecos están vacíos esta semana hasta que llega el día.

Esta demo cubre todos los frentes con un solo sistema.

---

## Qué incluye el producto

### Atención a la clienta
- ✅ **Chatbot web** embebible en cualquier landing.
- ✅ **Chatbot WhatsApp** (Twilio sandbox + listo para Meta Cloud API).
- ✅ **Agente telefónico de voz** "Mara" (Vapi + Claude Haiku).
- ✅ **Multi-idioma** automático: ES / EN / FR / IT / DE / PT detectado por mensaje.
- ✅ **Memoria entre canales**: la clienta que llamó por teléfono y luego escribe por WhatsApp es reconocida.

### Gestión de citas
- ✅ **Catálogo de servicios** con precios y duraciones reales (corte mujer 45 min, color completo 2 h, mechas 2 h 30 min, etc.).
- ✅ **Equipo con especialidades**: cada estilista declara qué hace (corte, color, barbería, peinado novia…). El bot asigna automáticamente quien sepa hacerlo y esté libre.
- ✅ **Citas multi-servicio**: corte + color + tratamiento en la misma franja, con suma de duraciones y precio total.
- ✅ **Cancelaciones seguras** con verificación de identidad (no se cancela una cita ajena por saber el teléfono).
- ✅ **Modificar cita _in-place_**: cambiar fecha, hora, servicios o estilista sin crear duplicados.
- ✅ **Handoff voz → WhatsApp**: si la clienta no recuerda el servicio exacto al llamar, Mara le envía un WhatsApp para acabar por texto.

### Insight para la dueña
- ✅ **Panel `/admin` con calendario** en vivo (FullCalendar, polling cada 15 s) coloreado por canal.
- ✅ **Estadísticas**: KPIs (citas hoy/semana/mes), citas por canal, **citas por estilista**, ingresos estimados, tasa de cancelación, evolución diaria.
- ✅ **Email automático** a la dueña en cada cita nueva, modificación o cancelación (verde / naranja / rojo según el caso).
- ✅ **Sincronización iCal** con su Google Calendar / iPhone (botón "Sincronizar al móvil").

### Calidad técnica
- ✅ **~30 smoke tests** automatizados, ejecutados en cada push (CI GitHub Actions).
- ✅ **Evals** del comportamiento del bot contra Claude real, para detectar regresiones al tocar prompts.
- ✅ **Guardrails** server-side que detectan alucinaciones del modelo (afirmar "cita confirmada" sin ejecutar la tool) y se corrigen automáticamente.

---

## Casos de uso (cómo se siente la demo)

### 1. Cita por WhatsApp en pocos mensajes
> Clienta: "Hola, quiero corte y color el viernes por la tarde"
> Bot: "Perfecto. Tengo hueco con Mara el viernes 12 a las 17:00 (2 h 45 min, total 93 €). ¿A qué nombre lo apunto y un teléfono de contacto?"
> Clienta: "Marta Ruiz, 600 11 12 22"
> Bot: "Te apunto: viernes 12, 17:00 con Mara, corte mujer + coloración raíz, 93 €. ¿Confirmas?"
> Clienta: "sí"
> Bot: "✅ Cita confirmada. Te esperamos el viernes en Salón Mara."

→ Cita en BD + email a la dueña + entrada en panel admin en <2 segundos.

### 2. Clienta extranjera
> Clienta: "Hi, can I book a cut and blowdry for tomorrow afternoon?"
> Bot: "Yes, we have availability. May I have your name and phone, please?"

→ Detecta inglés automáticamente, mantiene el idioma toda la conversación.

### 3. Asignación automática de estilista
> Clienta: "Quiero arreglo de barba y corte de hombre el sábado"
> Bot: "Para barba lo hace Diego. Tengo hueco el sábado a las 11:30 (50 min, 30 €). ¿Te va bien?"

→ El bot sabe que Diego es el barbero del equipo y asigna directamente sin preguntar al equipo.

### 4. Modificar cita sin duplicar
> Clienta: "Tengo cita el viernes a las 17:00 pero me viene mejor el sábado a las 12:00"
> Bot busca la cita por teléfono → confirma con la clienta → llama a `modificar_cita(id, fecha, hora_inicio)` → reasigna estilista si hace falta.

→ Misma fila en BD, mismo `id`. La dueña recibe email "Cita MODIFICADA" (naranja), no dos emails confusos.

### 5. Panel de la dueña
Calendario con citas pintadas por canal (azul=web, verde=WhatsApp, violeta=voz). Click en cualquier cita → modal con estilista + servicios + alergias + botón cancelar. Pestaña Estadísticas con donut de canales, donut por estilista, evolución diaria.

---

## Stack

- **Anthropic Claude Haiku 4.5** — modelo conversacional con tool use.
- **Supabase** (Postgres + Auth + DB Webhooks) — datos y notificaciones reactivas.
- **Vapi** — agente telefónico (voz Azure ES + Claude).
- **Twilio** — WhatsApp (sandbox y Meta Cloud API listo).
- **Resend** — emails a la dueña.
- **FastAPI + uvicorn** — backend.
- **Railway** — hosting.
- **FullCalendar + Chart.js** — panel admin.

---

## Adaptación a otra peluquería

El repo está pensado como **plantilla**. Todo lo específico del cliente vive
en **un solo fichero** (`config/peluqueria.yaml`): nombre, equipo,
servicios, precios, duraciones, horarios, colores de marca, textos de la
landing, dominios CORS y URL de Google Reviews. El resto del código
(bot, endpoints, panel, tests) no se toca.

Onboarding de un cliente nuevo (objetivo: **<1 hora**):

1. **Fork** del repo.
2. Copiar la plantilla y rellenarla:
   ```bash
   cp config/peluqueria.example.yaml config/peluqueria.yaml
   # editar config/peluqueria.yaml con los datos del cliente
   ```
3. **Crear proyecto Supabase nuevo** y aplicar la migración de
   `supabase/migrations/` (`0001_initial_schema.sql`).
4. **Configurar `.env`** con credenciales del cliente (ver `.env.example`).
   Datos del salón NO van aquí — van en el YAML.
5. **Desplegar en Railway** conectando el fork a la rama `main`.
   Railway detecta el push y redeploya automáticamente.
6. (Opcional) Sustituir imágenes del landing en `static/branding/` si
   no valen las actuales.

Tras el paso 2, al arrancar el backend:
- La landing y el panel admin leen `GET /api/salon` y se repintan
  solos con el nombre, colores, equipo y textos del nuevo cliente.
- Los prompts de los bots sustituyen `{SALON['nombre']}` y la lista de
  servicios y estilistas por los valores del YAML automáticamente.

Coste mensual estimado por cliente (uso medio): ~30-50 €/mes en infra
(Railway + Supabase + Twilio + Resend) + variable en Vapi y Anthropic
según volumen.

---

## Contacto

¿Interesado en una demo o presupuesto para tu negocio?

📧 **gestionalnora@gmail.com**
🌐 **alnora.es**

---

## Para developers

Información técnica de cómo arrancar local, contribuir y testear: ver [CLAUDE.md](./CLAUDE.md).
