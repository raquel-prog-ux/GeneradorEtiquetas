"""
Impresión de etiquetas: plantilla PDF + capa de datos (ReportLab) fusionada con pypdf/PyPDF2.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Callable

try:
    from PIL import Image as PILImage  # type: ignore[import-untyped]
except ImportError:
    PILImage = None  # type: ignore[misc, assignment]

try:
    from pypdf import PdfReader, PdfWriter  # type: ignore[import-untyped]
except ImportError:
    from PyPDF2 import PdfReader, PdfWriter  # type: ignore[import-untyped]

from reportlab.lib.colors import black  # type: ignore[import-untyped]
from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

from utils.barcode_gen import generar_imagen_code128

# --- Rutas base ---
_ROOT = Path(__file__).resolve().parent.parent.parent
_ASSETS = _ROOT / "assets"
_ICONS_DIR = _ASSETS / "icons"
_TEMP_DIR = _ASSETS / "temp"

# Plantillas por número de etiquetas por hoja
PLANTILLAS_PDF: dict[int, Path] = {
    2: _ASSETS / "Plantilla_2.pdf",
    4: _ASSETS / "Plantilla_4.pdf",
    8: _ASSETS / "Plantilla_8.pdf",
    16: _ASSETS / "Plantilla_16.pdf",
}

# Cuadrícula (columnas, filas) por formato
GRID_POR_ETIQUETAS: dict[int, tuple[int, int]] = {
    2: (1, 2),
    4: (2, 2),
    8: (2, 4),
    16: (4, 4),
}

# Márgenes respecto al borde de la página (puntos PDF), coherentes con la rejilla
MARGIN_X = 36
MARGIN_Y = 36

# Logo sucursal (izquierda): mismo mapa que antes
LOGO_POR_SUCURSAL: dict[str, Path] = {
    f"Sucursal {n}": _ICONS_DIR / f"Logos_Plaza Guzman-{n:02d}.png"
    for n in range(1, 13)
}

_LOGO_DERECHA_PRINCIPAL = _ICONS_DIR / "Logos_Plaza Guzman-01.png"
_LOGO_DERECHA_RESPALDO = _ICONS_DIR / "Logos_Plaza Guzman_Mesa de trabajo 1.png"

# Logo "Novedades Lilian" (derecha): nombres habituales; si no hay archivo, se usa respaldo
_CANDIDATOS_LOGO_LILIAN: tuple[Path, ...] = (
    _ICONS_DIR / "Novedades_Lilian.png",
    _ICONS_DIR / "Novedades Lilian.png",
    _ICONS_DIR / "Logo_Novedades_Lilian.png",
    _ICONS_DIR / "NovedadesLilian.png",
)


def _numero_sucursal(sucursal: str) -> int:
    s = (sucursal or "").strip()
    if not s.lower().startswith("sucursal"):
        return 1
    try:
        n = int(s.replace("Sucursal", "").strip())
    except ValueError:
        return 1
    return max(1, min(12, n))


def ruta_logo_sucursal(sucursal: str) -> Path:
    clave = f"Sucursal {_numero_sucursal(sucursal)}"
    return LOGO_POR_SUCURSAL.get(clave, LOGO_POR_SUCURSAL["Sucursal 1"])


def ruta_logo_novedades_lilian() -> Path:
    """Logo fijo esquina derecha (Novedades Lilian o respaldo Plaza Guzmán)."""
    for p in _CANDIDATOS_LOGO_LILIAN:
        if p.is_file():
            return p
    if _LOGO_DERECHA_PRINCIPAL.is_file():
        return _LOGO_DERECHA_PRINCIPAL
    if _LOGO_DERECHA_RESPALDO.is_file():
        return _LOGO_DERECHA_RESPALDO
    return _CANDIDATOS_LOGO_LILIAN[0]


def _tamano_pagina_pdf(reader: Any) -> tuple[float, float]:
    """Ancho y alto en puntos desde mediabox de la primera página."""
    box = reader.pages[0].mediabox
    return float(box.width), float(box.height)


def _envolver_texto(
    texto: str,
    fuente: str,
    tam: float,
    ancho_max: float,
) -> list[str]:
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


def _tamano_imagen_ajustada(
    png_path: Path, max_w: float, max_h: float
) -> tuple[float, float]:
    try:
        if PILImage is None:
            raise RuntimeError("Pillow no está disponible.")
        with PILImage.open(png_path) as im:
            iw, ih = im.size
        if iw <= 0 or ih <= 0:
            raise ValueError("Dimensiones inválidas.")
        escala = min(max_w / iw, max_h / ih)
        return iw * escala, ih * escala
    except Exception:
        return max_w * 0.9, max_h * 0.85


# --- Diccionario de coordenadas por formato: offsets relativos a la celda (0..1) ---
# Cada clave describe la posición dentro de la celda para encajar en los cuadros de la plantilla.
# Formato: fracciones del ancho/alto de celda desde esquina inferior izquierda de la celda.
COORD_RELATIVAS: dict[int, dict[str, tuple[float, float, float, float]]] = {
    2: {
        "logo_izq": (0.04, 0.72, 0.38, 0.22),
        "logo_der": (0.58, 0.72, 0.38, 0.22),
        "precio": (0.12, 0.46, 0.76, 0.20),
        "codigo": (0.08, 0.36, 0.84, 0.06),
        "barcode": (0.08, 0.16, 0.84, 0.18),
        "descripcion": (0.06, 0.04, 0.88, 0.10),
    },
    # Formato 4: logo izq arriba-izq; código en casilla “CÓDIGO:”; barras a la derecha (misma franja, más arriba)
    4: {
        "logo_izq": (0.02, 0.74, 0.36, 0.22),
        "logo_der": (0.58, 0.70, 0.38, 0.22),
        "precio": (0.10, 0.44, 0.80, 0.22),
        "codigo": (0.052, 0.378, 0.28, 0.065),
        "barcode": (0.36, 0.362, 0.58, 0.128),
        "descripcion": (0.06, 0.04, 0.88, 0.08),
    },
    8: {
        "logo_izq": (0.03, 0.68, 0.40, 0.20),
        "logo_der": (0.57, 0.68, 0.40, 0.20),
        "precio": (0.08, 0.42, 0.84, 0.20),
        "codigo": (0.06, 0.32, 0.88, 0.05),
        "barcode": (0.06, 0.14, 0.88, 0.16),
        "descripcion": (0.05, 0.03, 0.90, 0.08),
    },
    16: {
        "logo_izq": (0.02, 0.66, 0.42, 0.18),
        "logo_der": (0.56, 0.66, 0.42, 0.18),
        "precio": (0.06, 0.40, 0.88, 0.18),
        "codigo": (0.05, 0.30, 0.90, 0.05),
        "barcode": (0.05, 0.12, 0.90, 0.15),
        "descripcion": (0.04, 0.02, 0.92, 0.07),
    },
}


def _rect_absoluto_celda(
    x0: float,
    y0: float,
    cw: float,
    ch: float,
    rel: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Convierte (fx, fy, fw, fh) relativos a la celda en (x, y, w, h) PDF."""
    fx, fy, fw, fh = rel
    w = cw * fw
    h = ch * fh
    x = x0 + cw * fx
    y = y0 + ch * fy
    return x, y, w, h


