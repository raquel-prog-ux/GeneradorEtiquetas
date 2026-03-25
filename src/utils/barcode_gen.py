"""
Generación de imágenes de código de barras Code128 (python-barcode + Pillow).
"""
from __future__ import annotations

import uuid
from pathlib import Path

from barcode import Code128  # type: ignore[import-untyped]
from barcode.writer import ImageWriter  # type: ignore[import-untyped]

# Raíz del proyecto (carpeta que contiene src/, assets/, etc.)
_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMP_DIR = _ROOT / "assets" / "temp"


def generar_imagen_code128(codigo: str, nombre_base: str | None = None) -> Path:
    """
    Genera una imagen PNG del código en formato Code128 y la guarda en assets/temp/.

    Args:
        codigo: Valor a codificar (texto no vacío).
        nombre_base: Opcional; prefijo del nombre del archivo (sin ruta ni extensión).

    Returns:
        Ruta absoluta al archivo PNG generado.

    Raises:
        ValueError: Si el código está vacío.
        RuntimeError: Si falla la generación o no se encuentra el archivo de salida.
    """
    texto = (codigo or "").strip()
    if not texto:
        raise ValueError("El código para el barras no puede estar vacío.")

    _TEMP_DIR.mkdir(parents=True, exist_ok=True)

    prefijo = (nombre_base or "bc").strip() or "bc"
    # Ruta base sin extensión; python-barcode añade .png
    ruta_base = _TEMP_DIR / f"{prefijo}_{uuid.uuid4().hex[:12]}"

    try:
        writer = ImageWriter()
        instancia = Code128(texto, writer=writer)
        instancia.save(str(ruta_base))
    except Exception as e:
        raise RuntimeError(f"No se pudo generar el código de barras: {e}") from e

    png = Path(str(ruta_base) + ".png")
    if not png.is_file():
        png = ruta_base.with_suffix(".png")
    if not png.is_file():
        raise RuntimeError(
            f"No se encontró el PNG generado para la base: {ruta_base}"
        )

    return png.resolve()
