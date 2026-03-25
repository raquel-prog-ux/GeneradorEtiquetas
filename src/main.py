"""
Punto de entrada: inicia la aplicación de generación de etiquetas.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Permite importar paquetes `gui`, `logic` y `utils` al ejecutar este archivo directamente
_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from gui.app import iniciar_aplicacion  # noqa: E402


def main() -> None:
    iniciar_aplicacion()


if __name__ == "__main__":
    main()
