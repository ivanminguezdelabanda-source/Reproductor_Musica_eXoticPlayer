import threading

try:
    from pypresence import Presence
except ImportError:
    Presence = None

try:
    from pynput import keyboard
except ImportError:
    keyboard = None


class DiscordRPC:
    """Gestiona el estado visible en Discord del usuario."""
    def __init__(self, client_id="1554600639097610242"):
        self.client_id = client_id
        self.rpc = None
        self.connected = False
        self._lock = threading.Lock()

    def connect(self):
        if not Presence or not self.client_id:
            return

        def _connect_thread():
            try:
                self.rpc = Presence(self.client_id)
                self.rpc.connect()
                self.connected = True
                print("Discord RPC conectado.")
            except Exception as e:
                print(f"No se pudo conectar a Discord: {e}")
                self.connected = False

        threading.Thread(target=_connect_thread, daemon=True).start()

    def update_presence(self, song_title, artist, is_playing=True, cover_url=None,
                        pos_s=None, dur_s=None, url=None):
        """Estado de Discord. Con carátula (URL), barra de tiempo y botón "Escuchar" si se dan."""
        if not self.connected or not self.rpc:
            return

        def _update():
            try:
                import time as _t
                state = f"🎤 {artist}" if artist else "Escuchando música"
                details = f"🎵 {song_title}" if song_title != "Detenido" else "Nada sonando"
                datos = dict(
                    state=state[:128],
                    details=details[:128],
                    large_image=cover_url or "logo",
                    large_text="eXotic Media Player",
                    small_image="play" if is_playing else "pause",
                    small_text="Reproduciendo" if is_playing else "Pausado",
                )
                if cover_url:
                    datos["small_image"] = "logo" if is_playing else "pause"
                if is_playing and dur_s and pos_s is not None and dur_s > 0:
                    inicio = int(_t.time() - pos_s)
                    datos["start"] = inicio                    # Discord pinta la barra de progreso
                    datos["end"] = int(inicio + dur_s)
                if url:
                    datos["buttons"] = [{"label": "🎧 Escuchar en YouTube Music", "url": url}]
                with self._lock:        # pypresence no es seguro entre hilos
                    try:
                        self.rpc.update(**datos)
                    except Exception:
                        # pypresence antiguo o imagen externa rechazada: versión sencilla
                        for k in ("buttons", "start", "end"):
                            datos.pop(k, None)
                        datos["large_image"] = "logo"
                        self.rpc.update(**datos)
            except Exception as e:
                print(f"Error actualizando Discord: {e}")

        threading.Thread(target=_update, daemon=True).start()

    def close(self):
        try:
            if self.rpc is not None and self.connected:
                self.rpc.close()
        except Exception:
            pass
        self.connected = False


class MediaKeyHook:
    """Escucha las teclas multimedia nativas del sistema operativo."""
    def __init__(self, on_play_pause, on_next, on_prev, on_stop=None):
        self.listener = None
        self.callbacks = {}
        if keyboard:
            self.callbacks = {
                keyboard.Key.media_play_pause: on_play_pause,
                keyboard.Key.media_next: on_next,
                keyboard.Key.media_previous: on_prev,
            }
            stop_key = getattr(keyboard.Key, "media_stop", None)
            if stop_key is not None and on_stop:
                self.callbacks[stop_key] = on_stop

    def _on_press(self, key):
        cb = self.callbacks.get(key)
        if cb:
            try:
                cb()
            except Exception as e:
                print(f"Tecla multimedia: {e}")

    def start(self):
        if not keyboard:
            print("pynput no instalado. Atajos globales desactivados.")
            return
        try:
            self.listener = keyboard.Listener(on_press=self._on_press)
            self.listener.daemon = True
            self.listener.start()
        except Exception as e:
            print(f"No se pudieron activar las teclas multimedia: {e}")
            self.listener = None

    def stop(self):
        """Antes no existía: al cerrar la app saltaba un error y no se cerraban bandeja ni mini modo."""
        listener, self.listener = self.listener, None
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Ecualizador de 10 bandas
# ---------------------------------------------------------------------------
BANDAS_HZ = (60, 170, 310, 600, 1000, 3000, 6000, 12000, 14000, 16000)
BANDAS_TXT = ("60", "170", "310", "600", "1K", "3K", "6K", "12K", "14K", "16K")

