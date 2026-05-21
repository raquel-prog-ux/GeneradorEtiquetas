"""
Impresión de etiquetas: plantilla PDF + capa de datos (ReportLab) fusionada con pypdf/PyPDF2.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Callable, Union

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

# Mayoreo: plantillas en PNG (se convierten a PDF en memoria).
# - FORMATO_4_MAYOREO usa una hoja carta con 2x2 etiquetas (plantilla_mayoreo.png).
# - FORMATO_2_MAYOREO usa una hoja carta con 1x2 etiquetas (etiquetas_2_mayoreo.png).
FORMATO_4_MAYOREO = "4_MAYOREO"
FORMATO_2_MAYOREO = "2_MAYOREO"

# Conjunto de claves "mayoreo" para chequeos rapidos.
FORMATOS_MAYOREO: tuple[str, ...] = (FORMATO_4_MAYOREO, FORMATO_2_MAYOREO)

# Mapas formato -> plantilla PNG y formato -> JSON de sobrecarga (zonas y margenes).
PLANTILLAS_PNG_MAYOREO: dict[str, Path] = {
    FORMATO_4_MAYOREO: _ASSETS / "plantilla_mayoreo.png",
    FORMATO_2_MAYOREO: _ASSETS / "etiquetas_2_mayoreo.png",
}
ARCHIVOS_COORDENADAS_MAYOREO: dict[str, Path] = {
    FORMATO_4_MAYOREO: _ASSETS / "coordenadas_4_mayoreo.json",
    FORMATO_2_MAYOREO: _ASSETS / "coordenadas_2_mayoreo.json",
}

# Compatibilidad con codigo previo (la GUI todavia se refiere a estos nombres
# para 4_MAYOREO). Permite hacer cambios incrementales sin romper imports.
PLANTILLA_MAYOREO_PNG = PLANTILLAS_PNG_MAYOREO[FORMATO_4_MAYOREO]
ARCHIVO_COORDENADAS_MAYOREO = ARCHIVOS_COORDENADAS_MAYOREO[FORMATO_4_MAYOREO]


def es_formato_mayoreo(formato: Union[int, str]) -> bool:
    """True si el formato es alguna variante mayoreo (plantilla PNG)."""
    return formato in FORMATOS_MAYOREO


# Plantillas por número de etiquetas por hoja
PLANTILLAS_PDF: dict[int, Path] = {
    2: _ASSETS / "Plantilla_2.pdf",
    4: _ASSETS / "Plantilla_4.pdf",
    8: _ASSETS / "Plantilla_8.pdf",
    16: _ASSETS / "Plantilla_16.pdf",
}

# Cuadrícula (columnas, filas) por formato
GRID_POR_ETIQUETAS: dict[Union[int, str], tuple[int, int]] = {
    2: (1, 2),
    4: (2, 2),
    8: (2, 4),
    16: (4, 4),
    FORMATO_4_MAYOREO: (2, 2),
    FORMATO_2_MAYOREO: (1, 2),
}

# Márgenes respecto al borde de la página (puntos PDF), coherentes con la rejilla
MARGIN_X = 36
MARGIN_Y = 36

# Para el formato mayoreo la plantilla PNG ya trae su propio espacio en blanco
# (cuatro etiquetas con bordes). Si forzamos los 36pt del resto, las celdas se
# desplazan y las cajas detectadas (CÓDIGO, DESCRIPCIÓN, PRECIO, A PARTIR DE,
# etc.) ya no coinciden con la rejilla del overlay → de ahí que todo aparecía
# diminuto y descentrado. Con margen 0 cada celda mide exactamente la mitad de
# la imagen y las fracciones de COORD_RELATIVAS apuntan al lugar correcto.
MARGIN_X_MAYOREO = 0
MARGIN_Y_MAYOREO = 0

# Nombres comerciales por sucursal (numero -> nombre amigable).
# Se usan para etiquetar el desplegable de la GUI y para mostrar al usuario;
# internamente la sucursal se sigue identificando por su numero.
NOMBRES_SUCURSAL: dict[int, str] = {
    1: "Novedades Lilian",
    2: "Novedades Margarita",
    3: "Novedades Hector",
    4: "Novedades Julia",
    5: "Novedades Julia B",
    6: "Novedades Jesús María",
    7: "Novedades Claudia",
    8: "Bonetería Richi 1",
    9: "Bonetería Richi 2",
    10: "Bonetería Richi 3",
    11: "Novedades Manzanares",
    12: "Novedades Zapata",
}

def _resolver_logo_sucursal(n: int) -> Path:
    """Devuelve el PNG del logo de la sucursal `n`.

    Probamos primero el nombre canonico ("Logos_Plaza Guzman-NN.png") y, si no
    existe (caso real de la Sucursal 1 cuyo PNG quedo exportado como
    "Logos_Plaza Guzman_Mesa de trabajo 1.png"), recorremos los archivos del
    directorio buscando alguno que termine en "-NN.png" o "_Mesa de trabajo N.png".
    Esto evita que el logo dejara de dibujarse cuando el nombre del archivo no
    coincide con la convencion `-NN`.
    """
    canonico = _ICONS_DIR / f"Logos_Plaza Guzman-{n:02d}.png"
    if canonico.is_file():
        return canonico
    # Sucursal 1 historicamente quedo con nombre "Mesa de trabajo 1".
    mesa = _ICONS_DIR / f"Logos_Plaza Guzman_Mesa de trabajo {n}.png"
    if mesa.is_file():
        return mesa
    # Ultimo recurso: cualquier archivo cuyo nombre contenga "-NN" o
    # "Mesa de trabajo N" (con N sin ceros).
    if _ICONS_DIR.is_dir():
        suf_nn = f"-{n:02d}.png".lower()
        suf_mesa = f"mesa de trabajo {n}.png".lower()
        for p in _ICONS_DIR.glob("*.png"):
            low = p.name.lower()
            if low.endswith(suf_nn) or low.endswith(suf_mesa):
                return p
    return canonico  # se devolvera pero `.is_file()` sera False


# Logo sucursal (izquierda): se resuelve dinamicamente por numero de sucursal.
LOGO_POR_SUCURSAL: dict[str, Path] = {
    f"Sucursal {n}": _resolver_logo_sucursal(n) for n in range(1, 13)
}


def etiqueta_sucursal(n: int) -> str:
    """Texto amigable para combos/UI: 'Sucursal N: Nombre comercial'."""
    n = max(1, min(12, int(n)))
    nombre = NOMBRES_SUCURSAL.get(n, "")
    return f"Sucursal {n}: {nombre}" if nombre else f"Sucursal {n}"


def opciones_sucursal() -> tuple[str, ...]:
    """Lista ordenada de etiquetas de sucursal (para el combobox de la GUI)."""
    return tuple(etiqueta_sucursal(n) for n in range(1, 13))


def _numero_sucursal(sucursal: str) -> int:
    """Extrae el numero de sucursal de cualquier texto que empiece por 'Sucursal'.

    Acepta tanto el formato antiguo ("Sucursal 3") como el nuevo
    ("Sucursal 3: Novedades Hector"), asi que los datos previos siguen
    apuntando al logo correcto.
    """
    s = (sucursal or "").strip()
    if not s.lower().startswith("sucursal"):
        return 1
    resto = s[len("Sucursal"):].strip()
    # Toma solo el primer token numerico (separado por espacios, ':' o ',').
    numero = ""
    for ch in resto:
        if ch.isdigit():
            numero += ch
        elif numero:
            break
        elif not ch.isspace():
            break
    try:
        n = int(numero) if numero else 1
    except ValueError:
        return 1
    return max(1, min(12, n))


def ruta_logo_sucursal(sucursal: str) -> Path:
    clave = f"Sucursal {_numero_sucursal(sucursal)}"
    return LOGO_POR_SUCURSAL.get(clave, LOGO_POR_SUCURSAL["Sucursal 1"])


def _tamano_pagina_pdf(reader: Any) -> tuple[float, float]:
    """Ancho y alto en puntos desde mediabox de la primera página."""
    box = reader.pages[0].mediabox
    return float(box.width), float(box.height)


def _plantilla_pdf_bytes_desde_png(ruta_png: Path) -> tuple[bytes, float, float]:
    """
    Construye un PDF de una pagina a partir del PNG (tamaño pagina = pixeles de la imagen).
    Asi merge_page funciona igual que con plantillas PDF.
    """
    if PILImage is None:
        raise RuntimeError("Pillow es necesario para la plantilla PNG de mayoreo.")
    if not ruta_png.is_file():
        raise FileNotFoundError(f"No se encontro la plantilla: {ruta_png}")
    with PILImage.open(ruta_png) as im:
        w_pt, h_pt = float(im.size[0]), float(im.size[1])
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w_pt, h_pt))
    c.drawImage(str(ruta_png), 0, 0, width=w_pt, height=h_pt, mask="auto")
    c.save()
    buf.seek(0)
    return buf.read(), w_pt, h_pt


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


# --- Coordenadas por plantilla PDF (una entrada por etiquetas_por_hoja) ---
# Cada plantilla tiene su propio dict: edita solo el bloque 2, 4, 8 o 16 que corresponda al PDF en assets/.
# Tupla por zona: (fx, fy, fw, fh) = posición y tamaño como fracción de la celda (origen abajo-izq. de la celda).
#   fx, fy = desplazamiento; fw, fh = ancho y alto relativos. Usa “Depuración: marcos de coordenadas” en la GUI.
COORD_RELATIVAS: dict[Union[int, str], dict[str, tuple[float, float, float, float]]] = {
    # assets/Plantilla_2.pdf — 1×2 etiquetas por hoja
    2: {
        "logo_izq": (0.01, 0.80, 0.30, 0.30),
        "precio": (0.07, 0.50, 0.65, 0.30),
        "codigo": (0.05, 0.01, 0.20, 0.60),
        "barcode": (0.30, 0.22, 0.60, 0.25),
        "descripcion": (0.01, 0.03, 0.88, 0.07),
    },
    # assets/Plantilla_4.pdf — 2×2 (referencia calibrada; 2/8/16 copian estos valores hasta que ajustes cada PDF)
    4: {
        "logo_izq": (0.01, 0.80, 0.30, 0.30),
        "precio": (0.07, 0.50, 0.65, 0.30),
        "codigo": (0.05, 0.01, 0.20, 0.60),
        "barcode": (0.30, 0.22, 0.60, 0.25),
        "descripcion": (0.01, 0.06, 0.88, 0.08),
    },
    # assets/Plantilla_8.pdf — 2×4
    8: {
        "logo_izq": (0.08, 0.90, 0.30, 0.30),
        "precio": (0.10, 0.53, 0.65, 0.30),
        "codigo": (0.09, 0.08, 0.20, 0.65),
        "barcode": (0.40, 0.32, 0.60, 0.25),
        "descripcion": (0.02, 0.15, 0.88, 0.08),
    },
    # assets/Plantilla_16.pdf — 4×4
    16: {
        "logo_izq": (0.05, 0.85, 0.30, 0.30),
        "precio": (0.10, 0.50, 0.65, 0.30),
        "codigo": (0.05, 0.01, 0.20, 0.60),
        "barcode": (0.50, 0.27, 0.60, 0.25),
        "descripcion": (0.01, 0.13, 0.88, 0.08),
    },
    # assets/plantilla_mayoreo.png — 2x2.
    # Fracciones medidas directamente sobre la PNG (analizando los bordes negros
    # de cada caja). Con MARGIN_*_MAYOREO=0 estas zonas coinciden con los
    # rectangulos impresos por la plantilla.
    FORMATO_4_MAYOREO: {
        # Logo sucursal: arriba a la izquierda (esquina opuesta al logo
        # "PLAZA GUZMAN" que ya trae la plantilla a la derecha), igual que en
        # los formatos Plantilla_2/4/8/16. La zona es generosa para que el
        # logo se vea con un tamano comparable al PG, sin invadir la caja
        # CODIGO (cuyo borde superior cae en fy=0.770).
        "logo_izq": (0.02, 0.800, 0.30, 0.150),
        # Numero de codigo dentro de la caja "CODIGO" (rotulo a la izquierda).
        "codigo": (0.25, 0.668, 0.65, 0.100),
        # Descripcion dentro de la caja "DESCRIPCION" (rotulo a la izquierda).
        "descripcion": (0.32, 0.555, 0.58, 0.097),
        # Precio por pieza: caja completa a la derecha del simbolo "$".
        "precio_regular": (0.424, 0.398, 0.452, 0.135),
        # Precio por mayoreo: caja izquierda inferior (debajo de "PRECIO POR MAYOREO $").
        "precio_mayoreo": (0.424, 0.196, 0.249, 0.135),
        # "A partir de": caja derecha inferior, debajo del rotulo "A PARTIR DE".
        "cantidad_mayoreo": (0.692, 0.196, 0.225, 0.135),
        # Codigo de barras (y el codigo legible que python-barcode dibuja
        # debajo de las barras) en el espacio libre de la parte inferior.
        "barcode": (0.15, 0.005, 0.70, 0.180),
    },
    # assets/etiquetas_2_mayoreo.png — 1x2 (hoja carta con 2 etiquetas mayoreo
    # apiladas). Mismas zonas conceptuales que 4_MAYOREO; las fracciones
    # cambian porque las cajas no estan en exactamente el mismo lugar dentro
    # de la celda.
    FORMATO_2_MAYOREO: {
        # Logo sucursal arriba a la izquierda (la plantilla trae el logo PG
        # arriba a la derecha en la misma franja). Zona generosa para que se
        # equilibre visualmente con el PG; no invade la caja CODIGO (borde
        # superior en fy=0.797).
        "logo_izq": (0.02, 0.820, 0.35, 0.160),
        "codigo": (0.24, 0.685, 0.625, 0.110),
        "descripcion": (0.32, 0.556, 0.545, 0.110),
        "precio_regular": (0.418, 0.382, 0.405, 0.150),
        "precio_mayoreo": (0.420, 0.156, 0.210, 0.152),
        "cantidad_mayoreo": (0.672, 0.156, 0.190, 0.152),
        "barcode": (0.10, 0.005, 0.80, 0.140),
    },
}


def _copia_zonas_mayoreo_base(
    formato: str = FORMATO_4_MAYOREO,
) -> dict[str, tuple[float, float, float, float]]:
    return {k: tuple(v) for k, v in COORD_RELATIVAS[formato].items()}


def cargar_coordenadas_mayoreo(
    formato: str = FORMATO_4_MAYOREO,
) -> tuple[dict[str, tuple[float, float, float, float]], float, float]:
    """
    Valores efectivos para un formato mayoreo: base en código + JSON opcional.
    El JSON puede definir "margenes" (margin_x, margin_y) y "zonas" (clave → [fx,fy,fw,fh]).
    """
    if formato not in FORMATOS_MAYOREO:
        raise ValueError(f"Formato mayoreo desconocido: {formato!r}")
    zonas = _copia_zonas_mayoreo_base(formato)
    mx, my = float(MARGIN_X_MAYOREO), float(MARGIN_Y_MAYOREO)
    archivo = ARCHIVOS_COORDENADAS_MAYOREO[formato]
    if not archivo.is_file():
        return zonas, mx, my
    try:
        raw = archivo.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return zonas, mx, my
    z = data.get("zonas") or data.get("coordenadas")
    if isinstance(z, dict):
        for nombre, tupla in z.items():
            if isinstance(tupla, (list, tuple)) and len(tupla) == 4:
                try:
                    zonas[str(nombre)] = tuple(float(x) for x in tupla)
                except (TypeError, ValueError):
                    pass
    m = data.get("margenes") or data.get("márgenes")
    if isinstance(m, dict):
        try:
            if "margin_x" in m:
                mx = float(m["margin_x"])
            if "margin_y" in m:
                my = float(m["margin_y"])
        except (TypeError, ValueError):
            pass
    return zonas, mx, my


def guardar_coordenadas_mayoreo(
    zonas: dict[str, tuple[float, float, float, float]],
    margin_x: float,
    margin_y: float,
    formato: str = FORMATO_4_MAYOREO,
) -> None:
    """Persiste zonas y margenes del formato mayoreo indicado en su JSON."""
    if formato not in FORMATOS_MAYOREO:
        raise ValueError(f"Formato mayoreo desconocido: {formato!r}")
    archivo = ARCHIVOS_COORDENADAS_MAYOREO[formato]
    payload = {
        "margenes": {"margin_x": margin_x, "margin_y": margin_y},
        "zonas": {k: list(v) for k, v in zonas.items()},
    }
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# Colores de trazo por clave (modo depuración de COORD_RELATIVAS)
_MARCOS_RGB: dict[str, tuple[float, float, float]] = {
    "logo_izq": (0.9, 0.15, 0.15),
    "precio": (0.15, 0.65, 0.15),
    "precio_regular": (0.2, 0.75, 0.25),
    "precio_mayoreo": (0.15, 0.45, 0.65),
    "cantidad_mayoreo": (0.65, 0.35, 0.85),
    "codigo": (0.55, 0.15, 0.75),
    "barcode": (0.85, 0.45, 0.1),
    "descripcion": (0.1, 0.55, 0.55),
}


def _dibujar_marcos_coordenadas_celda(
    c: canvas.Canvas,
    formato: Union[int, str],
    x0: float,
    y0: float,
    cw: float,
    ch: float,
    rel_override: dict[str, tuple[float, float, float, float]] | None = None,
) -> None:
    """Dibuja contornos y etiquetas de cada zona definida en COORD_RELATIVAS (solo depuración)."""
    rel = rel_override if rel_override is not None else COORD_RELATIVAS[formato]
    c.saveState()
    c.setLineWidth(0.8)
    for nombre, cuad in rel.items():
        rx, ry, rw, rh = _rect_absoluto_celda(x0, y0, cw, ch, cuad)
        r, g, b = _MARCOS_RGB.get(nombre, (0.4, 0.4, 0.4))
        c.setStrokeColorRGB(r, g, b)
        c.rect(rx, ry, rw, rh, fill=0, stroke=1)
        c.setFillColorRGB(r, g, b)
        c.setFont("Helvetica-Bold", 5.5)
        c.drawString(rx + 1.5, ry + rh - 6.5, nombre)
    c.restoreState()


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


def _dibujar_texto_caja_centro(
    c: canvas.Canvas,
    texto: str,
    rx: float,
    ry: float,
    rw: float,
    rh: float,
    fuente: str = "Helvetica-Bold",
    factor_tam: float = 0.55,
) -> None:
    """Texto centrado en rectángulo; el tamaño sigue ancho y alto de la zona (no solo el alto)."""
    c.setFillColor(black)
    t = (texto or "").strip() or "—"
    margen = 4.0
    ancho_disp = max(rw - margen, 1.0)
    # Anchura del texto es ~ proporcional al tamaño de fuente → máximo por ancho de caja
    w_unit = pdfmetrics.stringWidth(t, fuente, 1.0)
    if w_unit > 0:
        tam_por_ancho = ancho_disp / w_unit
    else:
        tam_por_ancho = rh * factor_tam * 2
    tam_por_alto = rh * factor_tam
    # tam_por_alto y tam_por_ancho ya acotan el tamaño respecto a la caja.
    # Antes habia un tope fijo de 160 pt que penalizaba el formato mayoreo,
    # cuya pagina (= pixeles de la PNG) puede medir miles de puntos: las
    # cajas eran enormes pero el texto quedaba diminuto. El tope ahora es
    # proporcional al lado mayor de la zona.
    tam_tope = max(rh, rw) * 1.15
    tam = min(tam_por_alto, tam_por_ancho, tam_tope)
    tam = max(4.0, tam)
    while tam > 4.0 and pdfmetrics.stringWidth(t, fuente, tam) > ancho_disp:
        tam -= 0.5
    c.setFont(fuente, tam)
    c.drawCentredString(rx + rw / 2, ry + rh / 2 - tam * 0.28, t)


def _dibujar_contenido_celda_mayoreo(
    c: canvas.Canvas,
    x0: float,
    y0: float,
    cw: float,
    ch: float,
    prod: dict[str, Any],
    sucursal: str,
    gen_bc: Callable[[str, str | None], Path],
    temp_pngs: list[Path],
    mostrar_marcos_coordenadas: bool,
    rel: dict[str, tuple[float, float, float, float]],
) -> None:
    """Capa de datos para plantilla mayoreo (PNG); no altera el flujo del formato 4 PDF."""
    logo_izq_p = ruta_logo_sucursal(sucursal)

    try:
        pr = float(prod.get("precio_regular", prod.get("precio", 0)))
    except (TypeError, ValueError):
        pr = 0.0
    try:
        pm = float(prod.get("precio_mayoreo", prod.get("precio", 0)))
    except (TypeError, ValueError):
        pm = 0.0
    cant_txt = str(prod.get("cantidad_mayoreo", "") or "").strip() or "—"
    txt_reg = f"{pr:,.2f}"
    txt_may = f"{pm:,.2f}"

    codigo = str(prod.get("codigo", "")).strip()
    descripcion = str(prod.get("descripcion", "")).strip()

    rx, ry, rw, rh = _rect_absoluto_celda(x0, y0, cw, ch, rel["logo_izq"])
    # Logo sucursal arriba a la izquierda (mismo anclaje que las plantillas
    # PDF normales): a la altura del logo PG que viene impreso en el lado
    # derecho de la plantilla mayoreo. Si la zona queda casi en cero, no se
    # dibuja nada (asi el usuario puede desactivarlo desde la GUI).
    if logo_izq_p.is_file() and rw > 4 and rh > 4:
        dw, dh = _tamano_imagen_ajustada(logo_izq_p, rw - 4, rh - 4)
        ix = rx + 3
        iy = ry + rh - dh - 3
        c.drawImage(
            str(logo_izq_p),
            ix,
            iy,
            width=dw,
            height=dh,
            mask="auto",
        )

    px, py, pw, ph = _rect_absoluto_celda(
        x0, y0, cw, ch, rel["precio_regular"]
    )
    _dibujar_texto_caja_centro(c, txt_reg, px, py, pw, ph)

    qx, qy, qw, qh = _rect_absoluto_celda(
        x0, y0, cw, ch, rel["cantidad_mayoreo"]
    )
    _dibujar_texto_caja_centro(c, cant_txt, qx, qy, qw, qh, factor_tam=0.65)

    mx, my, mw, mh = _rect_absoluto_celda(
        x0, y0, cw, ch, rel["precio_mayoreo"]
    )
    _dibujar_texto_caja_centro(c, txt_may, mx, my, mw, mh)

    cx_r, cy_r, cw_r, ch_r = _rect_absoluto_celda(x0, y0, cw, ch, rel["codigo"])
    c.setFillColor(black)
    fuente_cod = "Helvetica-Bold"
    codigo_txt = codigo or "—"
    # El tope de 48 pt funcionaba para Plantilla_2/4/8/16 (paginas pequenas),
    # pero en mayoreo (pagina = pixeles de la PNG, miles de pt) dejaba el
    # codigo casi invisible dentro de su caja. El while de abajo siempre
    # reduce si no entra por ancho, asi que un tope alto es seguro.
    tam_cod = max(4.0, ch_r * 0.72)
    ancho_disp = max(cw_r - 4, 1.0)
    while tam_cod > 4.0 and pdfmetrics.stringWidth(
        codigo_txt, fuente_cod, tam_cod
    ) > ancho_disp:
        tam_cod -= 0.5
    c.setFont(fuente_cod, tam_cod)
    baseline_cod = cy_r + ch_r / 2 - tam_cod * 0.28
    c.drawCentredString(cx_r + cw_r / 2, baseline_cod, codigo_txt)

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

    dx, dy, dw, dh = _rect_absoluto_celda(x0, y0, cw, ch, rel["descripcion"])
    fuente = "Helvetica-Bold"
    ancho_txt = max(dw - 8, 1.0)
    # Mismo motivo que el codigo: sin tope fijo, dejamos que la caja mande;
    # el bucle while reduce el tamano hasta que las lineas envueltas caben.
    tam_desc = max(5.0, dh * 0.78)
    _guarda = 0
    while True:
        lineas = _envolver_texto(descripcion, fuente, tam_desc, ancho_txt)
        leading = tam_desc * 1.12
        max_lines = max(1, int((dh - 6) / leading)) if leading > 0 else 1
        if len(lineas) <= max_lines or tam_desc <= 5.0:
            break
        tam_desc -= 0.5
        _guarda += 1
        if _guarda > 500:
            break
    leading = tam_desc * 1.12
    max_lines = max(1, int((dh - 6) / leading)) if leading > 0 else 1
    y_t = dy + dh - tam_desc - 2
    c.setFont(fuente, tam_desc)
    for li in lineas[:max_lines]:
        wline = pdfmetrics.stringWidth(li, fuente, tam_desc)
        c.drawString(dx + (dw - wline) / 2, y_t, li)
        y_t -= leading

    if mostrar_marcos_coordenadas:
        _dibujar_marcos_coordenadas_celda(
            c, FORMATO_4_MAYOREO, x0, y0, cw, ch, rel_override=rel
        )


# El argumento `formato` aqui solo sirve para el log de marcos; el dibujo es
# identico para todas las variantes mayoreo (cambian las fracciones, no la
# semantica de las zonas).
def _dibujar_contenido_celda(
    c: canvas.Canvas,
    formato: Union[int, str],
    x0: float,
    y0: float,
    cw: float,
    ch: float,
    prod: dict[str, Any],
    sucursal: str,
    gen_bc: Callable[[str, str | None], Path],
    temp_pngs: list[Path],
    mostrar_marcos_coordenadas: bool = False,
    rel_mayoreo: dict[str, tuple[float, float, float, float]] | None = None,
) -> None:
    """Dibuja solo datos dinamicos sobre una celda (sin marcos: la plantilla ya los trae)."""
    if es_formato_mayoreo(formato):
        rel = rel_mayoreo or COORD_RELATIVAS[formato]
        _dibujar_contenido_celda_mayoreo(
            c,
            x0,
            y0,
            cw,
            ch,
            prod,
            sucursal,
            gen_bc,
            temp_pngs,
            mostrar_marcos_coordenadas,
            rel,
        )
        return

    rel = COORD_RELATIVAS[int(formato)]
    logo_izq_p = ruta_logo_sucursal(sucursal)

    try:
        precio_val = float(prod.get("precio", 0))
    except (TypeError, ValueError):
        precio_val = 0.0
    # Solo número (la plantilla ya incluye el símbolo $ en el círculo)
    precio_txt = f"{precio_val:,.2f}"
    codigo = str(prod.get("codigo", "")).strip()
    descripcion = str(prod.get("descripcion", "")).strip()

    # --- Logo sucursal (izquierda): arriba-izquierda del rectángulo (misma lógica que Plantilla_4 en todos los formatos).
    rx, ry, rw, rh = _rect_absoluto_celda(x0, y0, cw, ch, rel["logo_izq"])
    if logo_izq_p.is_file():
        dw, dh = _tamano_imagen_ajustada(logo_izq_p, rw - 4, rh - 4)
        ix = rx + 3
        iy = ry + rh - dh - 3
        c.drawImage(
            str(logo_izq_p),
            ix,
            iy,
            width=dw,
            height=dh,
            mask="auto",
        )

    # --- Precio (sin círculo ni $: la plantilla ya los trae) ---
    px, py, pw, ph = _rect_absoluto_celda(x0, y0, cw, ch, rel["precio"])
    c.setFillColor(black)
    # Monto a la derecha del círculo impreso (misma proporción que Plantilla_4).
    base_factor = 0.96
    tam_precio = ph * base_factor
    fuente_p = "Helvetica-Bold"
    area_x = px + pw * 0.26
    area_w = pw * 0.72
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
    # Tamaño ligado al alto de la zona (fh en COORD_RELATIVAS); se reduce si no cabe en el ancho.
    cx_r, cy_r, cw_r, ch_r = _rect_absoluto_celda(x0, y0, cw, ch, rel["codigo"])
    c.setFillColor(black)
    fuente_cod = "Helvetica-Bold"
    codigo_txt = codigo or "—"
    tam_cod = min(ch_r * 0.72, 48.0)
    tam_cod = max(4.0, tam_cod)
    ancho_disp = max(cw_r - 4, 1.0)
    while tam_cod > 4.0 and pdfmetrics.stringWidth(
        codigo_txt, fuente_cod, tam_cod
    ) > ancho_disp:
        tam_cod -= 0.5
    c.setFont(fuente_cod, tam_cod)
    baseline_cod = cy_r + ch_r / 2 - tam_cod * 0.28
    c.drawCentredString(cx_r + cw_r / 2, baseline_cod, codigo_txt)

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
    # Antes: min(10.0, ...) fijaba un tope de 10 pt e impedía letras más grandes.
    # Ahora: tamaño según alto de caja (hasta 48 pt) y se reduce solo si no caben las líneas.
    dx, dy, dw, dh = _rect_absoluto_celda(x0, y0, cw, ch, rel["descripcion"])
    fuente = "Helvetica-Bold"
    ancho_txt = max(dw - 8, 1.0)
    tam_desc = max(5.0, min(dh * 0.78, 48.0))
    _guarda = 0
    while True:
        lineas = _envolver_texto(descripcion, fuente, tam_desc, ancho_txt)
        leading = tam_desc * 1.12
        max_lines = max(1, int((dh - 6) / leading)) if leading > 0 else 1
        if len(lineas) <= max_lines or tam_desc <= 5.0:
            break
        tam_desc -= 0.5
        _guarda += 1
        if _guarda > 500:
            break
    leading = tam_desc * 1.12
    max_lines = max(1, int((dh - 6) / leading)) if leading > 0 else 1
    y_t = dy + dh - tam_desc - 2
    c.setFont(fuente, tam_desc)
    for li in lineas[:max_lines]:
        wline = pdfmetrics.stringWidth(li, fuente, tam_desc)
        c.drawString(dx + (dw - wline) / 2, y_t, li)
        y_t -= leading

    if mostrar_marcos_coordenadas:
        _dibujar_marcos_coordenadas_celda(c, formato, x0, y0, cw, ch)


def _capa_datos_pdf_bytes(
    formato: Union[int, str],
    page_w: float,
    page_h: float,
    productos_en_hoja: list[dict[str, Any]],
    sucursal: str,
    gen_bc: Callable[[str, str | None], Path],
    temp_pngs: list[Path],
    mostrar_marcos_coordenadas: bool = False,
    coord_mayoreo: dict[str, tuple[float, float, float, float]] | None = None,
    margin_x_override: float | None = None,
    margin_y_override: float | None = None,
) -> bytes:
    """Genera un PDF de una página en memoria con la capa de datos (solo contenido)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))

    cols, rows = GRID_POR_ETIQUETAS[formato]
    if es_formato_mayoreo(formato):
        mgx = (
            float(margin_x_override)
            if margin_x_override is not None
            else float(MARGIN_X_MAYOREO)
        )
        mgy = (
            float(margin_y_override)
            if margin_y_override is not None
            else float(MARGIN_Y_MAYOREO)
        )
    else:
        mgx, mgy = float(MARGIN_X), float(MARGIN_Y)

    usable_w = page_w - 2 * mgx
    usable_h = page_h - 2 * mgy
    cell_w = usable_w / cols
    cell_h = usable_h / rows

    for slot, prod in enumerate(productos_en_hoja):
        col = slot % cols
        row = slot // cols
        x0 = mgx + col * cell_w
        y0 = page_h - mgy - (row + 1) * cell_h
        _dibujar_contenido_celda(
            c,
            formato,
            x0,
            y0,
            cell_w,
            cell_h,
            prod,
            sucursal,
            gen_bc,
            temp_pngs,
            mostrar_marcos_coordenadas=mostrar_marcos_coordenadas,
            rel_mayoreo=coord_mayoreo,
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
    etiquetas_por_hoja: Union[int, str],
    ruta_salida: str | Path,
    sucursal: str = "Sucursal 1",
    generador_barras: Callable[[str, str | None], Path] | None = None,
    mostrar_marcos_coordenadas: bool = False,
) -> Path:
    """
    Genera el PDF final: para cada hoja carga la plantilla, crea la capa de datos
    en memoria (ReportLab) y fusiona con merge_page.

    Args:
        productos: Lista de dicts con codigo, descripcion, precio (y opc. precio_regular,
            precio_mayoreo, cantidad_mayoreo si usa alguna variante mayoreo).
        etiquetas_por_hoja: 2, 4, 8, 16, FORMATO_4_MAYOREO ("4_MAYOREO") o
            FORMATO_2_MAYOREO ("2_MAYOREO").
        ruta_salida: Archivo PDF de salida.
        sucursal: Selección de logo izquierdo (Sucursal 1…12).
        generador_barras: Opcional para pruebas.
        mostrar_marcos_coordenadas: Si True, dibuja rectángulos y nombres de cada
            zona de COORD_RELATIVAS encima del contenido para alinear con la plantilla.
    """
    if etiquetas_por_hoja not in GRID_POR_ETIQUETAS:
        raise ValueError(
            "etiquetas_por_hoja debe ser 2, 4, 8, 16 o un formato mayoreo "
            "(4_MAYOREO o 2_MAYOREO)."
        )
    if not productos:
        raise ValueError("No hay productos para generar etiquetas.")

    plantilla_path: Path | None = None
    plantilla_pdf_bytes_mayoreo: bytes | None = None
    if es_formato_mayoreo(etiquetas_por_hoja):
        png_plantilla = PLANTILLAS_PNG_MAYOREO[etiquetas_por_hoja]
        plantilla_pdf_bytes_mayoreo, page_w, page_h = _plantilla_pdf_bytes_desde_png(
            png_plantilla
        )
    else:
        plantilla_path = PLANTILLAS_PDF.get(int(etiquetas_por_hoja))
        if not plantilla_path or not plantilla_path.is_file():
            raise FileNotFoundError(
                f"No se encontró la plantilla: {plantilla_path}"
            )
        tr = PdfReader(str(plantilla_path))
        page_w, page_h = _tamano_pagina_pdf(tr)

    gen_bc = generador_barras or generar_imagen_code128
    cols, rows = GRID_POR_ETIQUETAS[etiquetas_por_hoja]
    slots = cols * rows

    out = Path(ruta_salida)
    out.parent.mkdir(parents=True, exist_ok=True)

    temp_pngs: list[Path] = []
    writer = PdfWriter()

    coord_m: dict[str, tuple[float, float, float, float]] | None = None
    mx_m: float | None = None
    my_m: float | None = None
    if es_formato_mayoreo(etiquetas_por_hoja):
        coord_m, mx_m, my_m = cargar_coordenadas_mayoreo(
            formato=str(etiquetas_por_hoja)
        )

    try:
        idx = 0
        n = len(productos)
        while idx < n:
            chunk = productos[idx : idx + slots]
            idx += len(chunk)

            capa_bytes = _capa_datos_pdf_bytes(
                etiquetas_por_hoja,
                page_w,
                page_h,
                chunk,
                sucursal,
                gen_bc,
                temp_pngs,
                mostrar_marcos_coordenadas=mostrar_marcos_coordenadas,
                coord_mayoreo=coord_m,
                margin_x_override=mx_m,
                margin_y_override=my_m,
            )
            if plantilla_pdf_bytes_mayoreo is not None:
                br = PdfReader(io.BytesIO(plantilla_pdf_bytes_mayoreo))
                base_page = br.pages[0]
                overlay_page = PdfReader(io.BytesIO(capa_bytes)).pages[0]
                base_page.merge_page(overlay_page)
                writer.add_page(base_page)
            else:
                assert plantilla_path is not None
                pagina_fusionada = _fusionar_plantilla_y_capa(
                    plantilla_path, capa_bytes
                )
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
