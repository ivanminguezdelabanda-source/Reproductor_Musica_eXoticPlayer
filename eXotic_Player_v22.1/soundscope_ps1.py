"""Soundscope PS1 para eXotic Player.

Visualizador a pantalla completa con estética de los reproductores de CD de la
PlayStation 1: render a baja resolución, color de 15 bits con dithering,
polígonos planos, vórtices de checkers y menús azules.

Escenas: VÓRTICE, TERRENO, CRISTAL, OSCILOSCOPIO, FEEDBACK (estilo Milkdrop),
TÚNEL (con la portada como textura), TORRES (inspirada en el menú de la memory card
de la PS2), CUBO (cubo de cubos que se abre con el ritmo) y KARAOKE (letra sincronizada).
Los colores salen de la portada de la canción que suena.

Piezas:
  * ``AudioAnalyzer``  -> espectro / forma de onda / beats. Usa captura WASAPI
    loopback (pyaudiowpatch) para analizar el audio REAL que suena; si no está
    disponible cae a un espectro simulado para que nunca se quede en blanco.
  * ``Renderer``       -> genera cada frame (PIL + numpy), sin depender de Tk.
  * ``SoundscopeVentana`` -> ventana Toplevel a pantalla completa con controles.
"""
import math
import random
import threading
import time
import urllib.request
import io
import textwrap
import tkinter as tk

try:
    import numpy as np
except Exception:               # sin numpy no hay Soundscope (se avisa al abrirlo)
    np = None

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageTk

NB = 32                         # bandas de espectro
ESCENAS = ["VORTICE", "TERRENO", "CRISTAL", "OSCILOSCOPIO", "FEEDBACK", "TUNEL", "TORRES", "CUBO", "KARAOKE"]
KARAOKE = ESCENAS.index("KARAOKE")
TEX = 64                        # tamaño de la textura del túnel
TRANSICION_S = 0.9


