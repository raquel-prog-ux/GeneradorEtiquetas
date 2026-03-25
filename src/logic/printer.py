"""
Generación de PDF tamaño carta con etiquetas (ReportLab).
Distribuye código de barras, descripción y precio según el número de etiquetas por hoja.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

try:
    from PIL import Image as PILImage  # type: ignore[import-untyped]
except ImportError:
    PILImage = None  # type: ignore[misc, assignment]

from reportlab.lib.pagesizes import letter  # type: ignore[import-untyped]
from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

from utils.barcode_gen import generar_imagen_code128

# Tamaño carta en puntos (ancho x alto)
PAGE_W, PAGE_H = letter

# Márgenes exteriores (pulgadas -> puntos implícitos en letter; usamos ~0.45")
MARGIN_X = 36
MARGIN_Y = 36

# Disposición (columnas, filas) para cada formato
GRID_POR_ETIQUETAS: dict[int, tuple[int, int]] = {
    2: (1, 2),
    4: (2, 2),
    8: (2, 4),
    16: (4, 4),
}


def _envolver_texto(
    texto: str,
    fuente: str,
    tam: float,
    ancho_max: float,
) -> list[str]:
    """Parte el texto en líneas que caben en ancho_max (puntos)."""
    t = (texto or "").strip() or "—"
    palabras = t.split()
    lineas: list[str] = []
    actual: list[str] = []
    for palabra in palabras:
        candidato = " ".join(actual + [palabra])
        w = pdfmetrics.stringWidth(candidato, fuente, tam)
        if w <= ancho_max:
            actual.append(palabra)
        else:
            if actual:
                lineas.append(" ".join(actual))
            # Palabra muy larga: cortar por caracteres si hace falta
            if pdfmetrics.stringWidth(palabra, fuente, tam) > ancho_max:
                resto = palabra
                while resto:
                    trozo = resto
                    while (
                        trozo
                        and pdfmetrics.stringWidth(trozo, fuente, tam) > ancho_max
                    ):
                        trozo = trozo[:-1]
                    if not trozo:
                        trozo = resto[0]
                    lineas.append(trozo)
                    resto = resto[len(trozo) :].lstrip()
                actual = []
            else:
                actual = [palabra]
    if actual:
        lineas.append(" ".join(actual))
    return lineas


def _tamanos_fuente_proporcionales(
    cell_w: float,
    cell_h: float,
    etiquetas_por_hoja: int,
) -> tuple[float, float, float]:
    """
    Devuelve (tamaño_descripcion, tamaño_precio, altura_máx_barras)
    proporcional al tamaño de cada celda.
    """
    # Referencia: celda “grande” ~ mitad de página
    ref = min(PAGE_W, PAGE_H) / 2.5
    escala = min(cell_w, cell_h) / ref
    escala = max(0.45, min(1.35, escala))

    base_desc = {2: 11.0, 4: 9.5, 8: 8.0, 16: 6.5}.get(
        etiquetas_por_hoja, 8.0
    )
    base_precio = {2: 20.0, 4: 16.0, 8: 13.0, 16: 10.5}.get(
        etiquetas_por_hoja, 13.0
    )

    tam_desc = max(5.0, min(16.0, base_desc * escala))
    tam_precio = max(7.0, min(24.0, base_precio * escala))
    altura_barra = max(28.0, min(cell_h * 0.42, cell_h * 0.5 * escala))
    return tam_desc, tam_precio, altura_barra


def generar_pdf_etiquetas(
    productos: list[dict[str, Any]],
    etiquetas_por_hoja: int,
    ruta_salida: str | Path,
    generador_barras: Callable[[str, str | None], Path] | None = None,
) -> Path:
    """
    Crea un PDF tamaño carta con las etiquetas indicadas.

    Args:
        productos: Lista de dicts con claves codigo, descripcion, precio (y opcional id).
        etiquetas_por_hoja: 2, 4, 8 o 16.
        ruta_salida: Ruta del PDF a crear.
        generador_barras: Inyectable para pruebas; por defecto generar_imagen_code128.

    Returns:
        Ruta del PDF generado.

    Raises:
        ValueError: Parámetros inválidos o lista vacía.
        RuntimeError: Errores al escribir el PDF o generar imágenes.
    """
    if etiquetas_por_hoja not in GRID_POR_ETIQUETAS:
        raise ValueError(
            "etiquetas_por_hoja debe ser 2, 4, 8 o 16."
        )
    if not productos:
        raise ValueError("No hay productos para generar etiquetas.")

    gen_bc = generador_barras or generar_imagen_code128
    cols, rows = GRID_POR_ETIQUETAS[etiquetas_por_hoja]
    slots = cols * rows

    usable_w = PAGE_W - 2 * MARGIN_X
    usable_h = PAGE_H - 2 * MARGIN_Y
    cell_w = usable_w / cols
    cell_h = usable_h / rows

    tam_desc, tam_precio, altura_barra_objetivo = (
        _tamanos_fuente_proporcionales(cell_w, cell_h, etiquetas_por_hoja)
    )

    out = Path(ruta_salida)
    out.parent.mkdir(parents=True, exist_ok=True)

    temp_pngs: list[Path] = []
    try:
        c = canvas.Canvas(str(out), pagesize=letter)
        fuente = "Helvetica"
        fuente_negrita = "Helvetica-Bold"

        idx_global = 0
        n = len(productos)

        # Paginar: cada hoja tiene hasta `slots` etiquetas en la cuadrícula definida
        while idx_global < n:
            for slot in range(slots):
                if idx_global >= n:
                    break
                prod = productos[idx_global]
                idx_global += 1

                col = slot % cols
                row = slot // cols  # fila 0 = parte superior de la página

                x0 = MARGIN_X + col * cell_w
                # ReportLab usa origen abajo-izquierda; y0 es la base de la celda
                y0 = PAGE_H - MARGIN_Y - (row + 1) * cell_h

                pad = max(4.0, min(10.0, cell_w * 0.04))
                x_centro = x0 + cell_w / 2
                ancho_texto = cell_w - 2 * pad

                codigo = str(prod.get("codigo", "")).strip()
                descripcion = str(prod.get("descripcion", "")).strip()
                try:
                    precio_val = float(prod.get("precio", 0))
                except (TypeError, ValueError):
                    precio_val = 0.0
                precio_txt = f"${precio_val:,.2f}"

                # Borde suave de celda (opcional, ayuda al corte)
                c.setStrokeGray(0.88)
                c.setLineWidth(0.3)
                c.rect(x0, y0, cell_w, cell_h, stroke=1, fill=0)

                png_path = gen_bc(codigo, "lbl")
                temp_pngs.append(png_path)

                # Imagen del barras escalada al ancho/alto disponibles
                box_w = ancho_texto
                box_h = min(altura_barra_objetivo, cell_h * 0.45)
                try:
                    if PILImage is None:
                        raise RuntimeError("Pillow no está disponible.")
                    with PILImage.open(png_path) as im:
                        iw, ih = im.size
                    if iw <= 0 or ih <= 0:
                        raise ValueError("Dimensiones de imagen inválidas.")
                    escala_img = min(box_w / iw, box_h / ih)
                    dw = iw * escala_img
                    dh = ih * escala_img
                except Exception:
                    # Si PIL falla, tamaño por defecto razonable
                    dw, dh = box_w, box_h * 0.85

                img_x = x_centro - dw / 2
                img_y = y0 + cell_h - pad - dh
                c.drawImage(
                    str(png_path),
                    img_x,
                    img_y,
                    width=dw,
                    height=dh,
                    mask="auto",
                )

                # Descripción (centrada, varias líneas)
                c.setFont(fuente, tam_desc)
                lineas = _envolver_texto(descripcion, fuente, tam_desc, ancho_texto)
                leading = tam_desc * 1.15
                max_lines = max(
                    1,
                    int((img_y - y0 - pad * 2 - tam_precio * 1.4) / leading),
                )
                y_text = img_y - pad * 0.8
                for li in lineas[:max_lines]:
                    y_text -= leading
                    if y_text < y0 + pad + tam_precio:
                        break
                    c.drawCentredString(x_centro, y_text, li)

                # Precio en la parte inferior de la celda
                c.setFont(fuente_negrita, tam_precio)
                c.drawCentredString(x_centro, y0 + pad, precio_txt)

            # Nueva página solo si quedan productos (evita hoja en blanco al final)
            if idx_global < n:
                c.showPage()

        c.save()
    except Exception as e:
        if out.is_file():
            try:
                out.unlink()
            except OSError:
                pass
        raise RuntimeError(f"Error al generar el PDF: {e}") from e
    finally:
        for p in temp_pngs:
            try:
                if p.is_file():
                    p.unlink()
            except OSError:
                pass

    return out.resolve()
