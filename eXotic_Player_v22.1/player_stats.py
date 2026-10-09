"""Estadísticas derivadas del historial y favoritos."""
from collections import Counter
from datetime import datetime, timedelta, timezone


def resumir_estadisticas(history, liked):
    history = history if isinstance(history, list) else []
    liked = liked if isinstance(liked, list) else []
    total_reproducciones = sum(int(x.get("playCount", 0) or 0) for x in history)
    artistas = Counter()
    for item in history:
        artista = str(item.get("artist", "")).strip() or "Desconocido"
        artistas[artista] += int(item.get("playCount", 0) or 0)
    top_song = max(history, key=lambda x: int(x.get("playCount", 0) or 0), default=None)
    top_artist = artistas.most_common(1)[0] if artistas else None
    ahora = datetime.now(timezone.utc)
    recientes_7 = 0
    recientes_30 = 0
    for item in history:
        try:
            fecha = datetime.fromisoformat(str(item.get("lastPlayed", "")).replace("Z", "+00:00"))
            if fecha.tzinfo is None:
                fecha = fecha.replace(tzinfo=timezone.utc)
            edad = ahora - fecha
            recientes_7 += edad <= timedelta(days=7)
            recientes_30 += edad <= timedelta(days=30)
        except Exception:
            continue
    return {
        "unique_songs": len(history),
        "total_plays": total_reproducciones,
        "liked": len(liked),
        "top_song": top_song,
        "top_artist": top_artist,
        "recent_7": recientes_7,
        "recent_30": recientes_30,
    }


class PlayerStatsMixin:
    def actualizar_estadisticas_ui(self):
        labels = getattr(self, "stats_labels", None)
        if not labels:
            return
        stats = resumir_estadisticas(self.cloud_data.get("history", []), self.cloud_data.get("liked", []))
        labels["unique"].config(text=str(stats["unique_songs"]))
        labels["plays"].config(text=str(stats["total_plays"]))
        labels["liked"].config(text=str(stats["liked"]))
        labels["week"].config(text=str(stats["recent_7"]))
        labels["month"].config(text=str(stats["recent_30"]))
        top_song = stats["top_song"]
        labels["top_song"].config(text=(f"{top_song.get('title','Desconocido')} — {top_song.get('artist','')} ({int(top_song.get('playCount',0) or 0)}×)" if top_song else "—"))
        top_artist = stats["top_artist"]
        labels["top_artist"].config(text=(f"{top_artist[0]} ({top_artist[1]}×)" if top_artist else "—"))