# Perfiles propios (dB, de -20 a 20). Los de VLC se añaden en tiempo de ejecución.
PRESETS_PROPIOS = {
    "Plano":        (0.0, [0.0] * 10),
    "Bass Boost":   (3.0, [9.0, 7.0, 4.0, 1.0, 0.0, 0.0, 1.0, 2.0, 3.0, 4.0]),
    "Rock":         (3.0, [5.0, 3.5, -1.5, -3.0, -1.0, 2.0, 4.5, 5.5, 6.0, 6.0]),
    "Pop":          (3.0, [-1.5, 2.0, 4.5, 3.5, 0.5, -2.0, -1.0, 2.5, 3.5, 3.5]),
    "Electrónica":  (3.0, [7.5, 6.0, 2.0, -1.5, -2.5, 3.5, 2.0, 4.0, 7.0, 8.0]),
    "Voces":        (2.0, [-3.0, -2.0, 0.0, 3.0, 5.0, 5.0, 3.5, 1.0, 0.0, -1.0]),
    "Lo-Fi":        (1.0, [4.0, 3.0, 1.5, 0.0, -1.0, -2.0, -4.0, -7.0, -9.0, -10.0]),
    "Auriculares":  (2.0, [4.0, 2.5, 0.0, -1.0, 0.0, 1.0, 2.5, 3.0, 2.0, 1.0]),
    "Noche (suave)": (0.0, [2.0, 1.0, 0.0, 0.0, -1.0, -2.0, -3.0, -4.0, -5.0, -6.0]),
}
# Nombres antiguos (v19) -> nuevos, por si estaban guardados
_ALIAS = {"Flat": "Plano", "Electronic": "Electrónica"}


def _clamp(v, lo=-20.0, hi=20.0):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(lo, min(hi, v))


def normalizar_eq(cfg):
    """Devuelve un dict EQ válido a partir de lo guardado en los ajustes (o None)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    bandas = cfg.get("bands")
    if not isinstance(bandas, (list, tuple)) or len(bandas) != 10:
        bandas = [0.0] * 10
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "preset": _ALIAS.get(cfg.get("preset"), cfg.get("preset") or "Plano"),
        "preamp": _clamp(cfg.get("preamp", 0.0)),
        "bands": [_clamp(b) for b in bandas],
    }


class VLCequalizer:
    """Ecualizador nativo de VLC: 10 bandas + preamplificador, con presets propios y de VLC."""

    def __init__(self, vlc_player):
        self.player = vlc_player
        self._eq = None
        self.config = normalizar_eq(None)
        self._presets_vlc = None
        self.extra_db = 0.0          # ganancia extra (igualar volumen entre canciones)

    # -- presets ------------------------------------------------------------
    def presets(self):
        """{nombre: (preamp, [10 bandas])} con los propios primero y luego los de VLC."""
        todos = dict(PRESETS_PROPIOS)
        for nombre, valor in self._cargar_presets_vlc().items():
            todos.setdefault(f"VLC · {nombre}", valor)
        return todos

    def _cargar_presets_vlc(self):
        if self._presets_vlc is not None:
            return self._presets_vlc
        self._presets_vlc = {}
        try:
            import vlc
            for i in range(vlc.libvlc_audio_equalizer_get_preset_count()):
                nombre = vlc.libvlc_audio_equalizer_get_preset_name(i)
                if isinstance(nombre, bytes):
                    nombre = nombre.decode("utf-8", "replace")
                eq = vlc.libvlc_audio_equalizer_new_from_preset(i)
                if not eq:
                    continue
                pre = vlc.libvlc_audio_equalizer_get_preamp(eq)
                bandas = [vlc.libvlc_audio_equalizer_get_amp_at_index(eq, b) for b in range(10)]
                vlc.libvlc_audio_equalizer_release(eq)
                self._presets_vlc[str(nombre)] = (round(pre, 1), [round(b, 1) for b in bandas])
        except Exception as e:
            print(f"No se pudieron leer los presets de VLC: {e}")
        return self._presets_vlc

    # -- aplicar --------------------------------------------------------------
    def aplicar(self, config=None):
        """Aplica la configuración (dict de normalizar_eq). Devuelve la config aplicada."""
        if config is not None:
            self.config = normalizar_eq(config)
        c = self.config
        try:
            import vlc
            extra = float(self.extra_db or 0.0)
            if not c["enabled"] and abs(extra) < 0.05:
                self.player.set_equalizer(None)
                self._eq = None
                return c
            eq = vlc.AudioEqualizer()
            # el preamplificador también sirve para igualar el volumen entre canciones
            eq.set_preamp(_clamp((c["preamp"] if c["enabled"] else 0.0) + extra))
            for i, amp in enumerate(c["bands"] if c["enabled"] else [0.0] * 10):
                eq.set_amp_at_index(float(amp), i)
            self.player.set_equalizer(eq)
            self._eq = eq          # se mantiene la referencia mientras esté activo
        except Exception as e:
            print(f"Error aplicando el ecualizador: {e}")
        return c

    def aplicar_preset(self, nombre):
        """Compatibilidad con v19: aplica un preset por nombre y lo activa."""
        nombre = _ALIAS.get(nombre, nombre)
        pre, bandas = self.presets().get(nombre, PRESETS_PROPIOS["Plano"])
        return self.aplicar({"enabled": nombre != "Plano", "preset": nombre,
                             "preamp": pre, "bands": list(bandas)})
