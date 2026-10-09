"""Tu cuenta de YouTube Music dentro de eXotic.

Conexión: YouTube Music no da un "iniciar sesión" para programas como este, así que se usan
las cabeceras de tu navegador (método oficial de ytmusicapi). Se pegan una vez y se guardan
en ``ytm_browser.json`` en tu carpeta de datos (tienen tus cookies: no las compartas).

Qué se sincroniza:
  * ⬇ Tus playlists de YouTube Music aparecen en eXotic (enlazadas) y tus "Me gusta"
    se suman a los de eXotic.
  * ⬆ Dar o quitar ♥ en eXotic lo hace también en YouTube Music.
  * ⬆ Añadir o quitar canciones de una playlist enlazada, o renombrarla, se hace también allí.
  Borrar una playlist en eXotic NO la borra en YouTube Music (por seguridad).
"""
import os
import tkinter as tk
import uuid
from tkinter import messagebox

import app_paths

AUTH_FILE = os.path.join(app_paths.DATA_DIR, "ytm_browser.json")
INSTRUCCIONES = (
    "1. Abre music.youtube.com en Chrome, Edge o Firefox con tu cuenta iniciada.\n"
    "2. Pulsa F12 y ve a la pestaña «Red» (Network). Escribe  browse  en el filtro.\n"
    "3. Navega un poco por YouTube Music (por ejemplo, abre «Biblioteca»).\n"
    "4. Clic en una petición «browse?…» (tipo POST) → «Encabezados de solicitud».\n"
    "   Chrome/Edge: selecciona TODO el bloque de encabezados de solicitud y cópialo.\n"
    "   Firefox: botón derecho → Copiar → Copiar encabezados de solicitud.\n"
    "5. Pégalo abajo y pulsa Conectar."
)


def es_local(vid):
    return str(vid or "").startswith("file:")


def fusionar_me_gusta(locales, remotos):
    """Suma a 'locales' los de YouTube Music que falten. Devuelve (lista, nº añadidos)."""
    vistos = {x.get("videoId") for x in locales}
    nuevos = [r for r in remotos if r.get("videoId") and r["videoId"] not in vistos]
    return list(locales) + nuevos, len(nuevos)


def fusionar_playlists(playlists, remotas, nombre_unico):
    """Actualiza/crea en ``playlists`` las playlists de YouTube Music.

    remotas: [{'ytmPlaylistId', 'name', 'coverUrl', 'tracks': [...]}]
    Las ya enlazadas se reemplazan por la versión de YouTube Music (que es la buena: los
    cambios hechos en eXotic se mandan allí al momento). Devuelve (nuevas, actualizadas)."""
    por_id = {p.get("ytmPlaylistId"): p for p in playlists if p.get("ytmPlaylistId")}
    nuevas = actualizadas = 0
    for r in remotas:
        p = por_id.get(r["ytmPlaylistId"])
        if p is None:
            playlists.append({"id": f"playlist-{uuid.uuid4().hex}",
                              "name": nombre_unico(r["name"], [x.get("name", "") for x in playlists]),
                              "tracks": r["tracks"], "coverUrl": r.get("coverUrl") or "",
                              "ytmPlaylistId": r["ytmPlaylistId"]})
            nuevas += 1
        else:
            p["tracks"] = r["tracks"]
            if r.get("coverUrl") and not p.get("coverUrl"):
                p["coverUrl"] = r["coverUrl"]
            actualizadas += 1
    return nuevas, actualizadas


