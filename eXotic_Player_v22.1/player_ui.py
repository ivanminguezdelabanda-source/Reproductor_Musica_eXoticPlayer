"""Interfaz y utilidades visuales de eXotic Player.

El mixin contiene solo comportamiento de UI; la fachada principal sigue siendo
``WinXP_ExoticPlayer`` para conservar la API existente.
"""
import io
import json
import os
from datetime import datetime
import queue
import tkinter as tk
from tkinter import ttk
import urllib.request

from PIL import Image, ImageTk
from themes import nombres as nombres_temas

MAX_IMG_CACHE = 200
RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS


def formato_tiempo(ms):
    """Formatea milisegundos como MM:SS para la UI."""
    try:
        total = max(0, int(ms or 0) / 1000)
    except (TypeError, ValueError):
        total = 0
    minutos = int(total // 60)
    segundos = int(total % 60)
    return f"{minutos:02d}:{segundos:02d}"


class PlayerUIMixin:
    def ui(self, fn, *args):
        self._ui_queue.put((fn, args))

    def _consejo(self, widget, texto):
        """Tooltip amarillo estilo XP al dejar el ratón encima."""
        estado = {"job": None, "tip": None}

        def mostrar():
            estado["job"] = None
            tip = estado["tip"] = tk.Toplevel(widget)
            tip.overrideredirect(True)
            tip.attributes("-topmost", True)
            tk.Label(tip, text=texto, bg="#FFFFE1", fg="#000000", relief=tk.SOLID, bd=1,
                     font=("Tahoma", 8), padx=5, pady=2).pack()
            tip.geometry(f"+{widget.winfo_rootx() + 8}+{widget.winfo_rooty() + widget.winfo_height() + 4}")

        def entrar(_e):
            estado["job"] = widget.after(600, mostrar)

        def salir(_e=None):
            if estado["job"] is not None:
                widget.after_cancel(estado["job"])
                estado["job"] = None
            if estado["tip"] is not None:
                try:
                    estado["tip"].destroy()
                except tk.TclError:
                    pass
                estado["tip"] = None

        widget.bind("<Enter>", entrar, add="+")
        widget.bind("<Leave>", salir, add="+")
        widget.bind("<ButtonPress>", salir, add="+")


    def mostrar_principal(self):
        self.mini.ocultar()
        self.root.deiconify()
        if self.root.state() == "iconic":        # sin quitar el maximizado si lo estaba
            self.root.state("normal")
        self.root.lift()
        self.root.focus_force()


    def mostrar_mini(self):
        self.root.withdraw()
        self.mini.mostrar()


    def a_bandeja(self):
        """Oculta la app junto al reloj (si no hay bandeja, la minimiza a la barra de tareas)."""
        self.mini.ocultar()
        if self.tray.disponible:
            self.root.withdraw()
            self.tray.avisar_una_vez()
        else:
            self.root.iconify()


    def alternar_principal(self):
        if self.root.state() in ("normal", "zoomed") and self.root.winfo_viewable():
            self.a_bandeja()
        else:
            self.mostrar_principal()


    def _al_minimizar(self, event):
        """Minimizar la ventana principal la manda a la bandeja (solo si hay bandeja)."""
        if event.widget is self.root and self.tray.disponible and self.root.state() == "iconic":
            self.root.after(50, self.a_bandeja)


    def _procesar_cola_ui(self):
        try:
            while True:
                fn, args = self._ui_queue.get_nowait()
                try:
                    fn(*args)
                except tk.TclError:
                    pass
                except Exception as e:
                    print(f"Error en tarea de interfaz: {e}")
        except queue.Empty:
            pass
        self.root.after(30, self._procesar_cola_ui)


    def abrir_configuracion(self):
        """Abre el centro de configuración de eXotic Player (en pestañas)."""
        if getattr(self, "_config_win", None) is not None:
            try:
                if self._config_win.winfo_exists():
                    self._config_win.deiconify()
                    self._config_win.lift()
                    self._config_win.focus_force()
                    self._actualizar_configuracion_ui()
                    return
            except Exception:
                pass

        bg = self.bg_color
        win = tk.Toplevel(self.root)
        self._config_win = win
        win.title("Configuración — eXotic Player")
        win.geometry(f"560x{min(720, win.winfo_screenheight() - 80)}")
        win.minsize(540, 560)
        win.configure(bg=bg)
        win.transient(self.root)

        def cerrar():
            self._config_win = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", cerrar)
        win.bind("<Escape>", lambda e: cerrar())

        header = tk.Frame(win, bg=self.header_blue, height=46, relief=tk.RAISED, bd=2)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text="⚙️ Configuración de eXotic Player", bg=self.header_blue,
                 fg="white", font=("Tahoma", 10, "bold")).pack(side=tk.LEFT, padx=10)

        footer = tk.Frame(win, bg=bg)
        footer.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=(0, 10))
        tk.Label(footer, text=f"eXotic Player v{getattr(self, 'APP_VERSION', '')} · Windows XP / Retro",
                 bg=bg, fg="#555555", font=("Tahoma", 7)).pack(side=tk.LEFT)
        tk.Button(footer, text="Cerrar", font=("Tahoma", 8, "bold"), bg="#E0DFE3",
                  relief=tk.RAISED, bd=2, command=cerrar).pack(side=tk.RIGHT)
        tk.Button(footer, text="⌨ Atajos (F1)", font=("Tahoma", 8), bg="#E0DFE3",
                  relief=tk.RAISED, bd=2, command=self.mostrar_atajos).pack(side=tk.RIGHT, padx=6)

        tabs = ttk.Notebook(win)
        tabs.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        def pestana(titulo):
            """Pestaña con barra de desplazamiento (en pantallas pequeñas no cabe todo)."""
            fuera = tk.Frame(tabs, bg=bg)
            lienzo = tk.Canvas(fuera, bg=bg, highlightthickness=0)
            barra = tk.Scrollbar(fuera, orient=tk.VERTICAL, command=lienzo.yview)
            dentro = tk.Frame(lienzo, bg=bg)
            ventana = lienzo.create_window((0, 0), window=dentro, anchor="nw")
            dentro.bind("<Configure>", lambda e: lienzo.configure(scrollregion=lienzo.bbox("all")))
            lienzo.bind("<Configure>", lambda e: lienzo.itemconfigure(ventana, width=e.width))
            lienzo.configure(yscrollcommand=barra.set)
            lienzo.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            barra.pack(side=tk.RIGHT, fill=tk.Y)

            def rueda(e):
                try:
                    if not lienzo.winfo_exists():
                        return
                    w = self.root.winfo_containing(e.x_root, e.y_root)
                except (tk.TclError, KeyError):
                    return
                while w is not None and w is not fuera:
                    w = w.master
                if w is fuera and lienzo.winfo_height() < dentro.winfo_height():
                    lienzo.yview_scroll(-1 if e.delta > 0 else 1, "units")
            self.root.bind_all("<MouseWheel>", rueda, add="+")
            tabs.add(fuera, text=titulo)
            return dentro

        t_general = pestana("  🎵 General  ")
        t_aspecto = pestana("  🎨 Apariencia  ")
        t_datos = pestana("  ☁️ Cuenta y datos  ")

        def section(parent, title):
            box = tk.LabelFrame(parent, text=f" {title} ", font=("Tahoma", 8, "bold"),
                                bg=bg, relief=tk.GROOVE, bd=2)
            box.pack(fill=tk.X, padx=6, pady=4)
            return box

        def check(parent, texto, var, cmd):
            tk.Checkbutton(parent, text=texto, variable=var, command=cmd, bg=bg,
                           activebackground=bg, font=("Tahoma", 8), cursor="hand2",
                           highlightthickness=0, anchor="w").pack(fill=tk.X, padx=8, pady=2)

        def boton(parent, texto, cmd, bold=False, side=tk.LEFT, padx=(0, 5)):
            tk.Button(parent, text=texto, font=("Tahoma", 8, "bold" if bold else "normal"),
                      bg="#E0DFE3", relief=tk.RAISED, bd=2, cursor="hand2",
                      command=cmd).pack(side=side, padx=padx)

        # ---------------- General
        playback = section(t_general, "🎵 Reproducción")
        self.config_autoplay_var = tk.BooleanVar(value=self.autoplay_var.get())
        check(playback, "✨ Recomendaciones automáticas al terminar la cola",
              self.config_autoplay_var, self._config_cambiar_autoplay)
        self.selector_fundido(playback, bg)
        fila = tk.Frame(playback, bg=bg)
        fila.pack(fill=tk.X, padx=8, pady=(2, 6))
        boton(fila, "🎚️ Ecualizador…", self.abrir_ventana_ecualizador, bold=True)
        boton(fila, "🌙 Temporizador…", lambda: self.menu_temporizador())

        history = section(t_general, "📜 Historial")
        self.config_history_var = tk.BooleanVar(value=True)
        check(history, "Guardar las canciones reproducidas en Historial y Estadísticas",
              self.config_history_var, self._config_cambiar_historial)
        fila = tk.Frame(history, bg=bg)
        fila.pack(fill=tk.X, padx=8, pady=(2, 6))
        boton(fila, "🗑 Borrar historial completo", self._borrar_historial)

        atajos = section(t_general, "⌨ Atajos globales y arranque")
        self.config_hotkeys_var = tk.BooleanVar(value=bool(self.prefs.get("hotkeys_on", True)))
        check(atajos, "Atajos globales (Ctrl+Alt+→, Ctrl+Alt+Espacio…) aunque eXotic esté en segundo plano",
              self.config_hotkeys_var,
              lambda: (self.prefs.update(hotkeys_on=bool(self.config_hotkeys_var.get())),
                       self._guardar_prefs(), self._iniciar_atajos_globales()))
        import hotkeys as _hk
        self.config_autostart_var = tk.BooleanVar(value=_hk.autoarranque_activo())

        def _autostart():
            ok = _hk.poner_autoarranque(self.config_autostart_var.get())
            if not ok:
                self.config_autostart_var.set(_hk.autoarranque_activo())
                self.status_var.set("No se pudo cambiar el arranque con Windows.")
            else:
                self.status_var.set("🪟 eXotic se abrirá al iniciar Windows (en la bandeja)."
                                    if self.config_autostart_var.get() else "Arranque con Windows desactivado.")
        cb = tk.Checkbutton(atajos, text="Abrir eXotic al iniciar Windows (minimizado en la bandeja)",
                            variable=self.config_autostart_var, command=_autostart, bg=bg, activebackground=bg,
                            font=("Tahoma", 8), cursor="hand2", highlightthickness=0, anchor="w")
        cb.pack(fill=tk.X, padx=8, pady=2)
        if not _hk.autoarranque_disponible():
            cb.config(state=tk.DISABLED)
        fila = tk.Frame(atajos, bg=bg)
        fila.pack(fill=tk.X, padx=8, pady=(2, 6))
        boton(fila, "⌨ Cambiar atajos…", self.configurar_atajos_globales)

        avisos = section(t_general, "🔔 Avisos")
        self.config_notify_var = tk.BooleanVar(value=bool(self.prefs.get("notify")))
        check(avisos, "Aviso de \"Ahora suena\" al cambiar de canción (con la app en la bandeja)",
              self.config_notify_var, self._config_cambiar_avisos)
        self.config_sounds_var = tk.BooleanVar(value=bool(self.prefs.get("sounds", True)))
        check(avisos, "Sonidos de sistema retro (inicio, sesión, amigos y jam)",
              self.config_sounds_var, self._config_cambiar_sonidos)
        fila = tk.Frame(avisos, bg=bg)
        fila.pack(fill=tk.X, padx=8, pady=(2, 6))
        for nombre, texto in (("conectar", "🔔 Ding"), ("amigo", "👥 Amigo"), ("inicio", "🎵 Inicio")):
            boton(fila, texto, lambda n=nombre: self.sonidos.tocar(n))

        # ---------------- Apariencia
        aspecto = section(t_aspecto, "🎨 Tema")
        self.config_tema_var = tk.StringVar(value=self.tema.nombre)
        for nombre in nombres_temas():
            tk.Radiobutton(aspecto, text=nombre, value=nombre, variable=self.config_tema_var,
                           command=lambda: self.cambiar_tema(self.config_tema_var.get()),
                           bg=bg, activebackground=bg, font=("Tahoma", 8), cursor="hand2",
                           highlightthickness=0, anchor="w").pack(fill=tk.X, padx=8, pady=1)
        tk.Label(aspecto, text="El tema se guarda en este ordenador.", bg=bg, fg="#666666",
                 font=("Tahoma", 7), anchor="w").pack(fill=tk.X, padx=8, pady=(2, 6))
        self.config_splash_var = tk.BooleanVar(value=bool(self.prefs.get("splash", True)))
        tk.Checkbutton(aspecto, text="Animación al abrir el programa (clic o Esc para saltarla)",
                       variable=self.config_splash_var, bg=bg, activebackground=bg,
                       font=("Tahoma", 8), cursor="hand2", highlightthickness=0, anchor="w",
                       command=lambda: (self.prefs.update(splash=bool(self.config_splash_var.get())),
                                        self._guardar_prefs())).pack(fill=tk.X, padx=8, pady=(0, 6))

        visual = section(t_aspecto, "📊 Visualizador del reproductor")
        self.config_visual_var = tk.StringVar(value=self.prefs.get("visualizer", "real"))
        for valor, texto in (("real", "Real: reacciona a lo que suena (captura el audio del sistema)"),
                             ("simulado", "Simulado: animación sin capturar audio (gasta menos)"),
                             ("off", "Apagado")):
            tk.Radiobutton(visual, text=texto, value=valor, variable=self.config_visual_var,
                           command=lambda: self.cambiar_visualizador(self.config_visual_var.get()),
                           bg=bg, activebackground=bg, font=("Tahoma", 8), cursor="hand2",
                           highlightthickness=0, anchor="w").pack(fill=tk.X, padx=8, pady=1)
        tk.Label(visual, text="F11 abre el Soundscope a pantalla completa.", bg=bg, fg="#666666",
                 font=("Tahoma", 7), anchor="w").pack(fill=tk.X, padx=8, pady=(2, 6))

        # ---------------- Cuenta y datos
        account = section(t_datos, "👤 Cuenta")
        self.config_account_label = tk.Label(account, text="", bg=bg,
                                              fg="#222222", font=("Tahoma", 8), anchor="w")
        self.config_account_label.pack(fill=tk.X, padx=8, pady=(6, 3))
        fila = tk.Frame(account, bg=bg)
        fila.pack(fill=tk.X, padx=8, pady=(0, 7))
        boton(fila, "🔑 Gestionar inicio de sesión", self.proceso_login, bold=True)

        cloud = section(t_datos, "☁️ Datos y sincronización")
        self.config_cloud_label = tk.Label(cloud, text="", bg=bg,
                                           fg="#222222", font=("Tahoma", 8), anchor="w", justify=tk.LEFT)
        self.config_cloud_label.pack(fill=tk.X, padx=8, pady=(6, 3))
        self.config_sync_detail = tk.Label(cloud, text="", bg=bg, wraplength=440,
                                           fg="#555555", font=("Tahoma", 7), anchor="w", justify=tk.LEFT)
        self.config_sync_detail.pack(fill=tk.X, padx=8, pady=(0, 4))
        fila = tk.Frame(cloud, bg=bg)
        fila.pack(fill=tk.X, padx=8, pady=(0, 7))
        boton(fila, "☁️ Sincronizar ahora", self._guardar_datos_cloud_async, bold=True)
        boton(fila, "⬇ Descargar de la nube", self._config_descargar_nube)

        backup = section(t_datos, "💾 Copia de seguridad")
        tk.Label(backup, text="Guarda playlists, favoritos, historial y ajustes en un archivo JSON.",
                 bg=bg, fg="#555555", font=("Tahoma", 7), anchor="w").pack(fill=tk.X, padx=8, pady=(6, 4))
        fila = tk.Frame(backup, bg=bg)
        fila.pack(fill=tk.X, padx=8, pady=(0, 7))
        boton(fila, "💾 Crear copia", self._config_exportar_copia, bold=True)
        boton(fila, "↩ Restaurar copia", self._config_importar_copia)

        self.seccion_ytm(t_datos, bg)
        self.seccion_lastfm(t_datos, bg)

        maintenance = section(t_datos, "🔧 Mantenimiento")
        fila_rep = tk.Frame(maintenance, bg=bg)
        fila_rep.pack(fill=tk.X, padx=8, pady=(6, 0))
        tk.Label(fila_rep, text="Versiones nuevas desde GitHub:", bg=bg, font=("Tahoma", 8)).pack(side=tk.LEFT)
        repo_entry = tk.Entry(fila_rep, width=24, font=("Tahoma", 8), relief=tk.SUNKEN, bd=2)
        repo_entry.insert(0, self.prefs.get("update_repo") or "")
        repo_entry.pack(side=tk.LEFT, padx=4)

        def buscar_version():
            import updates
            repo = updates.repo_valido(repo_entry.get())
            if repo_entry.get().strip() and not repo:
                self.status_var.set("Escribe el repositorio como usuario/repositorio.")
                return
            self.prefs["update_repo"] = repo or ""
            self._guardar_prefs()
            self.comprobar_actualizaciones(manual=True)
        boton(fila_rep, "Buscar", buscar_version)
        tk.Label(maintenance, text="(usuario/repositorio donde GitHub Actions publica las versiones)", bg=bg,
                 fg="#666666", font=("Tahoma", 7), anchor="w").pack(fill=tk.X, padx=8)
        fila = tk.Frame(maintenance, bg=bg)
        fila.pack(fill=tk.X, padx=8, pady=6)
        boton(fila, "Actualizar yt-dlp", self.actualizar_ytdlp_async)
        boton(fila, "📂 Carpeta de datos", self._config_abrir_carpeta_datos)
        boton(fila, "↺ Restaurar ajustes", self._config_restaurar_ajustes)

        self.tematizar(win)
        self._actualizar_configuracion_ui()

    def _config_cambiar_avisos(self):
        self.prefs["notify"] = bool(self.config_notify_var.get())
        self._guardar_prefs()

    def _config_cambiar_sonidos(self):
        self.prefs["sounds"] = bool(self.config_sounds_var.get())
        self.sonidos.activado = self.prefs["sounds"]
        self._guardar_prefs()
        if self.prefs["sounds"]:
            self.sonar("conectar")

    def _actualizar_configuracion_ui(self):
        if not getattr(self, "_config_win", None):
            return
        try:
            if not self._config_win.winfo_exists():
                return
        except Exception:
            return
        cuenta = self.email_cuenta or ("Cuenta conectada" if self.sesion_iniciada else "Modo invitado")
        self.config_account_label.config(text=f"Cuenta actual: {cuenta}")
        if self.cloud.logged_in:
            self.config_cloud_label.config(text="Estado: conectado · sincronización disponible.")
        else:
            self.config_cloud_label.config(text="Estado: local · inicia sesión para sincronizar con la nube.")
        estados = {
            "ok": "🟢 Sincronizado",
            "working": "🟡 Sincronizando...",
            "error": "🔴 Error de sincronización",
            "local": "⚪ Solo en este ordenador",
        }
        detalle = estados.get(getattr(self, "_sync_status", "local"), "⚪ Solo en este ordenador")
        mensaje = getattr(self, "_sync_message", "Sin sincronizar")
        ultimo = getattr(self, "_last_sync_at", None)
        if ultimo:
            detalle += f" · Última: {ultimo.strftime('%d/%m/%Y %H:%M')}"
        self.config_sync_detail.config(text=f"{detalle} · {mensaje}")
        self.config_autoplay_var.set(bool(self.autoplay_var.get()))
        st = self.cloud_data.get("settings") or {}
        self.config_history_var.set(bool(st.get("save_history", True)))
        self._pintar_seccion_ytm()

    def _config_cambiar_autoplay(self):
        self.autoplay_var.set(bool(self.config_autoplay_var.get()))
        self._al_cambiar_autoplay()
        self._actualizar_configuracion_ui()

    def _config_cambiar_historial(self):
        st = self.cloud_data.setdefault("settings", {})
        st["save_history"] = bool(self.config_history_var.get())
        self._guardar_si_corresponde()
        self.status_var.set("Historial activado." if st["save_history"] else "Historial desactivado.")

    def _config_descargar_nube(self):
        if not self.cloud.logged_in:
            self.status_var.set("Inicia sesión para descargar tus datos de la nube.")
            return
        self._cargar_datos_cloud_async()
        self.status_var.set("☁️ Descargando datos de la nube...")

    def _config_exportar_copia(self):
        from tkinter import filedialog, messagebox
        try:
            self._sincronizar_cola_en_datos()
            datos = json.loads(json.dumps(self.cloud_data, ensure_ascii=False))
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
            nombre = f"eXoticPlayer_backup_{stamp}.json"
            ruta = filedialog.asksaveasfilename(
                title="Guardar copia de seguridad",
                defaultextension=".json",
                initialfile=nombre,
                filetypes=[("Copia de eXotic Player", "*.json"), ("Todos los archivos", "*.*")],
            )
            if not ruta:
                return
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            self.status_var.set("💾 Copia de seguridad creada.")
            messagebox.showinfo("Copia creada", "La copia de seguridad se ha guardado correctamente.")
        except Exception as e:
            self.status_var.set(f"No se pudo crear la copia: {e}")

    def _config_importar_copia(self):
        from tkinter import filedialog, messagebox
        ruta = filedialog.askopenfilename(
            title="Restaurar copia de eXotic Player",
            filetypes=[("Copia de eXotic Player", "*.json"), ("Todos los archivos", "*.*")],
        )
        if not ruta:
            return
        if not messagebox.askyesno(
            "Restaurar copia",
            "Esto reemplazará tus playlists, favoritos, historial y ajustes actuales "
            "por los de la copia seleccionada.\n\n¿Continuar?"
        ):
            return
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                datos = json.load(f)
            if not isinstance(datos, dict):
                raise ValueError("el archivo no contiene datos válidos")
            for clave in ("playlists", "liked", "history"):
                if not isinstance(datos.get(clave, []), list):
                    raise ValueError(f"el campo {clave} no es válido")
            if not isinstance(datos.get("settings", {}), dict):
                datos["settings"] = {}
            datos.setdefault("version", 2)
            self.cloud_data = datos
            self._asegurar_playlist_principal()
            self._refrescar_escuchado_reciente_ui()
            self._refrescar_favoritos_ui()
            self.actualizar_estadisticas_ui()
            self._aplicar_ajustes()
            self._guardar_local()
            if self.cloud.logged_in:
                self._subir_cloud_data_async("☁️ Copia restaurada y sincronizada.")
            else:
                self.status_var.set("↩ Copia restaurada en este ordenador.")
            self._actualizar_configuracion_ui()
        except Exception as e:
            messagebox.showerror("No se pudo restaurar", f"La copia no es válida o no se pudo leer.\n\n{e}")
            self.status_var.set("No se pudo restaurar la copia.")


    def _config_abrir_carpeta_datos(self):
        try:
            import app_paths
            os.startfile(app_paths.DATA_DIR)
        except Exception as e:
            self.status_var.set(f"No se pudo abrir la carpeta de datos: {e}")

    def _config_restaurar_ajustes(self):
        from tkinter import messagebox
        if not messagebox.askyesno("Restaurar ajustes", "¿Restaurar solo los ajustes de eXotic Player?\n\nTus playlists, favoritos e historial no se borrarán."):
            return
        self.cloud_data.setdefault("settings", {}).clear()
        self._aplicar_ajustes()
        self.autoplay_var.set(True)
        self.config_autoplay_var.set(True)
        self.config_history_var.set(True)
        self._guardar_si_corresponde()
        self.status_var.set("↺ Ajustes restaurados.")
        self._actualizar_configuracion_ui()


    # ------------------------------------------------------------------
    # Modo pantalla completa / SoundScope inspirado en PlayStation 1
    # ------------------------------------------------------------------
    def construir_interfaz(self):
        header = tk.Frame(self.root, bg=self.header_blue, height=42, relief=tk.RAISED, bd=2)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Label(
            header, text="🎛️ eXotic Media Player Pro", bg=self.header_blue,
            fg="white", font=("Tahoma", 10, "bold")
        ).pack(side=tk.LEFT, padx=10)

        self.config_btn = tk.Button(
            header, text="⚙️ Config", bg="#316AC5", fg="white",
            font=("Tahoma", 8, "bold"), relief=tk.RAISED, bd=2,
            cursor="hand2", command=self.abrir_configuracion
        )
        self.config_btn.pack(side=tk.RIGHT, padx=0, pady=6)

        self.auth_btn = tk.Button(
            header, text="🔑 Iniciar sesión", bg="#316AC5", fg="white",
            font=("Tahoma", 8, "bold"), relief=tk.RAISED, bd=2,
            cursor="hand2", command=self.proceso_login
        )
        self.auth_btn.pack(side=tk.RIGHT, padx=12, pady=6)

        self.social_btn = tk.Button(
            header, text="👥 Amigos y Jam", bg="#7B4FA3", fg="white",
            font=("Tahoma", 8, "bold"), relief=tk.RAISED, bd=2,
            cursor="hand2", command=self.social.abrir
        )
        self.social_btn.pack(side=tk.RIGHT, padx=0, pady=6)

        self.video_btn = tk.Button(
            header, text="🎬 Videoclip", bg="#C0763A", fg="white",
            font=("Tahoma", 8, "bold"), relief=tk.RAISED, bd=2,
            cursor="hand2", command=self.alternar_videoclip
        )
        self.video_btn.pack(side=tk.RIGHT, padx=6, pady=6)

        # Menú "Ver": junta lo que antes eran cuatro botones sueltos en la cabecera
        self.ver_btn = tk.Menubutton(
            header, text="🖥 Ver ▾", bg="#316AC5", fg="white", activebackground="#4A82D8",
            activeforeground="white", font=("Tahoma", 8, "bold"), relief=tk.RAISED, bd=2,
            cursor="hand2", direction="below"
        )
        menu_ver = tk.Menu(self.ver_btn, tearoff=0, font=("Tahoma", 9))
        menu_ver.add_command(label="🌀 Soundscope a pantalla completa", accelerator="F11",
                             command=lambda: self.soundscope.alternar())
        menu_ver.add_command(label="🎵 Mini modo", command=self.mostrar_mini)
        menu_ver.add_command(label="📝 Letra", accelerator="Ctrl+T", command=self.letra.alternar)
        menu_ver.add_command(label="🎚️ Ecualizador", accelerator="Ctrl+E", command=self.abrir_ventana_ecualizador)
        menu_ver.add_separator()
        menu_ver.add_command(label="🎁 Mi Wrapped…", command=lambda: self.menu_wrapped(self.ver_btn))
        menu_ver.add_command(label="⌨ Atajos de teclado", accelerator="F1", command=self.mostrar_atajos)
        self.ver_btn.config(menu=menu_ver)
        self.ver_btn.pack(side=tk.RIGHT, padx=6, pady=6)

        player_card = self._player_card = tk.LabelFrame(
            self.root, text=" Visualizer & Album Artwork System ",
            font=("Tahoma", 8, "bold"), bg=self.bg_color, relief=tk.GROOVE, bd=2
        )
        player_card.pack(fill=tk.X, padx=12, pady=8)

        display_container = self._display_container = tk.Frame(player_card, bg=self.bg_color)
        display_container.pack(fill=tk.X, padx=8, pady=6)

        cover_frame = tk.Frame(display_container, bg="black", relief=tk.SUNKEN, bd=3, width=95, height=95)
        cover_frame.pack(side=tk.LEFT, padx=(0, 8))
        cover_frame.pack_propagate(False)

        self.cover_label = tk.Label(
            cover_frame, text="NO\nCOVER", bg="#101010", fg="#555555",
            font=("Consolas", 8, "bold")
        )
        self.cover_label.pack(fill=tk.BOTH, expand=True)

        lcd_frame = self._lcd_frame = tk.Frame(display_container, bg=self.lcd_bg, relief=tk.SUNKEN, bd=3)
        lcd_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        top_lcd_line = tk.Frame(lcd_frame, bg=self.lcd_bg)
        top_lcd_line.pack(fill=tk.X, padx=8, pady=(4, 0))

        self.lcd_title = tk.Label(
            top_lcd_line, text="*** Modo Invitado (pulsa 'Iniciar sesión') ***",
            bg=self.lcd_bg, fg=self.lcd_green,
            font=("Consolas", 10, "bold"), anchor="w"
        )
        self.lcd_title.pack(side=tk.LEFT, fill=tk.X, expand=True)
        for w in (lcd_frame, self.lcd_title):
            w.bind("<Button-3>", self.menu_lcd)          # clic derecho: ♥, letra, enlace...

        self.lcd_time = tk.Label(
            top_lcd_line, text="[00:00 / 00:00]", bg=self.lcd_bg, fg=self.lcd_green,
            font=("Consolas", 9, "bold")
        )
        self.lcd_time.pack(side=tk.RIGHT)

        self.canvas_eq = tk.Canvas(lcd_frame, bg="#000000", height=60, highlightthickness=0)
        self.canvas_eq.pack(fill=tk.X, padx=8, pady=4)
        self.canvas_eq.bind("<Configure>", self._construir_eq)
        self.canvas_eq.bind("<Button-3>", self.menu_lcd)
        self.canvas_eq.bind("<Double-Button-1>", lambda e: self.soundscope.alternar())

        controls_bar = self._controls_bar = tk.Frame(player_card, bg=self.bg_color)
        controls_bar.pack(fill=tk.X, padx=10, pady=4)

        self.time_slider = ttk.Scale(controls_bar, from_=0, to=100, orient=tk.HORIZONTAL, style="TScale")
        self.time_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 15))
        self.time_slider.bind("<ButtonPress-1>", self.on_slider_press)
        self.time_slider.bind("<ButtonRelease-1>", self.on_seek)

        muted = bool(self.prefs.get("muted"))
        self.mute_btn = tk.Button(controls_bar, text="🔇" if muted else "🔊", bg=self.bg_color,
                                  relief=tk.FLAT, bd=0, cursor="hand2", font=("Segoe UI Symbol", 10),
                                  activebackground=self.bg_color, command=self.alternar_silencio)
        self.mute_btn.pack(side=tk.LEFT, padx=(0, 2))
        self.vol_slider = ttk.Scale(controls_bar, from_=0, to=100, orient=tk.HORIZONTAL, length=110, command=self.cambiar_volumen)
        volumen = int(self.prefs.get("volume", 80))
        self.vol_slider.set(volumen)
        self.player.audio_set_volume(volumen)
        if muted:
            self.player.audio_set_mute(True)
        self.vol_slider.pack(side=tk.LEFT)
        self.vol_label = tk.Label(controls_bar, text=f"{volumen}%", width=4, bg=self.bg_color,
                                  font=("Tahoma", 7), fg="#555555")
        self.vol_label.pack(side=tk.LEFT, padx=(2, 0))

        btn_bar = self._btn_bar = tk.Frame(player_card, bg=self.bg_color)
        btn_bar.pack(fill=tk.X, pady=(4, 8))

        controls_buttons = tk.Frame(btn_bar, bg=self.bg_color)
        controls_buttons.pack()

        btn_opt = {
            "font": ("Segoe UI Symbol", 11, "bold"), "relief": tk.RAISED,
            "bg": "#E0DFE3", "activebackground": "#D4D0C8",
            "width": 5, "bd": 2, "cursor": "hand2"
        }
        botones = [
            ("⏮", self.anterior_cancion), ("▶", self.reproducir_actual),
            ("⏸", self.pausar_cancion), ("⏹", self.detener_cancion),
            ("⏭", self.siguiente_cancion),
        ]
        for col, (txt, cmd) in enumerate(botones):
            tk.Button(controls_buttons, text=txt, command=cmd, **btn_opt).grid(row=0, column=col, padx=5)

        # Extras: repetir, mezclar, me gusta, temporizador y letra
        mini_opt = {"font": ("Tahoma", 8, "bold"), "relief": tk.RAISED, "bg": "#E0DFE3",
                    "activebackground": "#D4D0C8", "bd": 2, "cursor": "hand2"}
        col = len(botones)
        tk.Frame(controls_buttons, bg="#A0A0A0", width=1, height=26).grid(row=0, column=col, padx=(10, 8))
        self.repeat_btn = tk.Button(controls_buttons, text="🔁 No", width=7,
                                    command=self.alternar_repetir, **mini_opt)
        self.repeat_btn.grid(row=0, column=col + 1, padx=2)
        tk.Button(controls_buttons, text="🔀", width=3, command=self.mezclar_cola,
                  **mini_opt).grid(row=0, column=col + 2, padx=2)
        self.like_btn = tk.Button(controls_buttons, text="♡", width=3, command=self.alternar_like_actual,
                                  **dict(mini_opt, font=("Tahoma", 10, "bold")))
        self.like_btn.grid(row=0, column=col + 3, padx=2)
        self.sleep_btn = tk.Button(controls_buttons, text="🌙", width=9, **mini_opt)
        self.sleep_btn.config(command=lambda: self.menu_temporizador(self.sleep_btn))
        self.sleep_btn.grid(row=0, column=col + 4, padx=2)
        tk.Button(controls_buttons, text="📝 Letra", command=self.letra.alternar,
                  **mini_opt).grid(row=0, column=col + 5, padx=2)
        self.fx_btn = tk.Button(controls_buttons, text="🎚 Efectos", **mini_opt)
        self.fx_btn.config(command=lambda: self.menu_efectos(self.fx_btn))
        self.fx_btn.grid(row=0, column=col + 6, padx=2)
        self._consejo(self.fx_btn, "Slowed, nightcore… e igualar el volumen entre canciones")
        tk.Checkbutton(
            controls_buttons, text="✨ Autoplay", variable=self.autoplay_var,
            command=self._al_cambiar_autoplay, bg=self.bg_color,
            activebackground=self.bg_color, font=("Tahoma", 8, "bold"), cursor="hand2"
        ).grid(row=0, column=col + 7, padx=(12, 0))
        self._consejo(self.repeat_btn, "Repetir: no / toda la cola / una canción (Ctrl+R)")
        self._consejo(self.like_btn, "Me gusta la canción actual (Ctrl+L)")
        self._consejo(self.sleep_btn, "Temporizador para dormir")
        self._consejo(self.mute_btn, "Silenciar (Ctrl+M)")

        main_panel = tk.Frame(self.root, bg=self.bg_color)
        main_panel.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 6))

        left_box = tk.LabelFrame(
            main_panel, text=" Buscador de Canciones ", font=("Tahoma", 8, "bold"),
            bg=self.bg_color, relief=tk.GROOVE, bd=2
        )
        left_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        search_bar = tk.Frame(left_box, bg=self.bg_color)
        search_bar.pack(fill=tk.X, padx=8, pady=6)

        tipo_bar = tk.Frame(left_box, bg=self.bg_color)
        tipo_bar.pack(fill=tk.X, padx=8, after=search_bar)
        for texto, valor in (("🎵 Canciones (solo audio)", "songs"), ("🎬 Videoclips", "videos")):
            tk.Radiobutton(
                tipo_bar, text=texto, value=valor, variable=self.tipo_busqueda_var,
                command=self.obtener_sugerencias_canciones, bg=self.bg_color,
                activebackground=self.bg_color, font=("Tahoma", 8, "bold"), cursor="hand2"
            ).pack(side=tk.LEFT, padx=(0, 12))

        self.search_entry = tk.Entry(search_bar, font=("Tahoma", 9), relief=tk.SUNKEN, bd=2)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.search_entry.bind("<KeyRelease>", self.al_escribir_busqueda)
        self.search_entry.bind("<Return>", lambda e: self.obtener_sugerencias_canciones())

        tk.Button(
            search_bar, text="Buscar", font=("Tahoma", 8, "bold"),
            relief=tk.RAISED, bg="#E0DFE3", bd=2,
            command=self.obtener_sugerencias_canciones
        ).pack(side=tk.RIGHT)
        tk.Button(
            search_bar, text="♥ Me gusta", font=("Tahoma", 8, "bold"),
            relief=tk.RAISED, bg="#E0DFE3", bd=2, cursor="hand2",
            command=self.cargar_me_gusta
        ).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(search_bar, text="🧭 Explorar", font=("Tahoma", 8, "bold"), relief=tk.RAISED,
                  bg="#D9F2D9", bd=2, cursor="hand2", command=lambda: self.explorar("inicio")
                  ).pack(side=tk.RIGHT, padx=(0, 6))
        local_btn = tk.Button(search_bar, text="📂 Mi música", font=("Tahoma", 8, "bold"),
                              relief=tk.RAISED, bg="#D6E4FF", bd=2, cursor="hand2")
        local_btn.config(command=lambda: self.menu_locales(local_btn))
        local_btn.pack(side=tk.RIGHT, padx=(0, 6))
        self._consejo(local_btn, "Reproducir MP3, FLAC y demás archivos de tu ordenador")

        self.sug_container = tk.Frame(left_box, bg="white", relief=tk.SUNKEN, bd=2)
        self.sug_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))

        self.canvas_sug = tk.Canvas(self.sug_container, bg="#FAFAFA", highlightthickness=0)
        sug_scroll = tk.Scrollbar(self.sug_container, orient=tk.VERTICAL, command=self.canvas_sug.yview)

        self.scroll_frame = tk.Frame(self.canvas_sug, bg="#FAFAFA")
        self.scroll_frame.bind(
            "<Configure>",
            lambda e: self.canvas_sug.configure(scrollregion=self.canvas_sug.bbox("all"))
        )
        self.canvas_window = self.canvas_sug.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas_sug.bind("<Configure>", lambda e: self.canvas_sug.itemconfig(self.canvas_window, width=e.width))
        self.canvas_sug.configure(yscrollcommand=sug_scroll.set)

        self.canvas_sug.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sug_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.root.bind_all(seq, self._on_mousewheel, add="+")

        right_col = tk.Frame(main_panel, bg=self.bg_color, width=500)
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(6, 0))
        right_col.pack_propagate(False)

        # La biblioteca queda organizada en pestañas para no saturar la columna.
        # "Biblioteca" conserva playlists + cola; "Recientes" contiene el historial.
        self.library_tabs = ttk.Notebook(right_col)
        self.library_tabs.pack(fill=tk.BOTH, expand=True)
        library_tab = tk.Frame(self.library_tabs, bg=self.bg_color)
        liked_tab = tk.Frame(self.library_tabs, bg=self.bg_color)
        recent_tab = tk.Frame(self.library_tabs, bg=self.bg_color)
        stats_tab = tk.Frame(self.library_tabs, bg=self.bg_color)
        self.library_tabs.add(library_tab, text="Biblioteca")
        self.library_tabs.add(liked_tab, text="♥ Me gusta")
        self.library_tabs.add(recent_tab, text="Recientes")
        self.library_tabs.add(stats_tab, text="📊 Estadísticas")

        playlist_box = tk.LabelFrame(
            library_tab, text=" Mis playlists ", font=("Tahoma", 8, "bold"),
            bg=self.bg_color, relief=tk.GROOVE, bd=2
        )
        # Altura reservada para que el historial y la cola queden siempre visibles.
        # Antes este frame usaba ``expand=True`` y podía comerse verticalmente
        # el resto de la columna derecha.
        playlist_box.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        playlist_box.configure(height=380)
        playlist_box.pack_propagate(False)

        # Cabecera visual de la playlist: portada + nombre/controles.
        playlist_head = tk.Frame(playlist_box, bg=self.bg_color)
        playlist_head.pack(fill=tk.X, padx=7, pady=(6, 4))

        self.playlist_cover_frame = tk.Frame(playlist_head, bg="#101010", relief=tk.SUNKEN, bd=2, width=72, height=72)
        self.playlist_cover_frame.pack(side=tk.LEFT, padx=(0, 7))
        self.playlist_cover_frame.pack_propagate(False)
        self.playlist_cover_label = tk.Label(
            self.playlist_cover_frame, text="♪", bg="#D4D0C8", fg="#555555",
            font=("Tahoma", 20, "bold")
        )
        self.playlist_cover_label.pack(fill=tk.BOTH, expand=True)

        playlist_head_right = tk.Frame(playlist_head, bg=self.bg_color)
        playlist_head_right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        playlist_select = tk.Frame(playlist_head_right, bg=self.bg_color)
        playlist_select.pack(fill=tk.X)
        self.playlist_combo = ttk.Combobox(
            playlist_select, textvariable=self.playlist_var, state="readonly",
            font=("Tahoma", 8), width=18
        )
        self.playlist_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.playlist_combo.bind("<<ComboboxSelected>>", self._seleccionar_playlist_ui)
        tk.Button(playlist_select, text="Nueva", font=("Tahoma", 7, "bold"),
                  bg="#E0DFE3", relief=tk.RAISED, bd=2, cursor="hand2",
                  command=self._mostrar_creador_playlist_inline).pack(side=tk.LEFT, padx=(4, 0))
        tk.Button(playlist_select, text="✏", font=("Tahoma", 7, "bold"),
                  bg="#E0DFE3", relief=tk.RAISED, bd=2, cursor="hand2",
                  command=self.playlist_renombrar).pack(side=tk.LEFT, padx=(2, 0))
        tk.Button(playlist_select, text="🖼", font=("Tahoma", 7, "bold"),
                  bg="#E0DFE3", relief=tk.RAISED, bd=2, cursor="hand2",
                  command=self.playlist_establecer_portada).pack(side=tk.LEFT, padx=(2, 0))
        tk.Button(playlist_select, text="🗑", font=("Tahoma", 7, "bold"),
                  bg="#F2D9D9", relief=tk.RAISED, bd=2, cursor="hand2",
                  command=self.playlist_eliminar).pack(side=tk.LEFT, padx=(2, 0))
        imp = tk.Button(playlist_select, text="⬇ YT", font=("Tahoma", 7, "bold"),
                        bg="#D6E4FF", relief=tk.RAISED, bd=2, cursor="hand2",
                        command=self.importar_playlist_youtube)
        imp.pack(side=tk.LEFT, padx=(2, 0))
        self._consejo(imp, "Importar una playlist de YouTube / YouTube Music")

        self.playlist_cover_title = tk.Label(
            playlist_head_right, text="Mi música", bg=self.bg_color, fg="#0A246A",
            font=("Tahoma", 10, "bold"), anchor="w"
        )
        self.playlist_cover_title.pack(fill=tk.X, pady=(5, 0))

        self.playlist_create_bar = tk.Frame(playlist_box, bg="#ECE9D8")
        self.playlist_create_bar.pack_forget()

        playlist_search = tk.Frame(playlist_box, bg=self.bg_color)
        playlist_search.pack(fill=tk.X, padx=7, pady=(0, 4))
        self.playlist_search_var = tk.StringVar()
        tk.Label(playlist_search, text="🔎", bg=self.bg_color, font=("Tahoma", 8)).pack(side=tk.LEFT)
        self.playlist_search_entry = tk.Entry(
            playlist_search, textvariable=self.playlist_search_var,
            font=("Tahoma", 8), relief=tk.SUNKEN, bd=2
        )
        self.playlist_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 2))
        self.playlist_search_entry.bind("<KeyRelease>", self._filtrar_playlist_ui)
        tk.Button(
            playlist_search, text="X", width=2, font=("Tahoma", 7),
            bg="#E0DFE3", relief=tk.RAISED, bd=2, cursor="hand2",
            command=lambda: self.playlist_search_var.set("") or self._refrescar_lista_playlist()
        ).pack(side=tk.RIGHT)

        self.playlist_info_label = tk.Label(playlist_box, text="0 canciones", bg=self.bg_color,
                                             fg="#555555", font=("Tahoma", 7, "bold"), anchor="w")
        self.playlist_info_label.pack(fill=tk.X, padx=8, pady=(0, 3))

        self.playlist_tracks_frame = tk.Frame(playlist_box, bg="#FFFFFF", relief=tk.SUNKEN, bd=2)
        self.playlist_tracks_frame.pack(fill=tk.BOTH, expand=True, padx=7, pady=(0, 4))

        self.playlist_columns_label = tk.Label(
            playlist_box,
            text=" Nº   TÍTULO                                      ARTISTA                   DURACIÓN",
            bg="#D4D0C8", fg="#333333", font=("Consolas", 7, "bold"),
            anchor="w", relief=tk.RAISED, bd=1
        )
        self.playlist_columns_label.pack(fill=tk.X, padx=7, pady=(0, 0))
        pl_scroll = tk.Scrollbar(self.playlist_tracks_frame)
        pl_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.list_playlist_tracks = tk.Listbox(
            self.playlist_tracks_frame, font=("Consolas", 8), bg="#FFFFFF", height=7, width=86,
            selectbackground="#316AC5", selectforeground="white",
            selectmode=tk.EXTENDED,
            yscrollcommand=pl_scroll.set, relief=tk.FLAT, activestyle="none",
            highlightthickness=0, exportselection=False
        )
        self.list_playlist_tracks.pack(fill=tk.BOTH, expand=True)
        pl_scroll.config(command=self.list_playlist_tracks.yview)
        self.list_playlist_tracks.bind("<Double-Button-1>", lambda e: self.playlist_reproducir_seleccion())
        self.list_playlist_tracks.bind("<ButtonPress-3>", self._menu_contextual_playlist, add="+")
        self.list_playlist_tracks.bind("<Delete>", self._playlist_tecla, add="+")
        self.list_playlist_tracks.bind("<Return>", self._playlist_tecla, add="+")
        self.list_playlist_tracks.bind("<ButtonPress-1>", self._iniciar_arrastre_playlist, add="+")
        self.list_playlist_tracks.bind("<B1-Motion>", self._arrastrar_playlist, add="+")
        self.list_playlist_tracks.bind("<ButtonRelease-1>", self._finalizar_arrastre_playlist, add="+")

        tk.Label(playlist_box, text="↕ Arrastra una canción para cambiar su orden",
                 bg=self.bg_color, fg="#555555", font=("Tahoma", 7, "italic")).pack(
                     fill=tk.X, padx=8, pady=(0, 3))

        pl_actions = tk.Frame(playlist_box, bg=self.bg_color)
        pl_actions.pack(fill=tk.X, padx=7, pady=(0, 6))
        for text, cmd in (("▶ Reproducir", self.playlist_reproducir_seleccion),
                          ("+ Cola", self.playlist_agregar_seleccion_a_cola),
                          ("+ Toda", self.playlist_agregar_todo_a_cola),
                          ("✕ Quitar", self.playlist_quitar_seleccion_multiple)):
            tk.Button(pl_actions, text=text, font=("Tahoma", 7), relief=tk.RAISED,
                      bg="#E0DFE3", bd=2, cursor="hand2", command=cmd).pack(
                          side=tk.LEFT, fill=tk.X, expand=True, padx=1)

        self.playlist_shuffle_btn = tk.Button(
            pl_actions, text="🔀 Aleatorio", font=("Tahoma", 7, "bold"),
            relief=tk.RAISED, bg="#E0DFE3", bd=2, cursor="hand2",
            command=self._alternar_aleatorio_playlist
        )
        self.playlist_shuffle_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
        self._actualizar_boton_aleatorio_playlist()

        recent_box = tk.LabelFrame(
            recent_tab, text=" Escuchado recientemente ", font=("Tahoma", 8, "bold"),
            bg=self.bg_color, relief=tk.GROOVE, bd=2
        )
        recent_box.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        recent_top = tk.Frame(recent_box, bg=self.bg_color)
        recent_top.pack(fill=tk.X, padx=7, pady=(7, 3))
        self.recent_info_label = tk.Label(
            recent_top, text="0 canciones · 0 reproducciones", bg=self.bg_color,
            fg="#0A246A", font=("Tahoma", 8, "bold"), anchor="w"
        )
        self.recent_info_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(
            recent_top, text="🗑", width=3, font=("Tahoma", 7, "bold"),
            bg="#F2D9D9", relief=tk.RAISED, bd=2, cursor="hand2",
            command=self._borrar_historial
        ).pack(side=tk.RIGHT)

        recent_search = tk.Frame(recent_box, bg=self.bg_color)
        recent_search.pack(fill=tk.X, padx=7, pady=(0, 4))
        self.recent_search_var = tk.StringVar()
        tk.Label(recent_search, text="🔎", bg=self.bg_color, font=("Tahoma", 8)).pack(side=tk.LEFT)
        recent_entry = tk.Entry(
            recent_search, textvariable=self.recent_search_var, font=("Tahoma", 8),
            relief=tk.SUNKEN, bd=2
        )
        recent_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))
        recent_entry.bind("<KeyRelease>", self._filtrar_recientes_ui)

        recent_frame = tk.Frame(recent_box, bg="#FFFFFF", relief=tk.SUNKEN, bd=2)
        recent_frame.pack(fill=tk.BOTH, expand=True, padx=7, pady=(2, 5))
        recent_scroll = tk.Scrollbar(recent_frame)
        recent_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.list_recent_tracks = tk.Listbox(
            recent_frame, font=("Tahoma", 8), bg="#FFFFFF", height=7,
            selectbackground="#316AC5", selectforeground="white",
            yscrollcommand=recent_scroll.set, relief=tk.FLAT, activestyle="none",
            highlightthickness=0, exportselection=False
        )
        self.list_recent_tracks.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        recent_scroll.config(command=self.list_recent_tracks.yview)
        self.list_recent_tracks.bind("<Double-Button-1>", self._reproducir_escuchado_seleccionado)
        self.list_recent_tracks.bind("<<ListboxSelect>>", self._seleccionar_reciente_ui)

        recent_selected = tk.Frame(recent_box, bg="#FFFFFF", relief=tk.GROOVE, bd=1)
        recent_selected.pack(fill=tk.X, padx=7, pady=(0, 5))
        self.recent_selected_label = tk.Label(
            recent_selected, text="Selecciona una canción", bg="#FFFFFF", fg="#0A246A",
            font=("Tahoma", 8, "bold"), anchor="w", justify=tk.LEFT
        )
        self.recent_selected_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=4)
        self.recent_play_count_label = tk.Label(
            recent_selected, text="", bg="#FFFFFF", fg="#666666", font=("Tahoma", 7)
        )
        self.recent_play_count_label.pack(side=tk.RIGHT, padx=5)

        recent_actions = tk.Frame(recent_box, bg=self.bg_color)
        recent_actions.pack(fill=tk.X, padx=7, pady=(0, 5))
        tk.Button(
            recent_actions, text="▶ Reproducir", font=("Tahoma", 7, "bold"), bg="#E0DFE3",
            relief=tk.RAISED, bd=2, cursor="hand2", command=self._reproducir_escuchado_seleccionado
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        tk.Button(
            recent_actions, text="➕ Cola", font=("Tahoma", 7, "bold"), bg="#E0DFE3",
            relief=tk.RAISED, bd=2, cursor="hand2", command=self._anadir_reciente_a_cola
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        tk.Label(
            recent_box, text="Doble clic para reproducir · busca por canción o artista",
            bg=self.bg_color, fg="#666666", font=("Tahoma", 7)
        ).pack(fill=tk.X, padx=8, pady=(0, 5))
        self._refrescar_escuchado_reciente_ui()

        liked_box = tk.LabelFrame(
            liked_tab, text=" ♥ Tus canciones favoritas ", font=("Tahoma", 8, "bold"),
            bg=self.bg_color, relief=tk.GROOVE, bd=2
        )
        liked_box.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        liked_frame = tk.Frame(liked_box, bg="#FFFFFF", relief=tk.SUNKEN, bd=2)
        liked_frame.pack(fill=tk.BOTH, expand=True, padx=7, pady=(6, 4))
        liked_scroll = tk.Scrollbar(liked_frame)
        liked_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.list_liked_tracks = tk.Listbox(
            liked_frame, font=("Tahoma", 8), bg="#FFFFFF",
            selectbackground="#316AC5", selectforeground="white",
            yscrollcommand=liked_scroll.set, relief=tk.FLAT, activestyle="none",
            highlightthickness=0, exportselection=False
        )
        self.list_liked_tracks.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        liked_scroll.config(command=self.list_liked_tracks.yview)
        self.list_liked_tracks.bind("<Double-Button-1>", self._reproducir_favorito_seleccionado)
        liked_actions = tk.Frame(liked_box, bg=self.bg_color)
        liked_actions.pack(fill=tk.X, padx=7, pady=(0, 6))
        tk.Button(
            liked_actions, text="▶ Reproducir", font=("Tahoma", 7), bg="#E0DFE3",
            relief=tk.RAISED, bd=2, cursor="hand2", command=self._reproducir_favorito_seleccionado
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        tk.Button(
            liked_actions, text="✕ Quitar favorito", font=("Tahoma", 7), bg="#F2D9D9",
            relief=tk.RAISED, bd=2, cursor="hand2", command=self._quitar_favorito_seleccionado
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        tk.Label(
            liked_box, text="Doble clic para reproducir · se sincroniza con tu cuenta",
            bg=self.bg_color, fg="#666666", font=("Tahoma", 7)
        ).pack(fill=tk.X, padx=8, pady=(0, 5))
        self._refrescar_favoritos_ui()

        stats_box = tk.LabelFrame(
            stats_tab, text=" 📊 Resumen de tu música ", font=("Tahoma", 8, "bold"),
            bg=self.bg_color, relief=tk.GROOVE, bd=2
        )
        stats_box.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.stats_labels = {}

        # Las tarjetas se distribuyen en 2 columnas para que cada dato tenga
        # espacio suficiente incluso con números grandes y textos largos.
        cards = tk.Frame(stats_box, bg=self.bg_color)
        cards.pack(fill=tk.X, padx=8, pady=(8, 5))
        cards.grid_columnconfigure(0, weight=1, uniform="stats_card")
        cards.grid_columnconfigure(1, weight=1, uniform="stats_card")

        card_defs = (
            ("unique", "Canciones", "diferentes"),
            ("plays", "Reproducciones", "totales"),
            ("liked", "Favoritas", "guardadas"),
            ("week", "Últimos 7 días", "escuchadas"),
            ("month", "Últimos 30 días", "escuchadas"),
        )
        for i, (key, title, subtitle) in enumerate(card_defs):
            row, col = divmod(i, 2)
            card = tk.Frame(cards, bg="#FFFFFF", relief=tk.GROOVE, bd=1, height=68)
            card.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)
            card.grid_propagate(False)
            value = tk.Label(
                card, text="0", bg="#FFFFFF", fg="#000000",
                font=("Tahoma", 15, "bold"), anchor="center"
            )
            value.pack(fill=tk.X, pady=(6, 0))
            tk.Label(
                card, text=f"{title} · {subtitle}", bg="#FFFFFF", fg="#555555",
                font=("Tahoma", 7, "bold"), wraplength=145, justify=tk.CENTER
            ).pack(fill=tk.X, padx=3, pady=(0, 4))
            self.stats_labels[key] = value

        # Detalles en ancho completo: así los nombres largos no quedan cortados.
        details = tk.Frame(stats_box, bg=self.bg_color)
        details.pack(fill=tk.X, padx=8, pady=(5, 4))

        song_box = tk.Frame(details, bg="#FFFFFF", relief=tk.GROOVE, bd=1, height=72)
        song_box.pack(fill=tk.X, pady=(0, 4))
        song_box.pack_propagate(False)
        tk.Label(
            song_box, text="🎵  MÁS REPRODUCIDA", bg="#FFFFFF", fg="#555555",
            font=("Tahoma", 7, "bold"), anchor="w"
        ).pack(fill=tk.X, padx=8, pady=(5, 1))
        self.stats_labels["top_song"] = tk.Label(
            song_box, text="—", bg="#FFFFFF", fg="#111111", font=("Tahoma", 8, "bold"),
            anchor="w", wraplength=300, justify=tk.LEFT
        )
        self.stats_labels["top_song"].pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        artist_box = tk.Frame(details, bg="#FFFFFF", relief=tk.GROOVE, bd=1, height=72)
        artist_box.pack(fill=tk.X)
        artist_box.pack_propagate(False)
        tk.Label(
            artist_box, text="🎤  ARTISTA MÁS ESCUCHADO", bg="#FFFFFF", fg="#555555",
            font=("Tahoma", 7, "bold"), anchor="w"
        ).pack(fill=tk.X, padx=8, pady=(5, 1))
        self.stats_labels["top_artist"] = tk.Label(
            artist_box, text="—", bg="#FFFFFF", fg="#111111", font=("Tahoma", 8, "bold"),
            anchor="w", wraplength=300, justify=tk.LEFT
        )
        self.stats_labels["top_artist"].pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        tk.Button(
            stats_box, text="🎁 Mi Wrapped (imagen para compartir)", font=("Tahoma", 8, "bold"),
            bg="#D6E4FF", relief=tk.RAISED, bd=2, cursor="hand2",
            command=lambda: self.menu_wrapped()
        ).pack(pady=(4, 8))
        self.actualizar_estadisticas_ui()

        queue_box = self.queue_box = tk.LabelFrame(
            library_tab, text=" Cola de reproducción ", font=("Tahoma", 8, "bold"),
            bg=self.bg_color, relief=tk.GROOVE, bd=2
        )
        queue_box.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        queue_mode_bar = tk.Frame(queue_box, bg=self.bg_color)
        queue_mode_bar.pack(fill=tk.X, padx=7, pady=(6, 0))
        self.queue_normal_btn = tk.Button(
            queue_mode_bar, text="Reproducción", font=("Tahoma", 7, "bold"),
            relief=tk.SUNKEN, bg="#C8E8C8", bd=2, cursor="hand2",
            command=lambda: self._elegir_cola("normal")
        )
        self.queue_normal_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        self.queue_playlist_btn = tk.Button(
            queue_mode_bar, text="Playlist", font=("Tahoma", 7, "bold"),
            relief=tk.RAISED, bg="#E0DFE3", bd=2, cursor="hand2",
            command=lambda: self._elegir_cola("playlist")
        )
        self.queue_playlist_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        self.queue_summary_var = tk.StringVar(value="0 canciones  •  Duración total: 0 s")
        tk.Label(
            queue_box, textvariable=self.queue_summary_var, bg=self.bg_color,
            fg="#333333", font=("Tahoma", 7), anchor=tk.W
        ).pack(fill=tk.X, padx=8, pady=(5, 0))

        queue_frame = tk.Frame(queue_box, bg="#FFFFFF", relief=tk.SUNKEN, bd=2)
        queue_frame.pack(fill=tk.BOTH, expand=True, padx=7, pady=(6, 4))
        queue_scroll = tk.Scrollbar(queue_frame)
        queue_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.list_queue = tk.Listbox(
            queue_frame, font=("Tahoma", 8), bg="#FFFFFF", height=6,
            selectmode=tk.EXTENDED,
            selectbackground="#316AC5", selectforeground="white",
            yscrollcommand=queue_scroll.set, relief=tk.FLAT, activestyle="none",
            highlightthickness=0, exportselection=False
        )
        self.list_queue.pack(fill=tk.BOTH, expand=True)
        queue_scroll.config(command=self.list_queue.yview)
        self.list_queue.bind("<Double-Button-1>", lambda e: self.reproducir_desde_cola())
        self.list_queue.bind("<Button-3>", self.menu_contextual_cola)
        self.list_queue.bind("<ButtonPress-1>", self._cola_arrastre_inicio, add="+")
        self.list_queue.bind("<B1-Motion>", self._cola_arrastre_mover, add="+")
        self.list_queue.bind("<ButtonRelease-1>", self._cola_arrastre_fin, add="+")

        queue_action_bar = tk.Frame(queue_box, bg=self.bg_color)
        queue_action_bar.pack(fill=tk.X, padx=7, pady=(0, 6))
        for text, cmd in (("▶ Reproducir", self.reproducir_desde_cola),
                          ("⏭ Siguiente", self.poner_seleccion_siguiente),
                          ("✕ Quitar", self.quitar_de_cola),
                          ("↑ Subir", lambda: self.mover_seleccion_cola(-1)),
                          ("↓ Bajar", lambda: self.mover_seleccion_cola(1)),
                          ("Limpiar", self.limpiar_cola)):
            tk.Button(queue_action_bar, text=text, font=("Tahoma", 7), relief=tk.RAISED,
                      bg="#E0DFE3", bd=2, cursor="hand2", command=cmd).pack(
                          side=tk.LEFT, fill=tk.X, expand=True, padx=1)

        self.status_var = tk.StringVar(value="Aplicación lista. Modo Invitado.")
        tk.Label(
            self.root, textvariable=self.status_var, bg="#D4D0C8",
            relief=tk.SUNKEN, bd=1, anchor=tk.W, font=("Tahoma", 8), padx=6, pady=2
        ).pack(side=tk.BOTTOM, fill=tk.X)


    def _on_mousewheel(self, event):
        w = self.root.winfo_containing(event.x_root, event.y_root)
        while w is not None:
            if w is self.sug_container:
                if getattr(event, "num", None) == 4:
                    delta = -1
                elif getattr(event, "num", None) == 5:
                    delta = 1
                else:
                    delta = -1 if event.delta > 0 else 1
                self.canvas_sug.yview_scroll(delta * 2, "units")
                return
            w = w.master


    def al_escribir_busqueda(self, event):
        if event.keysym in ("Return", "Escape", "Tab"):
            return
        if self._search_timer:
            self.root.after_cancel(self._search_timer)
        self._search_timer = self.root.after(350, self.obtener_sugerencias_canciones)


    def obtener_sugerencias_canciones(self):
        if self._search_timer:
            self.root.after_cancel(self._search_timer)
            self._search_timer = None

        query = self.search_entry.get().strip()
        if len(query) < 2:
            return

        self._search_token += 1
        token = self._search_token
        filtro = self.tipo_busqueda_var.get()
        self.status_var.set(f"Buscando '{query}'... ⏳")

        def task():
            try:
                canciones = self._mapear_canciones(self._buscar(query, filtro))
                if filtro == "videos":
                    for c in canciones:
                        c['es_clip'] = True
                        self._ids_clip.add(c['videoId'])
                self.ui(self.renderizar_sugerencias, token, canciones)
            except Exception as e:
                print(f"Error de búsqueda: {e}")
                self.ui(self._error_busqueda, token)

        self.pool_stream.submit(task)


    def _error_busqueda(self, token, msg="❌ Error en la búsqueda."):
        if token == self._search_token:
            self.status_var.set(msg)


    def renderizar_sugerencias(self, token, canciones):
        if token != self._search_token:
            return

        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self.canvas_sug.yview_moveto(0)

        if not canciones:
            self.status_var.set("No se encontraron resultados.")
            return

        self.status_var.set(f"{len(canciones)} resultados. Usa ♥ para guardar una canción.")
        for item in canciones:
            liked = any(x.get("videoId") == item.get("videoId") for x in self.cloud_data.get("liked", []))
            card = tk.Frame(self.scroll_frame, bg="#FFFFFF", relief=tk.RAISED, bd=1)
            card.pack(fill=tk.X, expand=True, padx=4, pady=3)

            img_container = tk.Frame(card, bg="#D4D0C8", width=58, height=58, relief=tk.SUNKEN, bd=1)
            img_container.pack(side=tk.LEFT, padx=5, pady=5)
            img_container.pack_propagate(False)
            img_box = tk.Label(img_container, text="♪", bg="#E8E8E8", fg="#555555", font=("Tahoma", 16, "bold"))
            img_box.pack(fill=tk.BOTH, expand=True)
            if item.get("coverUrl"):
                self.cargar_imagen_async(item["coverUrl"], 58, img_box)

            info = tk.Frame(card, bg="#FFFFFF")
            titulo = str(item.get("title", "Desconocido") or "Desconocido")
            if item.get("es_clip"):
                titulo = "🎬 " + titulo
            artista = str(item.get("artist", "") or "")
            if len(titulo) > 32:
                titulo = titulo[:31].rstrip() + "…"
            if len(artista) > 28:
                artista = artista[:27].rstrip() + "…"
            info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=5)
            tk.Label(info, text=titulo, width=30, bg="#FFFFFF", fg="#111111",
                     font=("Tahoma", 9, "bold"), anchor="w", justify=tk.LEFT).pack(fill=tk.X)
            tk.Label(info, text=artista, width=26, bg="#FFFFFF", fg="#666666",
                     font=("Tahoma", 8), anchor="w", justify=tk.LEFT).pack(fill=tk.X, pady=(2, 0))

            actions = tk.Frame(card, bg="#FFFFFF")
            actions.pack(side=tk.RIGHT, padx=5, pady=4)
            # Acciones directas: reproducir, cola, Me gusta y playlist.
            tk.Button(actions, text="▶", width=3, font=("Tahoma", 10, "bold"), bg="#D6E4FF",
                      relief=tk.RAISED, bd=2, cursor="hand2",
                      command=lambda can=item: self.reproducir_directo(can)).pack(side=tk.LEFT, padx=1)
            if not item.get("es_clip") and not str(item.get("videoId", "")).startswith("file:"):
                tk.Button(actions, text="🎬", width=3, font=("Tahoma", 9, "bold"), bg="#F3DFC8",
                          relief=tk.RAISED, bd=2, cursor="hand2",
                          command=lambda can=item: self.reproducir_clip_directo(can)).pack(side=tk.LEFT, padx=1)
            tk.Button(actions, text="+", width=3, font=("Tahoma", 10, "bold"), bg="#E0DFE3",
                      relief=tk.RAISED, bd=2, cursor="hand2",
                      command=lambda can=item: self.agregar_cancion_a_cola(can)).pack(side=tk.LEFT, padx=1)
            heart = tk.Button(actions, text="♥" if liked else "♡", width=3,
                               font=("Tahoma", 10, "bold"), bg="#FFDADA" if liked else "#E0DFE3",
                               activebackground="#FFC0C0", relief=tk.RAISED, bd=2, cursor="hand2")
            heart.config(command=lambda can=item, b=heart: (self._alternar_me_gusta_desde_resultado(can, b),
                                                            self._actualizar_boton_like()))
            heart.pack(side=tk.LEFT, padx=1)
            tk.Button(actions, text="📁", width=3, font=("Tahoma", 9), bg="#E0DFE3",
                      relief=tk.RAISED, bd=2, cursor="hand2",
                      command=lambda can=item, b=actions: self._menu_guardar_en_playlist(can, b)).pack(side=tk.LEFT, padx=1)
            for w in (card, info, img_container):
                w.bind("<Double-Button-1>", lambda e, can=item: self.reproducir_directo(can))
        self.tematizar(self.scroll_frame)


    def cargar_imagen_async(self, url, size, label, vigente=None):
        if url and url.startswith("//"):          # YouTube a veces da URLs sin protocolo
            url = "https:" + url
        key = (url, size)
        cached = self.image_cache.get(key)
        if cached is not None:
            self.image_cache.move_to_end(key)
            label.config(image=cached, text="")
            label.image = cached
            return

        def descargar():
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=8) as r:
                    raw = r.read()
                pil = Image.open(io.BytesIO(raw)).convert("RGB").resize((size, size), RESAMPLE)
            except Exception:
                return
            self.ui(self._mostrar_imagen, key, pil, label, vigente)

        self.pool_img.submit(descargar)


    def _mostrar_imagen(self, key, pil, label, vigente):
        if vigente is not None and not vigente():
            return
        if not label.winfo_exists():
            return
        photo = ImageTk.PhotoImage(pil)
        self.image_cache[key] = photo
        while len(self.image_cache) > MAX_IMG_CACHE:
            self.image_cache.popitem(last=False)
        label.config(image=photo, text="")
        label.image = photo


    def _reset_caratula(self):
        self._cover_url = None
        self.cover_label.config(image='', text="NO\nCOVER")
        self.cover_label.image = None


    def cargar_caratula_principal(self, url):
        if not url:
            self._reset_caratula()
            return
        self._cover_url = url
        self.cargar_imagen_async(url, 89, self.cover_label, vigente=lambda: self._cover_url == url)


    def cambiar_volumen(self, val):
        v = int(float(val))
        if getattr(self, "_fundido_job", None) is None:      # durante el fundido manda el temporizador
            self.player.audio_set_volume(v)
        if hasattr(self, "vol_label"):
            self.vol_label.config(text=f"{v}%")
        if self.prefs.get("muted") and v > 0 and getattr(self, "_vol_ready", False):
            self.alternar_silencio(forzar=False)            # mover el volumen quita el silencio
        if self.prefs.get("volume") != v:
            self.prefs["volume"] = v
            if getattr(self, "_vol_ready", False):
                self._guardar_prefs()
        self._vol_ready = True
        mini = getattr(self, "mini", None)
        if mini is not None and mini.visible:
            try:
                if abs(float(mini.vol.get()) - v) > 0.5:
                    mini.vol.set(v)
            except Exception:
                pass


    def on_slider_press(self, event):
        self.user_dragging = True


    def on_seek(self, event):
        import vlc
        if self.player.get_state() in (vlc.State.Playing, vlc.State.Paused):
            length = self.player.get_length()
            if length > 0:
                self.player.set_time(int(float(self.time_slider.get()) / 100.0 * length))
                self.social.al_seek()
                self.root.after(300, lambda: self._discord(self.player.is_playing()))
        self.user_dragging = False


    def _construir_eq(self, event=None):
        c = self.canvas_eq
        w, h = c.winfo_width(), c.winfo_height()
        if w <= 1 or h <= 1 or (w, h) == self.eq_dim:
            return
        self.eq_dim = (w, h)
        c.delete("all")

        paso = self.eq_step
        self.eq_segs = max(1, (h - 6) // paso)
        bar_w = max(2, w // self.num_bars - 2)

        self.eq_items, self.eq_peak_items, self.eq_x = [], [], []
        for i in range(self.num_bars):
            x0 = i * (bar_w + 2) + 4
            x1 = x0 + bar_w
            self.eq_x.append((x0, x1))
            col = []
            for s in range(self.eq_segs):
                y1 = h - 3 - s * paso
                pct = s / self.eq_segs
                color = (self.c("#00FF66", "fg") if pct < 0.6
                         else ("#FFFF00" if pct < 0.85 else "#FF0055"))
                col.append(c.create_rectangle(x0, y1 - 3, x1, y1, fill=color, outline="", state="hidden"))
            self.eq_items.append(col)
            self.eq_peak_items.append(c.create_rectangle(x0, 0, x1, 0, fill="#FFFFFF", outline="", state="hidden"))

        self.eq_visible = [0] * self.num_bars
        self.eq_peak_vis = [0] * self.num_bars


    def _pintar_barra(self, i, n, peak):
        c = self.canvas_eq
        old = self.eq_visible[i]
        col = self.eq_items[i]
        if n > old:
            for s in range(old, n):
                c.itemconfigure(col[s], state="normal")
        elif n < old:
            for s in range(n, old):
                c.itemconfigure(col[s], state="hidden")
        self.eq_visible[i] = n

        if peak != self.eq_peak_vis[i]:
            item = self.eq_peak_items[i]
            if peak <= 0:
                c.itemconfigure(item, state="hidden")
            else:
                x0, x1 = self.eq_x[i]
                y1 = self.eq_dim[1] - 3 - min(peak, self.eq_segs - 1) * self.eq_step
                c.coords(item, x0, y1 - 2, x1, y1)
                c.itemconfigure(item, state="normal")
            self.eq_peak_vis[i] = peak


    def animar_ecualizador(self):
        """Barras del panel con el espectro del analizador (real o simulado)."""
        import time as _t
        import vlc
        playing = self.player.get_state() == vlc.State.Playing
        activo = playing
        ahora = _t.time()
        dt = min(0.2, ahora - getattr(self, "_eq_t", ahora)) or 0.05
        self._eq_t = ahora
        modo = self.prefs.get("visualizer", "real")
        an = getattr(self, "analizador", None)
        niveles = None
        if modo != "off" and an is not None:
            try:
                if not (self.soundscope.abierto and self.soundscope.analizador is an):
                    an.actualizar(playing, dt)
                bandas = an.bands
                n = len(bandas)
                niveles = [float(bandas[min(n - 1, int(i * n / self.num_bars))]) for i in range(self.num_bars)]
            except Exception as e:
                print(f"Visualizador: {e}")
                niveles = None

        if self.eq_items:
            segs = self.eq_segs
            for i in range(self.num_bars):
                if niveles is not None and playing:
                    self.eq_levels[i] = niveles[i] * segs
                else:
                    self.eq_levels[i] = max(0.0, self.eq_levels[i] - 0.7)

                n = min(segs, int(round(self.eq_levels[i])))
                if n >= self.eq_peaks[i]:
                    self.eq_peaks[i] = float(n)
                else:
                    self.eq_peaks[i] = max(float(n), self.eq_peaks[i] - 0.25)

                if n > 0 or self.eq_peaks[i] > 0:
                    activo = True
                self._pintar_barra(i, n, int(self.eq_peaks[i]))

        visible = self.root.state() not in ("withdrawn", "iconic")   # "zoomed" = maximizada
        mini = getattr(self, "mini", None)
        visible = visible or bool(mini is not None and mini.visible)
        self.root.after(40 if (activo and visible) else 250, self.animar_ecualizador)


    def actualizar_reproductor(self):
        import vlc
        state = self.player.get_state()

        if getattr(self, "_xf", None) is not None and state in (vlc.State.Ended, vlc.State.Stopped):
            self._terminar_fundido()                # la anterior acabó: la nueva ya está sonando
            state = self.player.get_state()
        elif not self._cargando:
            if state == vlc.State.Ended:
                self._al_terminar_cancion()
            elif state == vlc.State.Error:
                self.player.stop()
                if self._reintentos_vlc < 2 and 0 <= self.current_index < len(self.queue):
                    self._reintentos_vlc += 1
                    self._stream_cache.pop(self.queue[self.current_index]['videoId'], None)
                    self._stream_cache_video.clear()
                    self.status_var.set(f"Stream caído, reintentando ({self._reintentos_vlc}/2)...")
                    self.cargar_y_reproducir_actual()
                elif self._reproduciendo_video and 0 <= self.current_index < len(self.queue):
                    self._video_fallido.add(self.queue[self.current_index]['videoId'])
                    self._reintentos_vlc = 0
                    self.status_var.set("El videoclip falló; paso a solo audio.")
                    self.cargar_y_reproducir_actual()
                else:
                    self.lcd_title.config(text="❌ Error de reproducción")
                    self.status_var.set("VLC no pudo reproducir el stream.")

        if state == vlc.State.Playing:
            self._reintentos_vlc = 0
        self._tick_escucha(state == vlc.State.Playing)

        if state == vlc.State.Playing and not self.user_dragging:
            time_ms = self.player.get_time()
            length_ms = self.player.get_length()
            if length_ms > 0 and time_ms >= 0:
                self.time_slider.set(time_ms / length_ms * 100)
                texto = f"[{formato_tiempo(time_ms)} / {formato_tiempo(length_ms)}]"
                if texto != getattr(self, "_lcd_time_txt", None):     # solo si cambia
                    self._lcd_time_txt = texto
                    self.lcd_time.config(text=texto)
                clave = (self.current_index, self._queue_mode)
                if getattr(self, "_duracion_apuntada", None) != clave:
                    self._duracion_apuntada = clave
                    self._apuntar_duracion_vlc(length_ms)
                self._vigilar_fundido(time_ms, length_ms)

        self.root.after(100, self.actualizar_reproductor)


