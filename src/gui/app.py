"""
Interfaz principal en Tkinter: formulario, tabla de productos y generación de PDF.
"""
from __future__ import annotations

import importlib
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from logic.database import BaseDatosProductos
from logic.excel_import import leer_productos_desde_excel
import logic.printer as printer_mod

# Carpeta sugerida para PDFs exportados
_ROOT = Path(__file__).resolve().parent.parent.parent
_OUTPUT_DIR = _ROOT / "output"

# Etiquetas legibles para el diálogo de coordenadas (formatos mayoreo)
_MAYOREO_ZONAS_UI: tuple[tuple[str, str], ...] = (
    ("logo_izq", "Logo"),
    ("precio_regular", "Precio regular"),
    ("cantidad_mayoreo", "Cantidad mayoreo"),
    ("precio_mayoreo", "Precio mayoreo"),
    ("codigo", "Código"),
    ("barcode", "Código de barras"),
    ("descripcion", "Descripción"),
)

# Etiquetas del combo de formato -> clave/numero usada por el printer.
# Cualquier label que empiece por "2 Etiquetas" o "4 Etiquetas" en este mapa
# activa los campos de mayoreo en la UI; los numeros simples (sin "Mayoreo")
# corresponden a Plantilla_2/4/8/16.pdf.
_FORMATOS_UI: tuple[tuple[str, object], ...] = (
    ("2", 2),
    ("4", 4),
    ("8", 8),
    ("16", 16),
    ("2 Etiquetas (Mayoreo 1/2 carta)", "2_MAYOREO"),
    ("4 Etiquetas (Mayoreo)", "4_MAYOREO"),
)
_FORMATOS_MAYOREO_LABELS = {
    "2 Etiquetas (Mayoreo 1/2 carta)": "2_MAYOREO",
    "4 Etiquetas (Mayoreo)": "4_MAYOREO",
}


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

        self.var_formato = tk.StringVar(value="4")
        self._construir_formulario()
        self._construir_tabla()
        self._construir_acciones()
        self._pdf_generando = False
        self.var_formato.trace_add("write", self._al_cambiar_formato)
        self._al_cambiar_formato()
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

        self._frm_mayoreo = ttk.Frame(marco)
        ttk.Label(self._frm_mayoreo, text="Precio Mayoreo:").grid(
            row=0, column=0, sticky=tk.W, pady=2
        )
        self.var_precio_mayoreo = tk.StringVar()
        ttk.Entry(self._frm_mayoreo, textvariable=self.var_precio_mayoreo, width=16).grid(
            row=0, column=1, sticky=tk.W, padx=6
        )
        ttk.Label(self._frm_mayoreo, text="A partir de (piezas):").grid(
            row=1, column=0, sticky=tk.W, pady=2
        )
        self.var_cantidad_mayoreo = tk.StringVar()
        ttk.Entry(self._frm_mayoreo, textvariable=self.var_cantidad_mayoreo, width=16).grid(
            row=1, column=1, sticky=tk.W, padx=6
        )

        self._lbl_sucursal = ttk.Label(marco, text="Sucursal:")
        self._lbl_sucursal.grid(row=3, column=0, sticky=tk.W, pady=2)
        opciones = printer_mod.opciones_sucursal()
        self.var_sucursal = tk.StringVar(value=opciones[0])
        self._combo_sucursal = ttk.Combobox(
            marco,
            textvariable=self.var_sucursal,
            values=opciones,
            state="readonly",
            width=36,
        )
        self._combo_sucursal.grid(row=3, column=1, sticky=tk.W, padx=6)

        self._fila_btns = ttk.Frame(marco)
        self._fila_btns.grid(row=4, column=1, sticky=tk.W, pady=(8, 0))
        ttk.Button(
            self._fila_btns, text="Agregar producto", command=self._agregar_producto
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            self._fila_btns,
            text="Importar Excel…",
            command=self._importar_excel,
        ).pack(side=tk.LEFT)

    def _construir_tabla(self) -> None:
        """Treeview con productos guardados."""
        marco = ttk.LabelFrame(self.master, text="Productos guardados", padding=8)
        marco.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        columnas = (
            "id",
            "codigo",
            "descripcion",
            "precio",
            "precio_mayoreo",
            "cantidad_mayoreo",
        )
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
        self.tabla.heading("precio_mayoreo", text="Mayoreo")
        self.tabla.heading("cantidad_mayoreo", text="Desde (pz)")

        self.tabla.column("id", width=40, anchor=tk.CENTER)
        self.tabla.column("codigo", width=110, anchor=tk.W)
        self.tabla.column("descripcion", width=260, anchor=tk.W)
        self.tabla.column("precio", width=72, anchor=tk.E)
        self.tabla.column("precio_mayoreo", width=72, anchor=tk.E)
        self.tabla.column("cantidad_mayoreo", width=72, anchor=tk.CENTER)

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
        combo = ttk.Combobox(
            barra,
            textvariable=self.var_formato,
            values=tuple(label for label, _ in _FORMATOS_UI),
            state="readonly",
            width=30,
        )
        combo.pack(side=tk.LEFT, padx=(6, 16))

        self._btn_generar_pdf = ttk.Button(
            barra,
            text="Generar PDF",
            command=self._generar_pdf,
        )
        self._btn_generar_pdf.pack(side=tk.LEFT)

        self.var_marcos_coords = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            barra,
            text="Depuración: marcos de coordenadas",
            variable=self.var_marcos_coords,
        ).pack(side=tk.LEFT, padx=(16, 0))

        self._btn_coord_mayoreo = ttk.Button(
            barra,
            text="Zonas mayoreo…",
            command=self._abrir_config_coord_mayoreo,
            state=tk.DISABLED,
        )
        self._btn_coord_mayoreo.pack(side=tk.LEFT, padx=(12, 0))

    def _al_cambiar_formato(self, *_args: object) -> None:
        """Muestra u oculta campos de mayoreo segun el formato de etiquetas."""
        sel = self.var_formato.get()
        es_mayoreo = sel in _FORMATOS_MAYOREO_LABELS
        self._btn_coord_mayoreo.config(
            state=tk.NORMAL if es_mayoreo else tk.DISABLED
        )
        if es_mayoreo:
            self._frm_mayoreo.grid(
                row=3,
                column=0,
                columnspan=2,
                sticky=tk.W,
                padx=0,
                pady=(4, 4),
            )
            self._lbl_sucursal.grid(row=4, column=0, sticky=tk.W, pady=2)
            self._combo_sucursal.grid(row=4, column=1, sticky=tk.W, padx=6)
            self._fila_btns.grid(row=5, column=1, sticky=tk.W, pady=(8, 0))
            for child in self._frm_mayoreo.winfo_children():
                if isinstance(child, ttk.Entry):
                    child.config(state=tk.NORMAL)
        else:
            self._frm_mayoreo.grid_remove()
            self.var_precio_mayoreo.set("")
            self.var_cantidad_mayoreo.set("")
            self._lbl_sucursal.grid(row=3, column=0, sticky=tk.W, pady=2)
            self._combo_sucursal.grid(row=3, column=1, sticky=tk.W, padx=6)
            self._fila_btns.grid(row=4, column=1, sticky=tk.W, pady=(8, 0))
            for child in self._frm_mayoreo.winfo_children():
                if isinstance(child, ttk.Entry):
                    child.config(state=tk.DISABLED)

    def _abrir_config_coord_mayoreo(self) -> None:
        """Diálogo para editar fracciones de zona y márgenes del formato mayoreo activo."""
        sel = self.var_formato.get()
        if sel not in _FORMATOS_MAYOREO_LABELS:
            return
        formato_mayoreo = _FORMATOS_MAYOREO_LABELS[sel]
        importlib.reload(printer_mod)
        zonas, mx, my = printer_mod.cargar_coordenadas_mayoreo(formato=formato_mayoreo)

        win = tk.Toplevel(self.master)
        win.title(f"Zonas y márgenes — {sel}")
        win.transient(self.master)
        win.grab_set()
        marco = ttk.Frame(win, padding=12)
        marco.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            marco,
            text=(
                "Cada zona usa cuatro valores en fracción de la celda (0–1): "
                "posición X, posición Y, ancho, alto. Origen abajo-izquierda."
            ),
            wraplength=520,
            justify=tk.LEFT,
        ).grid(row=0, column=0, columnspan=6, sticky=tk.W, pady=(0, 8))

        ttk.Label(marco, text="Margen X (pt):").grid(
            row=1, column=0, sticky=tk.W, pady=2
        )
        var_mx = tk.StringVar(value=f"{mx:g}")
        ttk.Entry(marco, textvariable=var_mx, width=10).grid(
            row=1, column=1, sticky=tk.W, padx=(0, 16)
        )
        ttk.Label(marco, text="Margen Y (pt):").grid(
            row=1, column=2, sticky=tk.W, pady=2
        )
        var_my = tk.StringVar(value=f"{my:g}")
        ttk.Entry(marco, textvariable=var_my, width=10).grid(
            row=1, column=3, sticky=tk.W
        )

        ttk.Separator(marco, orient=tk.HORIZONTAL).grid(
            row=2, column=0, columnspan=6, sticky=tk.EW, pady=8
        )

        ttk.Label(marco, text="Zona", font=("TkDefaultFont", 9, "bold")).grid(
            row=3, column=0, sticky=tk.W
        )
        for col, cab in enumerate(("fx", "fy", "ancho", "alto")):
            ttk.Label(marco, text=cab, font=("TkDefaultFont", 9, "bold")).grid(
                row=3, column=col + 1, padx=4
            )

        entradas: dict[str, tuple[tk.StringVar, tk.StringVar, tk.StringVar, tk.StringVar]] = {}
        fila = 4
        for clave, titulo in _MAYOREO_ZONAS_UI:
            ttk.Label(marco, text=titulo).grid(
                row=fila, column=0, sticky=tk.W, pady=2
            )
            fx, fy, fw, fh = zonas.get(
                clave, printer_mod.COORD_RELATIVAS[formato_mayoreo][clave]
            )
            v1 = tk.StringVar(value=f"{fx:g}")
            v2 = tk.StringVar(value=f"{fy:g}")
            v3 = tk.StringVar(value=f"{fw:g}")
            v4 = tk.StringVar(value=f"{fh:g}")
            entradas[clave] = (v1, v2, v3, v4)
            for j, v in enumerate((v1, v2, v3, v4)):
                ttk.Entry(marco, textvariable=v, width=9).grid(
                    row=fila, column=j + 1, padx=4, pady=2
                )
            fila += 1

        btns = ttk.Frame(marco)
        btns.grid(row=fila, column=0, columnspan=6, pady=(12, 0), sticky=tk.W)

        def restaurar_defecto() -> None:
            importlib.reload(printer_mod)
            base = printer_mod.COORD_RELATIVAS[formato_mayoreo]
            var_mx.set(f"{printer_mod.MARGIN_X_MAYOREO:g}")
            var_my.set(f"{printer_mod.MARGIN_Y_MAYOREO:g}")
            for clave, _titulo in _MAYOREO_ZONAS_UI:
                fx, fy, fw, fh = base[clave]
                e = entradas[clave]
                e[0].set(f"{fx:g}")
                e[1].set(f"{fy:g}")
                e[2].set(f"{fw:g}")
                e[3].set(f"{fh:g}")

        def guardar() -> None:
            try:
                nmx = float(var_mx.get().replace(",", ".").strip())
                nmy = float(var_my.get().replace(",", ".").strip())
            except ValueError:
                messagebox.showwarning(
                    "Validación", "Los márgenes deben ser números.", parent=win
                )
                return
            if nmx < 0 or nmy < 0:
                messagebox.showwarning(
                    "Validación", "Los márgenes no pueden ser negativos.", parent=win
                )
                return
            nuevo: dict[str, tuple[float, float, float, float]] = {}
            for clave, titulo in _MAYOREO_ZONAS_UI:
                vs = entradas[clave]
                try:
                    nums = tuple(
                        float(v.get().replace(",", ".").strip()) for v in vs
                    )
                except ValueError:
                    messagebox.showwarning(
                        "Validación",
                        f"Valores numéricos inválidos en la zona «{titulo}».",
                        parent=win,
                    )
                    return
                if nums[2] <= 0 or nums[3] <= 0:
                    messagebox.showwarning(
                        "Validación",
                        f"Ancho y alto de «{titulo}» deben ser mayores que cero.",
                        parent=win,
                    )
                    return
                nuevo[clave] = (
                    float(nums[0]),
                    float(nums[1]),
                    float(nums[2]),
                    float(nums[3]),
                )
            try:
                printer_mod.guardar_coordenadas_mayoreo(
                    nuevo, nmx, nmy, formato=formato_mayoreo
                )
            except OSError as e:
                messagebox.showerror(
                    "Guardar",
                    f"No se pudo guardar el archivo de configuración:\n{e}",
                    parent=win,
                )
                return
            archivo_destino = printer_mod.ARCHIVOS_COORDENADAS_MAYOREO[formato_mayoreo]
            messagebox.showinfo(
                "Guardado",
                "Se guardó la configuración en:\n"
                f"{archivo_destino}\n\n"
                "Al generar el PDF se usarán estos valores.",
                parent=win,
            )
            win.destroy()

        ttk.Button(btns, text="Valores por defecto", command=restaurar_defecto).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(btns, text="Guardar", command=guardar).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(btns, text="Cerrar", command=win.destroy).pack(side=tk.LEFT)

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
            pm = p.get("precio_mayoreo")
            pm_txt = f"{float(pm):,.2f}" if pm is not None else ""
            cant_m = p.get("cantidad_mayoreo") or ""
            self.tabla.insert(
                "",
                tk.END,
                values=(
                    p["id"],
                    p["codigo"],
                    p["descripcion"],
                    precio_txt,
                    pm_txt,
                    cant_m,
                ),
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

        pm_val: float | None = None
        cant_txt: str | None = None
        if self.var_formato.get() in _FORMATOS_MAYOREO_LABELS:
            pm_txt = self.var_precio_mayoreo.get().strip().replace(",", "")
            if pm_txt:
                try:
                    pm_val = float(pm_txt)
                except ValueError:
                    messagebox.showwarning(
                        "Validación",
                        "Precio Mayoreo debe ser un número (ej. 99.00).",
                    )
                    return
            ap = self.var_cantidad_mayoreo.get().strip()
            cant_txt = ap if ap else None

        try:
            self.db.insertar(
                codigo,
                desc,
                precio,
                precio_mayoreo=pm_val,
                cantidad_mayoreo=cant_txt,
            )
        except ValueError as e:
            messagebox.showwarning("Validación", str(e))
            return
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar:\n{e}")
            return

        self.var_codigo.set("")
        self.var_descripcion.set("")
        self.var_precio.set("")
        self.var_precio_mayoreo.set("")
        self.var_cantidad_mayoreo.set("")
        self._refrescar_tabla()

    def _importar_excel(self) -> None:
        """Reemplaza todos los productos por el contenido de un .xlsx (codigo, descripcion, precio)."""
        ruta = filedialog.askopenfilename(
            title="Importar productos desde Excel",
            filetypes=[
                ("Excel", "*.xlsx"),
                ("Todos", "*.*"),
            ],
            initialdir=str(_ROOT),
        )
        if not ruta:
            return
        try:
            productos, avisos = leer_productos_desde_excel(Path(ruta))
            n = self.db.reemplazar_todos(productos)
        except Exception as e:
            msg = str(e)
            if "openpyxl" in msg.lower():
                msg += (
                    "\n\nUse el mismo intérprete con el que abre la aplicación "
                    "(si usa venv, active venv o ejecute pip dentro de venv\\Scripts)."
                )
            messagebox.showerror("Importar Excel", msg)
            return

        self._refrescar_tabla()
        msg = f"Se importaron {n} producto(s) desde:\n{ruta}"
        if avisos:
            msg += "\n\nAdvertencias:\n" + "\n".join(avisos[:25])
            if len(avisos) > 25:
                msg += f"\n… y {len(avisos) - 25} más."
        messagebox.showinfo("Importar Excel", msg)

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

        sel_fmt = self.var_formato.get()
        if sel_fmt in _FORMATOS_MAYOREO_LABELS:
            # _FORMATOS_MAYOREO_LABELS guarda "2_MAYOREO"/"4_MAYOREO";
            # printer_mod expone esos mismos strings como constantes.
            n = _FORMATOS_MAYOREO_LABELS[sel_fmt]
        else:
            try:
                n = int(sel_fmt)
            except ValueError:
                messagebox.showwarning("Formato", "Seleccione un formato valido.")
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

        if self._pdf_generando:
            return
        self._pdf_generando = True
        self._btn_generar_pdf.config(state=tk.DISABLED)
        self.master.config(cursor="watch")
        self.master.update_idletasks()

        # Copias para el hilo (evitar condiciones de carrera con la lista en memoria)
        productos_copia = [dict(p) for p in productos]
        sucursal = self.var_sucursal.get()
        marcos = self.var_marcos_coords.get()
        resultado: dict[str, object] = {}

        def trabajo() -> None:
            try:
                importlib.reload(printer_mod)
                printer_mod.generar_pdf_etiquetas(
                    productos_copia,
                    n,
                    ruta,
                    sucursal=sucursal,
                    mostrar_marcos_coordenadas=marcos,
                )
                resultado["ok"] = True
            except ValueError as e:
                resultado["valor"] = str(e)
            except Exception as e:
                resultado["error"] = e

        def al_terminar() -> None:
            self._pdf_generando = False
            self._btn_generar_pdf.config(state=tk.NORMAL)
            self.master.config(cursor="")

            if "valor" in resultado:
                messagebox.showwarning("PDF", str(resultado["valor"]))
                return
            if "error" in resultado:
                messagebox.showerror(
                    "PDF",
                    f"No se pudo generar el archivo:\n{resultado['error']}",
                )
                return

            try:
                self.db.vaciar_todos()
            except Exception as e:
                messagebox.showwarning(
                    "Limpieza",
                    f"El PDF se generó, pero no se pudo vaciar la lista de productos:\n{e}",
                )
                self._refrescar_tabla()
                return

            self._refrescar_tabla()
            messagebox.showinfo(
                "PDF",
                f"Archivo generado correctamente:\n{ruta}\n\n"
                "La lista de productos se vació para importar o registrar un nuevo lote.",
            )

        def hilo_worker() -> None:
            trabajo()
            self.master.after(0, al_terminar)

        threading.Thread(target=hilo_worker, daemon=True).start()


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