def _dibujar_contenido_celda(
    c: canvas.Canvas,
    formato: int,
    x0: float,
    y0: float,
    cw: float,
    ch: float,
    prod: dict[str, Any],
    sucursal: str,
    gen_bc: Callable[[str, str | None], Path],
    temp_pngs: list[Path],
) -> None:
    """Dibuja solo datos dinámicos sobre una celda (sin marcos: la plantilla ya los trae)."""
    rel = COORD_RELATIVAS[formato]
    logo_izq_p = ruta_logo_sucursal(sucursal)
    logo_der_p = ruta_logo_novedades_lilian()

    try:
        precio_val = float(prod.get("precio", 0))
    except (TypeError, ValueError):
        precio_val = 0.0
    # Solo número (la plantilla ya incluye el símbolo $ en el círculo)
    precio_txt = f"{precio_val:,.2f}"
    codigo = str(prod.get("codigo", "")).strip()
    descripcion = str(prod.get("descripcion", "")).strip()

    # --- Logos: sucursal arriba-izquierda en formato 4; derecha sin cambios (centrado vertical en caja) ---
    for nombre, path in (("logo_izq", logo_izq_p), ("logo_der", logo_der_p)):
        rx, ry, rw, rh = _rect_absoluto_celda(x0, y0, cw, ch, rel[nombre])
        if path.is_file():
            dw, dh = _tamano_imagen_ajustada(path, rw - 4, rh - 4)
            if nombre == "logo_izq" and formato == 4:
                # Esquina superior izquierda del área de logo
                ix = rx + 3
                iy = ry + rh - dh - 3
            else:
                ix = rx + 2
                iy = ry + (rh - dh) / 2
            c.drawImage(
                str(path),
                ix,
                iy,
                width=dw,
                height=dh,
                mask="auto",
            )

    # --- Precio (sin círculo ni $: la plantilla ya los trae) ---
    px, py, pw, ph = _rect_absoluto_celda(x0, y0, cw, ch, rel["precio"])
    c.setFillColor(black)
    # Formato 4: fuente al doble del tamaño base anterior (~0.48 * ph → ~0.96 * ph)
    base_factor = 0.96 if formato == 4 else 0.48
    tam_precio = ph * base_factor
    fuente_p = "Helvetica-Bold"
    # En formato 4 el monto va a la derecha del círculo impreso en la plantilla
    if formato == 4:
        area_x = px + pw * 0.26
        area_w = pw * 0.72
    else:
        area_x = px + pw * 0.05
        area_w = pw * 0.90
    while tam_precio > 10 and pdfmetrics.stringWidth(
        precio_txt, fuente_p, tam_precio
    ) > area_w:
        tam_precio -= 1.0
    c.setFont(fuente_p, tam_precio)
    c.drawCentredString(
        area_x + area_w / 2,
        py + ph / 2 - tam_precio * 0.3,
        precio_txt,
    )

    # --- Código numérico (texto): centrado en la casilla “CÓDIGO:” ---
    cx_r, cy_r, cw_r, ch_r = _rect_absoluto_celda(x0, y0, cw, ch, rel["codigo"])
    c.setFillColor(black)
    tam_cod = min(9.0, ch_r * 0.75)
    c.setFont("Helvetica-Bold", tam_cod)
    baseline_cod = cy_r + ch_r / 2 - tam_cod * 0.28
    c.drawCentredString(cx_r + cw_r / 2, baseline_cod, codigo or "—")

    # --- Código de barras (zona reservada en plantilla) ---
    bx, by, bw, bh = _rect_absoluto_celda(x0, y0, cw, ch, rel["barcode"])
    if codigo:
        png_path = gen_bc(codigo, "lbl")
        temp_pngs.append(png_path)
        pad = 4.0
        dw, dh = _tamano_imagen_ajustada(png_path, bw - 2 * pad, bh - 2 * pad)
        c.drawImage(
            str(png_path),
            bx + (bw - dw) / 2,
            by + (bh - dh) / 2,
            width=dw,
            height=dh,
            mask="auto",
        )

    # --- Descripción ---
    dx, dy, dw, dh = _rect_absoluto_celda(x0, y0, cw, ch, rel["descripcion"])
    fuente = "Helvetica-Bold"
    tam_desc = min(10.0, dh * 0.55)
    tam_desc = max(5.0, tam_desc)
    lineas = _envolver_texto(descripcion, fuente, tam_desc, dw - 6)
    leading = tam_desc * 1.1
    max_lines = max(1, int((dh - 4) / leading))
    y_t = dy + dh - tam_desc - 2
    c.setFont(fuente, tam_desc)
    for li in lineas[:max_lines]:
        wline = pdfmetrics.stringWidth(li, fuente, tam_desc)
        c.drawString(dx + (dw - wline) / 2, y_t, li)
        y_t -= leading


