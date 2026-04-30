"""
Script CLI para detectar no-shows (issue #10).

Pensado para correr cada 30 min durante las horas de servicio.
En Railway se configura como segundo cron job.

Uso:
    python scripts/detectar_no_shows.py

Exit code 0 siempre (no queremos fallar el cron si no hay nada que hacer).
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.no_show import detectar_y_marcar_no_shows


def main() -> int:
    print("=" * 60)
    print("Casa Lola — deteccion de no-shows")
    print("=" * 60)

    resumen = detectar_y_marcar_no_shows()

    print()
    print(f"Candidatos detectados:  {resumen['total_candidatos']}")
    print(f"Marcados como no_show:  {resumen['marcados']}")
    if resumen["detalle"]:
        print("Detalle:")
        for d in resumen["detalle"]:
            print(f"  - {d['nombre']} ({d['num_personas']}p) hora {d['hora']}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
