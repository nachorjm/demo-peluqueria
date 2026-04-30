"""Configuracion centralizada: carga .env y provee clientes compartidos.

Este modulo se importa desde chatbot_whatsapp y agente_telefonico para
asegurar que ambos servicios comparten un unico cliente Anthropic y un
unico cliente Supabase.

El .env vive historicamente en chatbot_whatsapp/.env. Se mantiene ahi
para no romper la configuracion previa; este modulo lo carga buscando
en la raiz primero y luego en chatbot_whatsapp/ como fallback.
"""
import os
import sys
from dotenv import load_dotenv
from anthropic import Anthropic
from supabase import create_client, Client


# ─── 1. Cargar variables de entorno ──────────────────────────────────
# Buscar .env en varias ubicaciones posibles (raiz y chatbot_whatsapp).
# El .env real esta en chatbot_whatsapp/.env, pero permitimos un .env
# en la raiz por si en el futuro alguien lo coloca alli.
# Nota sobre override: en Windows a veces hay variables preexistentes
# en el entorno (vacias o con valor) que bloquearian la carga del .env
# sin override=True. Por eso forzamos la sobrescritura.
load_dotenv(override=True)
load_dotenv("chatbot_whatsapp/.env", override=True)  # fallback historico (WhatsApp)
load_dotenv("chatbot_web/.env", override=True)  # fallback chatbot web

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

for var_name, var_value in [
    ("ANTHROPIC_API_KEY", ANTHROPIC_KEY),
    ("SUPABASE_URL", SUPABASE_URL),
    ("SUPABASE_SERVICE_ROLE_KEY", SUPABASE_KEY),
]:
    if not var_value or var_value.startswith("PEGA_"):
        # Excepcion al criterio "no print()": este modulo se carga ANTES
        # de que setup_logging() corra (es importado por server.py durante
        # el arranque). Usamos stderr directamente para que el mensaje
        # salga seguro y luego sys.exit(1) aborta. No hay otro modo limpio.
        sys.stderr.write(f"ERROR: falta configurar {var_name} en el archivo .env\n")
        sys.exit(1)


# ─── 2. Clientes Claude y Supabase ──────────────────────────────────
claude = Anthropic(api_key=ANTHROPIC_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 500
MAX_HISTORY_MESSAGES = 20
# Temperature mas baja => modelo mas determinista y obediente al prompt
# (menos alucinaciones de "ya esta hecho" sin ejecutar la tool). Default
# de Anthropic es 1.0; bajamos a 0.3 para reducir creatividad innecesaria.
TEMPERATURE = 0.3
