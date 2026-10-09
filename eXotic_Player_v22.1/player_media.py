"""Funciones nuevas de eXotic Player v21.

- Archivos de música del ordenador (MP3, FLAC...).
- Fundido (crossfade) entre canciones con dos reproductores de VLC.
- Discord con carátula, barra de tiempo y botón "Escuchar".
- eXotic Wrapped (imagen vertical con tu resumen del mes o del año).
- Scrobbling a Last.fm.
- Contador de tiempo escuchado (para Wrapped y Last.fm).
"""
import os
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import duraciones
import local_files
import wrapped
from lastfm import LastFM, Scrobbler

FUNDIDOS = (0, 3, 5, 8, 12)


class PlayerMediaMixin:
    # ==================================================================
    # Archivos locales
    # ==================================================================
    def menu_locales(self, widget=None):
        menu = tk.Menu(self.root, tearoff=0, font=("Tahoma", 9))
        menu.add_command(label="🎵 Abrir archivos de música…", command=self.abrir_archivos_locales)
        menu.add_command(label="📂 Abrir una carpeta entera…", command=self.abrir_carpeta_local)
        w = widget or self.root
        try:
            menu.tk_popup(w.winfo_rootx(), w.winfo_rooty() + w.winfo_height())
        finally:
            menu.grab_release()

    def abrir_archivos_locales(self):
        tipos = " ".join(f"*{e}" for e in sorted(local_files.EXTENSIONES))
        rutas = filedialog.askopenfilenames(
            parent=self.root, title="Abrir música del ordenador",
            filetypes=[("Música", tipos), ("Todos los archivos", "*.*")])
        rutas = [r for r in (rutas or ()) if local_files.es_audio(r)]
        if rutas:
            self._cargar_locales(rutas)

    def abrir_carpeta_local(self):
        carpeta = filedialog.askdirectory(parent=self.root, title="Elige una carpeta con música")
        if not carpeta:
            return
        self.status_var.set("📂 Buscando canciones en la carpeta…")

        def buscar():
            rutas = local_files.buscar_audio(carpeta)
            self.ui(self._cargar_locales, rutas, os.path.basename(carpeta.rstrip("/\\")))

        self.pool_img.submit(buscar)

    def _cargar_locales(self, rutas, nombre_carpeta=None):
        if not rutas:
            self.status_var.set("No he encontrado archivos de música ahí.")
            return
        if self._en_jam():
            self.status_var.set("En una jam solo se pueden poner canciones de YouTube Music (los demás no tienen tus archivos).")
            return
        total = len(rutas)
        self.status_var.set(f"⏳ Leyendo {total} archivo(s)…")
        instancia = self.vlc_instance

        def leer():
            canciones = []
            for i, r in enumerate(rutas):
                canciones.append(local_files.leer_metadatos(instancia, r))
                if i % 25 == 24:
                    self.ui(self.status_var.set, f"⏳ Leyendo archivos… {i + 1}/{total}")
            self.ui(self._locales_leidos, canciones, nombre_carpeta)

        self.pool_img.submit(leer)

    def _locales_leidos(self, canciones, nombre_carpeta=None):
        if not canciones:
            return
        sonaba = self._cargando or bool(self.player.is_playing())
        if not sonaba and self._queue_mode != "normal":
            self._activar_cola("normal", refrescar=False)
        inicio = len(self.queue_normal)
        for c in canciones:
            self.queue_normal.append({k: c.get(k) for k in ("title", "artist", "videoId", "coverUrl", "duration")})
        self.actualizar_vista_cola()
        self._guardar_si_corresponde()
        # se muestran también en el panel de resultados, con sus botones de ♥, playlist...
        self._search_token += 1
        self.renderizar_sugerencias(self._search_token, canciones)
        donde = f" de «{nombre_carpeta}»" if nombre_carpeta else ""
        if not sonaba:
            self.current_index = inicio
            self.cargar_y_reproducir_actual()
            self.status_var.set(f"▶ {len(canciones)} canción(es){donde} en la cola.")
        else:
            self.status_var.set(f"➕ {len(canciones)} canción(es){donde} añadidas a la cola.")

    # ==================================================================
    # Discord
    # ==================================================================
    def _discord(self, sonando=True):
        rpc = getattr(self, "discord_rpc", None)
        if rpc is None:
            return
        c = self._cancion_actual()
        if c is None:
            rpc.update_presence("Detenido", "", is_playing=False)
            return
        try:
            pos = max(0, self.player.get_time()) / 1000.0
        except Exception:
            pos = 0
        dur = duraciones.de_pista(c)
        largo = self.player.get_length()
        if largo and largo > 0:
            dur = largo / 1000.0
        local = local_files.es_local(c.get("videoId"))
        portada = c.get("coverUrl") if str(c.get("coverUrl") or "").startswith("http") else None
        rpc.update_presence(c.get("title", ""), c.get("artist", ""), is_playing=sonando,
                            cover_url=portada, pos_s=pos, dur_s=dur,
                            url=None if local else self.enlace_cancion(c))

    # ==================================================================
    # Tiempo escuchado (Wrapped + Last.fm)
    # ==================================================================
    def _tick_escucha(self, sonando):
        ahora = time.monotonic()
        dt = ahora - getattr(self, "_escucha_t", ahora)
        self._escucha_t = ahora
        if not sonando or dt <= 0 or dt > 2:
            return
        self._escucha_pend = getattr(self, "_escucha_pend", 0.0) + dt
        if self._escucha_pend >= 15:
            self._volcar_escucha()
        sc = getattr(self, "scrobbler", None)
        if sc is not None:
            sc.escuchado(dt, max(0, self.player.get_length()) / 1000.0)

    def _volcar_escucha(self):
        pend, self._escucha_pend = getattr(self, "_escucha_pend", 0.0), 0.0
        if pend > 0 and (self.cloud_data.get("settings") or {}).get("save_history", True):
            wrapped.sumar_tiempo(self.cloud_data, pend)

    def _empieza_cancion(self, cancion):
        """Una canción nueva empieza a sonar (no al reanudar ni al cambiar a videoclip)."""
        self._volcar_escucha()
        if (self.cloud_data.get("settings") or {}).get("save_history", True):
            wrapped.contar_reproduccion(self.cloud_data, cancion)
        sc = getattr(self, "scrobbler", None)
        if sc is not None:
            sc.empezar(cancion, duraciones.de_pista(cancion))

    # ==================================================================
    # Wrapped
    # ==================================================================
    def menu_wrapped(self, widget=None):
        menu = tk.Menu(self.root, tearoff=0, font=("Tahoma", 9))
        for clave, texto in wrapped.periodos_disponibles():
            menu.add_command(label=f"🎁 {texto}", command=lambda c=clave: self.crear_wrapped(c))
        if widget is not None:
            x, y = widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height()
        else:
            x, y = self.root.winfo_pointerx(), self.root.winfo_pointery()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def crear_wrapped(self, periodo):
        self._volcar_escucha()
        res = wrapped.resumen(self.cloud_data, periodo, self.cloud_data.get("history", []))
        if not res["reproducciones"]:
            messagebox.showinfo("eXotic Wrapped", "Todavía no hay música registrada en ese periodo.\n"
                                "¡Dale al play y vuelve más tarde!", parent=self.root)
            return
        self.status_var.set("🎁 Preparando tu Wrapped…")
        usuario = ""
        perfil = getattr(self.social, "perfil", None)
        if perfil:
            usuario = perfil.get("nombre") or perfil.get("username") or ""
        portada_url = next((t[3] for t in res["top_canciones"] if t[3]), None)

        def tarea():
            portada = None
            if portada_url:
                try:
                    import io
                    import urllib.request
                    from PIL import Image
                    req = urllib.request.Request(portada_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=8) as r:
                        portada = Image.open(io.BytesIO(r.read()))
                        portada.load()
                except Exception:
                    portada = None
            try:
                img = wrapped.generar_imagen(res, portada, usuario)
            except Exception as e:
                print(f"Wrapped: {e}")
                self.ui(self.status_var.set, f"No se pudo crear el Wrapped: {e}")
                return
            self.ui(self._mostrar_wrapped, img, periodo)

        self.pool_img.submit(tarea)

    def _mostrar_wrapped(self, img, periodo):
        from PIL import ImageTk
        top = tk.Toplevel(self.root)
        top.title(f"🎁 eXotic Wrapped — {wrapped.nombre_periodo(periodo)}")
        top.configure(bg=self.bg_color)
        top.resizable(False, False)
        alto = min(720, self.root.winfo_screenheight() - 160)
        vista = img.resize((int(alto * 9 / 16), alto))
        foto = ImageTk.PhotoImage(vista)
        lbl = tk.Label(top, image=foto, bd=0)
        lbl.image = foto
        lbl.pack(padx=10, pady=(10, 6))
        fila = tk.Frame(top, bg=self.bg_color)
        fila.pack(fill=tk.X, padx=10, pady=(0, 10))

        def guardar():
            ruta = filedialog.asksaveasfilename(
                parent=top, title="Guardar Wrapped", defaultextension=".png",
                initialfile=f"eXotic_Wrapped_{periodo}.png",
                initialdir=os.path.join(os.path.expanduser("~"), "Pictures"),
                filetypes=[("Imagen PNG", "*.png")])
            if ruta:
                img.save(ruta)
                self.status_var.set(f"💾 Wrapped guardado: {os.path.basename(ruta)}")
                top.destroy()

        tk.Button(fila, text="💾 Guardar imagen (1080×1920)", font=("Tahoma", 8, "bold"), bg="#D9F2D9",
                  bd=2, cursor="hand2", command=guardar).pack(side=tk.LEFT)
        tk.Button(fila, text="Cerrar", font=("Tahoma", 8), bg="#E0DFE3", bd=2,
                  command=top.destroy).pack(side=tk.RIGHT)
        self.tematizar(top)
        self.status_var.set("🎁 Tu Wrapped está listo: guárdalo y compártelo en tus historias.")

    # ==================================================================
    # Last.fm
    # ==================================================================
    def _iniciar_lastfm(self):
        p = self.prefs
        cliente = LastFM(p.get("lastfm_key"), p.get("lastfm_secret"), p.get("lastfm_sk"))
        if not cliente.listo:
            self.scrobbler = None
            return
        self.scrobbler = Scrobbler(cliente, p.get("lastfm_pend") or [],
                                   enviar=lambda fn: self.pool_cloud.submit(fn))

    def _guardar_pendientes_lastfm(self):
        sc = getattr(self, "scrobbler", None)
        if sc is not None:
            self.prefs["lastfm_pend"] = list(sc.pendientes)

    def conectar_lastfm(self, key, secret, usuario, password, al_terminar=None):
        key, secret, usuario = key.strip(), secret.strip(), usuario.strip()
        if not (key and secret and usuario and password):
            messagebox.showwarning("Last.fm", "Rellena la API key, el secret, tu usuario y tu contraseña.",
                                   parent=self._config_win or self.root)
            return
        self.status_var.set("Conectando con Last.fm…")

        def tarea():
            try:
                sk = LastFM(key, secret).conectar(usuario, password)
                self.ui(self._lastfm_conectado, key, secret, usuario, sk, al_terminar)
            except Exception as e:
                self.ui(self.status_var.set, f"Last.fm: no se pudo conectar ({e}).")
                if al_terminar:
                    self.ui(al_terminar)

        self.pool_cloud.submit(tarea)

    def _lastfm_conectado(self, key, secret, usuario, sk, al_terminar=None):
        self.prefs.update(lastfm_key=key, lastfm_secret=secret, lastfm_user=usuario, lastfm_sk=sk)
        self._guardar_prefs()
        self._iniciar_lastfm()
        self.sonar("conectar")
        self.status_var.set(f"🎵 Last.fm conectado como {usuario}: tus canciones se registrarán solas.")
        if al_terminar:
            al_terminar()

    def desconectar_lastfm(self):
        for k in ("lastfm_sk", "lastfm_user", "lastfm_pend"):
            self.prefs[k] = None if k != "lastfm_pend" else []
        self._guardar_prefs()
        self.scrobbler = None
        self.status_var.set("Last.fm desconectado.")

    def seccion_lastfm(self, parent, bg):
        """Bloque de Last.fm para la ventana de Configuración."""
        box = tk.LabelFrame(parent, text=" 🎵 Last.fm (scrobbling) ", font=("Tahoma", 8, "bold"),
                            bg=bg, relief=tk.GROOVE, bd=2)
        box.pack(fill=tk.X, padx=6, pady=4)
        estado = tk.Label(box, bg=bg, font=("Tahoma", 8), anchor="w")
        estado.pack(fill=tk.X, padx=8, pady=(6, 2))
        form = tk.Frame(box, bg=bg)
        campos = {}
        for i, (clave, texto, oculto) in enumerate((("key", "API key", False), ("secret", "Secret", True),
                                                    ("user", "Usuario", False), ("pass", "Contraseña", True))):
            tk.Label(form, text=texto + ":", bg=bg, font=("Tahoma", 8)).grid(row=i // 2, column=(i % 2) * 2,
                                                                               sticky="e", padx=(0, 3), pady=2)
            e = tk.Entry(form, width=20, font=("Tahoma", 8), show="•" if oculto else "", relief=tk.SUNKEN, bd=2)
            e.grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(0, 8), pady=2)
            campos[clave] = e
        campos["key"].insert(0, self.prefs.get("lastfm_key") or "")
        campos["secret"].insert(0, self.prefs.get("lastfm_secret") or "")
        campos["user"].insert(0, self.prefs.get("lastfm_user") or "")
        botones = tk.Frame(box, bg=bg)
        ayuda = tk.Label(box, bg=bg, fg="#666666", font=("Tahoma", 7), anchor="w", justify=tk.LEFT,
                         text="Crea una API key gratis en last.fm/api/account/create. "
                              "La contraseña no se guarda.")

        def pintar():
            for w in (form, botones, ayuda):
                w.pack_forget()
            for w in botones.winfo_children():
                w.destroy()
            if self.prefs.get("lastfm_sk"):
                estado.config(text=f"🟢 Conectado como {self.prefs.get('lastfm_user')}", fg=self.c("#1F5F1F", "fg"))
                tk.Button(botones, text="Desconectar", font=("Tahoma", 8), bg=self.c("#E0DFE3"), bd=2,
                          command=lambda: (self.desconectar_lastfm(), pintar())).pack(side=tk.LEFT)
            else:
                estado.config(text="⚪ Sin conectar", fg=self.c("#555555", "fg"))
                form.pack(fill=tk.X, padx=8)
                tk.Button(botones, text="Conectar", font=("Tahoma", 8, "bold"), bg=self.c("#D9F2D9"), bd=2,
                          command=lambda: self.conectar_lastfm(campos["key"].get(), campos["secret"].get(),
                                                               campos["user"].get(), campos["pass"].get(),
                                                               al_terminar=pintar)).pack(side=tk.LEFT)
                ayuda.pack(fill=tk.X, padx=8, pady=(2, 0))
            botones.pack(fill=tk.X, padx=8, pady=(4, 7))
            self.tematizar(botones)
        pintar()
        return box

    # ==================================================================
    # Fundido entre canciones (crossfade)
    # ==================================================================
    def selector_fundido(self, parent, bg):
        fila = tk.Frame(parent, bg=bg)
        fila.pack(fill=tk.X, padx=8, pady=(2, 4))
        tk.Label(fila, text="Fundido entre canciones:", bg=bg, font=("Tahoma", 8)).pack(side=tk.LEFT)
        opciones = ["Desactivado"] + [f"{s} segundos" for s in FUNDIDOS[1:]]
        actual = int(self.prefs.get("crossfade") or 0)
        var = tk.StringVar(value=opciones[FUNDIDOS.index(actual)] if actual in FUNDIDOS else opciones[0])
        combo = ttk.Combobox(fila, textvariable=var, values=opciones, state="readonly", width=13,
                             font=("Tahoma", 8))
        combo.pack(side=tk.LEFT, padx=6)

        def elegir(_e=None):
            self.prefs["crossfade"] = FUNDIDOS[opciones.index(var.get())]
            self._guardar_prefs()
            self.status_var.set("Fundido desactivado." if not self.prefs["crossfade"]
                                else f"🌊 Fundido de {self.prefs['crossfade']} s entre canciones.")
        combo.bind("<<ComboboxSelected>>", elegir)
        tk.Label(fila, text="(no se usa en jams ni con videoclips)", bg=bg, fg="#666666",
                 font=("Tahoma", 7)).pack(side=tk.LEFT)

    def _indice_siguiente(self):
        """Índice que sonará después de la actual, sin cambiar nada (None si no se sabe)."""
        if self._queue_mode == "playlist" and self._playlist_shuffle:
            orden = self._playlist_shuffle_order
            if self.current_index in orden:
                pos = orden.index(self.current_index)
                if pos + 1 < len(orden):
                    return orden[pos + 1]
            return None
        if self.current_index + 1 < len(self.queue):
            return self.current_index + 1
        if self.modo_repetir == "all" and self.queue:
            return 0
        return None

    def _vigilar_fundido(self, time_ms, length_ms):
        """Lo llama el bucle del reproductor mientras suena. Empieza el fundido si toca."""
        xf = int(self.prefs.get("crossfade") or 0)
        if (not xf or getattr(self, "_xf", None) is not None or self._cargando or self._reproduciendo_video
                or self._en_jam() or self.modo_repetir == "one" or getattr(self, "_sleep_fin_cancion", False)
                or getattr(self, "_fundido_job", None) is not None):
            return
        if length_ms <= xf * 3000:                      # canciones muy cortas: sin fundido
            return
        restante = length_ms - time_ms
        if restante > xf * 1000 or restante < 800:
            return
        nxt = self._indice_siguiente()
        if nxt is None:
            return
        cancion = self.queue[nxt]
        if self._quiere_video(cancion):
            return
        vid = cancion["videoId"]
        if local_files.es_local(vid):
            ruta = local_files.ruta_de(vid)
            if not os.path.exists(ruta):
                return
            url, ua = ruta, None
        else:
            cache = self._stream_cache.get(vid)
            if not cache or time.time() - cache[1] >= 3 * 3600:
                return                                   # sin el stream precargado no hay fundido
            url, ua = cache[0], cache[2]
        self._empezar_fundido(nxt, url, ua, min(xf, restante / 1000.0))

    def _empezar_fundido(self, idx, url, ua, segundos):
        p2 = self.vlc_instance.media_player_new()
        media = self.vlc_instance.media_new(url)
        if ua:
            media.add_option(f":http-user-agent={ua}")
        media.add_option(":no-video")
        p2.set_media(media)
        p2.audio_set_volume(0)
        if self.prefs.get("muted"):
            p2.audio_set_mute(True)
        eq = getattr(self.vlc_eq, "_eq", None)
        if eq is not None:
            p2.set_equalizer(eq)
        p2.play()
        self.aplicar_velocidad(p2)
        self._xf = {"player": p2, "idx": idx, "t0": time.monotonic(), "dur": max(0.5, segundos),
                    "token": self._play_token}
        self._paso_fundido()

    def _paso_fundido(self):
        xf = getattr(self, "_xf", None)
        if xf is None:
            return
        if xf["token"] != self._play_token:          # el usuario cambió de canción
            self._cancelar_fundido()
            return
        k = (time.monotonic() - xf["t0"]) / xf["dur"]
        vol = int(float(self.vol_slider.get()))
        if k < 1.0:
            self.player.audio_set_volume(int(vol * (1 - k)))
            xf["player"].audio_set_volume(int(vol * k))
            xf["job"] = self.root.after(80, self._paso_fundido)
        else:
            self._terminar_fundido()

    def _terminar_fundido(self):
        xf, self._xf = getattr(self, "_xf", None), None
        if xf is None:
            return
        if xf.get("job"):
            try:
                self.root.after_cancel(xf["job"])
            except tk.TclError:
                pass
        viejo = self.player
        self.player = xf["player"]
        self.vlc_eq.player = self.player
        self.player.audio_set_volume(int(float(self.vol_slider.get())))
        self.pool_stream.submit(lambda: (viejo.stop(), viejo.release()))
        self._play_token += 1
        self.current_index = xf["idx"]
        cancion = self.queue[self.current_index]
        self._reintentos_vlc = 0
        self.social.al_cargar(cancion["videoId"])
        self.actualizar_vista_cola()
        self.cargar_caratula_principal(cancion.get("coverUrl"))
        self._tras_iniciar(cancion, 0, " 🌊")

    def _cancelar_fundido(self):
        xf, self._xf = getattr(self, "_xf", None), None
        if xf is None:
            return
        if xf.get("job"):
            try:
                self.root.after_cancel(xf["job"])
            except tk.TclError:
                pass
        p2 = xf["player"]
        self.pool_stream.submit(lambda: (p2.stop(), p2.release()))
        try:
            self.player.audio_set_volume(int(float(self.vol_slider.get())))
        except Exception:
            pass

    # ==================================================================
    # Reacciones de la jam (flotan por el visualizador)
    # ==================================================================
    def mostrar_reaccion(self, emoji):
        from social_extra import lanzar_reaccion
        lanzar_reaccion(self.canvas_eq, emoji)

    # ==================================================================
    # Estado del día (para mostrar en el panel)
    # ==================================================================
    def minutos_hoy(self):
        m = (self.cloud_data.get("monthly") or {}).get(datetime.now().strftime("%Y-%m")) or {}
        return int(((m.get("days") or {}).get(datetime.now().strftime("%d"), 0) + getattr(self, "_escucha_pend", 0)) // 60)
