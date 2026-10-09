from player_history import HISTORY_LIMIT, PlayerHistoryMixin


class FakeHistory(PlayerHistoryMixin):
    def __init__(self):
        self.cloud_data = {"version": 2, "history": []}
        self.saved = 0

    def _guardar_si_corresponde(self):
        self.saved += 1


def test_historial_actualiza_la_misma_cancion_y_sube_contador():
    app = FakeHistory()
    track = {"title": "Song", "artist": "Artist", "videoId": "abc", "coverUrl": "cover"}
    app._registrar_reproduccion(track)
    app._registrar_reproduccion(track)

    assert len(app.cloud_data["history"]) == 1
    assert app.cloud_data["history"][0]["videoId"] == "abc"
    assert app.cloud_data["history"][0]["playCount"] == 2
    assert app.cloud_data["history"][0]["lastPlayed"]
    assert app.saved == 2


def test_historial_mantiene_primero_lo_mas_reciente_y_limita_tamano():
    app = FakeHistory()
    for i in range(HISTORY_LIMIT + 5):
        app._registrar_reproduccion({"title": str(i), "artist": "A", "videoId": str(i)})

    assert len(app.cloud_data["history"]) == HISTORY_LIMIT
    assert app.cloud_data["history"][0]["videoId"] == str(HISTORY_LIMIT + 4)
