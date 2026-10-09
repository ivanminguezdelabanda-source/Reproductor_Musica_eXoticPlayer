from datetime import datetime, timedelta, timezone

from player_stats import resumir_estadisticas


def _hace(dias):
    return (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat(timespec="seconds")


def test_resumen_estadisticas_basico():
    # Fechas relativas a hoy: antes eran fijas y el test fallaba con el paso de los días
    history = [
        {"videoId": "1", "title": "A", "artist": "X", "playCount": 3, "lastPlayed": _hace(1)},
        {"videoId": "2", "title": "B", "artist": "X", "playCount": 1, "lastPlayed": _hace(12)},
        {"videoId": "3", "title": "C", "artist": "Y", "playCount": 2, "lastPlayed": _hace(2)},
    ]
    stats = resumir_estadisticas(history, [{"videoId": "1"}, {"videoId": "4"}])
    assert stats["unique_songs"] == 3
    assert stats["total_plays"] == 6
    assert stats["liked"] == 2
    assert stats["top_song"]["title"] == "A"
    assert stats["top_artist"] == ("X", 4)
    assert stats["recent_7"] == 2
    assert stats["recent_30"] == 3


def test_resumen_vacio():
    stats = resumir_estadisticas([], [])
    assert stats["unique_songs"] == 0
    assert stats["total_plays"] == 0
    assert stats["top_song"] is None
    assert stats["top_artist"] is None
