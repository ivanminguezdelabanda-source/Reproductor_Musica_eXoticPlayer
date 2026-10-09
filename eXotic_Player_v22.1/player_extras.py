"""Funciones nuevas de eXotic Player v20.

- Preferencias de este ordenador (volumen, tema, visualizador, sonidos, avisos).
- Repetir (no / toda la cola / una canción) y mezclar la cola.
- Temporizador para dormir (con fundido de volumen).
- Silenciar, ♥ a la canción actual, copiar enlace, abrir en YouTube Music.
- Seguir por donde ibas al volver a abrir la app.
- Atajos de teclado.
- Importar playlists de YouTube / YouTube Music.
- Ecualizador de 10 bandas guardado en tu cuenta.
- Temas, sonidos retro y avisos de "Ahora suena".
"""
import json
import os
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, simpledialog, ttk

import app_paths
from integrations import BANDAS_TXT, normalizar_eq
from playlist_logic import extraer_id_playlist, mezclar_desde, nombre_unico
from themes import TEMA_POR_DEFECTO

PREFS_FILE = os.path.join(app_paths.DATA_DIR, "exotic_prefs.json")
PREFS_DEFECTO = {
    "volume": 80,
    "muted": False,
    "theme": TEMA_POR_DEFECTO,
    "visualizer": "real",        # real | simulado | off
    "sounds": True,
    "notify": False,             # aviso de "Ahora suena" cuando la app está en la bandeja
    "crossfade": 0,              # segundos de fundido entre canciones (0 = no)
    "splash": True,              # animación al abrir el programa
    "audio_mode": "normal",      # normal | slowed | muy_slowed | speed_up | nightcore
    "normalize": True,           # igualar el volumen entre canciones
    "hotkeys_on": True,          # atajos globales (aunque la app esté en segundo plano)
    "hotkeys": {},               # {acción: "<ctrl>+<alt>+<right>"}; vacío = los de por defecto
    "search_history": [],        # últimas búsquedas (solo en este ordenador)
    "ytm_auth": False,           # cuenta de YouTube Music conectada (cabeceras en ytm_browser.json)
    "update_repo": "",           # usuario/repositorio de GitHub donde se publican las versiones
    "update_skip": "",           # versión que el usuario decidió no instalar
    "update_last": 0,            # última comprobación (una vez al día)
    "share_activity": True,      # que tus amigos vean lo que escuchas
    "lastfm_key": None,
    "lastfm_secret": None,
    "lastfm_user": None,
    "lastfm_sk": None,           # session key (la contraseña no se guarda)
    "lastfm_pend": [],           # scrobbles que no se pudieron enviar (sin red)
}
REPETIR = ("off", "all", "one")
REPETIR_TXT = {"off": "🔁 No", "all": "🔁 Todo", "one": "🔂 Una"}
TEMPORIZADOR_MIN = (15, 30, 45, 60, 90, 120)
VISUALIZADOR_TXT = {"real": "Real (audio del sistema)", "simulado": "Simulado", "off": "Apagado"}


