"""Explorar YouTube Music y buscador con sugerencias + historial.

- 🧭 Explorar (en el panel de resultados):
    Novedades · Tendencias · Estados de ánimo y géneros · Éxitos (España) · Para ti
  Cada categoría abre playlists o álbumes; al abrir uno se ven sus canciones con
  "Reproducir todo", "+ Cola" y "Guardar como playlist". "← Volver" deshace el camino.
- Buscador: mientras escribes salen sugerencias de YouTube Music; con la caja vacía,
  tus últimas búsquedas. Flechas para moverte, Intro para elegir, Esc para cerrar.
"""
import tkinter as tk

MAX_HISTORIAL = 25
TRADUCCION = {"Moods & moments": "Estados de ánimo", "Genres": "Géneros", "For you": "Para ti"}


# ---------------------------------------------------------------------------
# Funciones puras (se prueban sin red ni Tk)
# ---------------------------------------------------------------------------
def anotar_busqueda(historial, texto, maximo=MAX_HISTORIAL):
    """Pone ``texto`` el primero del historial (sin repetir, sin distinguir mayúsculas)."""
    texto = " ".join(str(texto or "").split())
    if len(texto) < 2:
        return list(historial or [])
    resto = [h for h in (historial or []) if str(h).casefold() != texto.casefold()]
    return [texto] + resto[:maximo - 1]


def textos_sugerencias(respuesta):
    """get_search_suggestions devuelve textos o, con detailed_runs, dicts: siempre textos."""
    out = []
    for s in respuesta or []:
        if isinstance(s, str):
            t = s
        elif isinstance(s, dict):
            t = s.get("text") or "".join(r.get("text", "") for r in s.get("runs", []) if isinstance(r, dict))
        else:
            t = ""
        t = t.strip()
        if t and t not in out:
            out.append(t)
    return out[:8]


def _miniatura(item):
    """URL de la carátula más grande (algunas vienen sin "https:" delante)."""
    th = item.get("thumbnails") or item.get("thumbnail") or []
    if isinstance(th, dict):
        th = th.get("thumbnails") or []
    url = th[-1]["url"] if th and isinstance(th[-1], dict) and th[-1].get("url") else None
    return ("https:" + url) if url and url.startswith("//") else url


def _subtitulo(item):
    arts = item.get("artists") or []
    if isinstance(arts, list) and arts:
        return ", ".join(a.get("name", "") for a in arts if isinstance(a, dict) and a.get("name"))
    return str(item.get("description") or item.get("year") or item.get("type") or "")[:60]


def tarjetas_desde(items):
    """Convierte cualquier lista de YouTube Music en tarjetas navegables:
    {'tipo': 'playlist'|'album'|'cancion'|'categoria', 'titulo', 'sub', 'img', 'id'}."""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        titulo = str(it.get("title") or "").strip()
        if not titulo:
            continue
        base = {"titulo": titulo, "sub": _subtitulo(it), "img": _miniatura(it)}
        if it.get("params") and not it.get("playlistId") and not it.get("browseId"):
            out.append(dict(base, tipo="categoria", id=it["params"]))
        elif it.get("videoId") and not it.get("playlistId"):
            out.append(dict(base, tipo="cancion", id=it["videoId"], item=it))
        elif it.get("playlistId"):
            out.append(dict(base, tipo="playlist", id=it["playlistId"]))
        elif it.get("audioPlaylistId"):
            out.append(dict(base, tipo="playlist", id=it["audioPlaylistId"]))
        elif str(it.get("browseId", "")).startswith("MPRE"):
            out.append(dict(base, tipo="album", id=it["browseId"]))
    return out