# ---------------------------------------------------------------------------
# Análisis de audio
# ---------------------------------------------------------------------------
class AudioAnalyzer:
    """Extrae bandas, onda y beat del audio del sistema (o los simula)."""

    FFT_N = 2048

    def __init__(self):
        self.modo = "simulado"          # "real" cuando la captura loopback funciona
        self.bands = np.zeros(NB, dtype=np.float32)
        self.peaks = np.zeros(NB, dtype=np.float32)
        self.wave = np.zeros(512, dtype=np.float32)
        self.level = 0.0
        self.beat = 0.0
        self._pa = None
        self._stream = None
        self._sr = 44100
        self._ch = 2
        self._buf = np.zeros(4096, dtype=np.float32)
        self._lock = threading.Lock()
        self._ultimo_dato = 0.0
        self._ref = 0.6
        self._bass_avg = 0.0
        self._t_beat = 0.0
        self._t = 0.0
        self._ruido = np.zeros(NB, dtype=np.float32)
        self._edges = None

    # -- captura -----------------------------------------------------------
    def iniciar(self):
        try:
            import pyaudiowpatch as pyaudio
            pa = pyaudio.PyAudio()
            wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            salida = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
            if not salida.get("isLoopbackDevice"):
                for lb in pa.get_loopback_device_info_generator():
                    if salida["name"] in lb["name"]:
                        salida = lb
                        break
            self._sr = int(salida["defaultSampleRate"])
            self._ch = max(1, int(salida["maxInputChannels"]))

            def cb(in_data, frame_count, time_info, status):
                try:
                    x = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
                    if self._ch > 1:
                        x = x[: (len(x) // self._ch) * self._ch].reshape(-1, self._ch).mean(axis=1)
                    with self._lock:
                        self._buf = np.concatenate((self._buf, x))[-4096:]
                        self._ultimo_dato = time.time()
                except Exception:
                    pass
                return (None, pyaudio.paContinue)

            self._stream = pa.open(
                format=pyaudio.paInt16, channels=self._ch, rate=self._sr,
                frames_per_buffer=1024, input=True,
                input_device_index=salida["index"], stream_callback=cb)
            self._pa = pa
            self.modo = "real"
        except Exception as e:
            print(f"Soundscope: captura de audio no disponible ({e}); uso espectro simulado.")
            self.modo = "simulado"
        nyq = self._sr / 2
        self._edges = np.geomspace(35, min(16000, nyq * 0.95), NB + 1)

    def detener(self):
        try:
            if self._stream is not None:
                self._stream.stop_stream()
                self._stream.close()
            if self._pa is not None:
                self._pa.terminate()
        except Exception:
            pass
        self._stream = self._pa = None

    # -- actualización por frame --------------------------------------------
    def actualizar(self, sonando, dt):
        self._t += dt
        if self.modo == "real":
            self._actualizar_real()
        else:
            self._actualizar_simulado(sonando)
        self.level = float(self.bands.mean())
        # beat con los graves
        bass = float(self.bands[:4].mean())
        self._bass_avg = 0.93 * self._bass_avg + 0.07 * bass
        ahora = time.time()
        if bass > self._bass_avg * 1.25 + 0.06 and ahora - self._t_beat > 0.20:
            self.beat = 1.0
            self._t_beat = ahora
        self.beat *= 0.86 ** (dt * 30)
        self.peaks = np.maximum(self.bands, self.peaks - dt * 0.6)

    def _suavizar(self, nuevo):
        subida = nuevo > self.bands
        self.bands = np.where(subida,
                              self.bands + (nuevo - self.bands) * 0.65,
                              self.bands + (nuevo - self.bands) * 0.18).astype(np.float32)

    def _actualizar_real(self):
        with self._lock:
            x = self._buf[-self.FFT_N:].copy()
            fresco = time.time() - self._ultimo_dato < 0.4
        if not fresco or float(np.abs(x).max()) < 1e-4:
            self._suavizar(np.zeros(NB, dtype=np.float32))
            self.wave *= 0.8
            return
        win = np.hanning(len(x)).astype(np.float32)
        mag = np.abs(np.fft.rfft(x * win)) / (len(x) / 4)
        freqs = np.fft.rfftfreq(len(x), 1.0 / self._sr)
        nuevo = np.zeros(NB, dtype=np.float32)
        for i in range(NB):
            lo = int(np.searchsorted(freqs, self._edges[i]))
            hi = max(lo + 1, int(np.searchsorted(freqs, self._edges[i + 1])))
            nuevo[i] = mag[lo:hi].max() if hi > lo else 0.0
        db = 20 * np.log10(nuevo + 1e-9)
        tilt = np.linspace(0.0, 14.0, NB, dtype=np.float32)       # compensa la caída de agudos
        v = np.clip((db + tilt + 70.0) / 60.0, 0.0, 1.0)
        self._ref = max(self._ref * 0.998, float(v.max()), 0.45)  # AGC lento
        v = np.clip(v / self._ref, 0.0, 1.0) ** 1.4
        self._suavizar(v)
        w = x[-512:]
        pico = float(np.abs(w).max()) + 1e-6
        self.wave = (w / max(pico, 0.15)).astype(np.float32)

    def _actualizar_simulado(self, sonando):
        t = self._t
        if not sonando:
            self._suavizar(np.zeros(NB, dtype=np.float32))
            self.wave *= 0.9
            return
        fase = (t * 2.0) % 1.0                                   # ~120 bpm
        kick = math.exp(-fase * 6.0)
        hat = math.exp(-((t * 4.0) % 1.0) * 9.0)
        idx = np.arange(NB, dtype=np.float32)
        graves = np.exp(-idx / 5.0) * kick
        medios = np.exp(-((idx - 14) ** 2) / 60.0) * (0.35 + 0.25 * math.sin(t * 1.3))
        agudos = np.exp(-((idx - 26) ** 2) / 40.0) * hat * 0.6
        self._ruido = self._ruido * 0.8 + np.random.rand(NB).astype(np.float32) * 0.2
        v = np.clip(graves * 1.05 + medios * (0.6 + self._ruido) + agudos + self._ruido * 0.12, 0, 1)
        self._suavizar(v.astype(np.float32))
        n = np.arange(512, dtype=np.float32)
        self.wave = (0.5 * np.sin(n * 0.09 + t * 9) * (0.4 + kick)
                     + 0.25 * np.sin(n * 0.31 + t * 17) + 0.02 * np.random.randn(512)).astype(np.float32)


# ---------------------------------------------------------------------------
# Utilidades gráficas
# ---------------------------------------------------------------------------
def _hsv_paleta(n=256):
    h = np.linspace(0, 1, n, endpoint=False)
    s, v = 0.85, 1.0
    i = (h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r = np.choose(i, [v + 0 * h, q, p, p, t, v + 0 * h])
    g = np.choose(i, [t, v + 0 * h, v + 0 * h, q, p, p])
    b = np.choose(i, [p, p, t, v + 0 * h, v + 0 * h, q])
    return np.stack([r, g, b], axis=1).astype(np.float32)


PALETA = None


def _color(h, bri=1.0):
    c = PALETA[int(h * 255) % 256] * bri
    return tuple(int(max(0, min(255, v * 255))) for v in c)


def paleta_desde_imagen(img, n=5):
    """Paleta cíclica de 256 colores (float 0..1) con los colores dominantes de una imagen.

    Se suben saturación y brillo para que una portada apagada siga luciendo, y se ordenan
    por tono para que el degradado sea suave. Función pura (se prueba sin Tk)."""
    import colorsys
    peq = img.convert("RGB").resize((48, 48))
    try:
        q = peq.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    except AttributeError:                      # Pillow antiguo
        q = peq.quantize(colors=n)
    pal = q.getpalette() or []
    usos = sorted(q.getcolors() or [], reverse=True)
    colores = []
    for _, i in usos:
        r, g, b = (c / 255.0 for c in pal[i * 3:i * 3 + 3])
        h, s_, v = colorsys.rgb_to_hsv(r, g, b)
        s_ = max(s_, 0.45) if s_ > 0.08 else s_          # los grises se quedan grises
        v = max(v, 0.60)
        colores.append((h, colorsys.hsv_to_rgb(h, s_, v)))
    if not colores:
        return _hsv_paleta()
    if len(colores) == 1:                                   # un solo color: degradado con su complementario
        h, c = colores[0]
        colores.append(((h + 0.5) % 1, colorsys.hsv_to_rgb((h + 0.5) % 1, 0.6, 0.9)))
    colores.sort(key=lambda x: x[0])
    nodos = np.array([c for _, c in colores] + [colores[0][1]], dtype=np.float32)   # cíclica
    pos = np.linspace(0, 1, len(nodos))
    x = np.linspace(0, 1, 256, endpoint=False)
    return np.stack([np.interp(x, pos, nodos[:, k]) for k in range(3)], axis=1).astype(np.float32)


def textura_desde_imagen(img):
    """Textura TEX×TEX (float 0..1) para el túnel."""
    return np.asarray(img.convert("RGB").resize((TEX, TEX), Image.BILINEAR), dtype=np.float32) / 255.0


def _limpiar(s):
    return "".join(c if ord(c) < 256 else "?" for c in (s or ""))


def _icosfera():
    """Icosaedro subdividido una vez (42 vértices, 80 caras)."""
    t = (1 + 5 ** 0.5) / 2
    v = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t),
         (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    f = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2),
         (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5),
         (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    verts = [np.array(p, dtype=np.float32) / np.linalg.norm(p) for p in v]
    cache = {}

    def medio(a, b):
        k = (min(a, b), max(a, b))
        if k not in cache:
            m = (verts[a] + verts[b]) / 2
            verts.append(m / np.linalg.norm(m))
            cache[k] = len(verts) - 1
        return cache[k]

    caras = []
    for a, b, c in f:
        ab, bc, ca = medio(a, b), medio(b, c), medio(c, a)
        caras += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
    return np.array(verts, dtype=np.float32), caras


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------
class Renderer:
    def __init__(self, w, h):
        global PALETA
        if PALETA is None:
            PALETA = _hsv_paleta()
        self.w, self.h = w, h
        self.t = 0.0
        self.escena = 0
        self.pal_base = PALETA.copy()
        self.pal = PALETA.copy()
        self.pal_obj = None             # paleta de la portada actual
        self._portada_id = None
        self.textura = None
        self.e_corto = 0.0              # energía reciente / de fondo (cambio automático de escena)
        self.e_largo = 0.0
        self._prev = None               # último frame (para la transición con tramado)
        self.hay_letra = False
        self.flash = 0.0
        self.zpos = 0.0
        self.rot = 0.0
        self.mostrar_hud = True
        self.auto = True
        self._t_cambio = 0.0
        self.titulo_visto = None
        self.t_titulo = -99.0
        try:
            self.fuente = ImageFont.load_default()
        except Exception:
            self.fuente = None

        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        x = (xx - w / 2) / (h / 2)
        y = (yy - h / 2) / (h / 2)
        self.rad = np.sqrt(x * x + y * y) + 1e-3
        self.ang = np.arctan2(y, x)
        BAYER = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], dtype=np.float32) / 16.0
        self.dither = np.tile(BAYER, (h // 4 + 1, w // 4 + 1))[:h, :w, None]
        self.viñeta = np.clip(1.15 - 0.55 * (self.rad / self.rad.max()) ** 2.2, 0, 1)[:, :, None].astype(np.float32)

        # terreno
        self.filas = 22
        self.hist = [np.zeros(NB, dtype=np.float32) for _ in range(self.filas)]
        self.t_push = 0.0
        self.cielo = self._gen_cielo()
        # cristal
        self.verts, self.caras = _icosfera()
        self.az = (np.abs(np.arctan2(self.verts[:, 0], self.verts[:, 2])) / math.pi * (NB - 1)).astype(int)
        self.rx = self.ry = 0.0
        self.estrellas = [[random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(0.1, 1)] for _ in range(90)]
        # osciloscopio
        self.trail = np.zeros((h, w, 3), dtype=np.float32)
        # marquesina
        self.marq = 0.0
        # feedback
        self.fb = None
        self.fb_dir = 1
        # túnel
        self.tu = (self.ang / (2 * math.pi) + 0.5).astype(np.float32)
        self.tv = (0.30 / self.rad).astype(np.float32)
        self.z_tunel = 0.0
        self.r_tunel = 0.0
        # transición: tramado Bayer en bloques de 2 px
        b2 = np.kron(BAYER, np.ones((2, 2), dtype=np.float32))
        self.trama = np.tile(b2, (h // 8 + 1, w // 8 + 1))[:h, :w]
        # torres (PS2) y cubo
        self.cam = 0.0
        self.niebla_part = [[random.uniform(-1, 1), random.uniform(-0.2, 1.0), random.uniform(0.2, 1)]
                            for _ in range(70)]
        self.cubo_rx = self.cubo_ry = 0.0
        self.cubo_abrir = 0.0
        # karaoke
        self.k_part = [[random.uniform(0, w), random.uniform(0, h), random.uniform(0.3, 1)] for _ in range(40)]

    # -- helpers --------------------------------------------------------------
    def siguiente_escena(self, d=1, saltar_karaoke=False):
        n = len(ESCENAS)
        destino = (self.escena + d) % n
        if saltar_karaoke and destino == KARAOKE:
            destino = (destino + d) % n
        self.ir_a(destino)

    def ir_a(self, i):
        self.marcar_transicion()
        self.escena = i % len(ESCENAS)
        self.flash = 0.35
        self._t_cambio = self.t
        self.trail[:] = 0
        self.fb = None

    def _col(self, h, bri=1.0):
        c = self.pal[int(h * 255) % 256] * bri
        return tuple(int(max(0, min(255, v * 255))) for v in c)

    def poner_portada(self, img):
        """Llamar cuando cambia la portada (o None si no hay)."""
        if img is None:
            self.pal_obj, self.textura, self._portada_id = None, None, None
            return
        if id(img) == self._portada_id:
            return
        self._portada_id = id(img)
        try:
            cov = paleta_desde_imagen(img)
            self.pal_obj = 0.8 * cov + 0.2 * self.pal_base
            self.textura = textura_desde_imagen(img)
        except Exception as e:
            print(f"Soundscope: paleta de la portada: {e}")
            self.pal_obj, self.textura = None, None

    def _gen_cielo(self):
        h, w = self.h, self.w
        hy = int(h * 0.46)
        arr = np.zeros((h, w, 3), dtype=np.float32)
        for y in range(hy):
            k = (y / hy) ** 1.6
            arr[y, :] = np.array([20 + 235 * k, 0 + 70 * k, 70 + 40 * k], dtype=np.float32)
        arr[hy:, :] = np.array([8, 0, 24], dtype=np.float32)
        return arr / 255.0

    def _texto(self, img, xy, s, fill=(255, 255, 255), escala=1, sombra=True):
        s = _limpiar(s)
        if not s:
            return 0
        d = ImageDraw.Draw(img)
        if escala == 1:
            if sombra:
                d.text((xy[0] + 1, xy[1] + 1), s, fill=(0, 0, 0), font=self.fuente)
            d.text(xy, s, fill=fill, font=self.fuente)
            return int(d.textlength(s, font=self.fuente))
        tmp = Image.new("L", (int(d.textlength(s, font=self.fuente)) + 2, 14), 0)
        ImageDraw.Draw(tmp).text((0, 0), s, fill=255, font=self.fuente)
        tmp = tmp.resize((tmp.width * escala, tmp.height * escala), Image.NEAREST)
        if sombra:
            img.paste((0, 0, 0), (xy[0] + escala, xy[1] + escala), tmp)
        img.paste(fill, xy, tmp)
        return tmp.width

    # -- escenas ---------------------------------------------------------------
    def _vortice(self, dt, au):
        w, h = self.w, self.h
        b = au.bands
        bass, mid = float(b[:5].mean()), float(b[8:18].mean())
        self.zpos += dt * (0.7 + 3.0 * au.level + 3.5 * au.beat)
        self.rot += dt * (0.18 + 0.7 * mid)
        prof = 0.35 / self.rad
        warp = 0.18 * np.sin(prof * 3 + self.t * 2) * (0.4 + bass)
        a = self.ang / (2 * math.pi) * 12 + self.rot + warp
        z = prof * 4.5 - self.zpos
        chk = ((np.floor(z) + np.floor(a)) % 2).astype(np.float32)
        hue = (np.floor(z) * 0.07 + self.t * 0.03 + chk * 0.10 + au.level * 0.25) % 1.0
        niebla = np.clip(self.rad * 1.5, 0, 1) ** 0.9
        bri = (0.30 + 0.70 * chk) * niebla * (0.8 + 0.5 * au.beat)
        rgb = self.pal[(hue * 255).astype(np.int32) % 256] * bri[:, :, None]
        brillo = np.exp(-self.rad * 5.0) * (0.35 + au.beat)
        rgb = rgb + brillo[:, :, None]
        img = Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), "RGB")
        d = ImageDraw.Draw(img)
        cx, cy = w // 2, h // 2
        r0 = h * 0.17
        for i in range(NB * 2):
            k = i if i < NB else (2 * NB - 1 - i)
            ang = (i / (NB * 2)) * 2 * math.pi + self.rot * 0.6
            l = 3 + float(au.bands[k]) * h * 0.30
            x0, y0 = cx + math.cos(ang) * r0, cy + math.sin(ang) * r0
            x1, y1 = cx + math.cos(ang) * (r0 + l), cy + math.sin(ang) * (r0 + l)
            d.line([(x0, y0), (x1, y1)], fill=self._col(i / (NB * 2) + self.t * 0.05, 1.0), width=2)
        d.ellipse([cx - r0 + 2, cy - r0 + 2, cx + r0 - 2, cy + r0 - 2], outline=(255, 255, 255))
        return img

    def _terreno(self, dt, au):
        w, h = self.w, self.h
        intervalo = 0.085
        if self.t - self.t_push >= intervalo:
            self.hist.insert(0, au.bands.copy())
            self.hist.pop()
            self.t_push = self.t
        frac = min(1.0, (self.t - self.t_push) / intervalo)
        img = Image.fromarray((np.clip(self.cielo, 0, 1) * 255).astype(np.uint8), "RGB")
        d = ImageDraw.Draw(img)
        hy = int(h * 0.46)
        # sol con rendijas
        cx, rs = w // 2, h * 0.20 * (1 + 0.10 * au.beat)
        sy = hy - rs * 0.35
        d.ellipse([cx - rs, sy - rs, cx + rs, sy + rs], fill=(255, 210, 60))
        d.ellipse([cx - rs, sy, cx + rs, sy + rs], fill=(255, 90, 140))
        for k in range(7):
            y = sy + rs * (0.15 + k * 0.13)
            d.rectangle([cx - rs - 1, y, cx + rs + 1, y + 1 + k * 0.5], fill=(40, 0, 70))
        d.rectangle([0, hy, w, h], fill=(8, 0, 24))
        d.line([(0, hy), (w, hy)], fill=(255, 120, 200))
        # filas de espectro (de lejos a cerca)
        k = h * 0.58
        for j in range(self.filas - 1, -1, -1):
            z = 1.0 + (j + frac) * 0.30
            bands = self.hist[j]
            vals = np.concatenate((bands[::-1], bands))             # simétrico
            pts = []
            n = len(vals)
            for i, v in enumerate(vals):
                x = (i / (n - 1) - 0.5) * 3.4
                sx = w / 2 + x / z * w * 0.55
                syy = hy + (0.85 - float(v) * 1.5) / z * k
                pts.append((sx, syy))
            prof = j / self.filas
            relleno = (int(30 * (1 - prof)), 0, int(60 * (1 - prof)) + 10)
            d.polygon([(pts[0][0], h)] + pts + [(pts[-1][0], h)], fill=relleno)
            tono = 0.5 + float(vals.mean()) * 0.3 + self.t * 0.03
            col = self._col(tono, 1.0 - prof * 0.75)
            d.line(pts, fill=col, width=1)
        return img

    def _cristal(self, dt, au):
        w, h = self.w, self.h
        b = au.bands
        # fondo degradado que cambia de tono + estrellas
        tono = (self.t * 0.02) % 1.0
        c1, c2 = np.array(self._col(tono, 0.25), dtype=np.float32), np.array(self._col(tono + 0.4, 0.55), dtype=np.float32)
        g = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
        fondo = (c1 * (1 - g) + c2 * g) * (0.8 + 0.4 * au.beat)
        img = Image.fromarray(np.broadcast_to(fondo, (h, w, 3)).astype(np.uint8).copy(), "RGB")
        d = ImageDraw.Draw(img)
        for s in self.estrellas:
            s[2] -= dt * (0.15 + au.level * 1.2 + au.beat * 0.8)
            if s[2] <= 0.04:
                s[0], s[1], s[2] = random.uniform(-1, 1), random.uniform(-1, 1), 1.0
            px, py = w / 2 + s[0] / s[2] * w * 0.15, h / 2 + s[1] / s[2] * h * 0.15
            if 0 <= px < w and 0 <= py < h:
                v = int(255 * (1 - s[2]))
                d.rectangle([px, py, px + (s[2] < 0.4), py + (s[2] < 0.4)], fill=(v, v, 255))
        # malla
        self.rx += dt * (0.4 + 0.8 * float(b[:6].mean()))
        self.ry += dt * (0.7 + 0.5 * au.level)
        crx, srx, cry, sry = math.cos(self.rx), math.sin(self.rx), math.cos(self.ry), math.sin(self.ry)
        rot = np.array([[cry, 0, sry], [srx * sry, crx, -srx * cry], [-crx * sry, srx, crx * cry]], dtype=np.float32)
        radios = 1.0 + 0.85 * b[self.az] ** 1.2 + 0.25 * au.beat
        v3 = (self.verts * radios[:, None]) @ rot.T
        zc = v3[:, 2] + 5.0
        f = h * 1.05
        proy = np.stack([w / 2 + v3[:, 0] / zc * f, h * 0.43 + v3[:, 1] / zc * f], axis=1)
        luz = np.array([0.4, -0.5, -0.8], dtype=np.float32)
        luz /= np.linalg.norm(luz)
        pol = []
        for ci, (a, bb, c) in enumerate(self.caras):
            n = np.cross(v3[bb] - v3[a], v3[c] - v3[a])
            nl = np.linalg.norm(n) + 1e-6
            n = n / nl
            if n[2] > 0:                           # cara trasera
                continue
            ilum = 0.50 + 0.50 * max(0.0, float(np.dot(n, -luz)))
            prof = float((zc[a] + zc[bb] + zc[c]) / 3)
            hue = (self.az[a] / NB * 0.9 + (ci % 5) * 0.03 + self.t * 0.06) % 1.0
            pol.append((prof, [tuple(proy[a]), tuple(proy[bb]), tuple(proy[c])], self._col(hue, ilum)))
        pol.sort(key=lambda p: -p[0])
        for _, pts, col in pol:
            d.polygon(pts, fill=col, outline=(0, 0, 0))
        return img

    def _osciloscopio(self, dt, au):
        w, h = self.w, self.h
        nuevo = Image.new("RGB", (w, h), (0, 0, 0))
        d = ImageDraw.Draw(nuevo)
        cy = h // 2
        n = len(au.wave)
        xs = np.linspace(0, w - 1, n)
        ys = cy - au.wave * h * 0.33
        d.line(list(zip(xs.tolist(), ys.tolist())), fill=(110, 255, 140), width=2)
        # lissajous
        retardo = 40
        lx = w / 2 + au.wave[:-retardo] * h * 0.42
        ly = cy - au.wave[retardo:] * h * 0.42
        d.line(list(zip(lx.tolist(), ly.tolist())), fill=(255, 90, 220), width=1)
        # barritas inferiores
        bw = w / NB
        for i in range(NB):
            alto = float(au.bands[i]) * h * 0.22
            d.rectangle([i * bw + 1, h - alto, (i + 1) * bw - 1, h], fill=self._col(0.30 - i / NB * 0.30, 0.9))
        arr = np.asarray(nuevo, dtype=np.float32) / 255.0
        self.trail = np.maximum(self.trail * (0.80 ** (dt * 30)), arr)
        # rejilla
        rej = np.zeros((h, w, 3), dtype=np.float32)
        rej[::20, :, 1] = 0.18
        rej[:, ::20, 1] = 0.18
        rej[cy, :, 1] = 0.35
        rej[:, w // 2, 1] = 0.35
        out = np.clip(self.trail + rej * (0.8 + 0.4 * au.beat), 0, 1)
        return Image.fromarray((out * 255).astype(np.uint8), "RGB")

    def _feedback(self, dt, au):
        """Estilo Milkdrop: el frame anterior se amplía, gira y se apaga; encima se pinta lo nuevo."""
        w, h = self.w, self.h
        if self.fb is None:
            self.fb = Image.new("RGB", (w, h), (0, 0, 0))
        b = au.bands
        if au.beat > 0.95 and random.random() < 0.15:
            self.fb_dir = -self.fb_dir                  # de vez en cuando cambia el sentido del giro
        zoom = 1.012 + 0.045 * au.beat + 0.02 * au.level
        ang = math.radians(0.5 + 2.2 * float(b[8:16].mean())) * self.fb_dir
        c, s_ = math.cos(ang) / zoom, math.sin(ang) / zoom
        cx, cy = w / 2 + math.sin(self.t * 0.31) * 2.0, h / 2 + math.cos(self.t * 0.23) * 1.5
        coef = (c, s_, cx - c * cx - s_ * cy, -s_, c, cy + s_ * cx - c * cy)
        prev = self.fb.transform((w, h), Image.AFFINE, coef, resample=Image.BILINEAR)
        arr = np.asarray(prev, dtype=np.float32) * (0.90 + 0.05 * min(1.0, au.level * 2))
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
        d = ImageDraw.Draw(img)
        # anillo con la forma de onda
        n = len(au.wave)
        idx = np.arange(0, n, 4)
        th = idx / n * 2 * math.pi + self.t * 0.6
        r = h * (0.17 + 0.05 * au.beat) + au.wave[idx] * h * 0.13
        pts = list(zip((w / 2 + np.cos(th) * r).tolist(), (h / 2 + np.sin(th) * r).tolist()))
        d.line(pts + pts[:1], fill=self._col(self.t * 0.06, 1.0), width=2)
        # puntos del espectro girando por fuera
        for i in range(NB):
            a2 = i / NB * 2 * math.pi - self.t * 0.4
            rr = h * 0.30 + float(b[i]) * h * 0.18
            x, y = w / 2 + math.cos(a2) * rr, h / 2 + math.sin(a2) * rr
            t2 = 1 + int(float(b[i]) * 3)
            d.rectangle([x - t2, y - t2, x + t2, y + t2], fill=self._col(i / NB + self.t * 0.05, 1.0))
        if au.beat > 0.9:                               # destello en el golpe
            rr = h * 0.08
            d.ellipse([w / 2 - rr, h / 2 - rr, w / 2 + rr, h / 2 + rr], fill=self._col(self.t * 0.1 + 0.5, 1.0))
        self.fb = img
        return img

    def _textura_actual(self):
        if self.textura is not None:
            return self.textura
        # sin portada: tablero de ajedrez con la paleta
        yy, xx = np.mgrid[0:TEX, 0:TEX]
        chk = (((yy // 8) + (xx // 8)) % 2).astype(np.float32)
        hue = ((xx + yy) / (2 * TEX) + self.t * 0.03) % 1.0
        return self.pal[(hue * 255).astype(np.int32) % 256] * (0.35 + 0.65 * chk)[:, :, None]

    def _tunel(self, dt, au):
        """Túnel PS1 con la portada mapeada (texturas afines, sin corrección de perspectiva)."""
        b = au.bands
        self.z_tunel += dt * (0.5 + 2.2 * au.level + 2.5 * au.beat)
        self.r_tunel += dt * (0.08 + 0.45 * float(b[8:18].mean()))
        tex = self._textura_actual()
        u = ((self.tu * 2 + self.r_tunel) * TEX).astype(np.int32) % TEX
        v = ((self.tv - self.z_tunel * 0.35) * TEX).astype(np.int32) % TEX
        rgb = tex[v, u]
        niebla = np.clip(self.rad * 1.7, 0, 1) ** 0.8
        rgb = rgb * (niebla * (0.85 + 0.35 * au.beat))[:, :, None]
        brillo = np.exp(-self.rad * 6.0) * (0.25 + 0.8 * au.beat)
        rgb = rgb + brillo[:, :, None] * np.array(self._col(self.t * 0.05), dtype=np.float32) / 255.0
        return Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), "RGB")

    # -- proyección 3D sencilla (cámara mirando al origen) --------------------------
    def _proy(self, pts, yaw, pitch, dist, foco, altura=0.0):
        """pts: array (N,3). Cámara a ``altura`` sobre el suelo, mirando ``pitch`` rad hacia abajo.
        Devuelve (x, y, z_cámara) en pantalla."""
        cy_, sy_ = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        x = pts[:, 0] * cy_ - pts[:, 2] * sy_
        z = pts[:, 0] * sy_ + pts[:, 2] * cy_ + dist
        y0 = pts[:, 1] - altura
        y = y0 * cp + z * sp
        z = -y0 * sp + z * cp
        z = np.maximum(z, 0.05)
        return self.w / 2 + x / z * foco, self.h / 2 - y / z * foco, z

    def _torres(self, dt, au):
        """Campo de torres translúcidas en la niebla azul, como el navegador de la PS2."""
        w, h = self.w, self.h
        b = au.bands
        self.cam += dt * (0.10 + 0.25 * au.level)
        # fondo: degradado azul profundo + niebla que se mueve
        g = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
        arriba = np.array([2, 4, 18], dtype=np.float32)
        abajo = np.array([10, 22, 70], dtype=np.float32) * (0.9 + 0.3 * au.beat)
        fondo = arriba * (1 - g) + abajo * g
        img = Image.fromarray(np.broadcast_to(fondo, (h, w, 3)).astype(np.uint8).copy(), "RGB")
        capa = Image.new("RGB", (w, h), (0, 0, 0))
        d = ImageDraw.Draw(capa)
        n = 7
        caras = []
        for i in range(n):
            for j in range(n):
                k = (i * n + j) % NB
                alto = 0.15 + float(b[k]) * 1.4 + 0.08 * math.sin(self.t * 1.3 + i + j)
                x0, z0 = (i - n / 2) * 0.55, (j - n / 2) * 0.55
                s_ = 0.17
                v = np.array([[x0 - s_, 0, z0 - s_], [x0 + s_, 0, z0 - s_], [x0 + s_, 0, z0 + s_], [x0 - s_, 0, z0 + s_],
                              [x0 - s_, alto, z0 - s_], [x0 + s_, alto, z0 - s_], [x0 + s_, alto, z0 + s_],
                              [x0 - s_, alto, z0 + s_]], dtype=np.float32)
                px, py, pz = self._proy(v, self.cam, 0.38, 4.6, h * 1.0, altura=1.9)
                prof = float(pz.mean())
                tono = self._col(0.58 + 0.12 * float(b[k]) + self.t * 0.01, 1.0)
                for cara, luz in (((4, 5, 6, 7), 1.0), ((0, 1, 5, 4), 0.55), ((1, 2, 6, 5), 0.75),
                                  ((2, 3, 7, 6), 0.55), ((3, 0, 4, 7), 0.75)):
                    zc = float(np.mean(pz[list(cara)]))
                    caras.append((zc, [(float(px[c]), float(py[c])) for c in cara], luz, tono, prof))
        caras.sort(key=lambda c: -c[0])
        for _, pts, luz, tono, prof in caras:
            atenua = max(0.15, min(1.0, 1.8 - prof * 0.32)) * luz
            col = tuple(int(c * atenua) for c in tono)
            d.polygon(pts, fill=col, outline=tuple(min(255, int(c * 1.4 + 30)) for c in col))
        # resplandor: la capa de torres + su versión desenfocada
        brillo = capa.filter(ImageFilter.GaussianBlur(4))
        img = Image.fromarray(np.clip(np.asarray(img, dtype=np.float32) + np.asarray(capa, dtype=np.float32) * 0.85
                                      + np.asarray(brillo, dtype=np.float32) * (0.6 + 0.6 * au.beat), 0, 255)
                              .astype(np.uint8), "RGB")
        d = ImageDraw.Draw(img)
        for p in self.niebla_part:                      # motas de luz flotando
            p[1] += dt * (0.05 + 0.2 * au.level) * p[2]
            if p[1] > 1.2:
                p[0], p[1] = random.uniform(-1, 1), -0.2
            x = w / 2 + (p[0] + math.sin(self.t * 0.4 + p[2] * 9) * 0.05) * w * 0.55
            y = h * (1 - p[1])
            v = int(90 + 120 * p[2])
            d.point((x, y), fill=(v // 2, v, 255))
        return img

    def _cubo(self, dt, au):
        """Cubo de 3×3×3 cubitos que se separan con los golpes y se recolocan."""
        w, h = self.w, self.h
        b = au.bands
        self.cubo_rx += dt * (0.35 + 0.6 * float(b[:6].mean()))
        self.cubo_ry += dt * (0.55 + 0.4 * au.level)
        self.cubo_abrir += (min(1.0, au.beat * 1.2 + au.level * 0.6) - self.cubo_abrir) * min(1.0, dt * 6)
        g = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
        c1 = np.array(self._col(self.t * 0.02 + 0.6, 0.12), dtype=np.float32)
        c2 = np.array(self._col(self.t * 0.02 + 0.75, 0.35), dtype=np.float32)
        img = Image.fromarray(np.broadcast_to(c1 * (1 - g) + c2 * g, (h, w, 3)).astype(np.uint8).copy(), "RGB")
        d = ImageDraw.Draw(img)
        sep = 0.62 + 0.38 * self.cubo_abrir
        lado = 0.27
        base = np.array([[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
                         [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]], dtype=np.float32) * lado
        caras_idx = ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (0, 3, 7, 4))
        luces = (0.55, 1.0, 0.7, 0.85, 0.65, 0.9)
        poligonos = []
        k = 0
        for ix in (-1, 0, 1):
            for iy in (-1, 0, 1):
                for iz in (-1, 0, 1):
                    k += 1
                    centro = np.array([ix, iy, iz], dtype=np.float32) * sep
                    puls = 1.0 + 0.25 * float(b[k % NB])
                    v = base * puls + centro
                    # rotación del conjunto
                    cx_, sx_ = math.cos(self.cubo_rx), math.sin(self.cubo_rx)
                    y2 = v[:, 1] * cx_ - v[:, 2] * sx_
                    z2 = v[:, 1] * sx_ + v[:, 2] * cx_
                    v = np.stack([v[:, 0], y2, z2], axis=1)
                    px, py, pz = self._proy(v, self.cubo_ry, 0.0, 4.4, h * 1.15)
                    tono = self._col(k / 27 + self.t * 0.04, 1.0)
                    for cara, luz in zip(caras_idx, luces):
                        pts = [(float(px[c]), float(py[c])) for c in cara]
                        zc = float(np.mean(pz[list(cara)]))
                        poligonos.append((zc, pts, tuple(int(c * luz) for c in tono)))
        poligonos.sort(key=lambda p: -p[0])
        for _, pts, col in poligonos:
            d.polygon(pts, fill=col, outline=(0, 0, 0))
        return img

    def _karaoke(self, dt, au, info):
        w, h = self.w, self.h
        # fondo: degradado con la paleta + partículas + espectro espejo abajo
        g = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
        c1 = np.array(self._col(self.t * 0.02, 0.20), dtype=np.float32)
        c2 = np.array(self._col(self.t * 0.02 + 0.35, 0.45), dtype=np.float32)
        fondo = (c1 * (1 - g) + c2 * g) * (0.85 + 0.3 * au.beat)
        img = Image.fromarray(np.broadcast_to(fondo, (h, w, 3)).astype(np.uint8).copy(), "RGB")
        d = ImageDraw.Draw(img)
        for p in self.k_part:
            p[1] -= dt * (8 + 30 * au.level) * p[2]
            if p[1] < 0:
                p[0], p[1] = random.uniform(0, w), h
            v = int(120 + 120 * p[2])
            d.rectangle([p[0], p[1], p[0] + 1, p[1] + 1], fill=(v, v, 255))
        bw = w / NB
        for i in range(NB):
            alto = float(au.bands[i]) * h * 0.16
            col = self._col(i / NB + self.t * 0.03, 0.8)
            d.rectangle([i * bw + 1, h - 44 - alto, (i + 1) * bw - 1, h - 44], fill=col)

        letra = info.get("letra")
        pos = info.get("pos_ms", 0) + 150
        lineas = []
        actual = -1
        if letra and letra.get("lineas"):
            lineas = [t for _, t in letra["lineas"]]
            ini = [i for i, _ in letra["lineas"]]
            import bisect
            actual = bisect.bisect_right(ini, pos) - 1
        elif letra and letra.get("texto"):
            # sin tiempos: se reparte la letra a lo largo de la canción (aproximado)
            lineas = [t for t in letra["texto"].split("\n") if t.strip()]
            dur = info.get("len_ms", 0)
            if lineas and dur > 0:
                actual = min(len(lineas) - 1, int(pos / dur * len(lineas)))
        if not lineas:
            msg = "BUSCANDO LETRA..." if info.get("letra_buscando") else "SIN LETRA"
            self._texto(img, ((w - len(msg) * 12) // 2, h // 2 - 20), msg, (255, 240, 160), escala=2)
            return img
        cy = int(h * 0.42)
        if actual >= 0:
            filas = textwrap.wrap(lineas[actual] or "~", 24) or ["~"]
            y = cy - len(filas) * 13
            for f in filas[:3]:
                ancho = int(ImageDraw.Draw(img).textlength(_limpiar(f), font=self.fuente)) * 2
                self._texto(img, ((w - ancho) // 2, y), f, (255, 240, 120), escala=2)
                y += 26
        else:
            y = cy
        for k, j in enumerate(range(actual + 1, actual + 3)):    # siguientes, más tenues
            if 0 <= j < len(lineas):
                f = textwrap.shorten(lineas[j] or "~", 48, placeholder="...")
                ancho = int(ImageDraw.Draw(img).textlength(_limpiar(f), font=self.fuente))
                v = 200 - k * 60
                self._texto(img, ((w - ancho) // 2, y + 4 + k * 14), f, (v, v, min(255, v + 40)))
        if actual >= 1:
            f = textwrap.shorten(lineas[actual - 1] or "~", 48, placeholder="...")
            ancho = int(ImageDraw.Draw(img).textlength(_limpiar(f), font=self.fuente))
            self._texto(img, ((w - ancho) // 2, cy - len(textwrap.wrap(lineas[actual] or "~", 24) or [1]) * 13 - 18),
                        f, (110, 110, 150))
        return img

    # -- postproceso y HUD --------------------------------------------------------
    def _fx(self, img):
        a = np.asarray(img, dtype=np.float32) / 255.0
        a = a * self.viñeta
        if self.flash > 0:
            a = np.clip(a + self.flash * 0.7, 0, 1)
            desp = int(self.flash * 6)
            if desp:
                filas = np.arange(self.h)
                a = a[filas[:, None], (np.arange(self.w)[None, :] + (np.sin(filas * 0.7)[:, None] * desp).astype(int)) % self.w]
        a = np.floor(a * 31 + self.dither)                  # 15 bits + dither
        a = np.clip(a, 0, 31) * (255.0 / 31.0)
        return Image.fromarray(a.astype(np.uint8), "RGB")

    def _caja_azul(self, img, x0, y0, x1, y1):
        d = ImageDraw.Draw(img)
        for y in range(y0, y1):
            k = (y - y0) / max(1, y1 - y0)
            d.line([(x0, y), (x1, y)], fill=(int(20 + 30 * k), int(20 + 40 * k), int(110 + 90 * k)))
        d.rectangle([x0, y0, x1, y1], outline=(210, 210, 230))
        d.line([(x0, y1), (x1, y1)], fill=(60, 60, 90))
        d.line([(x1, y0), (x1, y1)], fill=(60, 60, 90))

    def _hud(self, img, info, au):
        w, h = self.w, self.h
        estado = info.get("estado", "stop")
        pos, dur = info.get("pos_ms", 0), info.get("len_ms", 0)
        titulo = f"{info.get('artista', '')} - {info.get('titulo', '')}".strip(" -") or "eXotic Media Player"
        # tarjeta "TRACK 03" al cambiar de canción (como el reproductor de CD de la PS1)
        if info.get("titulo") != self.titulo_visto:
            self.titulo_visto = info.get("titulo")
            self.t_titulo = self.t
        et = self.t - self.t_titulo
        if info.get("titulo") and et < 3.5 and self.escena != KARAOKE:
            entrada = min(1.0, et / 0.35)
            salida = max(0.0, (et - 3.1) / 0.4)
            alto = 52
            y0 = int(-alto + (alto + 14) * entrada - (alto + 14) * salida)
            x0, x1 = 24, w - 24
            self._caja_azul(img, x0, y0, x1, y0 + alto)
            pista = info.get("pista")
            cab = f"TRACK {pista:02d}" if pista else "TRACK"
            if info.get("total"):
                cab += f" / {info['total']:02d}"
            self._texto(img, (x0 + 8, y0 + 5), cab, (255, 220, 90), escala=2)
            self._texto(img, (x0 + 8, y0 + 26), textwrap.shorten(_limpiar(info["titulo"]), 46, placeholder="..."),
                        (255, 255, 255))
            self._texto(img, (x0 + 8, y0 + 38), textwrap.shorten(_limpiar(info.get("artista", "")), 46, placeholder="..."),
                        (170, 200, 255))

        # menú inferior estilo memory card
        y0 = h - 40
        self._caja_azul(img, 6, y0, w - 7, h - 7)
        cov = info.get("cover")
        x_txt = 12
        if cov is not None:
            img.paste(cov, (10, y0 + 4))
            ImageDraw.Draw(img).rectangle([9, y0 + 3, 10 + cov.width, y0 + 4 + cov.height], outline=(230, 230, 255))
            x_txt = 14 + cov.width + 4
        simbolo = {"play": ">", "pause": "||", "stop": "[]"}.get(estado, ">")
        self._texto(img, (x_txt, y0 + 4), f"{simbolo} {int(pos // 60000):02d}:{int(pos // 1000 % 60):02d} / {int(dur // 60000):02d}:{int(dur // 1000 % 60):02d}",
                    (255, 255, 160))
        ancho_vis = w - x_txt - 14
        cadena = _limpiar(titulo) + "     "
        total = max(1, int(ImageDraw.Draw(img).textlength(cadena, font=self.fuente)))
        tmp = Image.new("RGBA", (ancho_vis, 12), (0, 0, 0, 0))
        if total <= ancho_vis:
            self._texto(tmp, (0, 0), cadena.strip(), (255, 255, 255))
        else:
            self.marq = (self.marq + 0.6) % total
            for rep in range(2):
                self._texto(tmp, (-int(self.marq) + rep * total, 0), cadena, (255, 255, 255))
        img.paste(tmp, (x_txt, y0 + 15), tmp)
        # barra de progreso
        if dur > 0:
            frac = max(0.0, min(1.0, pos / dur))
            d = ImageDraw.Draw(img)
            d.rectangle([x_txt, h - 14, x_txt + ancho_vis, h - 11], fill=(10, 10, 50), outline=(150, 150, 200))
            d.rectangle([x_txt + 1, h - 13, x_txt + 1 + int((ancho_vis - 2) * frac), h - 12], fill=(255, 210, 60))
        # cabecera
        tag = f"SOUNDSCOPE  <{ESCENAS[self.escena]}>" + ("  AUTO" if self.auto else "")
        self._texto(img, (6, 5), tag, (230, 230, 255))
        modo = "REAL" if au.modo == "real" else "SIM"
        self._texto(img, (w - 10 - int(ImageDraw.Draw(img).textlength(f"AUDIO:{modo}", font=self.fuente)), 5), f"AUDIO:{modo}", (150, 255, 170) if modo == "REAL" else (255, 190, 120))
        if estado == "pause" and int(self.t * 2) % 2 == 0:
            self._texto(img, (w // 2 - 15, h // 2 - 12), "PAUSA", (255, 255, 255), escala=2)

    # -- frame completo ------------------------------------------------------------
    def _cambio_automatico(self, au):
        """Cambia de escena en un golpe fuerte cuando la energía sube de golpe (un 'drop'),
        o en cualquier golpe si lleva mucho rato en la misma."""
        self.e_corto = 0.85 * self.e_corto + 0.15 * au.level
        self.e_largo = 0.996 * self.e_largo + 0.004 * au.level
        desde = self.t - self._t_cambio
        subida = self.e_corto > self.e_largo * 1.35 + 0.03
        if au.beat > 0.9 and ((desde > 18 and subida) or desde > 70):
            self.siguiente_escena(saltar_karaoke=not self.hay_letra)

    def frame(self, dt, au, info):
        self.t += dt
        self.flash = max(0.0, self.flash - dt * 2.2)
        objetivo = self.pal_obj if self.pal_obj is not None else self.pal_base
        self.pal += (objetivo - self.pal) * min(1.0, dt * 1.2)        # la paleta cambia suave
        self.hay_letra = bool(info.get("letra"))
        if self.auto:
            self._cambio_automatico(au)
        if self.escena == KARAOKE:
            base = self._karaoke(dt, au, info)
        else:
            base = (self._vortice, self._terreno, self._cristal, self._osciloscopio,
                    self._feedback, self._tunel, self._torres, self._cubo)[self.escena](dt, au)
        img = self._fx(base)
        k = (self.t - self._t_cambio) / TRANSICION_S
        if self._prev is not None and k < 1.0:
            # disolución con tramado (como las transiciones de la PS1)
            mascara = (self.trama < k)[:, :, None]
            img = Image.fromarray(np.where(mascara, np.asarray(img), np.asarray(self._prev)).astype(np.uint8), "RGB")
        else:
            self._prev = None
        if k >= 1.0 or self._prev is None:
            self._ultimo = img
        if self.mostrar_hud:
            hud = img.copy()
            self._hud(hud, info, au)
            return hud
        return img

    def marcar_transicion(self):
        """Guarda el frame actual para disolverlo en la siguiente escena."""
        self._prev = getattr(self, "_ultimo", None)


# ---------------------------------------------------------------------------
# Ventana a pantalla completa
# ---------------------------------------------------------------------------
class SoundscopeVentana:
    """Ventana a pantalla completa. El dibujo se hace en un hilo aparte (numpy y PIL
    sueltan el GIL), así la interfaz no se traba; el hilo de Tk solo copia el frame."""
    FPS = 30

    def __init__(self, app):
        self.app = app
        self.top = None
        self.analizador = None
        self.renderer = None
        self._cover_url = None
        self._cover_img = None          # 26×26 para el HUD
        self._cover_full = None         # 128×128 para paleta y textura
        self._cursor_t = 0.0
        self._foto = None
        self._hilo = None
        self._corriendo = False
        self._lock = threading.Lock()
        self._listo = None
        self._info = {"estado": "stop"}
        self._job = None
        self._propio = True
        self.fps_real = 0.0

    @property
    def abierto(self):
        try:
            return self.top is not None and self.top.winfo_exists()
        except tk.TclError:
            return False

    def alternar(self, evento=None):
        if self.abierto:
            self.cerrar()
        else:
            self.abrir()

    def abrir(self):
        if self.abierto:
            return
        if np is None:
            from tkinter import messagebox
            messagebox.showwarning("Soundscope", "Falta numpy.\nInstálalo con:  pip install numpy pyaudiowpatch")
            return
        root = self.app.root
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.zoom = max(2, round(sw / 320))
        rw, rh = -(-sw // self.zoom), -(-sh // self.zoom)
        self.sw, self.sh = sw, sh
        compartido = getattr(self.app, "analizador", None)
        if compartido is not None and compartido.modo == "real":
            self.analizador, self._propio = compartido, False   # reutiliza la captura del panel
        else:
            self.analizador, self._propio = AudioAnalyzer(), True
            self.analizador.iniciar()
        self.renderer = Renderer(rw, rh)
        # scanlines CRT "horneadas" al escalar (antes eran cientos de rectángulos en el canvas):
        # cada fila de pantalla sale de una fila del frame pequeño, normal u oscurecida
        alto = max(1, self.zoom // 3)
        self._filas = np.minimum(np.arange(sh) // self.zoom, rh - 1)
        self._oscura = ((np.arange(sh) % self.zoom) >= self.zoom - alto).astype(np.intp)

        top = self.top = tk.Toplevel(root)
        top.configure(bg="black", cursor="none")
        top.title("eXotic Soundscope")
        top.geometry(f"{sw}x{sh}+0+0")
        top.attributes("-fullscreen", True)
        try:
            top.attributes("-topmost", True)
        except Exception:
            pass
        self.canvas = tk.Canvas(top, bg="black", highlightthickness=0, cursor="none")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self._foto = ImageTk.PhotoImage(Image.new("RGB", (sw, sh)))
        self.item = self.canvas.create_image(0, 0, anchor="nw", image=self._foto)

        for tecla in ("<Escape>", "<F11>", "<q>", "<Q>"):
            top.bind(tecla, lambda e: self.cerrar())
        top.bind("<space>", lambda e: self.app.toggle_play())
        top.bind("<Left>", lambda e: self.app.anterior_cancion())
        top.bind("<Right>", lambda e: self.app.siguiente_cancion())
        top.bind("<Up>", lambda e: self._volumen(5))
        top.bind("<Down>", lambda e: self._volumen(-5))
        top.bind("<MouseWheel>", lambda e: self._volumen(5 if e.delta > 0 else -5))
        top.bind("<Tab>", lambda e: self._escena(1))
        top.bind("<n>", lambda e: self._escena(1))
        top.bind("<b>", lambda e: self._escena(-1))
        top.bind("<Button-1>", lambda e: self._escena(1))
        top.bind("<Button-3>", lambda e: self._escena(-1))
        for i in range(len(ESCENAS)):
            top.bind(str(i + 1), lambda e, i=i: self._ir_escena(i))
        top.bind("<a>", lambda e: self._con_lock(lambda: setattr(self.renderer, "auto", not self.renderer.auto)))
        top.bind("<h>", lambda e: self._con_lock(lambda: setattr(self.renderer, "mostrar_hud", not self.renderer.mostrar_hud)))
        top.bind("<l>", lambda e: self._ir_escena(KARAOKE))
        top.bind("<Motion>", self._mostrar_cursor)
        top.protocol("WM_DELETE_WINDOW", self.cerrar)
        top.focus_force()

        self._info = self._leer_info()
        self._corriendo = True
        self._hilo = threading.Thread(target=self._bucle, name="soundscope", daemon=True)
        self._hilo.start()
        self._tick()

    def cerrar(self):
        self._corriendo = False
        if self._hilo is not None:
            self._hilo.join(timeout=0.5)
            self._hilo = None
        if self._job is not None and self.top is not None:
            try:
                self.top.after_cancel(self._job)
            except tk.TclError:
                pass
        self._job = None
        if self.analizador and self._propio:
            self.analizador.detener()
        self.analizador = None
        if self.top is not None:
            try:
                self.top.destroy()
            except Exception:
                pass
        self.top = None
        self._listo = None
        try:
            self.app.root.focus_force()
        except Exception:
            pass

    # -- controles ---------------------------------------------------------------
    def _con_lock(self, fn):
        with self._lock:
            fn()

    def _volumen(self, delta):
        try:
            v = max(0, min(100, float(self.app.vol_slider.get()) + delta))
            self.app.vol_slider.set(v)
            self.app.cambiar_volumen(v)
        except Exception:
            pass

    def _escena(self, d):
        self._con_lock(lambda: self.renderer.siguiente_escena(d))

    def _ir_escena(self, i):
        self._con_lock(lambda: self.renderer.ir_a(i))

    def _mostrar_cursor(self, e=None):
        self._cursor_t = time.time()
        try:
            self.top.configure(cursor="arrow")
            self.canvas.configure(cursor="arrow")
        except Exception:
            pass

    # -- datos de la canción (se leen en el hilo de Tk) ------------------------------
    def _leer_info(self):
        import vlc
        app = self.app
        estado = app.player.get_state()
        e = "play" if estado == vlc.State.Playing else ("pause" if estado == vlc.State.Paused else "stop")
        info = {"estado": e, "pos_ms": 0, "len_ms": 0, "titulo": "", "artista": "",
                "cover": self._cover_img, "cover_full": self._cover_full,
                "pista": 0, "total": len(app.queue), "letra": None, "letra_buscando": False}
        if e != "stop":
            info["pos_ms"] = max(0, app.player.get_time())
            info["len_ms"] = max(0, app.player.get_length())
        if 0 <= app.current_index < len(app.queue) and (e != "stop" or app._cargando):
            c = app.queue[app.current_index]
            info["titulo"], info["artista"] = c.get("title", ""), c.get("artist", "")
            info["pista"] = app.current_index + 1
            self._pedir_cover(c.get("coverUrl"))
            cache = getattr(app, "letras", None)
            if cache is not None:
                info["letra"], info["letra_buscando"] = cache.obtener(c)
        else:
            self._cover_img = self._cover_full = None
            info["cover"] = info["cover_full"] = None
        return info

    def _pedir_cover(self, url):
        if url and url.startswith("//"):
            url = "https:" + url
        if not url or url == self._cover_url:
            return
        self._cover_url = url
        self._cover_img = None
        self._cover_full = None

        def descargar():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    pil = Image.open(io.BytesIO(r.read())).convert("RGB")
                if self._cover_url == url:
                    self._cover_full = pil.resize((128, 128), Image.BILINEAR)
                    self._cover_img = pil.resize((26, 26), Image.BILINEAR)
            except Exception:
                pass

        self.app.pool_img.submit(descargar)

    # -- hilo de dibujo -------------------------------------------------------------
    def _bucle(self):
        t_ult = time.time()
        periodo = 1.0 / self.FPS
        media = periodo
        while self._corriendo:
            t0 = time.time()
            dt = min(0.1, t0 - t_ult)
            t_ult = t0
            info = self._info
            try:
                with self._lock:
                    self.renderer.poner_portada(info.get("cover_full"))
                    self.analizador.actualizar(info["estado"] == "play", dt)
                    img = self.renderer.frame(dt, self.analizador, info)
                self._listo = self._a_pantalla(img)
            except Exception as e:
                print(f"Soundscope: error en frame: {e}")
                time.sleep(0.2)
            gasto = time.time() - t0
            media = 0.9 * media + 0.1 * max(gasto, periodo)
            self.fps_real = 1.0 / media
            if gasto < periodo:
                time.sleep(periodo - gasto)

    def _a_pantalla(self, img):
        """Escala con píxeles gordos y scanlines (~3 ms a 1080p)."""
        a = np.asarray(img)
        oscura = (a.astype(np.uint16) * 150 >> 8).astype(np.uint8)
        filas = np.stack((a, oscura))[self._oscura, self._filas]
        return Image.fromarray(filas, "RGB").resize((self.sw, self.sh), Image.NEAREST)

    def _tick(self):
        """Hilo de Tk: pasa los datos de la canción y copia el último frame a la pantalla."""
        self._job = None
        if not self.abierto:
            return
        try:
            self._info = self._leer_info()
            frame, self._listo = self._listo, None
            if frame is not None:
                self._foto.paste(frame)
            if time.time() - self._cursor_t > 2.0:
                self.top.configure(cursor="none")
                self.canvas.configure(cursor="none")
        except tk.TclError:
            return
        except Exception as e:
            print(f"Soundscope: {e}")
        self._job = self.top.after(15, self._tick)