def _fmt_mmss(segundos):
    segundos = max(0, int(segundos))
    h, r = divmod(segundos, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class PlayerExtrasMixin:
    # ------------------------------------------------------------------
    # Preferencias locales (no se suben a la nube: son de este ordenador)
    # ------------------------------------------------------------------
    def _cargar_prefs(self):
        prefs = dict(PREFS_DEFECTO)
        try:
            with open(PREFS_FILE, encoding="utf-8") as f:
                datos = json.load(f)
            if isinstance(datos, dict):
                prefs.update({k: v for k, v in datos.items() if k in PREFS_DEFECTO})
        except (OSError, ValueError):
            pass
        try:
            prefs["volume"] = max(0, min(100, int(prefs["volume"])))
        except (TypeError, ValueError):
            prefs["volume"] = 80
        if prefs["visualizer"] not in VISUALIZADOR_TXT:
            prefs["visualizer"] = "real"
        self.prefs = prefs
        self._prefs_job = None
        return prefs

    def _guardar_prefs(self, inmediato=False):
        def escribir():
            self._prefs_job = None
            try:
                tmp = PREFS_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.prefs, f, ensure_ascii=False, indent=1)
                os.replace(tmp, PREFS_FILE)
            except OSError as e:
                print(f"No se pudieron guardar las preferencias: {e}")

        if getattr(self, "_prefs_job", None) is not None:
            try:
                self.root.after_cancel(self._prefs_job)
            except tk.TclError:
                pass
            self._prefs_job = None
        if inmediato:
            escribir()
        else:
            self._prefs_job = self.root.after(800, escribir)

    def _ajustes(self):
        st = self.cloud_data.setdefault("settings", {})
        if not isinstance(st, dict):
            st = self.cloud_data["settings"] = {}
        return st

    def c(self, base, tipo="bg"):
        """Color del tema actual para un color base (Luna). Úsalo en .config(bg=...)."""
        tema = getattr(self, "tema", None)
        return tema.c(base, tipo) if tema is not None else base

    def _en_jam(self):
        return bool(getattr(getattr(self, "social", None), "en_jam", False))

    # ------------------------------------------------------------------
    # Temas y sonidos
    # ------------------------------------------------------------------
    def cambiar_tema(self, nombre):
        ventanas = [self.root]
        for attr in ("_config_win", "_eq_win"):
            ventanas.append(getattr(self, attr, None))
        for obj in (getattr(self, "mini", None), getattr(self, "letra", None)):
            ventanas.append(getattr(obj, "win", None) or getattr(obj, "top", None))
        dlg = getattr(getattr(self, "social", None), "dialog", None)
        ventanas.append(dlg)
        self.tema.cambiar(nombre, [v for v in ventanas if v is not None], self.style)
        self.prefs["theme"] = self.tema.nombre
        self._guardar_prefs()
        self._refrescar_lista_playlist()           # filas alternas con el color del tema
        self._actualizar_botones_modo_cola()
        self._actualizar_boton_aleatorio_playlist()
        self._actualizar_boton_repetir()
        self._actualizar_boton_like()
        self._actualizar_boton_fx()
        self._actualizar_boton_temporizador()
        self._actualizar_boton_video()
        self._actualizar_boton_auth()
        self.social._actualizar_boton()
        self.actualizar_vista_cola()                  # fila de la canción actual
        self.eq_dim = (0, 0)                          # barras del visualizador con el color nuevo
        self._construir_eq()
        self.letra.colorear()
        var = getattr(self, "config_tema_var", None)
        if var is not None:
            var.set(self.tema.nombre)
        self.status_var.set(f"🎨 Tema: {self.tema.nombre}")

    def tematizar(self, widget):
        """Aplica el tema actual a un widget recién creado (con colores base)."""
        tema = getattr(self, "tema", None)
        if tema is not None and widget is not None:
            tema.aplicar_arbol(widget)

    def sonar(self, nombre):
        s = getattr(self, "sonidos", None)
        if s is not None:
            s.tocar(nombre)

    # ------------------------------------------------------------------
    # Repetir / mezclar
    # ------------------------------------------------------------------
    @property
    def modo_repetir(self):
        modo = self._ajustes().get("repeat", "off")
        return modo if modo in REPETIR else "off"

    def alternar_repetir(self):
        if self._en_jam():
            self.status_var.set("En una jam no se puede usar Repetir.")
            return
        actual = REPETIR.index(self.modo_repetir)
        nuevo = REPETIR[(actual + 1) % len(REPETIR)]
        self._ajustes()["repeat"] = nuevo
        self._actualizar_boton_repetir()
        self._guardar_si_corresponde()
        self.status_var.set({"off": "Repetir desactivado.",
                             "all": "🔁 Repetir toda la cola.",
                             "one": "🔂 Repetir esta canción."}[nuevo])

    def _actualizar_boton_repetir(self):
        b = getattr(self, "repeat_btn", None)
        if b is None:
            return
        modo = self.modo_repetir
        b.config(text=REPETIR_TXT[modo], relief=tk.SUNKEN if modo != "off" else tk.RAISED,
                 bg=self.c("#C8E8C8" if modo != "off" else "#E0DFE3"))

    def mezclar_cola(self):
        if self._en_jam():
            self.status_var.set("La cola de una jam se gestiona entre todos.")
            return
        if len(self.queue) - (self.current_index + 1) < 2:
            self.status_var.set("No hay suficientes canciones por delante para mezclar.")
            return
        self._apuntar_deshacer("mezclar")
        n = mezclar_desde(self.queue, self.current_index)
        if self._queue_mode == "playlist" and self._playlist_shuffle:
            self._playlist_shuffle_order = []
        self.actualizar_vista_cola()
        if self._queue_mode == "normal":
            self._guardar_si_corresponde()
        self.status_var.set(f"🔀 {n} canciones mezcladas después de la actual.")

    def _al_terminar_cancion(self):
        """Lo llama el bucle del reproductor cuando VLC llega al final de la pista."""
        if getattr(self, "_sleep_fin_cancion", False):
            self.cancelar_temporizador(silencioso=True)
            self.detener_cancion()
            self.status_var.set("🌙 Temporizador: música parada al terminar la canción. ¡Buenas noches!")
            return
        if self.modo_repetir == "one" and not self._en_jam() and 0 <= self.current_index < len(self.queue):
            self.cargar_y_reproducir_actual()
            return
        self.siguiente_cancion()

    # ------------------------------------------------------------------
    # Temporizador para dormir
    # ------------------------------------------------------------------
    def menu_temporizador(self, widget=None):
        menu = tk.Menu(self.root, tearoff=0, font=("Tahoma", 9))
        for m in TEMPORIZADOR_MIN:
            texto = f"{m} minutos" if m < 60 else (f"{m // 60} hora" + ("s" if m >= 120 else "")
                                                  + (" y media" if m % 60 else ""))
            menu.add_command(label=f"🌙 {texto}", command=lambda m=m: self.iniciar_temporizador(m))
        menu.add_command(label="🌙 Al terminar esta canción", command=self.temporizador_fin_cancion)
        if self._temporizador_activo():
            menu.add_separator()
            menu.add_command(label="✕ Cancelar temporizador", command=self.cancelar_temporizador)
        w = widget or getattr(self, "sleep_btn", None)
        try:
            if w is not None:
                menu.tk_popup(w.winfo_rootx(), w.winfo_rooty() + w.winfo_height())
            else:
                menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def _temporizador_activo(self):
        return bool(getattr(self, "_sleep_fin", None) or getattr(self, "_sleep_fin_cancion", False))

    def iniciar_temporizador(self, minutos):
        self.cancelar_temporizador(silencioso=True)
        self._sleep_fin = time.time() + minutos * 60
        self._sleep_fin_cancion = False
        self.status_var.set(f"🌙 La música se parará dentro de {minutos} minutos.")
        self._tick_temporizador()

    def temporizador_fin_cancion(self):
        self.cancelar_temporizador(silencioso=True)
        self._sleep_fin_cancion = True
        self._actualizar_boton_temporizador()
        self.status_var.set("🌙 La música se parará al terminar esta canción.")

    def cancelar_temporizador(self, silencioso=False):
        job = getattr(self, "_sleep_job", None)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        self._sleep_job = None
        self._sleep_fin = None
        self._sleep_fin_cancion = False
        if getattr(self, "_fundido_job", None) is not None:
            try:
                self.root.after_cancel(self._fundido_job)
            except tk.TclError:
                pass
            self._fundido_job = None
            self.player.audio_set_volume(int(float(self.vol_slider.get())))
        self._actualizar_boton_temporizador()
        if not silencioso:
            self.status_var.set("Temporizador cancelado.")

    def _actualizar_boton_temporizador(self):
        b = getattr(self, "sleep_btn", None)
        if b is None:
            return
        if getattr(self, "_sleep_fin", None):
            b.config(text=f"🌙 {_fmt_mmss(self._sleep_fin - time.time())}", relief=tk.SUNKEN,
                     bg=self.c("#C8E8C8"))
        elif getattr(self, "_sleep_fin_cancion", False):
            b.config(text="🌙 Fin canción", relief=tk.SUNKEN, bg=self.c("#C8E8C8"))
        else:
            b.config(text="🌙", relief=tk.RAISED, bg=self.c("#E0DFE3"))

    def _tick_temporizador(self):
        self._sleep_job = None
        fin = getattr(self, "_sleep_fin", None)
        if not fin:
            self._actualizar_boton_temporizador()
            return
        if time.time() >= fin:
            self._sleep_fin = None
            self._actualizar_boton_temporizador()
            self._fundido_y_parar()
            return
        self._actualizar_boton_temporizador()
        self._sleep_job = self.root.after(1000, self._tick_temporizador)

    def _fundido_y_parar(self, paso=0, pasos=16):
        """Baja el volumen poco a poco (~8 s) y pausa. En una jam solo silencia tu altavoz."""
        self._fundido_job = None
        objetivo = int(float(self.vol_slider.get()))
        if paso < pasos:
            self.player.audio_set_volume(int(objetivo * (1 - (paso + 1) / pasos)))
            self._fundido_job = self.root.after(500, lambda: self._fundido_y_parar(paso + 1, pasos))
            return
        if self._en_jam():
            self.alternar_silencio(forzar=True)
        else:
            self.pausar_cancion()
        self.player.audio_set_volume(objetivo)
        self.status_var.set("🌙 Temporizador: música parada. ¡Buenas noches!")

    # ------------------------------------------------------------------
    # Volumen / silencio
    # ------------------------------------------------------------------
    def alternar_silencio(self, forzar=None):
        muted = (not self.prefs.get("muted")) if forzar is None else bool(forzar)
        self.prefs["muted"] = muted
        try:
            self.player.audio_set_mute(muted)
        except Exception:
            pass
        if not muted:
            self.player.audio_set_volume(int(float(self.vol_slider.get())))
        b = getattr(self, "mute_btn", None)
        if b is not None:
            b.config(text="🔇" if muted else "🔊")
        self._guardar_prefs()
        self.status_var.set("🔇 Silenciado." if muted else "🔊 Sonido activado.")

    def subir_volumen(self, delta):
        v = max(0, min(100, float(self.vol_slider.get()) + delta))
        self.vol_slider.set(v)
        self.cambiar_volumen(v)
        self.status_var.set(f"🔊 Volumen: {int(v)}%")

    # ------------------------------------------------------------------
    # ♥ de la canción actual, enlaces
    # ------------------------------------------------------------------
    def _cancion_actual(self):
        if 0 <= self.current_index < len(self.queue):
            return self.queue[self.current_index]
        return None

    def _es_favorita(self, video_id):
        return any(x.get("videoId") == video_id for x in self.cloud_data.get("liked", []))

    def alternar_like_actual(self):
        c = self._cancion_actual()
        if c is None:
            self.status_var.set("No suena ninguna canción.")
            return
        self._alternar_me_gusta_desde_resultado(c)
        self._actualizar_boton_like()

    def _actualizar_boton_like(self):
        b = getattr(self, "like_btn", None)
        if b is None:
            return
        c = self._cancion_actual()
        liked = bool(c) and self._es_favorita(c.get("videoId"))
        b.config(text="♥" if liked else "♡", fg=self.c("#C0003A" if liked else "#333333", "fg"),
                 bg=self.c("#FFDADA" if liked else "#E0DFE3"))

    @staticmethod
    def enlace_cancion(cancion):
        return f"https://music.youtube.com/watch?v={cancion['videoId']}"

    def copiar_enlace(self, cancion=None):
        cancion = cancion or self._cancion_actual()
        if not cancion:
            return
        import local_files
        ruta = local_files.ruta_de(cancion.get("videoId"))
        self.root.clipboard_clear()
        self.root.clipboard_append(ruta or self.enlace_cancion(cancion))
        self.status_var.set(f"🔗 {'Ruta' if ruta else 'Enlace'} copiad{'a' if ruta else 'o'}: {cancion.get('title', '')}")

    def abrir_en_navegador(self, cancion=None):
        cancion = cancion or self._cancion_actual()
        if not cancion:
            return
        import local_files
        ruta = local_files.ruta_de(cancion.get("videoId"))
        if ruta:                                   # canción del ordenador: abre su carpeta
            try:
                os.startfile(os.path.dirname(ruta))
            except Exception as e:
                self.status_var.set(f"No se pudo abrir la carpeta: {e}")
            return
        webbrowser.open(self.enlace_cancion(cancion))

    def menu_lcd(self, event):
        c = self._cancion_actual()
        menu = tk.Menu(self.root, tearoff=0, font=("Tahoma", 9))
        if c:
            liked = self._es_favorita(c.get("videoId"))
            menu.add_command(label=f"{c.get('title', '')[:40]}", state=tk.DISABLED)
            menu.add_separator()
            menu.add_command(label="♡ Quitar de Me gusta" if liked else "♥ Me gusta",
                             command=self.alternar_like_actual)
            menu.add_command(label="📝 Ver letra", command=self.letra.abrir)
            menu.add_command(label="🔗 Copiar enlace", command=self.copiar_enlace)
            menu.add_command(label="📂 Abrir carpeta del archivo" if str(c.get("videoId", "")).startswith("file:")
                             else "🌐 Abrir en YouTube Music", command=self.abrir_en_navegador)
            menu.add_separator()
        menu.add_command(label="🌀 Soundscope (F11)", command=self.soundscope.alternar)
        menu.add_command(label="🎵 Mini modo", command=self.mostrar_mini)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ------------------------------------------------------------------
    # Seguir por donde ibas
    # ------------------------------------------------------------------
    def _guardar_punto_reanudar(self):
        st = self._ajustes()
        try:
            import vlc
            estado = self.player.get_state()
            if (self._queue_mode == "normal" and 0 <= self.current_index < len(self.queue_normal)
                    and estado in (vlc.State.Playing, vlc.State.Paused)):
                c = self.queue_normal[self.current_index]
                st["resume"] = {"videoId": c["videoId"], "index": self.current_index,
                                "ms": max(0, int(self.player.get_time()))}
            elif estado in (vlc.State.Stopped, vlc.State.NothingSpecial, vlc.State.Ended):
                st.pop("resume", None)
        except Exception as e:
            print(f"No se pudo guardar el punto de reanudación: {e}")

    def _preparar_reanudar(self):
        self._reanudar_pendiente = None
        r = self._ajustes().get("resume")
        if not isinstance(r, dict) or self._queue_mode != "normal":
            return
        try:
            idx, ms = int(r.get("index", -1)), int(r.get("ms", 0))
        except (TypeError, ValueError):
            return
        if not (0 <= idx < len(self.queue_normal)) or self.queue_normal[idx].get("videoId") != r.get("videoId"):
            return
        self.current_index = idx
        self._reanudar_pendiente = (r["videoId"], ms)
        c = self.queue_normal[idx]
        if hasattr(self, "lcd_title"):
            self.lcd_title.config(text=f"⏯ Pulsa ▶ para seguir: {c['title']} ({_fmt_mmss(ms / 1000)})")
        self.actualizar_vista_cola()

    # ------------------------------------------------------------------
    # Aviso "Ahora suena"
    # ------------------------------------------------------------------
    def _notificar_cancion(self, cancion):
        if not self.prefs.get("notify"):
            return
        tray = getattr(self, "tray", None)
        if tray is None or not tray.disponible:
            return
        try:
            if self.root.state() not in ("withdrawn", "iconic") and self.root.winfo_viewable():
                return                    # la ventana está a la vista: no molestamos
            tray.icon.notify(f"{cancion.get('title', '')}\n{cancion.get('artist', '')}", "♫ Ahora suena")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Atajos de teclado
    # ------------------------------------------------------------------
    ATAJOS = (
        ("Espacio", "Reproducir / pausar"),
        ("Ctrl + → / ←", "Siguiente / anterior"),
        ("Ctrl + ↑ / ↓", "Subir / bajar volumen"),
        ("Ctrl + M", "Silenciar"),
        ("Ctrl + L", "♥ Me gusta a la canción actual"),
        ("Ctrl + R", "Cambiar modo Repetir"),
        ("Ctrl + F", "Ir al buscador"),
        ("Ctrl + T", "Ver letra"),
        ("Ctrl + E", "Ecualizador"),
        ("Ctrl + Z", "Deshacer el último cambio en la cola"),
        ("F11", "Soundscope a pantalla completa"),
        ("F1", "Esta ayuda"),
        ("Teclas multimedia", "Funcionan aunque la app esté en segundo plano"),
    )

    def _instalar_atajos(self):
        r = self.root

        texto = (tk.Entry, tk.Text, tk.Spinbox, ttk.Entry, ttk.Combobox)

        def guardia(fn, tambien_botones=False):
            """No roba la tecla si estás escribiendo (ni, para Espacio, si hay un botón enfocado)."""
            tipos = texto + ((tk.Button, tk.Checkbutton, tk.Radiobutton) if tambien_botones else ())

            def handler(event):
                w = event.widget
                if isinstance(w, tipos):
                    return None
                try:
                    if w.winfo_toplevel() is not r:
                        return None
                except Exception:
                    return None
                fn()
                return "break"
            return handler

        r.bind("<space>", guardia(self.toggle_play, tambien_botones=True))
        r.bind("<Control-Right>", guardia(self.siguiente_cancion))
        r.bind("<Control-Left>", guardia(self.anterior_cancion))
        r.bind("<Control-Up>", guardia(lambda: self.subir_volumen(5)))
        r.bind("<Control-Down>", guardia(lambda: self.subir_volumen(-5)))
        for k in ("m", "M"):
            r.bind(f"<Control-{k}>", lambda e: self.alternar_silencio())
        for k in ("l", "L"):
            r.bind(f"<Control-{k}>", lambda e: self.alternar_like_actual())
        for k in ("r", "R"):
            r.bind(f"<Control-{k}>", lambda e: self.alternar_repetir())
        for k in ("f", "F"):
            r.bind(f"<Control-{k}>", lambda e: self._ir_al_buscador())
        for k in ("t", "T"):
            r.bind(f"<Control-{k}>", lambda e: self.letra.alternar())
        for k in ("e", "E"):
            r.bind(f"<Control-{k}>", lambda e: self.abrir_ventana_ecualizador())
        for k in ("z", "Z"):
            r.bind(f"<Control-{k}>", guardia(self.deshacer_cola))
        r.bind("<F1>", lambda e: self.mostrar_atajos())

    def _ir_al_buscador(self):
        self.search_entry.focus_set()
        self.search_entry.select_range(0, tk.END)
        return "break"

    # ------------------------------------------------------------------
    # Atajos globales y arranque con Windows
    # ------------------------------------------------------------------
    def _iniciar_atajos_globales(self):
        import hotkeys
        if getattr(self, "atajos_globales", None) is None:
            acciones = {
                "play_pausa": lambda: self.ui(self.toggle_play),
                "siguiente": lambda: self.ui(self.siguiente_cancion),
                "anterior": lambda: self.ui(self.anterior_cancion),
                "subir": lambda: self.ui(self.subir_volumen, 5),
                "bajar": lambda: self.ui(self.subir_volumen, -5),
                "like": lambda: self.ui(self.alternar_like_actual),
                "mostrar": lambda: self.ui(self.alternar_principal),
            }
            self.atajos_globales = hotkeys.AtajosGlobales(acciones)
        if self.prefs.get("hotkeys_on", True):
            self.atajos_globales.iniciar(hotkeys.normalizar(self.prefs.get("hotkeys")))
        else:
            self.atajos_globales.detener()

    def configurar_atajos_globales(self):
        import hotkeys
        parent = getattr(self, "_config_win", None) or self.root
        win = tk.Toplevel(parent)
        win.title("Atajos globales — eXotic Player")
        win.configure(bg=self.bg_color)
        win.resizable(False, False)
        win.transient(parent)
        tk.Label(win, text="Funcionan aunque estés en otro programa o eXotic esté en la bandeja.\n"
                           "Formato: <ctrl>+<alt>+<right>, <ctrl>+<shift>+p… Déjalo vacío para no usarlo.",
                 bg=self.bg_color, fg="#555555", font=("Tahoma", 8), justify=tk.LEFT).pack(padx=12, pady=(10, 6), anchor="w")
        actuales = hotkeys.normalizar(self.prefs.get("hotkeys"))
        tabla = tk.Frame(win, bg=self.bg_color)
        tabla.pack(padx=12, fill=tk.X)
        entradas = {}
        for i, (clave, nombre, _) in enumerate(hotkeys.ACCIONES):
            tk.Label(tabla, text=nombre, bg=self.bg_color, font=("Tahoma", 8), anchor="w", width=24).grid(row=i, column=0, sticky="w", pady=2)
            e = tk.Entry(tabla, width=26, font=("Consolas", 9), relief=tk.SUNKEN, bd=2)
            e.insert(0, actuales.get(clave, ""))
            e.grid(row=i, column=1, pady=2, padx=(6, 0))
            entradas[clave] = e
        aviso = tk.Label(win, text="", bg=self.bg_color, fg="#A00000", font=("Tahoma", 8))
        aviso.pack(padx=12, anchor="w")

        def guardar():
            nuevos = {}
            for clave, e in entradas.items():
                v = e.get().strip().lower()
                if v and not hotkeys.combo_valido(v):
                    aviso.config(text=f"No entiendo el atajo «{v}».")
                    e.focus_set()
                    return
                nuevos[clave] = v
            usados = [v for v in nuevos.values() if v]
            if len(usados) != len(set(usados)):
                aviso.config(text="Hay dos acciones con el mismo atajo.")
                return
            self.prefs["hotkeys"] = nuevos
            self._guardar_prefs()
            self._iniciar_atajos_globales()
            self.status_var.set("⌨ Atajos globales guardados.")
            win.destroy()

        def restaurar():
            for clave, e in entradas.items():
                e.delete(0, tk.END)
                e.insert(0, hotkeys.POR_DEFECTO[clave])
        botones = tk.Frame(win, bg=self.bg_color)
        botones.pack(fill=tk.X, padx=12, pady=10)
        tk.Button(botones, text="Guardar", font=("Tahoma", 8, "bold"), bg="#D9F2D9", bd=2,
                  command=guardar).pack(side=tk.RIGHT)
        tk.Button(botones, text="Por defecto", font=("Tahoma", 8), bg="#E0DFE3", bd=2,
                  command=restaurar).pack(side=tk.LEFT)
        self.tematizar(win)

    def mostrar_atajos(self):
        texto = "\n".join(f"{k:<20} {v}" for k, v in self.ATAJOS)
        messagebox.showinfo("Atajos de teclado — eXotic Player", texto, parent=self.root)

    # ------------------------------------------------------------------
    # Importar playlist de YouTube / YouTube Music
    # ------------------------------------------------------------------
    def importar_playlist_youtube(self):
        enlace = simpledialog.askstring(
            "Importar playlist",
            "Pega el enlace de una playlist pública de YouTube o YouTube Music\n"
            "(también vale un álbum de YouTube Music):",
            parent=self.root)
        if enlace is None:
            return
        pid = extraer_id_playlist(enlace)
        if not pid:
            messagebox.showwarning("Importar playlist", "No encuentro el ID de la playlist en ese enlace.",
                                   parent=self.root)
            return
        self.status_var.set("⏳ Importando playlist de YouTube…")

        def task():
            try:
                try:
                    res = self.ytmusic.get_playlist(pid, limit=None)
                except Exception:
                    from ytmusicapi import YTMusic
                    res = YTMusic().get_playlist(pid, limit=None)
                canciones = self._mapear_canciones(res.get("tracks") or [])
                thumbs = res.get("thumbnails") or []
                portada = thumbs[-1]["url"] if thumbs else ""
                self.ui(self._playlist_importada, res.get("title") or "Playlist importada", canciones, portada)
            except Exception as e:
                print(f"Error importando playlist: {e}")
                self.ui(self.status_var.set, "❌ No se pudo importar (¿es pública? ¿hay conexión?).")

        self.pool_stream.submit(task)

    def _playlist_importada(self, titulo, canciones, portada):
        if not canciones:
            self.status_var.set("La playlist está vacía o no se pudo leer.")
            return
        playlists = self.cloud_data.setdefault("playlists", [])
        nombre = nombre_unico(titulo, [p.get("name", "") for p in playlists])
        import uuid
        tracks = []
        vistos = set()
        for c in canciones:
            if c["videoId"] in vistos:
                continue
            vistos.add(c["videoId"])
            t = self._normalizar_track(dict(c, coverUrl=c.get("highCoverUrl") or c.get("coverUrl")))
            if t:
                tracks.append(t)
        playlists.append({"id": f"playlist-{uuid.uuid4().hex}", "name": nombre,
                          "tracks": tracks, "coverUrl": portada})
        self.cloud_data["version"] = 2
        self._actualizar_selector_playlists()
        self.playlist_var.set(nombre)
        self._seleccionar_playlist_ui()
        self._subir_cloud_data_async(f"☁️ Playlist '{nombre}' importada ({len(tracks)} canciones).")
        self.status_var.set(f"✓ Importada '{nombre}': {len(tracks)} canciones.")

    # ------------------------------------------------------------------
    # Ecualizador (10 bandas, guardado en la cuenta)
    # ------------------------------------------------------------------
    def _aplicar_eq_guardado(self):
        cfg = normalizar_eq(self._ajustes().get("eq"))
        self.vlc_eq.aplicar(cfg)
        return cfg

    def abrir_ventana_ecualizador(self):
        win = getattr(self, "_eq_win", None)
        try:
            if win is not None and win.winfo_exists():
                win.deiconify()
                win.lift()
                return
        except tk.TclError:
            pass

        bg = self.bg_color
        win = self._eq_win = tk.Toplevel(self.root)
        win.title("🎚️ Ecualizador — eXotic Player")
        win.configure(bg=bg)
        win.resizable(False, False)
        win.transient(self.root)

        def cerrar():
            self._eq_win = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", cerrar)
        win.bind("<Escape>", lambda e: cerrar())

        cfg = normalizar_eq(self._ajustes().get("eq"))
        presets = self.vlc_eq.presets()
        estado = {"cargando": False, "job": None}

        cab = tk.Frame(win, bg=bg)
        cab.pack(fill=tk.X, padx=10, pady=(10, 4))
        activo_var = tk.BooleanVar(value=cfg["enabled"])
        tk.Checkbutton(cab, text="Ecualizador activado", variable=activo_var, bg=bg,
                       activebackground=bg, font=("Tahoma", 8, "bold"),
                       command=lambda: cambiado()).pack(side=tk.LEFT)
        tk.Label(cab, text="Preset:", bg=bg, font=("Tahoma", 8)).pack(side=tk.LEFT, padx=(14, 3))
        preset_var = tk.StringVar(value=cfg["preset"] if cfg["preset"] in presets else "Personalizado")
        combo = ttk.Combobox(cab, textvariable=preset_var, state="readonly", width=22,
                             values=list(presets) + ["Personalizado"], font=("Tahoma", 8))
        combo.pack(side=tk.LEFT)

        marco = tk.LabelFrame(win, text=" Bandas (dB) ", font=("Tahoma", 8, "bold"), bg=bg,
                              relief=tk.GROOVE, bd=2)
        marco.pack(fill=tk.BOTH, padx=10, pady=4)

        def escala(parent, valor, texto):
            col = tk.Frame(parent, bg=bg)
            col.pack(side=tk.LEFT, padx=2, pady=4)
            s = tk.Scale(col, from_=20, to=-20, resolution=0.5, orient=tk.VERTICAL, length=150,
                         showvalue=False, bg=bg, highlightthickness=0, troughcolor="#B0B0B0",
                         activebackground="#316AC5", sliderlength=16, width=12,
                         command=lambda v: cambiado(manual=True))
            s.set(valor)
            s.pack()
            tk.Label(col, text=texto, bg=bg, font=("Tahoma", 7, "bold")).pack()
            return s

        pre_scale = escala(marco, cfg["preamp"], "Pre")
        tk.Frame(marco, bg="#808080", width=1).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=6)
        bandas = [escala(marco, cfg["bands"][i], BANDAS_TXT[i]) for i in range(10)]

        pie = tk.Frame(win, bg=bg)
        pie.pack(fill=tk.X, padx=10, pady=(4, 10))
        info = tk.Label(pie, text="Los cambios suenan al momento y se guardan en tu cuenta.",
                        bg=bg, fg="#555555", font=("Tahoma", 7))
        info.pack(side=tk.LEFT)

        def poner(pre, valores):
            estado["cargando"] = True
            pre_scale.set(pre)
            for s, v in zip(bandas, valores):
                s.set(v)
            estado["cargando"] = False

        def guardar(c):
            estado["job"] = None
            self._ajustes()["eq"] = c
            self._guardar_si_corresponde()

        def cambiado(manual=False):
            if estado["cargando"]:
                return
            if manual and preset_var.get() != "Personalizado":
                preset_var.set("Personalizado")
            c = self.vlc_eq.aplicar({
                "enabled": activo_var.get(), "preset": preset_var.get(),
                "preamp": pre_scale.get(), "bands": [s.get() for s in bandas]})
            if estado["job"] is not None:
                win.after_cancel(estado["job"])
            estado["job"] = win.after(1000, lambda: guardar(c))

        def elegir_preset(_e=None):
            nombre = preset_var.get()
            if nombre in presets:
                pre, valores = presets[nombre]
                poner(pre, valores)
                activo_var.set(nombre != "Plano")
                cambiado()
                self.status_var.set(f"🎚️ Preset de audio: {nombre}")
        combo.bind("<<ComboboxSelected>>", elegir_preset)

        def reset():
            preset_var.set("Plano")
            elegir_preset()
        tk.Button(pie, text="↺ Plano", font=("Tahoma", 8), bg="#E0DFE3", bd=2, cursor="hand2",
                  command=reset).pack(side=tk.RIGHT)
        self.tematizar(win)

    # ------------------------------------------------------------------
    # Visualizador del panel principal (espectro real o simulado)
    # ------------------------------------------------------------------
    def _iniciar_analizador(self):
        self._detener_analizador()
        modo = self.prefs.get("visualizer", "real")
        if modo == "off":
            return
        try:
            from soundscope_ps1 import AudioAnalyzer, np
            if np is None:
                return
            a = AudioAnalyzer()
            if modo == "real":
                a.iniciar()          # si no hay captura WASAPI se queda en "simulado"
            self.analizador = a
        except Exception as e:
            print(f"Visualizador: {e}")
            self.analizador = None

    def _detener_analizador(self):
        a = getattr(self, "analizador", None)
        self.analizador = None
        if a is not None:
            try:
                a.detener()
            except Exception:
                pass

    def cambiar_visualizador(self, modo):
        if modo not in VISUALIZADOR_TXT:
            return
        self.prefs["visualizer"] = modo
        self._guardar_prefs()
        self._iniciar_analizador()
        a = getattr(self, "analizador", None)
        if modo == "real" and a is not None and a.modo != "real":
            self.status_var.set("Visualizador: no se pudo capturar el audio del sistema; uso el simulado.")
        else:
            self.status_var.set(f"Visualizador: {VISUALIZADOR_TXT[modo]}.")