class PlayerYTMMixin:
    # ------------------------------------------------------------------ estado
    @property
    def ytm_conectado(self):
        return bool(self.prefs.get("ytm_auth")) and os.path.exists(AUTH_FILE)

    def _iniciar_ytm(self):
        if self.ytm_conectado:
            try:
                from exotic_player import crear_ytmusic
                self.ytmusic = crear_ytmusic(AUTH_FILE)
                self.root.after(6000, lambda: self.sincronizar_ytm(silencioso=True))
            except Exception as e:
                print(f"YouTube Music: no se pudo usar la cuenta guardada ({e})")

    # ------------------------------------------------------------------ conectar
    def conectar_ytm(self):
        parent = getattr(self, "_config_win", None) or self.root
        win = tk.Toplevel(parent)
        win.title("Conectar YouTube Music")
        win.configure(bg=self.bg_color)
        win.transient(parent)
        win.geometry("620x520")
        tk.Label(win, text="▶ Conectar tu cuenta de YouTube Music", bg=self.bg_color, fg="#0A246A",
                 font=("Tahoma", 11, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        tk.Label(win, text=INSTRUCCIONES, bg=self.bg_color, font=("Tahoma", 8), justify=tk.LEFT).pack(anchor="w", padx=12)
        marco = tk.Frame(win, bg="#FFFFFF", relief=tk.SUNKEN, bd=2)
        marco.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)
        texto = tk.Text(marco, font=("Consolas", 8), wrap="none", height=12, relief=tk.FLAT)
        texto.pack(fill=tk.BOTH, expand=True)
        aviso = tk.Label(win, text="🔒 Las cabeceras llevan tus cookies: se guardan solo en este ordenador.",
                         bg=self.bg_color, fg="#555555", font=("Tahoma", 7))
        aviso.pack(anchor="w", padx=12)
        estado = tk.Label(win, text="", bg=self.bg_color, fg="#A00000", font=("Tahoma", 8), wraplength=580,
                          justify=tk.LEFT)
        estado.pack(anchor="w", padx=12)
        botones = tk.Frame(win, bg=self.bg_color)
        botones.pack(fill=tk.X, padx=12, pady=10)

        def conectar():
            crudo = texto.get("1.0", tk.END).strip()
            if not crudo:
                estado.config(text="Pega primero las cabeceras.")
                return
            estado.config(text="Comprobando…", fg="#333333")
            b.config(state=tk.DISABLED)

            def task():
                try:
                    import ytmusicapi
                    tmp = AUTH_FILE + ".nuevo"
                    ytmusicapi.setup(filepath=tmp, headers_raw=crudo)
                    from exotic_player import crear_ytmusic
                    yt = crear_ytmusic(tmp)
                    yt.get_library_playlists(limit=1)          # prueba real de que la sesión vale
                    os.replace(tmp, AUTH_FILE)
                    self.ui(ok, yt)
                except Exception as e:
                    try:
                        os.remove(AUTH_FILE + ".nuevo")
                    except OSError:
                        pass
                    self.ui(mal, str(e))
            self.pool_cloud.submit(task)

        def ok(yt):
            self.ytmusic = yt
            self.prefs["ytm_auth"] = True
            self._guardar_prefs()
            self.sonar("conectar")
            if win.winfo_exists():
                win.destroy()
            self.status_var.set("▶ YouTube Music conectado. Trayendo tus playlists y Me gusta…")
            self.sincronizar_ytm()
            self._actualizar_configuracion_ui()

        def mal(msg):
            if win.winfo_exists():
                b.config(state=tk.NORMAL)
                estado.config(text=f"No se pudo conectar: {msg[:300]}", fg="#A00000")

        b = tk.Button(botones, text="Conectar", font=("Tahoma", 8, "bold"), bg="#D9F2D9", bd=2, command=conectar)
        b.pack(side=tk.RIGHT)
        tk.Button(botones, text="Cancelar", font=("Tahoma", 8), bg="#E0DFE3", bd=2,
                  command=win.destroy).pack(side=tk.RIGHT, padx=6)
        self.tematizar(win)
        texto.focus_set()

    def desconectar_ytm(self):
        if not messagebox.askyesno("YouTube Music", "¿Desconectar tu cuenta de YouTube Music de eXotic?\n\n"
                                   "Tus playlists se quedan en eXotic, pero dejarán de sincronizarse.",
                                   parent=getattr(self, "_config_win", None) or self.root):
            return
        try:
            os.remove(AUTH_FILE)
        except OSError:
            pass
        self.prefs["ytm_auth"] = False
        self._guardar_prefs()
        from exotic_player import crear_ytmusic
        self.ytmusic = crear_ytmusic()
        self.status_var.set("YouTube Music desconectado.")
        self._actualizar_configuracion_ui()

    # ------------------------------------------------------------------ bajar
    def sincronizar_ytm(self, silencioso=False):
        if not self.ytm_conectado:
            if not silencioso:
                self.status_var.set("Conecta primero tu cuenta de YouTube Music (Configuración → Cuenta y datos).")
            return
        if getattr(self, "_ytm_sync_en_curso", False):
            return
        self._ytm_sync_en_curso = True
        yt = self.ytmusic

        def task():
            try:
                remotas = []
                for p in yt.get_library_playlists(limit=None) or []:
                    pid = p.get("playlistId")
                    if not pid or pid in ("LM", "SE"):          # "Me gusta" y episodios van aparte
                        continue
                    try:
                        datos = yt.get_playlist(pid, limit=None)
                    except Exception as e:
                        print(f"[ytm] playlist {pid}: {e}")
                        continue
                    pistas = []
                    for t in datos.get("tracks") or []:
                        mapeada = self._mapear_canciones([t])
                        if not mapeada:                  # pistas no disponibles (sin videoId)
                            continue
                        c = mapeada[0]
                        pista = {"title": c["title"], "artist": c["artist"], "videoId": c["videoId"],
                                 "coverUrl": c.get("highCoverUrl") or c.get("coverUrl"), "duration": c.get("duration") or 0}
                        if t.get("setVideoId"):
                            pista["setVideoId"] = t["setVideoId"]
                        pistas.append(pista)
                    th = datos.get("thumbnails") or p.get("thumbnails") or []
                    remotas.append({"ytmPlaylistId": pid, "name": datos.get("title") or p.get("title") or "Playlist",
                                    "coverUrl": th[-1]["url"] if th else "", "tracks": pistas})
                gustan = yt.get_liked_songs(limit=1000) or {}
                me_gusta = [{"title": c["title"], "artist": c["artist"], "videoId": c["videoId"],
                             "coverUrl": c.get("highCoverUrl") or c.get("coverUrl"), "duration": c.get("duration") or 0}
                            for c in self._mapear_canciones(gustan.get("tracks") or [])]
                self.ui(self._ytm_sincronizado, remotas, me_gusta, silencioso)
            except Exception as e:
                print(f"[ytm] sincronizar: {e}")
                self.ui(self._ytm_fallo, str(e), silencioso)

        self.pool_cloud.submit(task)

    def _ytm_fallo(self, msg, silencioso):
        self._ytm_sync_en_curso = False
        if not silencioso or "401" in msg or "403" in msg:
            self.status_var.set("YouTube Music: no se pudo sincronizar. Si sigue pasando, vuelve a conectar la cuenta.")

    def _ytm_sincronizado(self, remotas, me_gusta, silencioso):
        from playlist_logic import nombre_unico
        self._ytm_sync_en_curso = False
        playlists = self.cloud_data.setdefault("playlists", [])
        nuevas, actualizadas = fusionar_playlists(playlists, remotas, nombre_unico)
        liked, anadidos = fusionar_me_gusta(self.cloud_data.setdefault("liked", []), me_gusta)
        self.cloud_data["liked"] = liked
        self.cloud_data["version"] = 2
        self._actualizar_selector_playlists()
        self._refrescar_favoritos_ui()
        self._subir_cloud_data_async(None)
        self.status_var.set(f"▶ YouTube Music sincronizado: {nuevas} playlist(s) nuevas, {actualizadas} actualizadas, "
                            f"{anadidos} canción(es) más en Me gusta.")

    # ------------------------------------------------------------------ subir (en segundo plano)
    def _ytm_tarea(self, fn, que):
        if not self.ytm_conectado:
            return
        yt = self.ytmusic

        def task():
            try:
                fn(yt)
            except Exception as e:
                print(f"[ytm] {que}: {e}")
                self.ui(self.status_var.set, f"YouTube Music: no se pudo {que}.")
        self.pool_cloud.submit(task)

    def ytm_me_gusta(self, video_id, gusta):
        if video_id and not es_local(video_id):
            self._ytm_tarea(lambda yt: yt.rate_song(video_id, "LIKE" if gusta else "INDIFFERENT"),
                            "actualizar el Me gusta")

    def ytm_anadir_a_playlist(self, playlist, video_id):
        pid = playlist.get("ytmPlaylistId")
        if not pid or not video_id or es_local(video_id):
            return

        def fn(yt):
            res = yt.add_playlist_items(pid, [video_id], duplicates=False)
            # guardamos el setVideoId para poder quitarla después
            for r in (res or {}).get("playlistEditResults", []) if isinstance(res, dict) else []:
                svid = (r.get("videoId") == video_id) and r.get("setVideoId")
                if svid:
                    self.ui(self._ytm_apuntar_set, playlist, video_id, svid)
        self._ytm_tarea(fn, "añadir la canción a la playlist")

    def _ytm_apuntar_set(self, playlist, video_id, set_video_id):
        for t in playlist.get("tracks", []):
            if t.get("videoId") == video_id and not t.get("setVideoId"):
                t["setVideoId"] = set_video_id
                break

    def ytm_quitar_de_playlist(self, playlist, pistas):
        pid = playlist.get("ytmPlaylistId")
        pistas = [p for p in pistas if p.get("videoId") and not es_local(p.get("videoId"))]
        if not pid or not pistas:
            return

        def fn(yt):
            faltan = [p for p in pistas if not p.get("setVideoId")]
            if faltan:                                   # se añadieron hace poco: buscamos su setVideoId
                remotas = {t.get("videoId"): t.get("setVideoId")
                           for t in (yt.get_playlist(pid, limit=None).get("tracks") or [])}
                for p in faltan:
                    p["setVideoId"] = remotas.get(p["videoId"])
            items = [{"videoId": p["videoId"], "setVideoId": p["setVideoId"]} for p in pistas if p.get("setVideoId")]
            if items:
                yt.remove_playlist_items(pid, items)
        self._ytm_tarea(fn, "quitar canciones de la playlist")

    def ytm_renombrar_playlist(self, playlist, nombre):
        pid = playlist.get("ytmPlaylistId")
        if pid:
            self._ytm_tarea(lambda yt: yt.edit_playlist(pid, title=nombre), "renombrar la playlist")

    # ------------------------------------------------------------------ configuración
    def seccion_ytm(self, parent, bg):
        box = tk.LabelFrame(parent, text=" ▶ YouTube Music ", font=("Tahoma", 8, "bold"),
                            bg=bg, relief=tk.GROOVE, bd=2)
        box.pack(fill=tk.X, padx=6, pady=4)
        self.config_ytm_label = tk.Label(box, bg=bg, font=("Tahoma", 8), anchor="w", justify=tk.LEFT)
        self.config_ytm_label.pack(fill=tk.X, padx=8, pady=(6, 2))
        fila = tk.Frame(box, bg=bg)
        fila.pack(fill=tk.X, padx=8, pady=(2, 7))
        self.config_ytm_fila = fila
        self._pintar_seccion_ytm()
        return box

    def _pintar_seccion_ytm(self):
        lbl = getattr(self, "config_ytm_label", None)
        fila = getattr(self, "config_ytm_fila", None)
        try:
            if lbl is None or not lbl.winfo_exists():
                return
        except tk.TclError:
            return
        for w in fila.winfo_children():
            w.destroy()
        estilo = dict(font=("Tahoma", 8), bg=self.c("#E0DFE3"), bd=2, cursor="hand2")
        if self.ytm_conectado:
            lbl.config(text="🟢 Conectado: tus playlists y Me gusta se sincronizan con YouTube Music.",
                       fg=self.c("#1F5F1F", "fg"))
            tk.Button(fila, text="🔄 Sincronizar ahora", command=self.sincronizar_ytm,
                      **dict(estilo, font=("Tahoma", 8, "bold"))).pack(side=tk.LEFT)
            tk.Button(fila, text="Desconectar", command=self.desconectar_ytm, **estilo).pack(side=tk.LEFT, padx=5)
        else:
            lbl.config(text="⚪ Sin conectar. Conecta tu cuenta para traer tus playlists y tus Me gusta.",
                       fg=self.c("#555555", "fg"))
            tk.Button(fila, text="Conectar mi cuenta…", command=self.conectar_ytm,
                      **dict(estilo, font=("Tahoma", 8, "bold"), bg=self.c("#D9F2D9"))).pack(side=tk.LEFT)
        for w in fila.winfo_children():
            w.config(fg=self.c("#000000", "fg"), activebackground=self.c("#D4D0C8"))
