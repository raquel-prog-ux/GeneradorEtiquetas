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
        except sqlite3.Error as e:
            raise RuntimeError(f"Error al crear la tabla productos: {e}") from e

    def insertar(self, codigo: str, descripcion: str, precio: float) -> int:
        """Inserta un producto y devuelve el id generado."""
        if not codigo or not codigo.strip():
            raise ValueError("El código no puede estar vacío.")
        if not descripcion or not descripcion.strip():
            raise ValueError("La descripción no puede estar vacía.")
        try:
            p = float(precio)
        except (TypeError, ValueError) as e:
            raise ValueError("El precio debe ser un número válido.") from e

        sql = "INSERT INTO productos (codigo, descripcion, precio) VALUES (?, ?, ?);"
        try:
            with self._conexion() as conn:
                cur = conn.execute(
                    sql,
                    (codigo.strip(), descripcion.strip(), p),
                )
                conn.commit()
                return int(cur.lastrowid)
        except sqlite3.Error as e:
            raise RuntimeError(f"Error al insertar producto: {e}") from e

    def listar_todos(self) -> list[dict[str, Any]]:
        """Devuelve todos los productos como lista de diccionarios."""
        sql = "SELECT id, codigo, descripcion, precio FROM productos ORDER BY id;"
        try:
            with self._conexion() as conn:
                filas = conn.execute(sql).fetchall()
            return [dict(f) for f in filas]
        except sqlite3.Error as e:
            raise RuntimeError(f"Error al listar productos: {e}") from e

    def obtener_por_id(self, producto_id: int) -> Optional[dict[str, Any]]:
        """Obtiene un producto por su id."""
        sql = "SELECT id, codigo, descripcion, precio FROM productos WHERE id = ?;"
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
