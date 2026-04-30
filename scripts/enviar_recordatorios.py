"""
Script CLI para enviar recordatorios de las reservas de manana (issue #5).

Pensado para correr una vez al dia, idealmente sobre las 18:00 hora local
de Espana. En Railway se configura como cron job apuntando a este script.

Uso:
    python scripts/enviar_recordatorios.py

Devuelve exit code 0 si todos los recordatorios pendientes se enviaron
correctamente, 1 si hubo fallos.
"""
import os
import sys

# Forzar UTF-8 en stdout (Windows usa CP1252 por defecto y los emojis
# de los logs revientan).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Anadir raiz del proyecto al sys.path para que los imports funcionen
# tanto si se llama "python scripts/enviar_recordatorios.py" desde la
# raiz como si se invoca desde otro sitio.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.recordatorios import enviar_recordatorios_del_dia_siguiente


def main() -> int:
    print("=" * 60)
    print("Casa Lola — envio de recordatorios diarios")
    print("=" * 60)

    resumen = enviar_recordatorios_del_dia_siguiente()

    print()
    print(f"Total reservas pendientes: {resumen['total']}")
    print(f"Enviados con exito:        {resumen['enviados']}")
    print(f"Fallidos:                  {resumen['fallidos']}")
    print("=" * 60)

    if resumen["fallidos"] > 0:
        for d in resumen["detalle"]:
            if not d["ok"]:
                print(f"  ✗ reserva {d.get('reserva_id')}: {d.get('error')}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
