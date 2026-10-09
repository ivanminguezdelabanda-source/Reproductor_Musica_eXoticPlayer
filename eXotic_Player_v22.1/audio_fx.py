"""Efectos de reproducción: velocidad/tono (slowed, nightcore...) e igualar el volumen.

- Velocidad y tono: VLC se arranca con ``--no-audio-time-stretch``, así que al cambiar la
  velocidad cambia también el tono, como en los "slowed" y "nightcore".
- Igualar volumen: YouTube indica en cada canción cuánto más fuerte o más suave suena que su
  referencia (``loudnessDb``). Se compensa con el preamplificador del ecualizador, igual que
  hace YouTube. Las canciones del ordenador no traen ese dato y suenan tal cual.
- La reverb no se puede añadir: libVLC no deja activar sus filtros de audio desde el programa.
"""
import tkinter as tk

MODOS = (
    ("normal", "Normal", 1.00),
    ("slowed", "Slowed  (−15 %)", 0.85),
    ("muy_slowed", "Muy slowed  (−25 %)", 0.75),
    ("speed_up", "Speed up  (+15 %)", 1.15),
    ("nightcore", "Nightcore  (+25 %)", 1.25),
)
VELOCIDAD = {k: v for k, _, v in MODOS}
NOMBRE = {k: n.split("  ")[0] for k, n, _ in MODOS}
MAX_SUBIR_DB = 3.0          # como mucho se sube un poco (más podría saturar)
MAX_BAJAR_DB = 12.0


def extraer_loudness(respuesta):
    """Busca 'loudnessDb' en la respuesta del reproductor de YouTube (cualquier formato)."""
    if not isinstance(respuesta, dict):
        return None
    cfg = ((respuesta.get("playerConfig") or {}).get("audioConfig") or {})
    if isinstance(cfg.get("loudnessDb"), (int, float)):
        return float(cfg["loudnessDb"])
    formatos = (respuesta.get("streamingData") or {}).get("adaptiveFormats") or []
    valores = [f.get("loudnessDb") for f in formatos
               if isinstance(f, dict) and str(f.get("mimeType", "")).startswith("audio")
               and isinstance(f.get("loudnessDb"), (int, float))]
    if valores:
        return float(sum(valores) / len(valores))
    return None


def ganancia(loudness_db):
    """dB que hay que sumar para que la canción suene como la referencia."""
    if loudness_db is None:
        return 0.0
    return max(-MAX_BAJAR_DB, min(MAX_SUBIR_DB, -float(loudness_db)))


class PlayerAudioFxMixin:
    @property
    def modo_audio(self):
        m = self.prefs.get("audio_mode", "normal")
        return m if m in VELOCIDAD else "normal"

    def velocidad_actual(self):
        return 1.0 if self._en_jam() else VELOCIDAD[self.modo_audio]

    def aplicar_velocidad(self, player=None):
        try:
            (player or self.player).set_rate(self.velocidad_actual())
        except Exception as e:
            print(f"[fx] velocidad: {e}")

    def cambiar_modo_audio(self, modo):
        if modo not in VELOCIDAD:
            return
        if self._en_jam() and modo != "normal":
            self.status_var.set("En una jam todos tienen que oír lo mismo: los efectos de velocidad no se pueden usar.")
            return
        self.prefs["audio_mode"] = modo
        self._guardar_prefs()
        self.aplicar_velocidad()
        var = getattr(self, "_fx_var", None)
        if var is not None:
            var.set(modo)
        self.status_var.set("🎚 Velocidad normal." if modo == "normal" else f"🎚 Modo {NOMBRE[modo]} activado.")
        self._actualizar_boton_fx()

    def _actualizar_boton_fx(self):
        b = getattr(self, "fx_btn", None)
        if b is None:
            return
        activo = self.modo_audio != "normal"
        b.config(text=f"🎚 {NOMBRE[self.modo_audio]}" if activo else "🎚 Efectos",
                 relief=tk.SUNKEN if activo else tk.RAISED,
                 bg=self.c("#C8E8C8" if activo else "#E0DFE3"))

    def menu_efectos(self, widget=None):
        menu = tk.Menu(self.root, tearoff=0, font=("Tahoma", 9))
        self._fx_var = tk.StringVar(value=self.modo_audio)
        for clave, nombre, _ in MODOS:
            menu.add_radiobutton(label=nombre, value=clave, variable=self._fx_var,
                                 command=lambda c=clave: self.cambiar_modo_audio(c))
        menu.add_separator()
        self._norm_var = tk.BooleanVar(value=bool(self.prefs.get("normalize", True)))
        menu.add_checkbutton(label="Igualar volumen entre canciones", variable=self._norm_var,
                             command=lambda: self.cambiar_normalizar(self._norm_var.get()))
        w = widget or getattr(self, "fx_btn", None) or self.root
        try:
            menu.tk_popup(w.winfo_rootx(), w.winfo_rooty() + w.winfo_height())
        finally:
            menu.grab_release()

    # -- igualar volumen ----------------------------------------------------------
    def cambiar_normalizar(self, activo):
        self.prefs["normalize"] = bool(activo)
        self._guardar_prefs()
        self.status_var.set("🔉 Volumen igualado entre canciones." if activo else "Igualar volumen desactivado.")
        self._ajustar_volumen_cancion(self._cancion_actual())

    def _ajustar_volumen_cancion(self, cancion):
        """Pone la ganancia de la canción que suena (la busca en segundo plano si hace falta)."""
        vid = (cancion or {}).get("videoId") or ""
        if not self.prefs.get("normalize", True) or not vid or vid.startswith("file:"):
            self._poner_ganancia(0.0)
            return
        cache = self.__dict__.setdefault("_loudness", {})
        if vid in cache:
            self._poner_ganancia(ganancia(cache[vid]))
            return

        def task():
            try:
                valor = extraer_loudness(self.ytmusic.get_song(vid))
            except Exception as e:
                print(f"[fx] loudness de {vid}: {e}")
                valor = None
            cache[vid] = valor
            self.ui(self._ganancia_recibida, vid)

        self.pool_img.submit(task)

    def _ganancia_recibida(self, vid):
        c = self._cancion_actual()
        if c and c.get("videoId") == vid:
            self._poner_ganancia(ganancia(self.__dict__.get("_loudness", {}).get(vid)))

    def _poner_ganancia(self, db):
        if abs(float(self.vlc_eq.extra_db or 0) - db) < 0.05:
            return
        self.vlc_eq.extra_db = db
        self.vlc_eq.aplicar()
