# Chatbot WhatsApp — Alnora IA

Proyecto de aprendizaje progresivo para construir un chatbot de WhatsApp con Claude como cerebro.

## 🎯 Fase actual: Fase 1 — MVP por terminal

Un script simple que te permite chatear con Claude desde la terminal.
Su objetivo es aprender lo básico de la API de Claude antes de complicarnos con WhatsApp.

---

## 🚀 Cómo ejecutarlo

### 1. Instalar las dependencias

Desde la carpeta `chatbot-whatsapp/`:

```bash
pip install -r requirements.txt
```

### 2. Configurar tu API key

Abre el archivo `.env` y reemplaza `PEGA_AQUI_TU_API_KEY` por tu key real:

```
ANTHROPIC_API_KEY=sk-ant-api03-tu-key-real-aqui
```

Guarda el archivo.

### 3. Ejecutar el chat

```bash
python chat.py
```

Deberías ver:

```
============================================================
  🤖 Chat con Claude — MVP Alnora IA
  Modelo: claude-sonnet-4-6
  Escribe 'salir' para terminar.
============================================================

Tú: _
```

Ya puedes escribir y charlar con Claude. Cuando quieras terminar, escribe `salir`.

---

## 🧪 Experimentos que puedes hacer

Para aprender a fondo, te recomiendo romper y modificar cosas:

1. **Cambiar el `SYSTEM_PROMPT`** (línea ~44 de `chat.py`). Prueba:
   - `"Eres un pirata del siglo XVII. Habla con expresiones de pirata."`
   - `"Eres un profesor de matemáticas paciente. Explícalo todo con ejemplos."`
   - `"Solo puedes responder en forma de haiku."`

2. **Cambiar el `MODEL`** (línea ~40). Prueba:
   - `claude-haiku-4-5` → más rápido y barato.
   - `claude-opus-4-6` → más inteligente, más caro.

3. **Cambiar `MAX_TOKENS`** → limita cuán largas pueden ser las respuestas.

4. **Romperlo a propósito**: borra una coma del código y ejecuta. Observa el error y aprende a leerlo.

---

## 📋 Próximos pasos (Fases siguientes)

### Fase 2 — Conectar con WhatsApp vía Twilio (en curso)

- Archivo: `webhook.py`
- Servidor FastAPI que recibe mensajes de WhatsApp a través del sandbox de Twilio.
- Por ahora solo hace eco del mensaje (en el siguiente paso conectaremos Claude).

**Ejecutar el webhook**:

```bash
uvicorn webhook:app --reload --port 8000
```

Prueba rápida: abre http://localhost:8000 → debes ver `{"status":"ok","message":"Webhook activo"}`.

Para que Twilio pueda llamar a este servidor, hay que exponer el puerto 8000 a internet con **ngrok** y configurar la URL pública en el dashboard del sandbox.

### Fase 3 — Memoria en Supabase

Guardar el historial de conversación por usuario en Supabase para que Claude recuerde a cada cliente.

### Fase 4 — Tool use

Añadir herramientas para que Claude pueda realizar acciones (agendar citas, consultar catálogo, etc.).

---

## 💰 Coste estimado

Por cada mensaje enviado, la API cobra algo así:

| Modelo | Coste aprox. por mensaje |
|---|---|
| claude-haiku-4-5 | ~$0.0005 |
| claude-sonnet-4-6 | ~$0.005 |
| claude-opus-4-6 | ~$0.025 |

Con $5 de crédito tienes para cientos/miles de mensajes de pruebas.
