"""Bandeja del sistema (pystray) y mini modo para eXoticPlayer.

- MiniPlayer : ventanita XP sin bordes, siempre encima, arrastrable (recuerda dónde la dejaste).
- TrayManager: icono junto al reloj con menú (mostrar/ocultar, play/pausa, siguiente, anterior,
               mini modo, salir). Si pystray no está instalado, simplemente no hay bandeja.

Reglas de hilos: pystray llama a sus callbacks desde su propio hilo, así que TODO lo que toque Tk
o el reproductor se pasa por app.ui(...) (se ejecuta en el hilo principal).
"""
import json
import os
import tkinter as tk
from tkinter import ttk

import vlc
from PIL import Image

import app_paths

try:
    import pystray
except Exception:   # sin pystray (o sin backend gráfico): la app sigue sin bandeja
    pystray = None

MINI_POS_FILE = os.path.join(app_paths.DATA_DIR, "mini_pos.json")
MINI_W, MINI_H = 470, 128
PORTADA = 84
BARRAS = 22
REFRESCO_MS = 80               # el mini visualizador necesita refrescarse a menudo
MARQUEE_CHARS = 24            # caracteres visibles del título; si es más largo, se desplaza
_ACTIVO = (vlc.State.Playing, vlc.State.Paused, vlc.State.Opening, vlc.State.Buffering)
_RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS


def _fmt(ms):
    m, s = divmod(max(0, int(ms // 1000)), 60)
    return f"{m:02d}:{s:02d}"


def _icono_bandeja(ruta):
    try:
        return Image.open(ruta).convert("RGBA").resize((64, 64), _RESAMPLE)
    except Exception:
        return Image.new("RGBA", (64, 64), (10, 36, 106, 255))   # azul XP si falta el .ico


# ======================================================================
# Mini modo
# ======================================================================
class MiniPlayer:
    def __init__(self, app):
        self.app = app
        self.win = None
        self._job = None
        self._texto = ""
        self._offset = 0
        self._drag = (0, 0)
        self._arrastrando_barra = False
        self._play_txt = None
        self._mostrado = None

    @property
    def visible(self):
        try:
            return self.win is not None and self.win.winfo_exists() and self.win.state() != "withdrawn"
        except tk.TclError:
            return False

    # ------------------------------------------------------------ construcción
    def _construir(self):
        a = self.app
        bg, azul = a.bg_color, a.header_blue
        w = self.win = tk.Toplevel(a.root)
        w.withdraw()
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=azul)
        w.resizable(False, False)

        marco = tk.Frame(w, bg=bg, bd=2, relief=tk.RAISED)
        marco.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # --- barra de título (se arrastra desde aquí)
        barra = tk.Frame(marco, bg=azul, height=20)
        barra.pack(fill=tk.X)
        barra.pack_propagate(False)
        titulo = tk.Label(barra, text="♫ eXotic Mini", bg=azul, fg="white",
                          font=("Tahoma", 8, "bold"), anchor="w", padx=6)
        titulo.pack(side=tk.LEFT, fill=tk.Y)
        for txt, cmd in (("✕", self._cerrar), ("□", a.mostrar_principal)):
            b = tk.Label(barra, text=txt, bg="#316AC5", fg="white", width=3,
                         font=("Tahoma", 8, "bold"), cursor="hand2", relief=tk.RAISED, bd=1)
            b.pack(side=tk.RIGHT, padx=1, pady=1)
            b.bind("<Button-1>", lambda e, c=cmd: c())
        for wdg in (barra, titulo):
            wdg.bind("<ButtonPress-1>", self._iniciar_arrastre)
            wdg.bind("<B1-Motion>", self._arrastrar)
            wdg.bind("<ButtonRelease-1>", lambda e: self._guardar_pos())

        # --- cuerpo: carátula a la izquierda, pantalla y controles a la derecha
        cuerpo = tk.Frame(marco, bg=bg)
        cuerpo.pack(fill=tk.BOTH, expand=True)
        marco_cov = tk.Frame(cuerpo, bg="black", bd=2, relief=tk.SUNKEN, width=PORTADA + 4, height=PORTADA + 4)
        marco_cov.pack(side=tk.LEFT, padx=(6, 0), pady=6)
        marco_cov.pack_propagate(False)
        self.lbl_cover = tk.Label(marco_cov, bg="#101010", fg="#555555", text="♪", font=("Tahoma", 22, "bold"))
        self.lbl_cover.pack(fill=tk.BOTH, expand=True)
        self.lbl_cover.bind("<Double-Button-1>", lambda e: a.mostrar_principal())
        self._cover_url = None
        derecha = tk.Frame(cuerpo, bg=bg)
        derecha.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        marco = derecha

        # --- pantalla LCD
        lcd = tk.Frame(marco, bg=a.lcd_bg, bd=2, relief=tk.SUNKEN)
        lcd.pack(fill=tk.X, padx=6, pady=(6, 0))
        self.lbl_titulo = tk.Label(lcd, bg=a.lcd_bg, fg=a.lcd_green, anchor="w",
                                   font=("Consolas", 10, "bold"), width=MARQUEE_CHARS, text="Nada sonando")
        self.lbl_titulo.pack(side=tk.LEFT, padx=(4, 0))
        self.lbl_tiempo = tk.Label(lcd, bg=a.lcd_bg, fg=a.lcd_green, font=("Consolas", 9), text="")
        self.lbl_tiempo.pack(side=tk.RIGHT, padx=4)
        for wdg in (lcd, self.lbl_titulo, self.lbl_tiempo):
            wdg.bind("<Double-Button-1>", lambda e: a.mostrar_principal())
        # mini visualizador (mismo analizador que el panel principal)
        self.viz = tk.Canvas(marco, height=20, bg=a.lcd_bg, highlightthickness=0)
        self.viz.pack(fill=tk.X, padx=8, pady=(0, 3))
        self._viz_items = []
        self._viz_ancho = 0

        # --- barra de progreso (clic o arrastrar para saltar)
        self.canvas = tk.Canvas(marco, height=8, bg="#0F1F0F", highlightthickness=1,
                                highlightbackground="#555555", cursor="hand2")
        self.canvas.pack(fill=tk.X, padx=6, pady=(0, 4))
        self._barra = self.canvas.create_rectangle(0, 0, 0, 8, fill=a.lcd_green, width=0)
        self.canvas.bind("<ButtonPress-1>", self._barra_mover)
        self.canvas.bind("<B1-Motion>", self._barra_mover)
        self.canvas.bind("<ButtonRelease-1>", self._barra_soltar)

        # --- controles
        fila = tk.Frame(marco, bg=bg)
        fila.pack(fill=tk.X, padx=6, pady=(0, 5))
        fuente = ("Segoe UI Symbol", 9)

        def boton(texto, cmd):
            b = tk.Button(fila, text=texto, width=3, font=fuente, bg="#E0DFE3",
                          relief=tk.RAISED, bd=2, cursor="hand2", command=cmd)
            b.pack(side=tk.LEFT, padx=1)
            return b

        boton("⏮", a.anterior_cancion)
        self.btn_play = boton("▶", a.toggle_play)
        boton("⏭", a.siguiente_cancion)
        boton("⏹", a.detener_cancion)
        tk.Label(fila, text="🔊", bg=bg, font=fuente).pack(side=tk.LEFT, padx=(10, 2))
        self.vol = ttk.Scale(fila, from_=0, to=100, orient=tk.HORIZONTAL, length=70,
                             command=lambda v: a.vol_slider.set(float(v)))
        self.vol.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.btn_like = boton("♡", a.alternar_like_actual)
        self.btn_like.pack_configure(padx=(6, 1))
        if hasattr(a, "tematizar"):
            a.tematizar(w)

    # ------------------------------------------------------------ mostrar / ocultar
    def mostrar(self):
        if self.win is None or not self.win.winfo_exists():
            self._construir()
        w = self.win
        w.update_idletasks()
        x, y = self._posicion_inicial()
        w.geometry(f"{MINI_W}x{MINI_H}+{x}+{y}")
        self.vol.set(self.app.vol_slider.get())
        self._texto, self._offset, self._play_txt, self._mostrado = "", 0, None, None
        w.deiconify()
        w.lift()
        w.attributes("-topmost", True)
        if self._job is not None:
            try:
                w.after_cancel(self._job)
            except Exception:
                pass
        self._refrescar()

    def ocultar(self):
        if self.win is None or not self.win.winfo_exists():
            return
        if self._job is not None:
            try:
                self.win.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        self.win.withdraw()

    def destruir(self):
        try:
            if self.win is not None:
                self.win.destroy()
        except Exception:
            pass
        self.win = None

    def _cerrar(self):
        """✕: manda la app a la bandeja (si hay) o, si no, vuelve a la ventana principal."""
        if self.app.tray.disponible:
            self.app.a_bandeja()
        else:
            self.app.mostrar_principal()

    # ------------------------------------------------------------ posición
    def _posicion_inicial(self):
        w = self.win
        try:
            with open(MINI_POS_FILE, encoding="utf-8") as f:
                d = json.load(f)
            x, y = int(d["x"]), int(d["y"])
            vx, vy = w.winfo_vrootx(), w.winfo_vrooty()
            vw, vh = w.winfo_vrootwidth(), w.winfo_vrootheight()
            if vx <= x <= vx + vw - 60 and vy <= y <= vy + vh - 40:
                return x, y
        except Exception:
            pass
        return w.winfo_screenwidth() - MINI_W - 20, w.winfo_screenheight() - MINI_H - 80

    def _guardar_pos(self):
        try:
            with open(MINI_POS_FILE, "w", encoding="utf-8") as f:
                json.dump({"x": self.win.winfo_x(), "y": self.win.winfo_y()}, f)
        except Exception:
            pass

    def _iniciar_arrastre(self, e):
        self._drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _arrastrar(self, e):
        self.win.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    # ------------------------------------------------------------ barra de progreso
    def _barra_mover(self, e):
        self._arrastrando_barra = True
        ancho = max(1, self.canvas.winfo_width())
        self.canvas.coords(self._barra, 0, 0, min(max(e.x, 0), ancho), 8)

    def _barra_soltar(self, e):
        self._arrastrando_barra = False
        a = self.app
        if a.player.get_state() not in (vlc.State.Playing, vlc.State.Paused):
            return
        largo = a.player.get_length()
        if largo <= 0:
            return
        frac = min(max(e.x / max(1, self.canvas.winfo_width()), 0.0), 1.0)
        a.player.set_time(int(frac * largo))
        a.social.al_seek()          # si hay jam, publica el salto como hace la barra principal

    # ------------------------------------------------------------ refresco
    def _texto_actual(self, estado):
        a = self.app
        if 0 <= a.current_index < len(a.queue) and (a._cargando or estado in _ACTIVO):
            t = a.queue[a.current_index]
            titulo, artista = t.get("title") or "Desconocido", t.get("artist") or ""
            if a._cargando:
                return f"Cargando: {titulo}…"
            return f"{titulo} — {artista}" if artista else titulo
        return "Nada sonando"

    def _pintar_portada(self, cancion):
        url = (cancion or {}).get("coverUrl")
        if url == self._cover_url:
            return
        self._cover_url = url
        if not url:
            self.lbl_cover.config(image="", text="♪")
            self.lbl_cover.image = None
            return
        self.app.cargar_imagen_async(url, PORTADA, self.lbl_cover, vigente=lambda: self._cover_url == url)

    def _pintar_viz(self, sonando):
        c = self.viz
        ancho = c.winfo_width()
        if ancho <= 1:
            return
        if ancho != self._viz_ancho:
            self._viz_ancho = ancho
            c.delete("all")
            paso = ancho / BARRAS
            verde = self.app.c("#00FF66", "fg") if hasattr(self.app, "c") else "#00FF66"
            self._viz_items = [c.create_rectangle(i * paso + 1, 20, (i + 1) * paso - 1, 20, fill=verde, width=0)
                               for i in range(BARRAS)]
            self._viz_niv = [0.0] * BARRAS
        an = getattr(self.app, "analizador", None)
        bandas = getattr(an, "bands", None) if an is not None else None
        for i, item in enumerate(self._viz_items):
            if sonando and bandas is not None and len(bandas):
                objetivo = float(bandas[min(len(bandas) - 1, int(i * len(bandas) / BARRAS))])
            else:
                objetivo = 0.0
            self._viz_niv[i] += (objetivo - self._viz_niv[i]) * 0.5
            x0, _, x1, _ = c.coords(item)
            c.coords(item, x0, 20 - max(1, self._viz_niv[i] * 19), x1, 20)

    def _refrescar(self):
        self._job = None
        if not self.visible:
            return
        a = self.app
        try:
            estado = a.player.get_state()

            # título (con desplazamiento si no cabe)
            texto = self._texto_actual(estado)
            if texto != self._texto:
                self._texto, self._offset = texto, 0
            if len(texto) > MARQUEE_CHARS:
                s = texto + "   ♫   "
                i = self._offset % len(s)
                mostrado = (s + s)[i:i + MARQUEE_CHARS]
                self._tic = getattr(self, '_tic', 0) + 1
                if self._tic % 3 == 0:            # la marquesina va a su ritmo de siempre
                    self._offset += 1
            else:
                mostrado = texto
            if mostrado != self._mostrado:
                self._mostrado = mostrado
                self.lbl_titulo.config(text=mostrado)

            # botón play/pausa
            play = "⏸" if estado == vlc.State.Playing else "▶"
            if play != self._play_txt:
                self._play_txt = play
                self.btn_play.config(text=play)
            c = a._cancion_actual() if hasattr(a, "_cancion_actual") else None
            corazon = "♥" if c and a._es_favorita(c.get("videoId")) else "♡"
            if self.btn_like.cget("text") != corazon:
                self.btn_like.config(text=corazon)
            self._pintar_portada(c if (c and (a._cargando or estado in _ACTIVO)) else None)
            self._pintar_viz(estado == vlc.State.Playing)

            # tiempo y progreso
            if estado in (vlc.State.Playing, vlc.State.Paused):
                t, largo = a.player.get_time(), a.player.get_length()
                if largo > 0 and t >= 0:
                    self.lbl_tiempo.config(text=f"{_fmt(t)}/{_fmt(largo)}")
                    if not self._arrastrando_barra:
                        ancho = self.canvas.winfo_width()
                        self.canvas.coords(self._barra, 0, 0, ancho * t / largo, 8)
            elif not a._cargando:
                self.lbl_tiempo.config(text="")
                if not self._arrastrando_barra:
                    self.canvas.coords(self._barra, 0, 0, 0, 8)
        except tk.TclError:
            return
        except Exception as e:
            print(f"Mini modo: error al refrescar: {e}")
        self._job = self.win.after(REFRESCO_MS, self._refrescar)


# ======================================================================
# Bandeja del sistema
# ======================================================================
class TrayManager:
    def __init__(self, app, ruta_icono):
        self.app = app
        self.ruta_icono = ruta_icono
        self.icon = None
        self._titulo = ""
        self._avisado = False

    @property
    def disponible(self):
        return self.icon is not None

    def _cb(self, fn):
        """Callback de pystray (otro hilo) -> se ejecuta en el hilo de Tk."""
        return lambda icon, item: self.app.ui(fn)

    def _sonando(self):
        try:
            return self.app.player.get_state() == vlc.State.Playing
        except Exception:
            return False

    def start(self):
        if pystray is None:
            print("pystray no instalado: sin icono en la bandeja.")
            return
        a = self.app
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Mostrar / ocultar eXotic", self._cb(a.alternar_principal), default=True),
                pystray.MenuItem(lambda item: "Pausar" if self._sonando() else "Reproducir",
                                 self._cb(a.toggle_play)),
                pystray.MenuItem("Siguiente", self._cb(a.siguiente_cancion)),
                pystray.MenuItem("Anterior", self._cb(a.anterior_cancion)),
                pystray.MenuItem("♥ Me gusta (canción actual)", self._cb(a.alternar_like_actual)),
                pystray.MenuItem("Silenciar", self._cb(a.alternar_silencio),
                                 checked=lambda item: bool(a.prefs.get("muted"))),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Mini modo", self._cb(a.mostrar_mini)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Salir", self._cb(a.al_cerrar)),
            )
            self.icon = pystray.Icon("eXoticPlayer", _icono_bandeja(self.ruta_icono),
                                     "eXotic Media Player", menu)
            self.icon.run_detached()
        except Exception as e:
            print(f"No se pudo crear el icono de la bandeja: {e}")
            self.icon = None
            return
        a.root.after(1500, self._vigilar)

    def _titulo_actual(self):
        a = self.app
        if 0 <= a.current_index < len(a.queue) and a.player.get_state() in _ACTIVO:
            t = a.queue[a.current_index]
            txt = f"{t.get('title') or 'Desconocido'} — {t.get('artist') or ''}".rstrip(" —")
            return ("⏸ " if a.player.get_state() == vlc.State.Paused else "▶ ") + txt
        return "eXotic Media Player"

    def _vigilar(self):
        """El texto al pasar el ratón por el icono muestra la canción actual."""
        if self.icon is None:
            return
        try:
            t = self._titulo_actual()[:120]        # Windows corta el tooltip a ~127 caracteres
            if t != self._titulo:
                self._titulo = t
                self.icon.title = t
        except Exception:
            pass
        self.app.root.after(2000, self._vigilar)

    def avisar_una_vez(self):
        """Globo de aviso la primera vez que la app se manda a la bandeja en esta sesión."""
        if self._avisado or self.icon is None:
            return
        self._avisado = True
        try:
            self.icon.notify("Sigue sonando desde la bandeja. Clic en el icono para abrirla.",
                             "eXotic Media Player")
        except Exception:
            pass

    def stop(self):
        icon, self.icon = self.icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
