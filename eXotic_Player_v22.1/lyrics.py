"""Letras de canciones (YouTube Music) con resaltado sincronizado si existe.

- ``obtener_letra(ytmusic, video_id)`` -> dict normalizado (se llama en un hilo).
- ``linea_actual(lineas, ms)``         -> índice de la línea que toca (función pura).
- ``VentanaLetra``                      -> ventana que sigue la canción que suena.
"""
import bisect
import tkinter as tk


def _attr(obj, *nombres, defecto=None):
    for n in nombres:
        if isinstance(obj, dict) and n in obj:
            return obj[n]
        if hasattr(obj, n):
            return getattr(obj, n)
    return defecto


def normalizar_letra(res):
    """Convierte la respuesta de ytmusicapi (cualquier versión) a
    {"texto": str, "lineas": [(inicio_ms, texto)], "fuente": str}."""
    if not res:
        return None
    letra = _attr(res, "lyrics")
    fuente = str(_attr(res, "source", defecto="") or "")
    lineas = []
    if isinstance(letra, (list, tuple)):
        for ln in letra:
            texto = str(_attr(ln, "text", defecto="") or "")
            ini = _attr(ln, "start_time", "startTime", defecto=None)
            try:
                ini = int(ini)
            except (TypeError, ValueError):
                ini = None
            lineas.append((ini, texto))
        texto_plano = "\n".join(t for _, t in lineas)
        if lineas and all(i is not None for i, _ in lineas):
            lineas.sort(key=lambda x: x[0])
        else:
            lineas = []
    else:
        texto_plano = str(letra or "")
    if not texto_plano.strip():
        return None
    return {"texto": texto_plano, "lineas": lineas, "fuente": fuente}


def obtener_letra(ytmusic, video_id):
    """Busca la letra de un videoId. Devuelve el dict normalizado o None."""
    wp = ytmusic.get_watch_playlist(videoId=video_id, limit=1)
    browse = (wp or {}).get("lyrics")
    if not browse:
        return None
    try:
        res = ytmusic.get_lyrics(browse, timestamps=True)
    except TypeError:            # ytmusicapi antiguo: sin letras sincronizadas
        res = ytmusic.get_lyrics(browse)
    except Exception:
        res = ytmusic.get_lyrics(browse)
    return normalizar_letra(res)


def linea_actual(lineas, ms):
    """Índice de la última línea cuyo inicio es <= ms (o -1)."""
    if not lineas:
        return -1
    inicios = [i for i, _ in lineas]
    return bisect.bisect_right(inicios, ms) - 1


class CacheLetras:
    """Letras ya buscadas (las comparten la ventana de letra y el Soundscope)."""
    MAX = 200

    def __init__(self, app):
        self.app = app
        self._datos = {}
        self._pendientes = {}

    @staticmethod
    def _id(cancion):
        vid = (cancion or {}).get("videoId") or ""
        return None if not vid or vid.startswith("file:") else vid      # archivos locales: sin letra

    def obtener(self, cancion):
        """(letra_o_None, buscando). Si no la tiene, la pide en segundo plano."""
        vid = self._id(cancion)
        if vid is None:
            return None, False
        if vid in self._datos:
            return self._datos[vid], False
        self.pedir(cancion)
        return None, True

    def pedir(self, cancion, callback=None):
        vid = self._id(cancion)
        if vid is None:
            if callback:
                callback(None)
            return
        if vid in self._datos:
            if callback:
                callback(self._datos[vid])
            return
        esperando = self._pendientes.get(vid)
        if esperando is not None:
            if callback:
                esperando.append(callback)
            return
        self._pendientes[vid] = [callback] if callback else []

        def task():
            try:
                letra = obtener_letra(self.app.ytmusic, vid)
            except Exception as e:
                print(f"[letra] {e}")
                letra = None
            self.app.ui(self._recibida, vid, letra)

        self.app.pool_stream.submit(task)

    def _recibida(self, vid, letra):
        if len(self._datos) >= self.MAX:
            self._datos.pop(next(iter(self._datos)))
        self._datos[vid] = letra
        for cb in self._pendientes.pop(vid, []):
            try:
                cb(letra)
            except Exception as e:
                print(f"[letra] {e}")


