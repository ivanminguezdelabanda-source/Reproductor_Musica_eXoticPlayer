"""Operaciones puras de filtrado y reordenación de playlists."""
import re
from urllib.parse import parse_qs, urlparse


def filtrar_indices(tracks, query):
    """Devuelve índices reales de las pistas que coinciden con ``query``."""
    query = (query or "").strip().casefold()
    if not query:
        return list(range(len(tracks)))
    return [
        i for i, track in enumerate(tracks)
        if query in str(track.get("title", "")).casefold()
        or query in str(track.get("artist", "")).casefold()
    ]


def mover_indice(tracks, source_index, target_index):
    """Mueve una pista a ``target_index`` y devuelve el índice final."""
    if not (0 <= source_index < len(tracks)):
        return None
    if not (0 <= target_index < len(tracks)) or source_index == target_index:
        return source_index
    item = tracks.pop(source_index)
    tracks.insert(target_index, item)
    return target_index


_ID_PLAYLIST = re.compile(r"^(?:VL)?((?:PL|OLAK5uy_|RD|UU|LL|FL|LM|OL)[\w-]{2,})$")


def extraer_id_playlist(texto):
    """Saca el ID de una playlist de YouTube / YouTube Music a partir de un enlace o del ID.

    Acepta 'https://music.youtube.com/playlist?list=PL...', enlaces de vídeo con
    '&list=...' o el ID suelto. Devuelve None si no encuentra ninguno.
    """
    texto = (texto or "").strip()
    if not texto:
        return None
    if "list=" in texto:
        consulta = urlparse(texto if "://" in texto else "https://x/?" + texto.split("?", 1)[-1]).query
        valor = (parse_qs(consulta).get("list") or [""])[0].strip()
        return valor or None
    m = _ID_PLAYLIST.match(texto)
    return m.group(1) if m else None


def nombre_unico(nombre, existentes):
    """'Mix' -> 'Mix (2)' si ya existe una playlist con ese nombre (sin distinguir mayúsculas)."""
    nombre = (nombre or "Playlist importada").strip() or "Playlist importada"
    usados = {str(n).casefold() for n in existentes}
    if nombre.casefold() not in usados:
        return nombre
    i = 2
    while f"{nombre} ({i})".casefold() in usados:
        i += 1
    return f"{nombre} ({i})"


def mezclar_desde(tracks, indice_actual, rng=None):
    """Mezcla las pistas que van DESPUÉS de la actual (la actual y las anteriores no se tocan)."""
    import random
    rng = rng or random
    inicio = max(0, indice_actual + 1)
    resto = tracks[inicio:]
    rng.shuffle(resto)
    tracks[inicio:] = resto
    return len(resto)
