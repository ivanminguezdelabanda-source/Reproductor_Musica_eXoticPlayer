# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules, collect_all

# Se puede cambiar con la variable de entorno VLC_DIR si VLC no esta en la ruta por defecto
VLC = os.environ.get('VLC_DIR', r'C:\Program Files\VideoLAN\VLC')

# Falla pronto y con un mensaje claro si falta algo (en vez de un error criptico a mitad del build)
for _f in ('exotic_player.ico', 'supabase_config.json', os.path.join(VLC, 'libvlc.dll'),
           os.path.join(VLC, 'libvlccore.dll'), os.path.join(VLC, 'plugins')):
    if not os.path.exists(_f):
        raise SystemExit(f'Falta {_f}')

# app_paths.py busca VLC en <recursos>\vlc\libvlc.dll (+ vlc\plugins), por eso van en la subcarpeta "vlc"
datas = [
    ('exotic_player.ico', '.'),
    ('supabase_config.json', '.'),          # sin esto: "Supabase no disponible"
    (os.path.join(VLC, 'plugins'), 'vlc/plugins'),
]
binaries = [
    (os.path.join(VLC, 'libvlc.dll'), 'vlc'),
    (os.path.join(VLC, 'libvlccore.dll'), 'vlc'),
]
# pynput elige su backend (win32) de forma dinámica y pypresence solo se importa dentro de try/except:
# sin esto el .exe arrancaría sin teclas multimedia ni Discord y sin avisar.
hiddenimports = (collect_submodules('pynput') + collect_submodules('pypresence')
                 + collect_submodules('pystray'))   # pystray tambien elige su backend (win32) al importar
for pkg in ('postgrest', 'gotrue', 'supabase_auth', 'realtime', 'storage3', 'supafunc'):
    hiddenimports += collect_submodules(pkg)
for pkg in ('ytmusicapi', 'yt_dlp', 'supabase', 'pyaudiowpatch'):   # pyaudiowpatch = captura del audio para el Soundscope
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h


a = Analysis(
    ['exotic_player.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='eXoticPlayer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX puede corromper las DLL de VLC/Python y dispara antivirus
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['exotic_player.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='eXoticPlayer',
)