class VentanaLetra:
    REFRESCO_MS = 200

    def __init__(self, app):
        self.app = app
        self.top = None
        self._vid = None
        self._letra = None
        self._linea = -2
        self._job = None
        self._peticion = 0

    @property
    def abierta(self):
        try:
            return self.top is not None and self.top.winfo_exists()
        except tk.TclError:
            return False

    def alternar(self):
        if self.abierta:
            self.cerrar()
        else:
            self.abrir()

    def abrir(self):
        if self.abierta:
            self.top.lift()
            return
        a = self.app
        top = self.top = tk.Toplevel(a.root)
        top.title("📝 Letra — eXotic Player")
        top.geometry(f"440x560+{a.root.winfo_rootx() + a.root.winfo_width() - 470}+{a.root.winfo_rooty() + 60}")
        top.minsize(300, 300)
        top.configure(bg=a.bg_color)
        top.protocol("WM_DELETE_WINDOW", self.cerrar)
        top.bind("<Escape>", lambda e: self.cerrar())

        cab = tk.Frame(top, bg=a.header_blue, height=34)
        cab.pack(fill=tk.X)
        cab.pack_propagate(False)
        self.lbl_titulo = tk.Label(cab, text="Letra", bg=a.header_blue, fg="white",
                                   font=("Tahoma", 9, "bold"), anchor="w", padx=8)
        self.lbl_titulo.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        marco = tk.Frame(top, bg="#FFFFFF", relief=tk.SUNKEN, bd=2)
        marco.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        sb = tk.Scrollbar(marco)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt = tk.Text(marco, wrap="word", font=("Tahoma", 11), bg="#FFFFFF", fg="#333333",
                           relief=tk.FLAT, padx=12, pady=10, spacing1=3, spacing3=3,
                           yscrollcommand=sb.set, cursor="arrow")
        self.txt.pack(fill=tk.BOTH, expand=True)
        sb.config(command=self.txt.yview)
        self.txt.tag_configure("centro", justify="center")
        self.txt.tag_configure("activa", font=("Tahoma", 13, "bold"))
        self.colorear()

        self.lbl_info = tk.Label(top, text="", bg=a.bg_color, fg="#555555", font=("Tahoma", 7),
                                 anchor="w")
        self.lbl_info.pack(fill=tk.X, padx=10, pady=(0, 6))
        if hasattr(a, "tema"):
            a.tema.aplicar_arbol(top)
        self._vid = None
        self._tick()

    def colorear(self):
        """Colores de las líneas según el tema (los 'tags' de Text no se tematizan solos)."""
        if not self.abierta:
            return
        c = getattr(self.app, "c", lambda b, t="bg": b)
        self.txt.tag_configure("activa", foreground=c("#0A246A", "fg"))
        self.txt.tag_configure("pasada", foreground=c("#999999", "fg"))

    def cerrar(self):
        if self._job is not None and self.abierta:
            try:
                self.top.after_cancel(self._job)
            except tk.TclError:
                pass
        self._job = None
        if self.top is not None:
            try:
                self.top.destroy()
            except tk.TclError:
                pass
        self.top = None

    # ------------------------------------------------------------------
    def _cancion(self):
        a = self.app
        if 0 <= a.current_index < len(a.queue):
            return a.queue[a.current_index]
        return None

    def _poner_texto(self, texto, info=""):
        self.txt.config(state=tk.NORMAL)
        self.txt.delete("1.0", tk.END)
        self.txt.insert("1.0", texto, "centro")
        self.txt.config(state=tk.DISABLED)
        self.lbl_info.config(text=info)
        self._linea = -2

    def _cargar(self, cancion):
        self._vid = cancion["videoId"]
        self._letra = None
        self.lbl_titulo.config(text=f"{cancion.get('title', '')} — {cancion.get('artist', '')}"[:70])
        self._poner_texto("\n\nBuscando la letra…")
        self._peticion += 1
        pet = self._peticion
        if self._vid.startswith("file:"):
            self._poner_texto("\n\nLas letras solo están disponibles para canciones de YouTube Music.")
            return
        self.app.letras.pedir(cancion, lambda letra: self._letra_recibida(pet, letra))

    def _letra_recibida(self, pet, letra):
        if pet != self._peticion or not self.abierta:
            return
        self._letra = letra
        if not letra:
            self._poner_texto("\n\nNo hay letra disponible para esta canción.")
            return
        if letra["lineas"]:
            self.txt.config(state=tk.NORMAL)
            self.txt.delete("1.0", tk.END)
            for _, linea in letra["lineas"]:
                self.txt.insert(tk.END, (linea or "♪") + "\n", "centro")
            self.txt.config(state=tk.DISABLED)
            self._linea = -2
            info = "Letra sincronizada"
        else:
            self._poner_texto(letra["texto"])
            info = "Letra"
        if letra.get("fuente"):
            info += f" · {letra['fuente']}"
        self.lbl_info.config(text=info)

    def _resaltar(self, ms):
        lineas = self._letra["lineas"]
        i = linea_actual(lineas, ms)
        if i == self._linea:
            return
        self._linea = i
        t = self.txt
        t.tag_remove("activa", "1.0", tk.END)
        t.tag_remove("pasada", "1.0", tk.END)
        if i >= 1:
            t.tag_add("pasada", "1.0", f"{i + 1}.0")
        if i >= 0:
            t.tag_add("activa", f"{i + 1}.0", f"{i + 1}.end")
            # deja la línea activa hacia el tercio superior de la ventana
            t.see(f"{min(len(lineas), i + 6)}.0")
            t.see(f"{i + 1}.0")

    def _tick(self):
        self._job = None
        if not self.abierta:
            return
        try:
            c = self._cancion()
            if c is None:
                if self._vid is not None or self._linea != -3:
                    self._vid = None
                    self.lbl_titulo.config(text="Letra")
                    self._poner_texto("\n\nNo suena nada.")
                    self._linea = -3
            elif c["videoId"] != self._vid:
                self._cargar(c)
            elif self._letra and self._letra["lineas"]:
                ms = self.app.player.get_time()
                if ms >= 0:
                    self._resaltar(ms + 150)       # pequeño adelanto: se lee antes de oírse
        except tk.TclError:
            return
        except Exception as e:
            print(f"[letra] {e}")
        self._job = self.top.after(self.REFRESCO_MS, self._tick)