def secciones_explorar(respuesta):
    """get_explore -> [(título, tarjetas)]"""
    r = respuesta if isinstance(respuesta, dict) else {}
    out = []
    nuevos = tarjetas_desde(r.get("new_releases"))
    if nuevos:
        out.append(("✨ Novedades", nuevos))
    for clave, nombre in (("trending", "🔥 Tendencias"), ("top_songs", "🎵 Más escuchadas")):
        bloque = r.get(clave) or {}
        tarjetas = tarjetas_desde(bloque.get("items") if isinstance(bloque, dict) else bloque)
        if tarjetas:
            out.append((nombre, tarjetas))
    moods = tarjetas_desde(r.get("moods_and_genres"))
    if moods:
        out.append(("🎭 Estados de ánimo y géneros", moods))
    nuevos_v = tarjetas_desde(r.get("new_videos"))
    if nuevos_v:
        out.append(("🎬 Vídeos nuevos", nuevos_v))
    return out


def secciones_charts(respuesta):
    r = respuesta if isinstance(respuesta, dict) else {}
    out = []
    for clave, nombre in (("songs", "🎵 Canciones"), ("videos", "🎬 Vídeos"), ("trending", "🔥 Tendencias"),
                          ("genres", "🎸 Por géneros"), ("artists", "🎤 Artistas")):
        v = r.get(clave)
        items = v.get("items") if isinstance(v, dict) else v
        tarjetas = [t for t in tarjetas_desde(items) if t["tipo"] != "categoria"]
        if tarjetas:
            out.append((nombre, tarjetas))
    return out


def secciones_moods(respuesta):
    r = respuesta if isinstance(respuesta, dict) else {}
    return [(TRADUCCION.get(k, k), tarjetas_desde(v)) for k, v in r.items() if tarjetas_desde(v)]


def secciones_home(respuesta):
    out = []
    for sec in respuesta or []:
        if isinstance(sec, dict):
            t = tarjetas_desde(sec.get("contents"))
            if t:
                out.append((sec.get("title") or "Para ti", t))
    return out


