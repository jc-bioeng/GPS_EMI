"""Entrada de consola al monitor de llegada de una ambulancia."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from gps_emi.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
