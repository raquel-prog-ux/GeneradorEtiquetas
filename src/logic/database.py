"""
Gestión de la base de datos SQLite para productos.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional


# Raíz del proyecto (carpeta que contiene src/, data/, assets/)
_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_PATH = _ROOT / "data" / "productos.db"


class BaseDatosProductos:
    """
    Clase para administrar la tabla 'productos' (id, codigo, descripcion, precio).
    """

    def __init__(self, ruta_db: Optional[Path] = None) -> None:
        self._ruta = Path(ruta_db) if ruta_db else _DB_PATH
        # Asegurar que exista la carpeta data/
        self._ruta.parent.mkdir(parents=True, exist_ok=True)
        self._inicializar_tabla()

    def _conexion(self) -> sqlite3.Connection:
        """Abre una conexión con manejo básico de errores."""
        try:
            conn = sqlite3.connect(self._ruta)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as e:
            raise RuntimeError(f"No se pudo conectar a la base de datos: {e}") from e

    def _inicializar_tabla(self) -> None:
        """Crea la tabla si no existe."""
        sql = """
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            precio REAL NOT NULL
        );
        """
        try:
            with self._conexion() as conn:
                conn.execute(sql)
                conn.commit()
            self._migrar_columnas_mayoreo()
        except sqlite3.Error as e:
            raise RuntimeError(f"Error al crear la tabla productos: {e}") from e

    def _migrar_columnas_mayoreo(self) -> None:
        """Anade precio_mayoreo y cantidad_mayoreo si la BD era anterior."""
        try:
            with self._conexion() as conn:
                cur = conn.execute("PRAGMA table_info(productos)")
                cols = {row[1] for row in cur.fetchall()}
                if "precio_mayoreo" not in cols:
                    conn.execute(
                        "ALTER TABLE productos ADD COLUMN precio_mayoreo REAL"
                    )
                if "cantidad_mayoreo" not in cols:
                    conn.execute(
                        "ALTER TABLE productos ADD COLUMN cantidad_mayoreo TEXT"
                    )
                conn.commit()
        except sqlite3.Error as e:
            raise RuntimeError(f"Error al migrar columnas mayoreo: {e}") from e

    def insertar(
        self,
        codigo: str,
        descripcion: str,
        precio: float,
        precio_mayoreo: Optional[float] = None,
        cantidad_mayoreo: Optional[str] = None,
    ) -> int:
        """Inserta un producto y devuelve el id generado."""
        if not codigo or not codigo.strip():
            raise ValueError("El código no puede estar vacío.")
        if not descripcion or not descripcion.strip():
            raise ValueError("La descripción no puede estar vacía.")
        try:
            p = float(precio)
        except (TypeError, ValueError) as e:
            raise ValueError("El precio debe ser un número válido.") from e

        sql = """
        INSERT INTO productos
            (codigo, descripcion, precio, precio_mayoreo, cantidad_mayoreo)
        VALUES (?, ?, ?, ?, ?);
        """
        try:
            with self._conexion() as conn:
                cur = conn.execute(
                    sql,
                    (
                        codigo.strip(),
                        descripcion.strip(),
                        p,
                        precio_mayoreo,
                        cantidad_mayoreo,
                    ),
                )
                conn.commit()
                return int(cur.lastrowid)
        except sqlite3.Error as e:
            raise RuntimeError(f"Error al insertar producto: {e}") from e

    def listar_todos(self) -> list[dict[str, Any]]:
        """Devuelve todos los productos como lista de diccionarios."""
        sql = """
        SELECT id, codigo, descripcion, precio, precio_mayoreo, cantidad_mayoreo
        FROM productos ORDER BY id;
        """
        try:
            with self._conexion() as conn:
                filas = conn.execute(sql).fetchall()
            return [dict(f) for f in filas]
        except sqlite3.Error as e:
            raise RuntimeError(f"Error al listar productos: {e}") from e

    def obtener_por_id(self, producto_id: int) -> Optional[dict[str, Any]]:
        """Obtiene un producto por su id."""
        sql = """
        SELECT id, codigo, descripcion, precio, precio_mayoreo, cantidad_mayoreo
        FROM productos WHERE id = ?;
        """
        try:
            with self._conexion() as conn:
                fila = conn.execute(sql, (producto_id,)).fetchone()
            return dict(fila) if fila else None
        except sqlite3.Error as e:
            raise RuntimeError(f"Error al obtener producto: {e}") from e

    def eliminar(self, producto_id: int) -> bool:
        """Elimina un producto. Devuelve True si se borró alguna fila."""
        sql = "DELETE FROM productos WHERE id = ?;"
        try:
            with self._conexion() as conn:
                cur = conn.execute(sql, (producto_id,))
                conn.commit()
                return cur.rowcount > 0
        except sqlite3.Error as e:
            raise RuntimeError(f"Error al eliminar producto: {e}") from e

    def actualizar(
        self,
        producto_id: int,
        codigo: str,
        descripcion: str,
        precio: float,
    ) -> bool:
        """Actualiza un producto existente."""
        if not codigo or not codigo.strip():
            raise ValueError("El código no puede estar vacío.")
        try:
            p = float(precio)
        except (TypeError, ValueError) as e:
            raise ValueError("El precio debe ser un número válido.") from e

        sql = """
        UPDATE productos
        SET codigo = ?, descripcion = ?, precio = ?
        WHERE id = ?;
        """
        try:
            with self._conexion() as conn:
                cur = conn.execute(
                    sql,
                    (codigo.strip(), descripcion.strip(), p, producto_id),
                )
                conn.commit()
                return cur.rowcount > 0
        except sqlite3.Error as e:
            raise RuntimeError(f"Error al actualizar producto: {e}") from e

    def vaciar_todos(self) -> None:
        """Elimina todos los productos de la tabla."""
        try:
            with self._conexion() as conn:
                conn.execute("DELETE FROM productos;")
                conn.commit()
        except sqlite3.Error as e:
            raise RuntimeError(f"Error al vaciar productos: {e}") from e

    def reemplazar_todos(
        self,
        filas: list[dict[str, Any]],
    ) -> int:
        """
        Borra todos los registros e inserta los dicts con claves codigo, descripcion, precio.
        Transacción única.
        """
        if not filas:
            raise ValueError("La lista de productos está vacía.")
        try:
            with self._conexion() as conn:
                conn.execute("DELETE FROM productos;")
                sql = """
                INSERT INTO productos
                    (codigo, descripcion, precio, precio_mayoreo, cantidad_mayoreo)
                VALUES (?, ?, ?, ?, ?);
                """
                for p in filas:
                    cod = str(p.get("codigo", "")).strip()
                    desc = str(p.get("descripcion", "")).strip()
                    precio = float(p["precio"])
                    if not cod or not desc:
                        raise ValueError("Cada fila debe tener código y descripción.")
                    pm = p.get("precio_mayoreo")
                    pm_val = float(pm) if pm is not None and pm != "" else None
                    cant = p.get("cantidad_mayoreo")
                    cant_txt = (
                        str(cant).strip() if cant is not None and str(cant).strip() else None
                    )
                    conn.execute(
                        sql,
                        (cod, desc, precio, pm_val, cant_txt),
                    )
                conn.commit()
            return len(filas)
        except sqlite3.Error as e:
            raise RuntimeError(f"Error al reemplazar productos: {e}") from e
