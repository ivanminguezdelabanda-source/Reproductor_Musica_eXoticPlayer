"""Lógica pura de sincronización de Jam.

Este módulo no conoce Tk, VLC, Supabase ni la clase del reproductor. Contiene las
reglas deterministas que son fáciles de probar: normalización de objetivos,
revisiones, detección de cambios locales y cadencias del tick/latido.
"""
import time


TICK_MS = 500
POLL_CADA_TICKS = 2
POLL_PENDIENTE_TICKS = 4
LATIDO_TICKS = 40
SOLICITUDES_TICKS = 20
SEEK_PENDIENTE_MAX_S = 30.0


def crear_objetivo(st, age, t):
    """Normaliza el estado remoto y calcula la canción válida y sus IDs."""
    st = st if isinstance(st, dict) else {}
    cola = [dict(x) for x in (st.get("queue") or [])
            if isinstance(x, dict) and x.get("videoId")]
    try:
        idx = int(st.get("index", -1))
    except (TypeError, ValueError):
        idx = -1
    if not (0 <= idx < len(cola)):
        idx = -1
    return {
        "queue": cola,
        "ids": [x["videoId"] for x in cola],
        "index": idx,
        "vid": cola[idx]["videoId"] if idx >= 0 else None,
        "playing": bool(st.get("playing")),
        "pos": float(st.get("position_ms") or 0),
        "age": float(age),
        "t": t,
        "by": st.get("by"),
    }


def destino(objetivo, now=None):
    """Estima la posición actual del estado compartido en milisegundos."""
    if not objetivo["playing"]:
        return objetivo["pos"]
    reloj = time.monotonic() if now is None else now
    return objetivo["pos"] + objetivo["age"] + (reloj - objetivo["t"]) * 1000


def seek_pendiente_activo(seek_pendiente, seek_pendiente_t, now=None,
                          max_s=SEEK_PENDIENTE_MAX_S):
    if not seek_pendiente:
        return False
    reloj = time.monotonic() if now is None else now
    return reloj - seek_pendiente_t < max_s


def hay_cambio(current_index, shared_index, seek_usuario, cargando,
               seek_pendiente, playing_local, shared_playing):
    """Determina si hay una acción local que todavía no refleja la Jam."""
    if current_index != shared_index:
        return True
    if seek_usuario:
        return True
    if cargando or seek_pendiente:
        return False
    return playing_local is not None and playing_local != shared_playing


def clasificar_revision(local_rev, remote_rev, tiene_estado):
    """Clasifica una respuesta del servidor frente a la revisión conocida."""
    if remote_rev < local_rev:
        return "stale"
    if remote_rev > local_rev and tiene_estado:
        return "new"
    return "same"


def tick_acciones(n, rol):
    """Devuelve qué tareas debe ejecutar un tick según el rol actual."""
    if rol == "pending":
        return {
            "poll": n % POLL_PENDIENTE_TICKS == 0,
            "heartbeat": False,
            "requests": False,
        }
    if rol not in ("host", "guest"):
        return {"poll": False, "heartbeat": False, "requests": False}
    return {
        "poll": n % POLL_CADA_TICKS == 0,
        "heartbeat": n % LATIDO_TICKS == 0,
        "requests": rol == "host" and n % SOLICITUDES_TICKS == 0,
    }


def necesita_seek(posicion, objetivo, tolerancia):
    """Indica si el reproductor está suficientemente desviado para corregirlo."""
    return posicion >= 0 and abs(posicion - objetivo) > tolerancia


# ---------------------------------------------------------------------------
# v22: votar para saltar
# ---------------------------------------------------------------------------
def votos_para(mensajes, video_id):
    """Personas distintas que han votado saltar ``video_id``."""
    return {m.get("user_id") for m in mensajes or []
            if m.get("kind") == "vote" and m.get("body") == video_id and m.get("user_id")}


def votos_necesarios(n_miembros):
    """La mitad redondeando hacia arriba (2 personas: 1 voto; 3: 2; 4: 2; 5: 3)."""
    return max(1, -(-max(1, int(n_miembros)) // 2))
