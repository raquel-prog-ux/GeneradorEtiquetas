"""
Interfaz principal en Tkinter: formulario, tabla de productos y generación de PDF.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from logic.database import BaseDatosProductos
from logic.printer import generar_pdf_etiquetas

# Carpeta sugerida para PDFs exportados
_ROOT = Path(__file__).resolve().parent.parent.parent
_OUTPUT_DIR = _ROOT / "output"


class VentanaPrincipal:
    """Ventana con formulario, Treeview y acciones sobre la base de datos."""

    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        self.master.title("Generador de etiquetas — Productos")
        self.master.minsize(720, 480)

        try:
            self.db = BaseDatosProductos()
        except Exception as e:
            messagebox.showerror(
                "Error de base de datos",
                f"No se pudo inicializar SQLite:\n{e}",
            )
            raise

        self._construir_formulario()
        self._construir_tabla()
        self._construir_acciones()
        self._refrescar_tabla()

    def _construir_formulario(self) -> None:
        """Entradas para código, descripción y precio."""
        marco = ttk.LabelFrame(self.master, text="Nuevo producto", padding=8)
        marco.pack(fill=tk.X, padx=10, pady=8)

        ttk.Label(marco, text="Código:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.var_codigo = tk.StringVar()
        ttk.Entry(marco, textvariable=self.var_codigo, width=28).grid(
            row=0, column=1, sticky=tk.W, padx=6
        )

        ttk.Label(marco, text="Descripción:").grid(
            row=1, column=0, sticky=tk.W, pady=2
        )
        self.var_descripcion = tk.StringVar()
        ttk.Entry(marco, textvariable=self.var_descripcion, width=48).grid(
            row=1, column=1, sticky=tk.W, padx=6
        )

        ttk.Label(marco, text="Precio:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.var_precio = tk.StringVar()
        ttk.Entry(marco, textvariable=self.var_precio, width=16).grid(
            row=2, column=1, sticky=tk.W, padx=6
        )

        ttk.Label(marco, text="Sucursal:").grid(
            row=3, column=0, sticky=tk.W, pady=2
        )
        self.var_sucursal = tk.StringVar(value="Sucursal 1")
        opciones_sucursal = tuple(f"Sucursal {i}" for i in range(1, 13))
        ttk.Combobox(
            marco,
            textvariable=self.var_sucursal,
            values=opciones_sucursal,
            state="readonly",
            width=26,
        ).grid(row=3, column=1, sticky=tk.W, padx=6)

        ttk.Button(marco, text="Agregar producto", command=self._agregar_producto).grid(
            row=4, column=1, sticky=tk.W, pady=(8, 0)
        )

    def _construir_tabla(self) -> None:
        """Treeview con productos guardados."""
        marco = ttk.LabelFrame(self.master, text="Productos guardados", padding=8)
        marco.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        columnas = ("id", "codigo", "descripcion", "precio")
        self.tabla = ttk.Treeview(
            marco,
            columns=columnas,
            show="headings",
            height=12,
            selectmode=tk.BROWSE,
        )
        self.tabla.heading("id", text="ID")
        self.tabla.heading("codigo", text="Código")
        self.tabla.heading("descripcion", text="Descripción")
        self.tabla.heading("precio", text="Precio")

        self.tabla.column("id", width=40, anchor=tk.CENTER)
        self.tabla.column("codigo", width=120, anchor=tk.W)
        self.tabla.column("descripcion", width=320, anchor=tk.W)
        self.tabla.column("precio", width=90, anchor=tk.E)

        contenedor_tabla = ttk.Frame(marco)
        contenedor_tabla.pack(fill=tk.BOTH, expand=True)

        scroll_y = ttk.Scrollbar(
            contenedor_tabla, orient=tk.VERTICAL, command=self.tabla.yview
        )
        self.tabla.configure(yscrollcommand=scroll_y.set)

        self.tabla.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

    def _construir_acciones(self) -> None:
        """Selector de formato y generación de PDF."""
        barra = ttk.Frame(self.master, padding=(10, 0, 10, 10))
        barra.pack(fill=tk.X)

        ttk.Label(barra, text="Etiquetas por hoja:").pack(side=tk.LEFT)
        self.var_formato = tk.StringVar(value="4")
        combo = ttk.Combobox(
            barra,
            textvariable=self.var_formato,
            values=("2", "4", "8", "16"),
            state="readonly",
            width=6,
        )
        combo.pack(side=tk.LEFT, padx=(6, 16))

        ttk.Button(
            barra,
            text="Generar PDF",
            command=self._generar_pdf,
        ).pack(side=tk.LEFT)

    def _refrescar_tabla(self) -> None:
        """Vuelve a cargar filas desde la base de datos."""
        for item in self.tabla.get_children():
            self.tabla.delete(item)
        try:
            filas = self.db.listar_todos()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron listar productos:\n{e}")
            return

        for p in filas:
            precio = float(p["precio"])
            precio_txt = f"{precio:,.2f}"
            self.tabla.insert(
                "",
                tk.END,
                values=(p["id"], p["codigo"], p["descripcion"], precio_txt),
            )

    def _agregar_producto(self) -> None:
        """Inserta un registro a partir del formulario."""
        codigo = self.var_codigo.get()
        desc = self.var_descripcion.get()
        precio_txt = self.var_precio.get().strip().replace(",", "")
        try:
            precio = float(precio_txt)
        except ValueError:
            messagebox.showwarning(
                "Validación",
                "El precio debe ser un número (ej. 12.50).",
            )
            return

        try:
            self.db.insertar(codigo, desc, precio)
        except ValueError as e:
            messagebox.showwarning("Validación", str(e))
            return
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar:\n{e}")
            return

        self.var_codigo.set("")
        self.var_descripcion.set("")
        self.var_precio.set("")
        self._refrescar_tabla()

    def _generar_pdf(self) -> None:
        """Exporta etiquetas a PDF según el formato elegido."""
        try:
            productos = self.db.listar_todos()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron leer productos:\n{e}")
            return

        if not productos:
            messagebox.showwarning(
                "PDF",
                "Agregue al menos un producto antes de generar el PDF.",
            )
            return

        try:
            n = int(self.var_formato.get())
        except ValueError:
            messagebox.showwarning("Formato", "Seleccione un formato válido.")
            return

        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ruta = filedialog.asksaveasfilename(
            title="Guardar PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf"), ("Todos", "*.*")],
            initialdir=str(_OUTPUT_DIR),
            initialfile="etiquetas.pdf",
        )
        if not ruta:
            return

        try:
            generar_pdf_etiquetas(
                productos,
                n,
                ruta,
                sucursal=self.var_sucursal.get(),
            )
        except ValueError as e:
            messagebox.showwarning("PDF", str(e))
            return
        except Exception as e:
            messagebox.showerror("PDF", f"No se pudo generar el archivo:\n{e}")
            return

        messagebox.showinfo("PDF", f"Archivo generado correctamente:\n{ruta}")


def iniciar_aplicacion() -> None:
    """Crea la ventana principal y entra al loop de Tkinter."""
    root = tk.Tk()
    try:
        VentanaPrincipal(root)
    except Exception:
        # Error ya notificado en el constructor (p. ej. base de datos)
        root.destroy()
        return
    root.mainloop()
