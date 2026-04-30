"""
Runner de evals (issue #12) con reporte legible.

Equivalente a `pytest -m eval` pero con output mas amigable que muestra
por canal qué evals pasan, fallan o se saltan.

Uso:
    python scripts/run_evals.py
    python scripts/run_evals.py --solo web
    python scripts/run_evals.py --solo whatsapp
"""
import argparse
import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def main() -> int:
    parser = argparse.ArgumentParser(description="Runner de evals Casa Lola")
    parser.add_argument("--solo", choices=["web", "whatsapp"], default=None,
                        help="Filtrar solo evals de un canal")
    parser.add_argument("-k", default=None, help="Pasar a pytest -k para filtro extra")
    args = parser.parse_args()

    print("=" * 60)
    print("Casa Lola — Suite de evals")
    print("=" * 60)

    cmd = [sys.executable, "-m", "pytest", "-m", "eval", "tests/test_evals.py",
           "--tb=short", "-v"]

    if args.solo:
        # Filtra por nombre del test (test_eval_web_* o test_eval_wa_*)
        prefijo = "test_eval_web_" if args.solo == "web" else "test_eval_wa_"
        cmd.extend(["-k", prefijo])
    elif args.k:
        cmd.extend(["-k", args.k])

    print(f"$ {' '.join(cmd)}")
    print()
    result = subprocess.run(cmd, cwd=_ROOT)
    print()
    print("=" * 60)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
