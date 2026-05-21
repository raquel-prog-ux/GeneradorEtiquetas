"""
Generacion de imagenes de codigo de barras Code128 (python-barcode + Pillow).
Code128 solo admite ASCII imprimible; se normalizan tildes y N/Ñ, etc.
"""
from __future__ import annotations

import unicodedata
import uuid
from pathlib import Path

from barcode import Code128  # type: ignore[import-untyped]
from barcode.writer import ImageWriter  # type: ignore[import-untyped]

# Raíz del proyecto (carpeta que contiene src/, assets/, etc.)
_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMP_DIR = _ROOT / "assets" / "temp"


def _texto_valido_code128(codigo: str) -> str:
    """
    Code128 (python-barcode) no acepta caracteres fuera de ASCII imprimible.
    NFD separa letras y tildes; se quitan marcas (ej. Ñ -> N, ñ -> n).
    """
    t = (codigo or "").strip()
    if not t:
        raise ValueError("El codigo para el barras no puede estar vacio.")
    base = unicodedata.normalize("NFD", t)
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    safe = "".join(c for c in base if 32 <= ord(c) <= 126)
    if not safe:
        raise ValueError(
            "El codigo no tiene caracteres validos para Code128 "
            "(use letras sin simbolos raros, numeros o ASCII basico)."
        )
    return safe


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
    texto = _texto_valido_code128(codigo)

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
