# -*- coding: utf-8 -*-
"""Read products from Excel (.xlsx): codigo, descripcion, precio."""
from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

try:
    import openpyxl  # type: ignore[import-untyped]
except ImportError as e:
    openpyxl = None  # type: ignore[misc, assignment]
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None


def _sin_tildes(s: str) -> str:
    s = (s or "").strip().lower()
    return "".join(
        c
        for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


_ENCABEZADO_A_CAMPO: dict[str, str] = {
    "codigo": "codigo",
    "code": "codigo",
    "sku": "codigo",
    "clave": "codigo",
    "descripcion": "descripcion",
    "desc": "descripcion",
    "description": "descripcion",
    "producto": "descripcion",
    "nombre": "descripcion",
    "precio": "precio",
    "price": "precio",
    "importe": "precio",
    "costo": "precio",
}

# Columnas opcionales (mayoreo); el nombre en Excel puede llevar espacios.
_ENCABEZADO_OPCIONAL: dict[str, str] = {
    "precio mayoreo": "precio_mayoreo",
    "precio_mayoreo": "precio_mayoreo",
    "precio mayoreo ($)": "precio_mayoreo",
    "mayoreo": "precio_mayoreo",
    "pm": "precio_mayoreo",
    "cantidad mayoreo": "cantidad_mayoreo",
    "cantidad_mayoreo": "cantidad_mayoreo",
    "a partir de": "cantidad_mayoreo",
    "a partir de (piezas)": "cantidad_mayoreo",
    "piezas": "cantidad_mayoreo",
    "desde": "cantidad_mayoreo",
    "minimo": "cantidad_mayoreo",
}


def _mapear_por_encabezado(fila: list[Any]) -> dict[str, int]:
    indices: dict[str, int] = {}
    for idx, val in enumerate(fila):
        clave = _sin_tildes(str(val) if val is not None else "")
        if not clave:
            continue
        campo = _ENCABEZADO_A_CAMPO.get(clave)
        if campo and campo not in indices:
            indices[campo] = idx
        elif not campo:
            op = _ENCABEZADO_OPCIONAL.get(clave)
            if op and op not in indices:
                indices[op] = idx
    return indices


def _parse_precio(val: Any) -> float:
    if val is None or (isinstance(val, str) and not str(val).strip()):
        raise ValueError("vacio")
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace("$", "").replace(",", "")
    return float(s)


def leer_productos_desde_excel(ruta: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Primera hoja: fila 1 encabezados (codigo, descripcion, precio o sinonimos).
    Opcional: precio mayoreo, cantidad mayoreo / a partir de / piezas.
    Datos desde fila 2. Si no hay 3 encabezados reconocidos, columnas A/B/C = codigo/desc/precio
    y opcionalmente D/E = precio mayoreo / cantidad mayoreo.
    """
    if openpyxl is None:
        raise RuntimeError(
            "Falta el paquete 'openpyxl' (necesario para importar Excel).\n\n"
            "En la carpeta del proyecto ejecute:\n"
            "  python -m pip install openpyxl\n\n"
            "Con el entorno virtual del proyecto:\n"
            "  .\\venv\\Scripts\\pip.exe install openpyxl\n\n"
            "O todas las dependencias:\n"
            "  pip install -r requirements.txt"
        ) from _IMPORT_ERROR

    path = Path(ruta)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        filas: list[list[Any]] = []
        for row in ws.iter_rows(values_only=True):
            filas.append(list(row))
    finally:
        wb.close()

    if not filas:
        return [], ["El archivo no tiene filas."]

    mapeo = _mapear_por_encabezado(filas[0])
    tiene_obligatorios = (
        "codigo" in mapeo and "descripcion" in mapeo and "precio" in mapeo
    )
    if tiene_obligatorios:
        ic, id_, ip = mapeo["codigo"], mapeo["descripcion"], mapeo["precio"]
        ipm = mapeo.get("precio_mayoreo")
        icant = mapeo.get("cantidad_mayoreo")
        datos = filas[1:]
        num_base = 2
    else:
        ic, id_, ip = 0, 1, 2
        ipm, icant = 3, 4
        datos = filas
        num_base = 1

    productos: list[dict[str, Any]] = []
    advertencias: list[str] = []

    for offset, fila in enumerate(datos):
        num_fila = num_base + offset

        def _val(i: int | None) -> Any:
            if i is None:
                return None
            return fila[i] if i < len(fila) else None

        cod = _val(ic)
        desc = _val(id_)
        pre = _val(ip)
        cod_s = str(cod).strip() if cod is not None else ""
        desc_s = str(desc).strip() if desc is not None else ""
        if not cod_s and not desc_s and (pre is None or str(pre).strip() == ""):
            continue
        if not cod_s:
            advertencias.append(f"Fila {num_fila}: codigo vacio, se omite.")
            continue
        if not desc_s:
            advertencias.append(f"Fila {num_fila}: descripcion vacia, se omite.")
            continue
        try:
            precio = _parse_precio(pre)
        except (ValueError, TypeError):
            advertencias.append(
                f"Fila {num_fila}: precio invalido ({pre!r}), se omite."
            )
            continue

        pm_val: float | None = None
        raw_pm = _val(ipm)
        if raw_pm is not None and str(raw_pm).strip() != "":
            try:
                pm_val = _parse_precio(raw_pm)
            except (ValueError, TypeError):
                advertencias.append(
                    f"Fila {num_fila}: precio mayoreo invalido ({raw_pm!r}), se ignora."
                )

        cant_txt: str | None = None
        raw_cant = _val(icant)
        if raw_cant is not None and str(raw_cant).strip() != "":
            cant_txt = str(raw_cant).strip()

        fila_prod: dict[str, Any] = {
            "codigo": cod_s,
            "descripcion": desc_s,
            "precio": precio,
        }
        if pm_val is not None:
            fila_prod["precio_mayoreo"] = pm_val
        if cant_txt is not None:
            fila_prod["cantidad_mayoreo"] = cant_txt
        productos.append(fila_prod)

    if not productos:
        raise ValueError(
            "No se importo ningun producto valido. Revise datos y encabezados."
        )
    return productos, advertencias
