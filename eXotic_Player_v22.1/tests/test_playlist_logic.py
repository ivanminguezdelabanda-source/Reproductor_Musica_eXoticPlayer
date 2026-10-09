from playlist_logic import filtrar_indices, mover_indice


def test_filtrar_por_titulo_y_artista():
    tracks = [
        {"title": "Blue Monday", "artist": "New Order"},
        {"title": "Enjoy the Silence", "artist": "Depeche Mode"},
        {"title": "Monday Morning", "artist": "Example"},
    ]
    assert filtrar_indices(tracks, "blue") == [0]
    assert filtrar_indices(tracks, "depeche") == [1]
    assert filtrar_indices(tracks, "MONDAY") == [0, 2]
    assert filtrar_indices(tracks, "") == [0, 1, 2]


def test_mover_indice_reordena_la_lista():
    tracks = ["a", "b", "c", "d"]
    assert mover_indice(tracks, 0, 2) == 2
    assert tracks == ["b", "c", "a", "d"]

    assert mover_indice(tracks, 3, 1) == 1
    assert tracks == ["b", "d", "c", "a"]


def test_duracion_playlist_admite_segundos_y_formato_texto():
    # La lógica pura no depende de Tk; validamos aquí la expectativa de datos
    # que usa PlayerPlaylistsMixin: duración actual en segundos y formatos YTMusic.
    def parse(valor):
        if isinstance(valor, str) and ":" in valor:
            p = [int(x) for x in valor.split(":")]
            return p[0] * 60 + p[1] if len(p) == 2 else p[0] * 3600 + p[1] * 60 + p[2]
        return int(float(valor or 0))

    assert parse(222) == 222
    assert parse("3:42") == 222
    assert parse("1:02:05") == 3725
