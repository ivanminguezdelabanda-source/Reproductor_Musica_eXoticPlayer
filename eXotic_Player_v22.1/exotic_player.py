import difflib
import json
import os
import re
import queue
import subprocess
import sys
import time
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageTk
from ytmusicapi import YTMusic
import yt_dlp

import app_paths
import duraciones
app_paths.preparar_entorno()  # debe ir ANTES de importar vlc
import vlc

# Supabase (login + datos en la nube). Si falla, la app sigue en modo local.
from cloud_supabase import SupabaseCloud
from social_ui import SocialManager  # amigos y jam

# --- Integraciones: Discord, Teclado y Ecualizador ---
from integrations import DiscordRPC, MediaKeyHook, VLCequalizer
from tray_mini import MiniPlayer, TrayManager   # bandeja del sistema y mini modo
from player_data import datos_vacios
from player_extras import PlayerExtrasMixin    # repetir, temporizador, atajos, temas, EQ...
from player_media import PlayerMediaMixin      # archivos locales, fundido, Wrapped, Last.fm, Discord
from audio_fx import PlayerAudioFxMixin        # slowed / nightcore e igualar volumen
from explore import PlayerExploreMixin         # Explorar y sugerencias del buscador
from ytm_account import PlayerYTMMixin         # tu cuenta de YouTube Music
from updates import PlayerUpdatesMixin         # avisos de versión nueva
import local_files
from lyrics import CacheLetras, VentanaLetra   # letras sincronizadas
from retro_sounds import SonidosRetro          # sonidos de sistema estilo XP
from themes import Tematizador, TEMA_POR_DEFECTO
from player_cloud import PlayerCloudMixin
from player_queue import PlayerQueueMixin
from player_playlists import PlayerPlaylistsMixin
from player_history import PlayerHistoryMixin
from player_stats import PlayerStatsMixin
from player_ui import PlayerUIMixin
from soundscope_ps1 import SoundscopeVentana   # visualizador PS1 a pantalla completa
from video_viewer import VisorVideo            # ventana del videoclip

# ---------------------------------------------------------------------------
# Datos de la aplicación
# ---------------------------------------------------------------------------
APP_VERSION = "22.1"
STREAM_TTL = 3 * 3600
VIDEO_ALTURA_MAX = 720          # calidad máxima del videoclip
AUTO_UPDATE_YTDLP = True


