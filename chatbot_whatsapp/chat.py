"""
chat.py — MVP de chatbot por terminal con Claude
-------------------------------------------------
Este script te permite chatear con Claude desde la terminal.
Mantiene el historial de la conversación para que Claude tenga memoria.

Uso:
    python chat.py

Salir:
    Escribe 'salir' y pulsa Enter.
"""

# ─── 1. Importaciones ───────────────────────────────────────────────
import os                               # Para leer variables de entorno
import sys                              # Para cerrar el script si hay errores
from dotenv import load_dotenv          # Para leer el archivo .env
from anthropic import Anthropic         # El SDK oficial de Anthropic


# ─── 2. Cargar la API key desde .env ───────────────────────────────
load_dotenv()                           # Lee el archivo .env y carga las variables
API_KEY = os.environ.get("ANTHROPIC_API_KEY")

if not API_KEY or API_KEY == "PEGA_AQUI_TU_API_KEY":
    print("❌ ERROR: No has configurado tu API key en el archivo .env")
    print("   Abre 'chatbot-whatsapp/.env' y pega tu key.")
    sys.exit(1)


# ─── 3. Crear el cliente de Claude ─────────────────────────────────
client = Anthropic(api_key=API_KEY)


# ─── 4. Configuración del modelo ───────────────────────────────────
MODEL = "claude-sonnet-4-6"             # Modelo a usar (Sonnet: buen balance)
MAX_TOKENS = 1024                        # Longitud máxima de cada respuesta


# ─── 5. System prompt: personalidad e instrucciones iniciales ──────
# ¡CÁMBIAME! Juega con este texto para ver cómo cambia Claude.
SYSTEM_PROMPT = """Eres un asistente amable y útil llamado Claude.
Respondes siempre en castellano de España, de forma clara y concisa.
Si no sabes algo, lo dices honestamente."""


# ─── 6. Historial de la conversación ────────────────────────────────
# Esta lista guarda todos los mensajes (tuyos y de Claude) en orden.
# Se envía entera en cada llamada, por eso Claude "recuerda".
messages = []


# ─── 7. Banner de bienvenida ────────────────────────────────────────
print("=" * 60)
print("  🤖 Chat con Claude — MVP Alnora IA")
print(f"  Modelo: {MODEL}")
print("  Escribe 'salir' para terminar.")
print("=" * 60)
print()


# ─── 8. Bucle principal: lee tu mensaje, manda a Claude, imprime ────
while True:
    # Pide al usuario que escriba
    user_input = input("Tú: ").strip()

    # Comprobaciones básicas
    if user_input.lower() in ("salir", "exit", "quit"):
        print("\n👋 ¡Hasta luego!")
        break

    if not user_input:
        # Si no ha escrito nada, pide de nuevo
        continue

    # Añade el mensaje del usuario al historial
    messages.append({"role": "user", "content": user_input})

    # Llama a la API de Claude con todo el historial
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
        )

        # Extrae el texto de la respuesta (puede venir en varios bloques)
        assistant_reply = response.content[0].text

        # Añade la respuesta de Claude al historial
        messages.append({"role": "assistant", "content": assistant_reply})

        # Imprime la respuesta
        print(f"\nClaude: {assistant_reply}\n")

    except Exception as e:
        # Si la API falla, muestra el error y quita el último mensaje
        # del historial para que no se quede una pregunta sin respuesta
        print(f"\n❌ ERROR: {e}\n")
        messages.pop()
