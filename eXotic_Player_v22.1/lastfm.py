"""Scrobbling a Last.fm (API 2.0, sin dependencias nuevas).

Hace falta una API key y su "shared secret" (gratis en https://www.last.fm/api/account/create).
La contraseña solo se usa una vez para obtener la "session key"; no se guarda.

Reglas de Last.fm: se registra una canción cuando dura más de 30 s y la has escuchado
la mitad o 4 minutos (lo que llegue antes).
"""
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request

API = "https://ws.audioscrobbler.com/2.0/"
MAX_PENDIENTES = 200

_RUIDO = re.compile(r"\s*[\(\[](?:official|oficial|video|vídeo|audio|lyrics?|letra|visualizer|hd|hq|4k|"
                    r"music video|videoclip|remaster(?:ed)?(?: \d{4})?)[^\)\]]*[\)\]]", re.I)


def firma(params, secret):
    """api_sig de Last.fm: md5 de clave+valor ordenados + secret (sin format/callback)."""
    cadena = "".join(f"{k}{params[k]}" for k in sorted(params) if k not in ("format", "callback"))
    return hashlib.md5((cadena + secret).encode("utf-8")).hexdigest()


def limpiar(titulo, artista):
    """Quita '(Official Video)' y similares y se queda con el primer artista."""
    t = _RUIDO.sub("", str(titulo or "")).strip()
    a = str(artista or "").split(",")[0].strip()
    return t, a


def debe_scrobblear(escuchado_s, duracion_s):
    if duracion_s and duracion_s <= 30:
        return False
    umbral = 240 if not duracion_s else min(duracion_s / 2, 240)
    return escuchado_s >= umbral


class LastFMError(RuntimeError):
    pass


class LastFM:
    def __init__(self, api_key, secret, sk=None):
        self.api_key = (api_key or "").strip()
        self.secret = (secret or "").strip()
        self.sk = sk

    @property
    def listo(self):
        return bool(self.api_key and self.secret and self.sk)

    def _llamar(self, metodo, params):
        p = dict(params, method=metodo, api_key=self.api_key)
        if self.sk and metodo != "auth.getMobileSession":
            p["sk"] = self.sk
        p = {k: str(v) for k, v in p.items() if v not in (None, "")}
        p["api_sig"] = firma(p, self.secret)
        p["format"] = "json"
        datos = urllib.parse.urlencode(p).encode("utf-8")
        req = urllib.request.Request(API, data=datos, headers={"User-Agent": "eXoticPlayer/21"})
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                res = json.load(r)
        except urllib.error.HTTPError as e:
            try:
                res = json.load(e)
            except Exception:
                raise LastFMError(f"HTTP {e.code}") from e
        if isinstance(res, dict) and "error" in res:
            raise LastFMError(f"{res.get('message', 'Error')} ({res['error']})")
        return res

    def conectar(self, usuario, password):
        res = self._llamar("auth.getMobileSession", {"username": usuario, "password": password})
        self.sk = res["session"]["key"]
        return self.sk

    def ahora_suena(self, artista, titulo, duracion=None):
        return self._llamar("track.updateNowPlaying", {"artist": artista, "track": titulo,
                                                       "duration": int(duracion) if duracion else None})

    def scrobble(self, lote):
        """lote: lista de dicts {artist, track, timestamp, duration} (máx. 50)."""
        p = {}
        for i, s in enumerate(lote[:50]):
            p[f"artist[{i}]"] = s["artist"]
            p[f"track[{i}]"] = s["track"]
            p[f"timestamp[{i}]"] = int(s["timestamp"])
            if s.get("duration"):
                p[f"duration[{i}]"] = int(s["duration"])
        return self._llamar("track.scrobble", p)


class Scrobbler:
    """Lleva la cuenta de lo escuchado de la canción actual y la registra cuando toca."""

    def __init__(self, cliente, pendientes=None, enviar=None):
        self.cliente = cliente
        self.pendientes = list(pendientes or [])[-MAX_PENDIENTES:]
        self.enviar = enviar or (lambda fn: fn())          # cómo ejecutar en segundo plano
        self._actual = None

    def empezar(self, cancion, duracion_s):
        titulo, artista = limpiar(cancion.get("title"), cancion.get("artist"))
        self._actual = None
        if not (titulo and artista and self.cliente.listo):
            return
        self._actual = {"track": titulo, "artist": artista, "duration": int(duracion_s or 0),
                        "timestamp": int(time.time()), "escuchado": 0.0, "hecho": False}
        a = dict(self._actual)
        self.enviar(lambda: self.cliente.ahora_suena(a["artist"], a["track"], a["duration"]))

    def escuchado(self, segundos, duracion_s=None):
        """Llamar mientras suena. Devuelve True si en esta llamada se ha registrado."""
        c = self._actual
        if c is None or c["hecho"]:
            return False
        c["escuchado"] += segundos
        if duracion_s and not c["duration"]:
            c["duration"] = int(duracion_s)
        if debe_scrobblear(c["escuchado"], c["duration"]):
            c["hecho"] = True
            self.pendientes.append({k: c[k] for k in ("artist", "track", "timestamp", "duration")})
            self.pendientes = self.pendientes[-MAX_PENDIENTES:]
            self.vaciar()
            return True
        return False

    def vaciar(self):
        if not self.pendientes or not self.cliente.listo:
            return
        lote = self.pendientes[:50]

        def tarea():
            try:
                self.cliente.scrobble(lote)
                del self.pendientes[:len(lote)]
            except Exception as e:                 # sin red: se reintenta con el siguiente
                print(f"[last.fm] scrobble pendiente: {e}")
        self.enviar(tarea)
