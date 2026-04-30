# Agente telefónico (Vapi)

Backend del agente de voz Kara que atiende llamadas telefónicas a través de Vapi.

## Endpoints

- `POST /vapi/tool/agendar_demo` — tool que Kara invoca para guardar una demo solicitada por llamada.
- `POST /vapi/tool/consultar_historial` — tool que Kara invoca al inicio de cada llamada para reconocer clientes conocidos.
- `POST /vapi/server-url` — endpoint que Vapi llama al colgar (`end-of-call-report`) para guardar la transcripción y generar un resumen.

## Tablas Supabase que usa

- `demos_solicitadas` (compartida con chatbot-whatsapp).
- `llamadas_voz` (exclusiva del agente).

## Variables de entorno requeridas

Las mismas que el chatbot: `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.

El `.env` real vive en `chatbot_whatsapp/.env` y se carga desde `core/config.py`. Si quieres separar la configuración en el futuro, puedes copiar las mismas variables a un `.env` propio en esta carpeta y ajustar `core/config.py`.

## Cómo se lanza

No tiene servidor propio. Se monta como router dentro de `server.py` en la raíz del proyecto junto con el router del chatbot.

Para arrancar todo:

```bash
python -m uvicorn server:app --reload --port 8000
```
