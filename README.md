# Casa Lola — Demo de gestión inteligente de reservas

> **Casa Lola** es un restaurante ficticio (arrocería en Russafa, Valencia)
> que enseña en directo qué puede hacer un sistema multicanal de IA en
> hostelería. Web, WhatsApp y teléfono unificados; panel del dueño con
> calendario en vivo; recordatorios, lista de espera y encuestas
> automáticas. El cliente reserva por donde quiera y al dueño le llega
> todo a un solo sitio.

[![Tests](https://github.com/theGSM03/demo-restaurante/actions/workflows/tests.yml/badge.svg)](https://github.com/theGSM03/demo-restaurante/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![Stack](https://img.shields.io/badge/Stack-Anthropic%20%C2%B7%20Supabase%20%C2%B7%20Vapi%20%C2%B7%20Twilio-7c3aed)](#stack)

---

## Demo en vivo

| Pieza | Enlace |
|---|---|
| **Landing + chatbot web** | https://demo-restaurante-production.up.railway.app |
| **Panel del dueño** | https://demo-restaurante-production.up.railway.app/admin (pedir contraseña) |
| **WhatsApp sandbox** | Manda `join famous-musical` al `+1 415 523 8886`, luego escribe lo que quieras |
| **Llamada telefónica (Lola)** | En desarrollo — número definitivo al cerrar piloto |

---

## Qué problema resuelve

Hostelería pequeña pierde reservas todos los días por:

- **El teléfono suena en plena cocina** y nadie lo coge → se pierde la reserva.
- **La web no tiene chat**, el cliente tiene que llamar o ir a la competencia.
- **WhatsApp se acumula sin atender**, mensajes a las 3 de la madrugada que nadie ve.
- **No-shows del 15-20%** porque el cliente olvidó la mesa.
- **Listas de espera manuales** que nadie gestiona.
- **Pocas reseñas en Google** porque a la salida nadie las pide.
- **El dueño no sabe** qué noches están vacías hasta que llegan.

Esta demo cubre los siete frentes con un solo sistema.

---

## Qué incluye el producto

### Atención al cliente
- ✅ **Chatbot web** embebible en cualquier landing.
- ✅ **Chatbot WhatsApp** (Twilio sandbox + listo para Meta Cloud API).
- ✅ **Agente telefónico de voz** "Lola" (Vapi + Claude Haiku).
- ✅ **Multi-idioma** automático: ES / EN / FR / IT / DE / PT detectado por mensaje.
- ✅ **Memoria entre canales**: el cliente que llamó por teléfono y luego escribe por WhatsApp es reconocido.

### Gestión de reservas
- ✅ **Modelo de mesas reales** con duración (1h45 comida, 2h cena, +30 min si arroz).
- ✅ **Asignación inteligente**: agrupa mesas para grupos grandes, libera al cancelar.
- ✅ **Cancelaciones seguras** con verificación de identidad (no se cancela una reserva ajena por saber el teléfono).
- ✅ **Recordatorios** automáticos por WhatsApp el día anterior. Cliente confirma o anula respondiendo SÍ/NO.
- ✅ **Lista de espera**: cuando una fecha está llena, el cliente se apunta y recibe oferta automática si alguien cancela.
- ✅ **Detección de no-shows**: pasados 30 min sin llegar, mesa liberada y notificada al dueño.

### Insight para el dueño
- ✅ **Panel `/admin` con calendario** en vivo (FullCalendar, polling cada 15s).
- ✅ **Estadísticas**: KPIs, reservas por canal, hora pico, evolución mensual.
- ✅ **Email automático** al dueño en cada reserva nueva, escalación, queja o feedback negativo.

### Captación de reseñas
- ✅ **Encuesta post-visita** por WhatsApp el día siguiente. Nota ≥4 → enlace de Google Reviews. Nota ≤3 → comentario al dueño en privado (evita reseñas negativas públicas).

### Calidad técnica
- ✅ **70 smoke tests** automatizados, ejecutados en cada push (CI GitHub Actions).
- ✅ **24 evals** del comportamiento del bot contra Claude real, para detectar regresiones al tocar prompts.
- ✅ **Guardrails** server-side que detectan alucinaciones del modelo (afirmar "reserva confirmada" sin ejecutar la tool) y se corrigen automáticamente.

---

## Casos de uso (cómo se siente la demo)

### 1. Reserva por WhatsApp en 4 mensajes
> Cliente: "Hola, quiero reservar mesa para 4 mañana a las 21:00"
> Bot: "Perfecto. ¿A qué nombre y un teléfono de contacto?"
> Cliente: "Marta Ruiz, 600111222"
> Bot: "Te apunto: jueves 24 a las 21:00, 4 personas, Marta. ¿Confirmas?"
> Cliente: "sí"
> Bot: "✅ Reservada. Te esperamos mañana en Casa Lola."

→ Reserva en BD + email al dueño + entrada en panel admin en <2 segundos.

### 2. Cliente extranjero
> Cliente: "Hi, do you have a table for 4 tomorrow night around 9?"
> Bot: "Yes, we have availability. May I have your name and phone, please?"

→ Detecta inglés automáticamente, mantiene el idioma toda la conversación.

### 3. Lista de espera
> Cliente quiere reservar el sábado noche pero está lleno.
> Bot: "Lo siento, ese turno no tiene plazas. Te apunto en lista de espera y te aviso si se libera mesa, ¿te apunto?"

Más tarde, alguien cancela su reserva del sábado:
> Cliente recibe WhatsApp automático: "Acaba de liberarse mesa para 4 el sábado a las 21:00, ¿la quieres? SÍ / NO"
> Cliente: "SÍ"
> Bot: "✅ Mesa apuntada. Te esperamos el sábado."

### 4. Encuesta post-visita
Día siguiente a la reserva:
> Bot: "Hola Marta, ¿qué tal anoche en Casa Lola? Puntúanos del 1 al 5."
> Cliente: "5"
> Bot: "¡Qué alegría! ¿Nos dejas una reseña en Google? https://g.page/CasaLola/review"

### 5. Panel del dueño
Calendario con reservas pintadas por canal (azul=web, verde=WhatsApp, violeta=voz). Click en cualquier reserva → modal con detalles + botón cancelar. Pestaña Estadísticas con donut de canales, hora pico y evolución.

---

## Stack

- **Anthropic Claude Haiku 4.5** — modelo conversacional con tool use.
- **Supabase** (Postgres + Auth + DB Webhooks) — datos y notificaciones reactivas.
- **Vapi** — agente telefónico (voz Azure ES + Claude).
- **Twilio** — WhatsApp (sandbox y Meta Cloud API listo).
- **Resend** — emails al dueño.
- **FastAPI + uvicorn** — backend.
- **Railway** — hosting + crons (recordatorios, no-show, encuestas).
- **FullCalendar + Chart.js** — panel admin.

---

## Adaptación a otro restaurante

El repo está pensado como **plantilla**. Todo lo específico del cliente vive
en **un solo fichero** (`config/restaurante.yaml`): nombre, carta, horarios,
colores de marca, textos de la landing, dominios CORS y URL de Google Reviews.
El resto del código (bot, endpoints, panel, tests) no se toca.

Onboarding de un cliente nuevo (objetivo: **<1 hora**):

1. **Fork** del repo.
2. Copiar la plantilla y rellenarla:
   ```bash
   cp config/restaurante.example.yaml config/restaurante.yaml
   # editar config/restaurante.yaml con los datos del cliente
   ```
3. **Crear proyecto Supabase nuevo** y aplicar las migraciones de
   `supabase/migrations/` en orden. Poblar la tabla `mesas` con las mesas
   reales del restaurante.
4. **Configurar `.env`** con credenciales del cliente (ver `.env.example`).
   Datos del restaurante NO van aquí — van en el YAML.
5. **Desplegar en Railway** conectando el fork a la rama `main`.
   Railway detecta el push y redeploya automáticamente.
6. (Opcional) Sustituir imágenes del landing en `index.html` si no valen
   las actuales.

Tras el paso 2, al arrancar el backend:
- La landing y el panel admin leen `GET /api/restaurante` y se repintan
  solos con el nombre, colores y textos del nuevo cliente.
- Los prompts de los bots sustituyen `{RESTAURANTE['nombre']}` por el valor
  del YAML automáticamente.

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
