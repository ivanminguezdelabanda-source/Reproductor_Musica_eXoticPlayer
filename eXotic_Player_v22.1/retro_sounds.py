"""Sonidos de sistema retro (estilo Windows XP) generados por síntesis.

No se incluye ningún archivo de audio: los WAV se generan la primera vez en la
carpeta de datos y se reproducen con ``winsound`` (solo Windows; en otros sistemas
no suenan, pero tampoco falla nada).

Sonidos:
  conectar  -> "ding" de dos notas (sesión iniciada)
  amigo     -> acorde ascendente (solicitud de amistad aceptada / jam)
  aviso     -> notificación suave (nueva solicitud)
  error     -> "bonk" grave
  inicio    -> arpegio corto al abrir la app
"""
import math
import os
import struct
import sys
import wave

SR = 22050

# (frecuencia Hz, inicio s, duración s, volumen)
_NOTAS = {
    "conectar": [(1318.5, 0.00, 0.55, 0.45), (987.8, 0.11, 0.70, 0.40)],
    "amigo":    [(784.0, 0.00, 0.45, 0.30), (987.8, 0.07, 0.45, 0.30),
                 (1174.7, 0.14, 0.55, 0.30), (1568.0, 0.21, 0.80, 0.28)],
    "aviso":    [(1046.5, 0.00, 0.35, 0.35), (1568.0, 0.09, 0.50, 0.30)],
    "error":    [(220.0, 0.00, 0.30, 0.55), (164.8, 0.05, 0.40, 0.45)],
    "inicio":   [(523.3, 0.00, 0.60, 0.25), (659.3, 0.12, 0.60, 0.25),
                 (784.0, 0.24, 0.70, 0.25), (1046.5, 0.36, 1.10, 0.28)],
}


def sintetizar(nombre):
    """Devuelve las muestras (lista de int16) del sonido. Función pura."""
    notas = _NOTAS[nombre]
    total = max(ini + dur for _, ini, dur, _ in notas) + 0.05
    n = int(total * SR)
    buf = [0.0] * n
    for f, ini, dur, vol in notas:
        i0 = int(ini * SR)
        largo = int(dur * SR)
        for k in range(largo):
            if i0 + k >= n:
                break
            t = k / SR
            env = min(1.0, t / 0.004) * math.exp(-t * 5.5 / dur)      # ataque rápido, caída suave
            # seno + un poco de 2º y 3er armónico = timbre de "campanita"
            s = (math.sin(2 * math.pi * f * t)
                 + 0.30 * math.sin(2 * math.pi * f * 2 * t)
                 + 0.12 * math.sin(2 * math.pi * f * 3.01 * t))
            buf[i0 + k] += s * env * vol
    pico = max(1e-6, max(abs(x) for x in buf))
    escala = 0.85 / pico if pico > 0.85 else 1.0
    return [int(max(-1.0, min(1.0, x * escala)) * 32767) for x in buf]


def ruta_sonido(nombre, carpeta):
    """Genera (si hace falta) y devuelve la ruta del WAV."""
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, f"{nombre}.wav")
    if not os.path.exists(ruta):
        muestras = sintetizar(nombre)
        tmp = ruta + ".tmp"
        with wave.open(tmp, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(struct.pack(f"<{len(muestras)}h", *muestras))
        os.replace(tmp, ruta)
    return ruta


class SonidosRetro:
    def __init__(self, carpeta, activado=True):
        self.carpeta = carpeta
        self.activado = activado

    def tocar(self, nombre):
        if not self.activado or nombre not in _NOTAS or not sys.platform.startswith("win"):
            return
        try:
            import winsound
            winsound.PlaySound(ruta_sonido(nombre, self.carpeta),
                               winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception as e:
            print(f"Sonido '{nombre}' no disponible: {e}")
