"""Duraciones de canciones: un único sitio para leerlas y formatearlas.

(Antes había cinco copias casi iguales repartidas por el reproductor, la cola y las playlists.)
YouTube Music y las versiones antiguas de la app guardan la duración de muchas formas:
"3:45", "1:02:03", 225, "225", 225000 (milisegundos)...
"""

CLAVES_MS = ("duration_ms", "durationMs")


def a_segundos(valor, clave=None):
    """Convierte cualquier formato de duración a segundos enteros (0 si no se entiende).

    ``clave``: nombre del campo del que viene; los campos *_ms siempre son milisegundos.
    El resto se considera milisegundos solo si el número es enorme (>100000)."""
    if valor is None or valor == "" or isinstance(valor, bool):
        return 0
    if isinstance(valor, str):
        texto = valor.strip()
        if ":" in texto:
            try:
                partes = [int(x.strip()) for x in texto.split(":")]
            except ValueError:
                return 0
            if len(partes) == 2:
                return max(0, partes[0] * 60 + partes[1])
            if len(partes) == 3:
                return max(0, partes[0] * 3600 + partes[1] * 60 + partes[2])
            return 0
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return 0
    if clave in CLAVES_MS or numero > 100000:
        numero /= 1000.0
    return max(0, int(numero))


def de_pista(item):
    """Duración en segundos de un dict de canción, mirando todos los campos conocidos."""
    if not isinstance(item, dict):
        return 0
    for clave in ("duration", "duration_seconds", "lengthSeconds", "length_seconds") + CLAVES_MS:
        if clave in item:
            s = a_segundos(item.get(clave), clave)
            if s > 0:
                return s
    return 0


def formatear_pista(segundos):
    """3:45 · 1:02:03 · '' si no hay duración."""
    segundos = max(0, int(segundos or 0))
    if not segundos:
        return ""
    minutos, secs = divmod(segundos, 60)
    horas, minutos = divmod(minutos, 60)
    if horas:
        return f"{horas}:{minutos:02d}:{secs:02d}"
    return f"{minutos}:{secs:02d}"


def formatear_total(segundos):
    """'1 h 05 min' · '12 min 03 s' · '40 s'."""
    segundos = max(0, int(segundos or 0))
    horas, resto = divmod(segundos, 3600)
    minutos, secs = divmod(resto, 60)
    if horas:
        return f"{horas} h {minutos:02d} min"
    if minutos:
        return f"{minutos} min {secs:02d} s"
    return f"{secs} s"