def ruta_recurso(nombre):
    """Ruta de un recurso tanto en desarrollo como dentro de un ejecutable PyInstaller."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, nombre)


ICON_PATH = ruta_recurso("exotic_player.ico")


def configurar_icono_ventana(root):
    """Aplica el icono de eXotic Player a la ventana y a la barra de tareas."""
    try:
        root.iconbitmap(ICON_PATH)
    except Exception:
        pass
    try:
        icon = Image.open(ICON_PATH).convert("RGBA")
        try:
            icon.seek(icon.n_frames - 1)
        except Exception:
            pass
        root._exotic_icon_photo = ImageTk.PhotoImage(icon.copy())
        root.iconphoto(True, root._exotic_icon_photo)
    except Exception:
        pass


def limpiar_path():
    buenas = []
    for p in os.environ.get("PATH", "").split(os.pathsep):
        try:
            if p and os.path.isdir(p):
                buenas.append(p)
        except OSError:
            pass
    os.environ["PATH"] = os.pathsep.join(buenas)


limpiar_path()


def formato_tiempo(ms):
    m, s = divmod(max(0, int(ms // 1000)), 60)
    return f"{m:02d}:{s:02d}"


class LoginDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        bg = app.bg_color
        self.title("Iniciar sesión")
        self.configure(bg=bg)
        self.resizable(False, False)
        self.transient(app.root)

        f = tk.Frame(self, bg=bg, padx=16, pady=12)
        f.pack()
        tk.Label(f, text="Email:", bg=bg, font=("Tahoma", 8, "bold")).grid(row=0, column=0, sticky="w")
        self.e_mail = tk.Entry(f, width=32, font=("Tahoma", 9), relief=tk.SUNKEN, bd=2)
        self.e_mail.grid(row=1, column=0, pady=(0, 6))
        tk.Label(f, text="Contraseña (mín. 6 caracteres):", bg=bg,
                 font=("Tahoma", 8, "bold")).grid(row=2, column=0, sticky="w")
        self.e_pass = tk.Entry(f, width=32, show="•", font=("Tahoma", 9), relief=tk.SUNKEN, bd=2)
        self.e_pass.grid(row=3, column=0, pady=(0, 6))

        self.lbl = tk.Label(f, text="", bg=bg, fg="#A00000", wraplength=260,
                            font=("Tahoma", 8), justify="left")
        self.lbl.grid(row=4, column=0, sticky="w")

        bar = tk.Frame(f, bg=bg)
        bar.grid(row=5, column=0, pady=(8, 0))
        self.b_login = tk.Button(bar, text="Iniciar sesión", bg="#D6E4FF", bd=2,
                                 font=("Tahoma", 8, "bold"), command=lambda: self._enviar(False))
        self.b_login.pack(side=tk.LEFT, padx=3)
        self.b_reg = tk.Button(bar, text="Crear cuenta", bg="#D9F2D9", bd=2,
                               font=("Tahoma", 8, "bold"), command=lambda: self._enviar(True))
        self.b_reg.pack(side=tk.LEFT, padx=3)

        self.bind("<Return>", lambda e: self._enviar(False))
        self.bind("<Escape>", lambda e: self.destroy())

        self.update_idletasks()
        r = app.root
        x = r.winfo_rootx() + (r.winfo_width() - self.winfo_width()) // 2
        y = r.winfo_rooty() + (r.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{x}+{y}")
        app.tematizar(self)
        self.grab_set()
        self.e_mail.focus_set()

    def _busy(self, busy):
        st = tk.DISABLED if busy else tk.NORMAL
        self.b_login.config(state=st)
        self.b_reg.config(state=st)

    def _enviar(self, registro):
        email = self.e_mail.get().strip()
        pw = self.e_pass.get()
        if "@" not in email or len(pw) < 6:
            self.lbl.config(text="Escribe un email válido y una contraseña de 6+ caracteres.",
                            fg="#A00000")
            return
        self.lbl.config(text="Conectando...", fg="#333333")
        self._busy(True)
        cloud = self.app.cloud

        def task():
            try:
                if registro:
                    if not cloud.registrar(email, pw):
                        self.app.ui(self._fin, "Cuenta creada. Confirma tu email y luego inicia sesión.", False)
                        return
                else:
                    cloud.login(email, pw)
                self.app.ui(self._fin, "", True)
            except Exception as e:
                self.app.ui(self._fin, str(e)[:200], False)

        self.app.pool_stream.submit(task)

    def _fin(self, msg, ok):
        if ok:
            self.app._sesion_activa()
            if self.winfo_exists():
                self.destroy()
            return
        if self.winfo_exists():
            self._busy(False)
            self.lbl.config(text=msg, fg="#A00000")


class WinXP_ExoticPlayer(PlayerUpdatesMixin, PlayerYTMMixin, PlayerExploreMixin, PlayerAudioFxMixin, PlayerMediaMixin, PlayerExtrasMixin, PlayerCloudMixin, PlayerQueueMixin, PlayerPlaylistsMixin, PlayerHistoryMixin, PlayerStatsMixin, PlayerUIMixin):
    def __init__(self, root, sonido_inicio=True):
        self.root = root
        self.APP_VERSION = APP_VERSION
        configurar_icono_ventana(self.root)
        self.root.title(f"eXotic Media Player v{APP_VERSION}")
        self.root.geometry("1240x900")
        self.root.minsize(1120, 820)
        self.root.resizable(True, True)

        self.bg_color = "#ECE9D8"
        self.header_blue = "#0A246A"
        self.lcd_bg = "#050B05"
        self.lcd_green = "#00FF66"
        self.root.configure(bg=self.bg_color)

        self.style = ttk.Style()
        self.style.theme_use('default')
        self.style.configure("TScale", background=self.bg_color, troughcolor="#B0B0B0")

        # Preferencias de este ordenador (volumen, tema, visualizador...)
        self._cargar_prefs()
        self.tema = Tematizador(self.root, self.prefs.get("theme", TEMA_POR_DEFECTO))
        self.sonidos = SonidosRetro(os.path.join(app_paths.DATA_DIR, "sonidos"), self.prefs.get("sounds", True))
        self.analizador = None
        self._xf = None                  # fundido en curso
        self._iniciar_lastfm()

        self._ui_queue = queue.Queue()
        self.pool_img = ThreadPoolExecutor(max_workers=4)
        self.pool_stream = ThreadPoolExecutor(max_workers=3)
        self.pool_cloud = ThreadPoolExecutor(max_workers=1)

        self.ytmusic = crear_ytmusic()
        self.cloud = SupabaseCloud()
        self.social = SocialManager(self)
        self.sesion_iniciada = False
        self.nombre_cuenta = None
        self.email_cuenta = None
        self.cloud_data = datos_vacios()
        self._local_file = app_paths_guest_file()      # el modo invitado también se guarda
        self._sync_status = "local"
        self._sync_message = "Sin sincronizar"
        self._last_sync_at = None

        # sin estirar el tiempo: al cambiar la velocidad cambia también el tono (slowed / nightcore)
        vlc_args = ['--network-caching=2000', '--no-audio-time-stretch']
        self.vlc_instance = vlc.Instance(*vlc_args)
        self.player = self.vlc_instance.media_player_new()
        self.vlc_eq = VLCequalizer(self.player)

        self.queue_normal = []
        self.queue_playlist = []
        self.queue_jam = []          # cola compartida mientras estás en una jam (la gestiona social_ui)
        self._queue_mode = "normal"
        self.queue = self.queue_normal
        self.current_index = -1
        self._playlist_shuffle = False
        self._playlist_shuffle_source = None
        self._playlist_shuffle_order = []
        self.user_dragging = False
        self._search_timer = None
        self._search_token = 0
        self._play_token = 0
        self._cargando = False
        self._cover_url = None
        self.image_cache = OrderedDict()
        self._stream_cache = {}
        self._reintentos_vlc = 0
        self.autoplay_var = tk.BooleanVar(value=True)
        self._reco_pendiente = False
        self._esperando_reco = False
        self._reproducidas = set()
        self.playlist_var = tk.StringVar(value="Mi música")
        self._playlist_entry = None

        self.num_bars = 24
        self.eq_levels = [0.0] * self.num_bars
        self.eq_peaks = [0.0] * self.num_bars
        self.eq_items = []
        self.eq_peak_items = []
        self.eq_visible = [0] * self.num_bars
        self.eq_peak_vis = [0] * self.num_bars
        self.eq_x = []
        self.eq_dim = (0, 0)
        self.eq_segs = 1
        self.eq_step = 4

        self.soundscope = SoundscopeVentana(self)
        # --- versión audio / videoclip ---
        self.visor = VisorVideo(self)
        self.tipo_busqueda_var = tk.StringVar(value="songs")   # "songs" | "videos"
        self._modo_video = False          # reproducir el videoclip siempre que exista
        self._forzar_video = set()        # canciones concretas a ver en videoclip
        self._solo_audio = set()          # videoclips que el usuario quiere solo en audio
        self._video_fallido = set()       # videoclips que VLC no pudo reproducir
        self._ids_clip = set()            # videoId que ya SON un videoclip (búsqueda de vídeos)
        self._clip_cache = {}             # videoId de canción -> videoId del videoclip (o None)
        self._stream_cache_video = {}
        self._reproduciendo_video = False
        self._reanudar_ms = 0
        self._reanudar_pendiente = None   # (videoId, ms) para "seguir por donde ibas"
        self._duraciones_en_curso = set()
        self._sleep_fin = None
        self._sleep_fin_cancion = False
        self.letras = CacheLetras(self)
        self.letra = VentanaLetra(self)
        # el modo invitado arranca con lo que guardó la última vez
        try:
            from player_data import cargar_datos_local
            if os.path.exists(self._local_file):
                self.cloud_data = cargar_datos_local(self._local_file)
        except Exception as e:
            print(f"No se pudieron cargar los datos de invitado: {e}")
        self.construir_interfaz()
        self.tema.aplicar_arbol(self.root)
        self.tema.estilo_ttk(self.style)
        self._instalar_atajos()
        self._instalar_sugerencias()
        self.root.bind("<F11>", lambda e: self.soundscope.alternar())
        self._asegurar_playlist_principal()
        self._reconstruir_playlist_guardada()
        self._actualizar_selector_playlists()
        self._aplicar_ajustes()
        self._preparar_reanudar()
        self._iniciar_analizador()

        self.root.protocol("WM_DELETE_WINDOW", self.al_cerrar)
        self.root.after(30, self._procesar_cola_ui)
        if AUTO_UPDATE_YTDLP and not os.environ.get("EXOTIC_SMOKE"):
            self.actualizar_ytdlp_async()
        self.root.after(100, self.animar_ecualizador)
        self.root.after(30, self.actualizar_reproductor)

        self._restaurar_sesion_async()

        # Integraciones
        self.discord_rpc = DiscordRPC(client_id="1554600639097610242")
        self.discord_rpc.connect()

        self.media_keys = MediaKeyHook(
            on_play_pause=lambda: self.ui(self.toggle_play),
            on_next=lambda: self.ui(self.siguiente_cancion),
            on_prev=lambda: self.ui(self.anterior_cancion),
            on_stop=lambda: self.ui(self.detener_cancion),
        )
        self.media_keys.start()
        self._iniciar_atajos_globales()
        self._iniciar_ytm()
        self.root.after(8000, self.comprobar_actualizaciones)

        # Bandeja del sistema y mini modo
        self.mini = MiniPlayer(self)
        self.tray = TrayManager(self, ICON_PATH)
        self.tray.start()
        self.root.bind("<Unmap>", self._al_minimizar)
        if sonido_inicio and self.prefs.get("sounds", True):
            self.root.after(300, lambda: self.sonar("inicio"))


    # --- modos de ventana: principal / mini / bandeja


    def al_cerrar(self):
        if getattr(self, "_cerrando", False):
            return
        self._cerrando = True
        try:
            self.root.withdraw()            # se cierra "al instante" aunque quede subir a la nube
        except Exception:
            pass
        try:
            self._cancelar_fundido()
            self._volcar_escucha()
            self._guardar_pendientes_lastfm()
            self._guardar_punto_reanudar()
            self._guardar_prefs(inmediato=True)
        except Exception as e:
            print(f"No se pudo guardar el estado al cerrar: {e}")
        try:
            self.cancelar_temporizador(silencioso=True)
            self.letra.cerrar()
            self._detener_analizador()
        except Exception:
            pass
        try:
            if hasattr(self, "soundscope"):
                self.soundscope.cerrar()
            if hasattr(self, "visor"):
                self.visor.ocultar()
        except Exception:
            pass
        for nombre, metodo in (("discord_rpc", "close"), ("media_keys", "stop"), ("atajos_globales", "detener"),
                               ("tray", "stop"), ("mini", "destruir")):
            try:                            # cada paso por separado: si uno falla, el resto sigue
                obj = getattr(self, nombre, None)
                if obj is not None:
                    getattr(obj, metodo)()
            except Exception as e:
                print(f"Error cerrando {nombre}: {e}")

        try:
            self.social.al_cerrar_app()
        except Exception as e:
            print(f"Error cerrando amigos/jam: {e}")
        try:
            try:
                self._sincronizar_cola_en_datos()
                self._guardar_local()
            except Exception as e:
                print(f"No se pudieron guardar los datos locales al cerrar: {e}")
            self._cancelar_subida_pendiente()
            if self.cloud.logged_in:
                try:
                    data = json.loads(json.dumps(self.cloud_data, ensure_ascii=False))
                    self.cloud.subir_datos(data, self.cloud.user_id)
                except Exception as e:
                    print(f"No se pudieron guardar los datos al cerrar: {e}")

            self.player.stop()
            self.player.release()
            self.vlc_instance.release()
        except Exception:
            pass
        self.pool_img.shutdown(wait=False, cancel_futures=True)
        self.pool_stream.shutdown(wait=False, cancel_futures=True)
        self.pool_cloud.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


    def proceso_login(self):
        if self.sesion_iniciada:
            if messagebox.askyesno("Cerrar sesión", "¿Cerrar la sesión en esta aplicación?"):
                self.cerrar_sesion()
            return
        if not self.cloud.disponible:
            messagebox.showerror("Supabase", "Supabase no está configurado.\n\n" + (self.cloud.error_init or ""))
            return
        LoginDialog(self)


    def _buscar(self, query, filtro="songs"):
        try:
            return self.ytmusic.search(query, filter=filtro, limit=10)
        except Exception:
            return YTMusic().search(query, filter=filtro, limit=10)


    @staticmethod
    def _duracion_a_segundos(valor):
        """Convierte MM:SS/HH:MM:SS, segundos o milisegundos a segundos."""
        return duraciones.a_segundos(valor)

    def _obtener_duracion_cancion(self, item, red=True):
        """Obtiene una duración fiable de cualquier formato que devuelva YTMusic.

        Con ``red=False`` no consulta Internet (para no congelar la interfaz)."""
        segundos = duraciones.de_pista(item)
        if segundos > 0:
            return segundos
        video_id = item.get('videoId') or ''
        if not video_id or not red or video_id.startswith("file:"):
            return 0
        # Fallback: algunos resultados de búsqueda no traen duración.
        try:
            detalle = self.ytmusic.get_song(video_id)
            segundos = duraciones.de_pista(detalle) or duraciones.de_pista(detalle.get('videoDetails') or {})
            if segundos > 0:
                return segundos
        except Exception as e:
            print(f"[duracion] no se pudo obtener {video_id}: {e}")
        return 0

    @staticmethod
    def _mapear_canciones(items):
        canciones = []
        for item in items:
            video_id = item.get('videoId')
            if not video_id:
                continue
            thumbs = item.get('thumbnails') or []
            canciones.append({
                'title': item.get('title', 'Desconocido'),
                'artist': ", ".join(a['name'] for a in item.get('artists') or []),
                'videoId': video_id,
                'coverUrl': thumbs[0]['url'] if thumbs else None,
                'highCoverUrl': thumbs[-1]['url'] if thumbs else None,
                'duration': duraciones.de_pista(item),
            })
        return canciones


    def actualizar_ytdlp_async(self):
        if getattr(sys, "frozen", False):
            # El .exe no puede actualizar yt-dlp por su cuenta: solo avisa si hay una versión nueva
            def avisar():
                try:
                    from yt_dlp.version import __version__ as actual

                    def num(v):
                        return tuple(int(x) for x in v.split("."))

                    with urllib.request.urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=10) as r:
                        ultima = json.load(r)["info"]["version"]
                    if num(ultima) > num(actual):
                        self.ui(self.status_var.set,
                                f"Hay un yt-dlp más nuevo ({ultima}; tienes {actual}). "
                                "Si falla la música, recompila la app con build_exe.bat.")
                except Exception as e:
                    print(f"No se pudo comprobar la versión de yt-dlp: {e}")

            self.pool_stream.submit(avisar)
            return

        def task():
            try:
                r = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"],
                    capture_output=True, text=True, timeout=240
                )
                if "Successfully installed" in r.stdout:
                    self.ui(self.status_var.set, "yt-dlp actualizado: reinicia la app para aplicar los cambios.")
            except Exception as e:
                print(f"No se pudo actualizar yt-dlp: {e}")

        self.pool_stream.submit(task)

    def _opciones_ytdlp(self, player_clients=None, formato=None):
        opts = {
            'format': formato or 'bestaudio[ext=m4a]/bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'socket_timeout': 15,
            'retries': 3,
            'js_runtimes': {'deno': {}, 'node': {}, 'bun': {}},
        }
        if player_clients:
            opts['extractor_args'] = {'youtube': {'player_client': player_clients}}
        navegador = os.environ.get("YTM_COOKIES_BROWSER")
        if navegador:
            opts['cookiesfrombrowser'] = (navegador,)
        return opts

    def obtener_stream_url(self, video_id):
        ahora = time.time()
        cached = self._stream_cache.get(video_id)
        if cached and ahora - cached[1] < STREAM_TTL:
            return cached[0], cached[2]

        page = f"https://music.youtube.com/watch?v={video_id}"
        ultimo_error = None
        for clients in (None, ['tv', 'web_safari'], ['android_vr'], ['mweb']):
            try:
                with yt_dlp.YoutubeDL(self._opciones_ytdlp(clients)) as ydl:
                    info = ydl.extract_info(page, download=False)
                url = info.get('url')
                if not url and info.get('requested_formats'):
                    url = info['requested_formats'][0].get('url')
                if not url:
                    raise RuntimeError("yt-dlp no devolvió una URL de audio")
                ua = (info.get('http_headers') or {}).get('User-Agent', 'Mozilla/5.0')
                self._stream_cache[video_id] = (url, ahora, ua)
                return url, ua
            except Exception as e:
                ultimo_error = e
                print(f"[yt-dlp] intento con {clients or 'defecto'} falló: {e}")
                time.sleep(0.5)
        raise ultimo_error

    # ------------------------------------------------------------------
    # Versión audio / videoclip
    # ------------------------------------------------------------------
    def _quiere_video(self, cancion):
        vid = cancion['videoId']
        if local_files.es_local(vid) or vid in self._video_fallido or vid in self._solo_audio:
            return False
        return self._modo_video or vid in self._forzar_video or vid in self._ids_clip

    @staticmethod
    def _norm_titulo(t):
        t = re.sub(r"[\(\[].*?[\)\]]", " ", (t or "").lower())
        return " ".join(re.sub(r"[^\w ]", " ", t).split())

    def _buscar_clip(self, cancion):
        """Devuelve el videoId del videoclip de una canción (o None si no hay)."""
        vid = cancion['videoId']
        if vid in self._ids_clip:
            return vid
        if vid in self._clip_cache:
            return self._clip_cache[vid]
        titulo, artista = cancion.get('title', ''), cancion.get('artist', '')
        try:
            res = self._buscar(f"{artista} {titulo}".strip(), "videos")
        except Exception as e:
            print(f"[clip] búsqueda falló: {e}")
            return None                      # no se cachea: puede ser un fallo puntual
        t0, a0 = self._norm_titulo(titulo), self._norm_titulo(artista)
        dur0 = cancion.get('duration') or 0
        mejor, mejor_pts = None, 0.0
        for r in res:
            rid = r.get('videoId')
            if not rid:
                continue
            t1 = self._norm_titulo(r.get('title'))
            pts = difflib.SequenceMatcher(None, t0, t1).ratio()
            nombres = " ".join(self._norm_titulo(a.get('name')) for a in (r.get('artists') or []))
            if a0 and (a0 in nombres or nombres in a0 and nombres):
                pts += 0.15
            if r.get('videoType') == 'MUSIC_VIDEO_TYPE_OMV':
                pts += 0.25                  # videoclip oficial
            for malo in ('lyric', 'letra', 'live', 'directo', 'cover', 'karaoke', 'reaction', 'audio'):
                if malo in t1 and malo not in t0:
                    pts -= 0.3
            dur1 = self._duracion_a_segundos(r.get('duration'))
            if dur0 and dur1:
                pts += 0.1 if abs(dur0 - dur1) <= max(15, dur0 * 0.12) else -0.1
            if pts > mejor_pts:
                mejor, mejor_pts = rid, pts
        resultado = mejor if mejor_pts >= 0.55 else None
        self._clip_cache[vid] = resultado
        if resultado:
            self._ids_clip.add(resultado)
        return resultado

    def obtener_stream_video(self, video_id):
        """(url_video, url_audio_o_None, user_agent) para reproducir un videoclip en VLC."""
        ahora = time.time()
        c = self._stream_cache_video.get(video_id)
        if c and ahora - c[3] < STREAM_TTL:
            return c[0], c[1], c[2]
        h = VIDEO_ALTURA_MAX
        formato = (f"bestvideo[height<={h}][vcodec^=avc1]+bestaudio[ext=m4a]/"
                   f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best")
        page = f"https://www.youtube.com/watch?v={video_id}"
        ultimo_error = None
        for clients in (None, ['tv', 'web_safari'], ['android_vr'], ['mweb']):
            try:
                with yt_dlp.YoutubeDL(self._opciones_ytdlp(clients, formato)) as ydl:
                    info = ydl.extract_info(page, download=False)
                v_url = a_url = None
                reqs = info.get('requested_formats') or []
                if reqs:
                    for f in reqs:
                        tv = f.get('vcodec') not in (None, 'none')
                        ta = f.get('acodec') not in (None, 'none')
                        if tv and v_url is None:
                            v_url = f.get('url')
                        elif ta and not tv:
                            a_url = f.get('url')
                else:
                    v_url = info.get('url')
                if not v_url:
                    raise RuntimeError("yt-dlp no devolvió una URL de vídeo")
                ua = (info.get('http_headers') or {}).get('User-Agent', 'Mozilla/5.0')
                self._stream_cache_video[video_id] = (v_url, a_url, ua, ahora)
                return v_url, a_url, ua
            except Exception as e:
                ultimo_error = e
                print(f"[yt-dlp vídeo] intento con {clients or 'defecto'} falló: {e}")
                time.sleep(0.5)
        raise ultimo_error

    def _actualizar_boton_video(self):
        btn = getattr(self, "video_btn", None)
        if btn is None:
            return
        activo = self._modo_video or self._reproduciendo_video
        btn.config(text="🎬 Videoclip: ON" if activo else "🎬 Videoclip",
                   bg=self.c("#2E9E4F" if activo else "#C0763A"),
                   relief=tk.SUNKEN if activo else tk.RAISED)

    def alternar_videoclip(self):
        if self._modo_video or self._reproduciendo_video:
            self.desactivar_videoclip()
        else:
            self.activar_videoclip()

    def activar_videoclip(self):
        self._modo_video = True
        self._solo_audio.clear()
        self._actualizar_boton_video()
        self._recargar_misma_posicion()

    def desactivar_videoclip(self):
        """Vuelve a la versión solo audio (cierra el visor y sigue por donde iba)."""
        self._modo_video = False
        self._forzar_video.clear()
        if 0 <= self.current_index < len(self.queue):
            vid = self.queue[self.current_index]['videoId']
            if vid in self._ids_clip:
                self._solo_audio.add(vid)
        if self._reproduciendo_video:
            self._recargar_misma_posicion()
        else:
            self.visor.ocultar()
        self._reproduciendo_video = False
        self._actualizar_boton_video()

    def reproducir_clip_directo(self, cancion):
        """Botón 🎬 de una tarjeta: reproduce esa canción en su versión videoclip."""
        self._forzar_video.add(cancion['videoId'])
        self._solo_audio.discard(cancion['videoId'])
        self.reproducir_directo(cancion)

    def _recargar_misma_posicion(self):
        """Recarga la pista actual (en la versión que toque) manteniendo el minuto."""
        import vlc
        if not (0 <= self.current_index < len(self.queue)):
            return
        if self.player.get_state() not in (vlc.State.Playing, vlc.State.Paused):
            return
        self._reanudar_ms = max(0, self.player.get_time())
        self.cargar_y_reproducir_actual()

    # ------------------------------------------------------------------
    def cargar_y_reproducir_actual(self):
        if not (0 <= self.current_index < len(self.queue)):
            return

        self._cancelar_fundido()
        self._play_token += 1
        token = self._play_token
        self._cargando = True
        self._esperando_reco = False
        reanudar_ms, self._reanudar_ms = self._reanudar_ms, 0
        self.player.stop()

        cancion = self.queue[self.current_index]
        pendiente, self._reanudar_pendiente = self._reanudar_pendiente, None
        if not reanudar_ms and pendiente and pendiente[0] == cancion['videoId']:
            reanudar_ms = pendiente[1]          # "seguir por donde ibas" al abrir la app
        self.social.al_cargar(cancion['videoId'])
        self.actualizar_vista_cola()
        self.cargar_caratula_principal(cancion.get('coverUrl'))
        self.lcd_title.config(text=f"Cargando: {cancion['title']}...")
        self._actualizar_boton_like()
        self.status_var.set(f"Extrayendo stream de: {cancion['title']}...")

        def task():
            nota = ""
            if local_files.es_local(cancion['videoId']):
                ruta = local_files.ruta_de(cancion['videoId'])
                if os.path.exists(ruta):
                    self.ui(self._iniciar_reproduccion, token, ruta, None, cancion, reanudar_ms, " 💾")
                else:
                    self.ui(self._error_stream, token, f"No encuentro el archivo: {ruta}")
                return
            if self._quiere_video(cancion):
                try:
                    clip_id = self._buscar_clip(cancion)
                    if clip_id:
                        v_url, a_url, ua = self.obtener_stream_video(clip_id)
                        self.ui(self._iniciar_reproduccion_video, token, v_url, a_url, ua, cancion, reanudar_ms)
                        return
                    nota = " (no hay videoclip, solo audio)"
                except Exception as e:
                    print(f"Error extrayendo videoclip: {e}")
                    nota = " (el videoclip falló, solo audio)"
            try:
                audio_url, ua = self.obtener_stream_url(cancion['videoId'])
            except Exception as e:
                print(f"Error extrayendo stream: {e}")
                self.ui(self._error_stream, token, str(e))
                return
            self.ui(self._iniciar_reproduccion, token, audio_url, ua, cancion, reanudar_ms, nota)

        self.pool_stream.submit(task)

    def _iniciar_reproduccion(self, token, audio_url, ua, cancion, reanudar_ms=0, nota=""):
        if token != self._play_token:
            return
        self._reproduciendo_video = False
        self.visor.ocultar()
        media = self.vlc_instance.media_new(audio_url)
        if ua:
            media.add_option(f":http-user-agent={ua}")
        media.add_option(":no-video")
        if reanudar_ms > 1000:
            media.add_option(f":start-time={reanudar_ms / 1000:.2f}")
        self.player.set_media(media)
        self.player.play()
        self._tras_iniciar(cancion, reanudar_ms, nota)

    def _iniciar_reproduccion_video(self, token, v_url, a_url, ua, cancion, reanudar_ms=0):
        if token != self._play_token:
            return
        self._reproduciendo_video = True
        self.visor.mostrar(f"{cancion['title']} — {cancion['artist']}")
        media = self.vlc_instance.media_new(v_url)
        media.add_option(f":http-user-agent={ua}")
        if a_url:
            media.add_option(f":input-slave={a_url}")
        if reanudar_ms > 1000:
            media.add_option(f":start-time={reanudar_ms / 1000:.2f}")
        self.player.set_media(media)
        self.player.play()
        self._tras_iniciar(cancion, reanudar_ms, " 🎬")

    def _tras_iniciar(self, cancion, reanudar_ms, nota=""):
        self._cargando = False
        self.aplicar_velocidad()
        self._ajustar_volumen_cancion(cancion)
        self._actualizar_boton_video()
        self.lcd_title.config(text=f"▶ {cancion['title']} — {cancion['artist']}")
        self.status_var.set(f"Reproduciendo: {cancion['title']}{nota}")

        self.root.after(1500, lambda: self._discord(True))     # con la duración ya conocida

        if not reanudar_ms:                 # al cambiar de versión no cuenta como otra reproducción
            self._reproducidas.add(cancion['videoId'])
            self._registrar_reproduccion(cancion)
            self._empieza_cancion(cancion)
            self.social.publicar_actividad(cancion)
            self._notificar_cancion(cancion)
        self._actualizar_boton_like()
        self._precargar_siguiente()
        self._asegurar_siguiente()

    def _error_stream(self, token, detalle=""):
        if token != self._play_token:
            return
        self._cargando = False
        self.lcd_title.config(text="❌ Error en streaming")
        linea = detalle.replace("\n", " ")[:110]
        self.status_var.set(f"Error al cargar: {linea}" if linea else "Error al cargar la canción.")

    def _precargar_siguiente(self):
        nxt = self.current_index + 1
        if nxt < len(self.queue) and self._quiere_video(self.queue[nxt]):
            sig = self.queue[nxt]

            def pre_video():
                try:
                    cid = self._buscar_clip(sig)
                    if cid:
                        self.obtener_stream_video(cid)
                except Exception:
                    pass
            self.pool_stream.submit(pre_video)
            return
        if nxt < len(self.queue):
            vid = self.queue[nxt]['videoId']
            if local_files.es_local(vid):
                return
            cached = self._stream_cache.get(vid)
            if not cached or time.time() - cached[1] >= STREAM_TTL:
                def pre():
                    try:
                        self.obtener_stream_url(vid)
                    except Exception:
                        pass
                self.pool_stream.submit(pre)

    def _asegurar_siguiente(self):
        if self._queue_mode != "normal":
            return
        if not self.autoplay_var.get() or self._reco_pendiente:
            return
        if not self.queue or self.current_index != len(self.queue) - 1:
            return
        base_id = self.queue[self.current_index]['videoId']
        if local_files.es_local(base_id):
            return                          # sin recomendaciones para archivos del ordenador
        self._reco_pendiente = True

        def task():
            try:
                recs = self._obtener_recomendaciones(base_id)
            except Exception as e:
                print(f"Error buscando recomendaciones: {e}")
                recs = []
            self.ui(self._agregar_recomendacion, base_id, recs)

        self.pool_stream.submit(task)

    def _agregar_recomendacion(self, base_id, recs):
        self._reco_pendiente = False
        if self._queue_mode != "normal" or not self.autoplay_var.get():
            self._esperando_reco = False
            return
            
        if (not self.queue or self.current_index != len(self.queue) - 1
                or self.queue[self.current_index]['videoId'] != base_id):
            self._asegurar_siguiente()
            return

        excluidas = {t['videoId'] for t in self.queue} | self._reproducidas
        nuevas = [t for t in recs if t['videoId'] not in excluidas]
        if not nuevas:
            if self._esperando_reco:
                self.detener_cancion()
                self.status_var.set("No encontré recomendaciones. Fin de la cola.")
            else:
                self.status_var.set("No se encontraron recomendaciones para esta canción.")
            return

        rec = dict(nuevas[0])
        rec['auto'] = True   
        self.queue.append(rec)
        self.actualizar_vista_cola()
        self._guardar_si_corresponde()
        self._precargar_siguiente()   
        if self._esperando_reco:
            self._esperando_reco = False
            self.siguiente_cancion()
        else:
            self.status_var.set(f"✨ Siguiente (recomendada): {rec['title']}")

    def _obtener_recomendaciones(self, video_id):
        try:
            res = self.ytmusic.get_watch_playlist(videoId=video_id, radio=True, limit=25)
        except Exception:
            res = YTMusic().get_watch_playlist(videoId=video_id, radio=True, limit=25)
        return self._mapear_watch((res or {}).get('tracks'))

    @staticmethod
    def _mapear_watch(items):
        canciones = []
        for it in items or []:
            vid = it.get('videoId')
            if not vid:
                continue
            thumbs = it.get('thumbnail') or it.get('thumbnails') or []
            cover = thumbs[-1]['url'] if thumbs else None
            canciones.append({
                'title': it.get('title', 'Desconocido'),
                'artist': ", ".join(a['name'] for a in it.get('artists') or [] if a.get('name')),
                'videoId': vid,
                'coverUrl': cover,
                'highCoverUrl': cover,
                'duration': WinXP_ExoticPlayer._duracion_a_segundos(it.get('duration')),
            })
        return canciones

    def _al_cambiar_autoplay(self):
        st = self.cloud_data.setdefault("settings", {})
        st["autoplay"] = bool(self.autoplay_var.get())
        self._guardar_si_corresponde()
        if self.autoplay_var.get():
            self._asegurar_siguiente()
            self.status_var.set("Autoplay activado: al acabar la cola sonará una recomendación.")
        else:
            self._esperando_reco = False
            self.status_var.set("Autoplay desactivado.")

    def _aplicar_ajustes(self):
        st = self.cloud_data.get("settings") or {}
        self.autoplay_var.set(bool(st.get("autoplay", True)))
        self._actualizar_boton_repetir()
        self._actualizar_boton_fx()
        self._aplicar_eq_guardado()

    def toggle_play(self):
        state = self.player.get_state()
        if state == vlc.State.Playing:
            self.pausar_cancion()
        else:
            self.reproducir_actual()

    def reproducir_actual(self):
        state = self.player.get_state()
        if state == vlc.State.Paused:
            self.player.set_pause(0)
            self.status_var.set("Reanudado.")
            self._discord(True)
                
        elif state == vlc.State.Playing or self._cargando:
            return
        elif self.queue:
            if self.current_index == -1:
                self.current_index = 0
            self.cargar_y_reproducir_actual()

    def pausar_cancion(self):
        if self.player.get_state() == vlc.State.Playing:
            self.player.set_pause(1)
            self.status_var.set("Pausado.")
            self._discord(False)

    def detener_cancion(self):
        self._cancelar_fundido()
        self._play_token += 1      
        self._cargando = False
        self._esperando_reco = False
        self.player.stop()
        self.social.al_detener()   
        self.lcd_title.config(text="*** Detenido ***")
        self.lcd_time.config(text="[00:00 / 00:00]")
        self.time_slider.set(0)
        self._reset_caratula()
        self.status_var.set("Detenido.")
        
        if hasattr(self, "discord_rpc"):
            self.discord_rpc.update_presence("Detenido", "", is_playing=False)

    def siguiente_cancion(self):
        if self._queue_mode == "playlist" and self._playlist_shuffle:
            if not self._playlist_shuffle_order:
                self._crear_orden_aleatorio_playlist(self.current_index if self.current_index >= 0 else None)
            try:
                pos = self._playlist_shuffle_order.index(self.current_index)
            except ValueError:
                pos = -1
            if pos + 1 < len(self._playlist_shuffle_order):
                self.current_index = self._playlist_shuffle_order[pos + 1]
                self.cargar_y_reproducir_actual()
                return
        elif self.current_index + 1 < len(self.queue):
            self.current_index += 1
            self.cargar_y_reproducir_actual()
            return
            
        # Repetir toda la cola: vuelve al principio (tiene prioridad sobre el autoplay)
        if self.modo_repetir == "all" and self.queue and not self._en_jam():
            if self._queue_mode == "playlist" and self._playlist_shuffle:
                self._crear_orden_aleatorio_playlist()
                self.current_index = self._playlist_shuffle_order[0]
            else:
                self.current_index = 0
            self.cargar_y_reproducir_actual()
            return

        if self._queue_mode == "normal" and self.autoplay_var.get() and 0 <= self.current_index < len(self.queue):
            if not self._esperando_reco:
                self._esperando_reco = True
                self.lcd_title.config(text="✨ Buscando recomendación...")
                self.status_var.set("Fin de la cola: buscando una recomendación...")
            self._asegurar_siguiente()
            return
        self.detener_cancion()
        self.status_var.set("Fin de la cola.")

    def anterior_cancion(self):
        if self._queue_mode == "playlist" and self._playlist_shuffle:
            if not self._playlist_shuffle_order:
                self._crear_orden_aleatorio_playlist(self.current_index if self.current_index >= 0 else None)
            try:
                pos = self._playlist_shuffle_order.index(self.current_index)
            except ValueError:
                pos = 0
            if pos > 0:
                self.current_index = self._playlist_shuffle_order[pos - 1]
                self.cargar_y_reproducir_actual()
        elif self.current_index > 0:
            # como en los reproductores clásicos: si llevas más de 4 s, ⏮ vuelve al principio
            if self.player.get_time() > 4000 and not self._cargando:
                self.player.set_time(0)
                self.social.al_seek()
                return
            self.current_index -= 1
            self.cargar_y_reproducir_actual()
        elif 0 <= self.current_index < len(self.queue) and self.player.get_time() > 0:
            self.player.set_time(0)
            self.social.al_seek()


def app_paths_guest_file():
    from player_data import LEGACY_DATA_FILE
    return LEGACY_DATA_FILE


def crear_ytmusic(auth=None):
    """YouTube Music en español y con resultados de España (si la versión lo permite)."""
    for kwargs in ({"language": "es", "location": "ES"}, {"language": "es"}, {}):
        try:
            return YTMusic(auth, **kwargs) if auth else YTMusic(**kwargs)
        except Exception:
            continue
    return YTMusic()


def _quiere_animacion():
    try:
        from player_extras import PREFS_FILE
        with open(PREFS_FILE, encoding="utf-8") as f:
            return bool(json.load(f).get("splash", True))
    except Exception:
        return True


def arrancar():
    en_bandeja = "--bandeja" in sys.argv          # arranque con Windows: directo a la bandeja
    root = tk.Tk()
    root.withdraw()                         # la ventana principal sale al acabar la animación
    configurar_icono_ventana(root)
    estado = {}
    errores = []

    def informar_error(tipo, valor, tb):
        """Errores dentro de la interfaz: al log (antes se perdían sin rastro en el .exe)."""
        import traceback
        texto = "".join(traceback.format_exception(tipo, valor, tb))
        print(f"[error en la interfaz]\n{texto}")
        errores.append(texto)
    root.report_callback_exception = informar_error

    salida_prueba = os.environ.get("EXOTIC_SMOKE")
    if salida_prueba:                       # prueba automática de arranque (GitHub Actions)
        def informe():
            import splash as _splash
            app = estado.get("app")
            datos = {"app": app is not None, "ventana_visible": bool(root.winfo_viewable()),
                     "titulo": root.title(), "errores": errores, "splash": _splash.EVENTOS}
            with open(salida_prueba, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=1)
            if app is not None:
                app.al_cerrar()
            else:
                root.destroy()
        root.after(int(os.environ.get("EXOTIC_SMOKE_MS", "9000")), informe)

    def cargar():
        estado["app"] = WinXP_ExoticPlayer(root, sonido_inicio=False)

    def mostrar():
        app = estado.get("app")
        if en_bandeja and app is not None:
            if app.tray.disponible:
                app.root.withdraw()
                return
            root.iconify()
            return
        root.deiconify()
        root.lift()
        try:
            root.focus_force()
        except tk.TclError:
            pass

    def sonido():
        app = estado.get("app")
        if app is not None and app.prefs.get("sounds", True):
            app.sonar("inicio")

    if _quiere_animacion() and not en_bandeja:
        from splash import SplashXP
        SplashXP(root, ICON_PATH, APP_VERSION).iniciar(cargar, mostrar, sonido)
    else:
        cargar()
        sonido()
        mostrar()
    root.mainloop()
    return estado.get("app")


if __name__ == "__main__":
    arrancar()