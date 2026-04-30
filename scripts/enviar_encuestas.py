"""
Script CLI para enviar encuestas post-visita a clientes que vinieron
ayer (issue #7).

Pensado para correr una vez al dia ~12:00 UTC (~13/14h Espana). En
Railway se configura como tercer cron job.

Uso:
    python scripts/enviar_encuestas.py
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.encuestas import enviar_encuestas_de_ayer


def main() -> int:
    print("=" * 60)
    print("Casa Lola — encuestas post-visita")
    print("=" * 60)

    resumen = enviar_encuestas_de_ayer()

    print()
    print(f"Reservas pendientes:  {resumen['total']}")
    print(f"Encuestas enviadas:   {resumen['enviadas']}")
    print(f"Fallidas:             {resumen['fallidas']}")
    print("=" * 60)

    return 0 if resumen["fallidas"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
