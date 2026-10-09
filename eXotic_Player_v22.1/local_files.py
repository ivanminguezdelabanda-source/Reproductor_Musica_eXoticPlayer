"""Archivos de música del ordenador (MP3, FLAC, WAV, M4A, OGG...).

Una canción local se guarda igual que una de YouTube Music, pero su ``videoId`` es
``"file:" + ruta absoluta``. Así funcionan sin cambios la cola, las playlists, el
historial, ♥ y las estadísticas. Los metadatos (título, artista, carátula, duración)
los lee el propio VLC, sin dependencias nuevas.
"""
import os
import urllib.parse
import urllib.request

EXTENSIONES = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wma",
               ".aiff", ".aif", ".alac", ".ape", ".mka", ".webm", ".mp4"}
PREFIJO = "file:"
MAX_CARPETA = 3000


def es_local(video_id):
    return str(video_id or "").startswith(PREFIJO)


def id_local(ruta):
    return PREFIJO + os.path.abspath(ruta)


def ruta_de(video_id):
    return str(video_id)[len(PREFIJO):] if es_local(video_id) else None


def es_audio(ruta):
    return os.path.splitext(ruta)[1].lower() in EXTENSIONES


def buscar_audio(carpeta, limite=MAX_CARPETA):
    """Rutas de audio dentro de ``carpeta`` (con subcarpetas), ordenadas como en el explorador."""
    encontrados = []
    for raiz, dirs, archivos in os.walk(carpeta):
        dirs.sort(key=str.casefold)
        for nombre in sorted(archivos, key=str.casefold):
            if es_audio(nombre):
                encontrados.append(os.path.join(raiz, nombre))
                if len(encontrados) >= limite:
                    return encontrados
    return encontrados


def titulo_desde_nombre(ruta):
    """'03 - Daft Punk - One More Time.mp3' -> ('One More Time', 'Daft Punk')."""
    base = os.path.splitext(os.path.basename(ruta))[0].replace("_", " ").strip()
    partes = [p.strip() for p in base.split(" - ") if p.strip()]
    if partes and partes[0].isdigit():
        partes = partes[1:]
    if len(partes) >= 2:
        return " - ".join(partes[1:]), partes[0]
    return (partes[0] if partes else base), ""


def _url_a_ruta(url):
    if not url:
        return None
    if url.startswith("file:"):
        try:
            return urllib.request.url2pathname(urllib.parse.urlparse(url).path)
        except Exception:
            return None
    return None


def leer_metadatos(instancia_vlc, ruta):
    """Devuelve un dict de canción para ``ruta`` (llamar en un hilo: VLC lee el archivo)."""
    titulo, artista = titulo_desde_nombre(ruta)
    cancion = {"title": titulo, "artist": artista, "videoId": id_local(ruta),
               "coverUrl": None, "highCoverUrl": None, "duration": 0, "local": True}
    try:
        import vlc
        media = instancia_vlc.media_new_path(ruta)
        try:
            media.parse()                       # síncrono; en un hilo no molesta
        except Exception:
            pass
        t = media.get_meta(vlc.Meta.Title)
        a = media.get_meta(vlc.Meta.Artist)
        arte = media.get_meta(vlc.Meta.ArtworkURL)
        dur = media.get_duration()
        if t and t.strip() and t.strip() != os.path.basename(ruta):
            cancion["title"] = t.strip()
        if a and a.strip():
            cancion["artist"] = a.strip()
        if dur and dur > 0:
            cancion["duration"] = int(dur / 1000)
        if arte and _url_a_ruta(arte) and os.path.exists(_url_a_ruta(arte)):
            cancion["coverUrl"] = cancion["highCoverUrl"] = arte
        media.release()
    except Exception as e:
        print(f"[local] metadatos de {ruta}: {e}")
    if not cancion["coverUrl"]:
        # carátula suelta en la carpeta (cover.jpg, folder.jpg...)
        carpeta = os.path.dirname(ruta)
        for nombre in ("cover.jpg", "cover.png", "folder.jpg", "folder.png", "front.jpg", "album.jpg"):
            p = os.path.join(carpeta, nombre)
            if os.path.exists(p):
                cancion["coverUrl"] = cancion["highCoverUrl"] = "file:" + urllib.request.pathname2url(p)
                break
    return cancion
