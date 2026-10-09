"""Visor de videoclips para eXotic Player.

Ventana con el vídeo de VLC embebido. Se puede pasar a pantalla completa
(doble clic o F), y tiene una barra con los controles básicos.

Atajos: Espacio pausa | ← → anterior/siguiente | ↑ ↓ volumen | F o doble clic
pantalla completa | Esc sale de pantalla completa (o cierra) | A solo audio.
"""
import sys
import tkinter as tk


class VisorVideo:
    def __init__(self, app):
        self.app = app
        self.top = None
        self.fullscreen = False

    @property
    def abierto(self):
        return self.top is not None and self.top.winfo_exists()

    # -- ciclo de vida ------------------------------------------------------
    def mostrar(self, titulo=""):
        """Crea la ventana si hace falta y engancha el vídeo de VLC en ella."""
        if not self.abierto:
            self._crear()
        if titulo:
            self.top.title(f"🎬 {titulo}")
        try:
            self.top.deiconify()
            self.top.update_idletasks()
        except Exception:
            pass
        self._enganchar()

    def ocultar(self):
        """Cierra el visor (no toca la reproducción)."""
        if self.top is not None:
            try:
                self.top.destroy()
            except Exception:
                pass
        self.top = None
        self.fullscreen = False

    def _crear(self):
        root = self.app.root
        top = self.top = tk.Toplevel(root)
        top.configure(bg="black")
        top.title("🎬 Videoclip")
        w = min(960, int(root.winfo_screenwidth() * 0.6))
        top.geometry(f"{w}x{int(w * 9 / 16) + 34}+80+60")
        top.minsize(320, 220)

        self.frame = tk.Frame(top, bg="black")
        self.frame.pack(fill=tk.BOTH, expand=True)

        self.barra = tk.Frame(top, bg="#1B2A6B", height=34)
        self.barra.pack(fill=tk.X, side=tk.BOTTOM)
        self.barra.pack_propagate(False)
        estilo = dict(font=("Tahoma", 9, "bold"), bg="#3A5BC7", fg="white",
                      activebackground="#5577E0", activeforeground="white",
                      relief=tk.RAISED, bd=2, cursor="hand2")
        for texto, cmd in (("⏮", lambda: self.app.anterior_cancion()),
                           ("⏯", lambda: self.app.toggle_play()),
                           ("⏭", lambda: self.app.siguiente_cancion()),
                           ("⛶ Pantalla completa", self.alternar_pantalla_completa),
                           ("🎵 Solo audio", lambda: self.app.desactivar_videoclip())):
            tk.Button(self.barra, text=texto, command=cmd, **estilo).pack(side=tk.LEFT, padx=3, pady=3)

        top.bind("<space>", lambda e: self.app.toggle_play())
        top.bind("<Left>", lambda e: self.app.anterior_cancion())
        top.bind("<Right>", lambda e: self.app.siguiente_cancion())
        top.bind("<Up>", lambda e: self._volumen(5))
        top.bind("<Down>", lambda e: self._volumen(-5))
        top.bind("<MouseWheel>", lambda e: self._volumen(5 if e.delta > 0 else -5))
        top.bind("<f>", lambda e: self.alternar_pantalla_completa())
        top.bind("<F>", lambda e: self.alternar_pantalla_completa())
        top.bind("<Double-Button-1>", lambda e: self.alternar_pantalla_completa())
        top.bind("<a>", lambda e: self.app.desactivar_videoclip())
        top.bind("<A>", lambda e: self.app.desactivar_videoclip())
        top.bind("<Escape>", self._escape)
        top.protocol("WM_DELETE_WINDOW", lambda: self.app.desactivar_videoclip())
        top.focus_force()

    def _enganchar(self):
        """Le dice a VLC dónde dibujar el vídeo."""
        p = self.app.player
        try:
            wid = self.frame.winfo_id()
            if sys.platform.startswith("win"):
                p.set_hwnd(wid)
            elif sys.platform == "darwin":
                p.set_nsobject(wid)
            else:
                p.set_xwindow(wid)
            # que el ratón y el teclado los reciba Tk y no la ventana de VLC
            p.video_set_mouse_input(False)
            p.video_set_key_input(False)
        except Exception as e:
            print(f"Visor: no se pudo enganchar el vídeo ({e})")

    # -- acciones --------------------------------------------------------------
    def alternar_pantalla_completa(self):
        if not self.abierto:
            return
        self.fullscreen = not self.fullscreen
        self.top.attributes("-fullscreen", self.fullscreen)
        if self.fullscreen:
            self.barra.pack_forget()
            self.top.configure(cursor="none")
        else:
            self.barra.pack(fill=tk.X, side=tk.BOTTOM)
            self.top.configure(cursor="arrow")
        self.top.focus_force()

    def _escape(self, e=None):
        if self.fullscreen:
            self.alternar_pantalla_completa()
        else:
            self.app.desactivar_videoclip()

    def _volumen(self, delta):
        try:
            v = max(0, min(100, float(self.app.vol_slider.get()) + delta))
            self.app.vol_slider.set(v)
            self.app.cambiar_volumen(v)
        except Exception:
            pass