def _capa_datos_pdf_bytes(
    formato: int,
    page_w: float,
    page_h: float,
    productos_en_hoja: list[dict[str, Any]],
    sucursal: str,
    gen_bc: Callable[[str, str | None], Path],
    temp_pngs: list[Path],
) -> bytes:
    """Genera un PDF de una página en memoria con la capa de datos (solo contenido)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))

    cols, rows = GRID_POR_ETIQUETAS[formato]
    usable_w = page_w - 2 * MARGIN_X
    usable_h = page_h - 2 * MARGIN_Y
    cell_w = usable_w / cols
    cell_h = usable_h / rows

    for slot, prod in enumerate(productos_en_hoja):
        col = slot % cols
        row = slot // cols
        x0 = MARGIN_X + col * cell_w
        y0 = page_h - MARGIN_Y - (row + 1) * cell_h
        _dibujar_contenido_celda(
            c, formato, x0, y0, cell_w, cell_h, prod, sucursal, gen_bc, temp_pngs
        )

    c.save()
    buf.seek(0)
    return buf.read()


def _fusionar_plantilla_y_capa(
    ruta_plantilla: Path,
    capa_bytes: bytes,
) -> Any:
    """Devuelve un PageObject: plantilla base con la capa fusionada encima."""
    base_reader = PdfReader(str(ruta_plantilla))
    base_page = base_reader.pages[0]
    overlay_reader = PdfReader(io.BytesIO(capa_bytes))
    overlay_page = overlay_reader.pages[0]
    # merge_page dibuja el argumento encima de la página base
    base_page.merge_page(overlay_page)
    return base_page


def _limpiar_temporales_assets(registrados: list[Path]) -> None:
    """Elimina PNG generados y limpia assets/temp/ (solo archivos .png)."""
    for p in registrados:
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass
    try:
        _TEMP_DIR.mkdir(parents=True, exist_ok=True)
        for p in _TEMP_DIR.glob("*.png"):
            try:
                p.unlink()
            except OSError:
                pass
    except OSError:
        pass


def generar_pdf_etiquetas(
    productos: list[dict[str, Any]],
    etiquetas_por_hoja: int,
    ruta_salida: str | Path,
    sucursal: str = "Sucursal 1",
    generador_barras: Callable[[str, str | None], Path] | None = None,
) -> Path:
    """
    Genera el PDF final: para cada hoja carga la plantilla, crea la capa de datos
    en memoria (ReportLab) y fusiona con merge_page.

    Args:
        productos: Lista de dicts con codigo, descripcion, precio.
        etiquetas_por_hoja: 2, 4, 8 o 16.
        ruta_salida: Archivo PDF de salida.
        sucursal: Selección de logo izquierdo (Sucursal 1…12).
        generador_barras: Opcional para pruebas.
    """
    if etiquetas_por_hoja not in GRID_POR_ETIQUETAS:
        raise ValueError("etiquetas_por_hoja debe ser 2, 4, 8 o 16.")
    if not productos:
        raise ValueError("No hay productos para generar etiquetas.")

    plantilla_path = PLANTILLAS_PDF.get(etiquetas_por_hoja)
    if not plantilla_path or not plantilla_path.is_file():
        raise FileNotFoundError(
            f"No se encontró la plantilla: {plantilla_path}"
        )

    gen_bc = generador_barras or generar_imagen_code128
    cols, rows = GRID_POR_ETIQUETAS[etiquetas_por_hoja]
    slots = cols * rows

    out = Path(ruta_salida)
    out.parent.mkdir(parents=True, exist_ok=True)

    temp_pngs: list[Path] = []
    writer = PdfWriter()

    try:
        # Dimensiones de la plantilla (carta vertical u horizontal según archivo)
        tr = PdfReader(str(plantilla_path))
        page_w, page_h = _tamano_pagina_pdf(tr)

        idx = 0
        n = len(productos)
        while idx < n:
            chunk = productos[idx : idx + slots]
            idx += len(chunk)
            # Solo se dibujan celdas con producto; el resto de la hoja queda solo la plantilla

            capa_bytes = _capa_datos_pdf_bytes(
                etiquetas_por_hoja,
                page_w,
                page_h,
                chunk,
                sucursal,
                gen_bc,
                temp_pngs,
            )
            pagina_fusionada = _fusionar_plantilla_y_capa(plantilla_path, capa_bytes)
            writer.add_page(pagina_fusionada)

        with open(out, "wb") as f:
            writer.write(f)
    except Exception as e:
        if out.is_file():
            try:
                out.unlink()
            except OSError:
                pass
        raise RuntimeError(f"Error al generar el PDF: {e}") from e
    finally:
        _limpiar_temporales_assets(temp_pngs)

    return out.resolve()
