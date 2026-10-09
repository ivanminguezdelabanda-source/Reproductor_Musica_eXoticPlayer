"""Rutas y preparación del entorno, tanto en desarrollo como empaquetado (PyInstaller).

- INSTALL_DIR : carpeta del programa (solo lectura cuando está instalado).
- RESOURCE_DIR: recursos empaquetados (supabase_config.json, etc.).
- DATA_DIR    : datos del usuario (sesión, playlists, log). Empaquetado -> %APPDATA%\\eXoticPlayer
"""
import os
import sys

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    INSTALL_DIR = os.path.dirname(sys.executable)
    RESOURCE_DIR = getattr(sys, "_MEIPASS", INSTALL_DIR)
else:
    INSTALL_DIR = RESOURCE_DIR = os.path.dirname(os.path.abspath(__file__))


def _data_dir():
    if not FROZEN:
        return INSTALL_DIR  # desarrollo: igual que antes
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "eXoticPlayer")
    os.makedirs(d, exist_ok=True)
    return d


DATA_DIR = _data_dir()


def _redirigir_salida():
    """Sin consola (--windowed) sys.stdout es None: se manda todo a un log."""
    if not FROZEN or (sys.stdout is not None and sys.stderr is not None):
        return
    try:
        log = open(os.path.join(DATA_DIR, "exotic_player.log"), "w",
                   encoding="utf-8", buffering=1)
    except OSError:
        log = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log


def _preparar_path():
    """Añade tools\\ (deno.exe, para yt-dlp) al PATH si viene incluido."""
    tools = os.path.join(INSTALL_DIR, "tools")
    if os.path.isdir(tools):
        os.environ["PATH"] = tools + os.pathsep + os.environ.get("PATH", "")


def _preparar_vlc():
    """Usa el VLC incluido en la carpeta vlc\\ (libvlc.dll + plugins) si existe."""
    for d in (os.path.join(INSTALL_DIR, "vlc"), os.path.join(RESOURCE_DIR, "vlc")):
        dll = os.path.join(d, "libvlc.dll")
        if os.path.exists(dll):
            os.environ["PYTHON_VLC_LIB_PATH"] = dll
            os.environ["VLC_PLUGIN_PATH"] = os.path.join(d, "plugins")
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(d)
                except OSError:
                    pass
            return


def preparar_entorno():
    """Llamar ANTES de 'import vlc'."""
    _redirigir_salida()
    _preparar_path()
    _preparar_vlc()