# ---------------------------------------------------------------------------
class PlayerExploreMixin:
    # ================================================================ sugerencias
    def _instalar_sugerencias(self):
        e = self.search_entry
        e.bind("<KeyRelease>", self._sug_tecla, add="+")
        e.bind("<FocusIn>", lambda ev: self.root.after(120, self._sug_mostrar_historial), add="+")
        e.bind("<FocusOut>", lambda ev: self.root.after(180, self._sug_ocultar_si_fuera), add="+")
        e.bind("<Down>", self._sug_bajar, add="+")
        e.bind("<Escape>", lambda ev: self._sug_ocultar(), add="+")
        e.bind("<Return>", lambda ev: self._sug_enter(), add="+")
        self.root.bind("<Configure>", lambda ev: self._sug_ocultar() if ev.widget is self.root else None, add="+")
        self._sug_win = None
        self._sug_token = 0
        self._sug_job = None

    def _anotar_busqueda(self, texto):
        self.prefs["search_history"] = anotar_busqueda(self.prefs.get("search_history") or [], texto)
        self._guardar_prefs()

    def _sug_tecla(self, ev):
        if ev.keysym in ("Return", "Escape", "Down", "Up", "Tab"):
            return
        texto = self.search_entry.get().strip()
        if self._sug_job is not None:
            self.root.after_cancel(self._sug_job)
            self._sug_job = None
        if not texto:
            self._sug_mostrar_historial()
            return
        if len(texto) < 2:
            self._sug_ocultar()
            return
        self._sug_job = self.root.after(220, lambda: self._sug_pedir(texto))

    def _sug_pedir(self, texto):
        self._sug_job = None
        self._sug_token += 1
        token = self._sug_token

        def task():
            try:
                res = textos_sugerencias(self.ytmusic.get_search_suggestions(texto))
            except Exception as e:
                print(f"[sugerencias] {e}")
                res = []
            self.ui(self._sug_recibidas, token, texto, res)

        self.pool_img.submit(task)

    def _sug_recibidas(self, token, texto, res):
        if token != self._sug_token or self.search_entry.get().strip() != texto:
            return
        if self.root.focus_get() is not self.search_entry:
            return
        historial = [h for h in (self.prefs.get("search_history") or []) if h.casefold().startswith(texto.casefold())]
        filas = [("🕘", h) for h in historial[:3]] + [("🔎", s) for s in res if s not in historial[:3]]
        self._sug_pintar(filas)

    def _sug_mostrar_historial(self):
        if self.root.focus_get() is not self.search_entry or self.search_entry.get().strip():
            return
        hist = self.prefs.get("search_history") or []
        if not hist:
            self._sug_ocultar()
            return
        self._sug_pintar([("🕘", h) for h in hist[:8]] + [("🗑", "Borrar historial de búsqueda")])

    def _sug_pintar(self, filas):
        if not filas:
            self._sug_ocultar()
            return
        e = self.search_entry
        if self._sug_win is None or not self._sug_win.winfo_exists():
            w = self._sug_win = tk.Toplevel(self.root)
            w.overrideredirect(True)
            try:
                w.attributes("-topmost", True)
            except tk.TclError:
                pass
            self._sug_lista = tk.Listbox(w, font=("Tahoma", 9), relief=tk.SOLID, bd=1, activestyle="none",
                                         selectbackground="#316AC5", selectforeground="white",
                                         highlightthickness=0, exportselection=False)
            self._sug_lista.pack(fill=tk.BOTH, expand=True)
            self._sug_lista.bind("<ButtonRelease-1>", lambda ev: self._sug_elegir())
            self._sug_lista.bind("<Return>", lambda ev: self._sug_elegir())
            self._sug_lista.bind("<Escape>", lambda ev: (self._sug_ocultar(), e.focus_set()))
            self._sug_lista.bind("<Up>", self._sug_subir)
            self._sug_lista.bind("<Motion>", lambda ev: (self._sug_lista.selection_clear(0, tk.END),
                                                          self._sug_lista.selection_set(self._sug_lista.nearest(ev.y))))
            self.tematizar(w)
        self._sug_filas = filas
        lb = self._sug_lista
        lb.delete(0, tk.END)
        for icono, texto in filas:
            lb.insert(tk.END, f" {icono}  {texto}")
        lb.config(height=len(filas))
        self._sug_win.geometry(f"{e.winfo_width()}x{len(filas) * 20 + 4}+{e.winfo_rootx()}+{e.winfo_rooty() + e.winfo_height()}")
        self._sug_win.deiconify()
        self._sug_win.lift()

    def _sug_ocultar(self):
        if self._sug_win is not None:
            try:
                self._sug_win.withdraw()
            except tk.TclError:
                pass

    def _sug_ocultar_si_fuera(self):
        f = self.root.focus_get()
        if f is not self.search_entry and f is not getattr(self, "_sug_lista", None):
            self._sug_ocultar()

    def _sug_visible(self):
        try:
            return self._sug_win is not None and self._sug_win.winfo_viewable()
        except tk.TclError:
            return False

    def _sug_bajar(self, ev=None):
        if not self._sug_visible():
            return None
        self._sug_lista.focus_set()
        self._sug_lista.selection_clear(0, tk.END)
        self._sug_lista.selection_set(0)
        self._sug_lista.activate(0)
        return "break"

    def _sug_subir(self, ev=None):
        sel = self._sug_lista.curselection()
        if sel and sel[0] == 0:
            self.search_entry.focus_set()
            self._sug_lista.selection_clear(0, tk.END)
            return "break"
        return None

    def _sug_enter(self):
        texto = self.search_entry.get().strip()
        self._sug_ocultar()
        self._anotar_busqueda(texto)

    def _sug_elegir(self):
        sel = self._sug_lista.curselection()
        if not sel or sel[0] >= len(self._sug_filas):
            return
        icono, texto = self._sug_filas[sel[0]]
        self._sug_ocultar()
        if icono == "🗑":
            self.prefs["search_history"] = []
            self._guardar_prefs()
            self.status_var.set("Historial de búsqueda borrado.")
            self.search_entry.focus_set()
            return
        self.search_entry.delete(0, tk.END)
        self.search_entry.insert(0, texto)
        self.search_entry.focus_set()
        self._anotar_busqueda(texto)
        self.obtener_sugerencias_canciones()

    # ================================================================ explorar
    def explorar(self, categoria="inicio"):
        """Abre Explorar en el panel de resultados."""
        self._sug_ocultar()
        self._exp_pila = []
        self._exp_ir(("menu", categoria), apilar=False)

    def _exp_ir(self, destino, apilar=True):
        if apilar and getattr(self, "_exp_actual", None):
            self._exp_pila.append(self._exp_actual)
        self._exp_actual = destino
        tipo, valor = destino[0], destino[1]
        self._search_token += 1
        token = self._search_token
        self._exp_limpiar()
        self._exp_cabecera(cargando=True)
        if tipo == "menu":
            fn = {"inicio": lambda: secciones_explorar(self.ytmusic.get_explore()),
                  "moods": lambda: secciones_moods(self.ytmusic.get_mood_categories()),
                  "charts": lambda: secciones_charts(self._charts()),
                  "home": lambda: secciones_home(self.ytmusic.get_home(limit=6))}[valor]
            self._exp_cargar(token, fn, self._exp_pintar_secciones)
        elif tipo == "categoria":
            self._exp_cargar(token, lambda: [(destino[2], tarjetas_desde(self.ytmusic.get_mood_playlists(valor)))],
                             self._exp_pintar_secciones)
        elif tipo in ("playlist", "album"):
            self._exp_cargar(token, lambda: self._exp_canciones(tipo, valor), self._exp_pintar_canciones)

    def _charts(self):
        try:
            return self.ytmusic.get_charts(country="ES")
        except Exception:
            return self.ytmusic.get_charts()

    def _exp_canciones(self, tipo, ident):
        if tipo == "album":
            alb = self.ytmusic.get_album(ident)
            portada = _miniatura(alb)
            canciones = self._mapear_canciones(alb.get("tracks") or [])
            for c in canciones:
                c["coverUrl"] = c.get("coverUrl") or portada
                c["highCoverUrl"] = c.get("highCoverUrl") or portada
            return alb.get("title") or "Álbum", canciones, portada
        pl = self.ytmusic.get_playlist(ident, limit=200)
        return pl.get("title") or "Playlist", self._mapear_canciones(pl.get("tracks") or []), _miniatura(pl)

    def _exp_cargar(self, token, fn, pintar):
        def task():
            try:
                datos = fn()
            except Exception as e:
                print(f"[explorar] {e}")
                self.ui(self._exp_error, token)
                return
            self.ui(pintar, token, datos)
        self.pool_stream.submit(task)

    def _exp_error(self, token):
        if token != self._search_token:
            return
        self._exp_limpiar()
        self._exp_cabecera()
        tk.Label(self.scroll_frame, text="No se pudo cargar (¿hay conexión?).", bg="#FAFAFA", fg="#A00000",
                 font=("Tahoma", 9)).pack(pady=20)
        self.tematizar(self.scroll_frame)

    def _exp_limpiar(self):
        for w in self.scroll_frame.winfo_children():
            w.destroy()
        self.canvas_sug.yview_moveto(0)

    def _exp_cabecera(self, cargando=False, extra=None):
        barra = tk.Frame(self.scroll_frame, bg="#FAFAFA")
        barra.pack(fill=tk.X, padx=4, pady=(4, 2))
        if self._exp_pila:
            tk.Button(barra, text="← Volver", font=("Tahoma", 8, "bold"), bg="#E0DFE3", bd=2, cursor="hand2",
                      command=self._exp_volver).pack(side=tk.LEFT, padx=(0, 6))
        for clave, texto in (("inicio", "✨ Explorar"), ("moods", "🎭 Ánimo y géneros"),
                             ("charts", "📈 Éxitos"), ("home", "🏠 Para ti")):
            activo = self._exp_actual == ("menu", clave)
            tk.Button(barra, text=texto, font=("Tahoma", 8, "bold" if activo else "normal"),
                      bg="#C8E8C8" if activo else "#E0DFE3", relief=tk.SUNKEN if activo else tk.RAISED,
                      bd=2, cursor="hand2", command=lambda c=clave: self.explorar(c)).pack(side=tk.LEFT, padx=1)
        if cargando:
            tk.Label(self.scroll_frame, text="⏳ Cargando…", bg="#FAFAFA", fg="#555555",
                     font=("Tahoma", 9)).pack(pady=16)
        if extra:
            extra(self.scroll_frame)
        self.tematizar(self.scroll_frame)

    def _exp_volver(self):
        if self._exp_pila:
            destino = self._exp_pila.pop()
            self._exp_ir(destino, apilar=False)

    def _exp_pintar_secciones(self, token, secciones):
        if token != self._search_token:
            return
        self._exp_limpiar()
        self._exp_cabecera()
        if not secciones:
            tk.Label(self.scroll_frame, text="No hay nada que mostrar aquí.", bg="#FAFAFA",
                     font=("Tahoma", 9)).pack(pady=20)
        for titulo, tarjetas in secciones:
            tk.Label(self.scroll_frame, text=titulo, bg="#FAFAFA", fg="#0A246A", anchor="w",
                     font=("Tahoma", 10, "bold")).pack(fill=tk.X, padx=8, pady=(10, 2))
            rejilla = tk.Frame(self.scroll_frame, bg="#FAFAFA")
            rejilla.pack(fill=tk.X, padx=4)
            columnas = 3
            for c in range(columnas):
                rejilla.grid_columnconfigure(c, weight=1, uniform="exp")
            for i, t in enumerate(tarjetas[:24]):
                self._exp_tarjeta(rejilla, t).grid(row=i // columnas, column=i % columnas, sticky="nsew", padx=3, pady=3)
        self.tematizar(self.scroll_frame)
        self.status_var.set("🧭 Explorar: elige una categoría, playlist o álbum.")

    def _exp_tarjeta(self, padre, t):
        if t["tipo"] == "categoria":
            b = tk.Button(padre, text=t["titulo"], font=("Tahoma", 8, "bold"), bg="#D6E4FF", bd=2,
                          cursor="hand2", wraplength=140, height=2,
                          command=lambda: self._exp_ir(("categoria", t["id"], t["titulo"])))
            return b
        f = tk.Frame(padre, bg="#FFFFFF", relief=tk.RAISED, bd=1, cursor="hand2")
        # Marco de tamaño fijo en píxeles: antes la etiqueta tenía width/height en caracteres y,
        # al poner la imagen, Tk los tomaba como píxeles (4×2) y la carátula no se veía.
        caja = tk.Frame(f, bg="#E8E8E8", width=50, height=50, relief=tk.SUNKEN, bd=1)
        caja.pack(side=tk.LEFT, padx=3, pady=3)
        caja.pack_propagate(False)
        img = tk.Label(caja, text="♪", bg="#E8E8E8", fg="#555555", font=("Tahoma", 14, "bold"))
        img.pack(fill=tk.BOTH, expand=True)
        if t.get("img"):
            self.cargar_imagen_async(t["img"], 48, img)
        info = tk.Frame(f, bg="#FFFFFF")
        info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        icono = {"album": "💿 ", "playlist": "📃 ", "cancion": "🎵 "}.get(t["tipo"], "")
        tk.Label(info, text=(icono + t["titulo"])[:34], bg="#FFFFFF", fg="#111111", anchor="w",
                 font=("Tahoma", 8, "bold")).pack(fill=tk.X)
        tk.Label(info, text=t["sub"][:38], bg="#FFFFFF", fg="#666666", anchor="w",
                 font=("Tahoma", 7)).pack(fill=tk.X)
        if t["tipo"] == "cancion":
            cancion = (self._mapear_canciones([t["item"]]) or [None])[0]
            accion = (lambda: self.reproducir_directo(cancion)) if cancion else (lambda: None)
        else:
            accion = lambda: self._exp_ir((t["tipo"], t["id"]))
        for w in (f, caja, img, info) + tuple(info.winfo_children()):
            w.bind("<Button-1>", lambda e: accion())
        return f

    def _exp_pintar_canciones(self, token, datos):
        if token != self._search_token:
            return
        titulo, canciones, portada = datos
        self._exp_canciones_actuales = (titulo, canciones, portada)
        self.renderizar_sugerencias(token, canciones)          # tarjetas de canción de siempre
        primero = (self.scroll_frame.winfo_children() or [None])[0]

        def acciones(padre):
            fila = tk.Frame(padre, bg="#FAFAFA")
            tk.Label(fila, text=f"{titulo}  ·  {len(canciones)} canciones", bg="#FAFAFA", fg="#0A246A",
                     font=("Tahoma", 10, "bold"), anchor="w").pack(fill=tk.X, padx=4)
            botones = tk.Frame(fila, bg="#FAFAFA")
            botones.pack(fill=tk.X, padx=2, pady=(2, 4))
            for texto, cmd in (("▶ Reproducir todo", self._exp_reproducir_todo), ("+ Cola", self._exp_a_cola),
                               ("⬇ Guardar como playlist", self._exp_guardar)):
                tk.Button(botones, text=texto, font=("Tahoma", 8, "bold"), bg="#D6E4FF", bd=2, cursor="hand2",
                          command=cmd).pack(side=tk.LEFT, padx=2)
            return fila
        barra = tk.Frame(self.scroll_frame, bg="#FAFAFA")
        if primero is not None:
            barra.pack(fill=tk.X, before=primero)
        else:
            barra.pack(fill=tk.X)
        if self._exp_pila:
            tk.Button(barra, text="← Volver", font=("Tahoma", 8, "bold"), bg="#E0DFE3", bd=2, cursor="hand2",
                      command=self._exp_volver).pack(side=tk.LEFT, padx=4, pady=4)
        acciones(barra).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.tematizar(barra)

    def _exp_reproducir_todo(self):
        titulo, canciones, _ = getattr(self, "_exp_canciones_actuales", ("", [], None))
        if not canciones:
            return
        if self._en_jam():
            self.social.cola_agregar([self._normalizar_track(dict(c, coverUrl=c.get("highCoverUrl") or c.get("coverUrl")))
                                      for c in canciones], reproducir=True)
            return
        self._activar_cola("normal")
        inicio = len(self.queue_normal)
        for c in canciones:
            self.queue_normal.append({"title": c["title"], "artist": c["artist"], "videoId": c["videoId"],
                                      "coverUrl": c.get("highCoverUrl") or c.get("coverUrl"),
                                      "duration": c.get("duration") or 0})
        self.current_index = inicio
        self.actualizar_vista_cola()
        self._guardar_si_corresponde()
        self.cargar_y_reproducir_actual()
        self.status_var.set(f"▶ {titulo}: {len(canciones)} canciones en la cola.")

    def _exp_a_cola(self):
        titulo, canciones, _ = getattr(self, "_exp_canciones_actuales", ("", [], None))
        if self._en_jam():
            self.social.cola_agregar([self._normalizar_track(dict(c, coverUrl=c.get("highCoverUrl") or c.get("coverUrl")))
                                      for c in canciones])
            return
        for c in canciones:
            self.queue_normal.append({"title": c["title"], "artist": c["artist"], "videoId": c["videoId"],
                                      "coverUrl": c.get("highCoverUrl") or c.get("coverUrl"),
                                      "duration": c.get("duration") or 0})
        if self._queue_mode == "normal":
            self.actualizar_vista_cola()
        self._guardar_si_corresponde()
        self.status_var.set(f"➕ {len(canciones)} canciones de «{titulo}» añadidas a la cola.")

    def _exp_guardar(self):
        titulo, canciones, portada = getattr(self, "_exp_canciones_actuales", ("", [], None))
        if canciones:
            self._playlist_importada(titulo, canciones, portada or "")
