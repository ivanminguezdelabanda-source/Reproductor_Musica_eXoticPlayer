"""Tests de la v22 (sin red ni Tk)."""
import audio_fx
import explore
import hotkeys
import jam_logic
import social_extra
import updates
import ytm_account
from playlist_logic import nombre_unico


# --- Explorar y buscador ---------------------------------------------------------
def test_historial_de_busqueda():
    h = explore.anotar_busqueda([], "Daft Punk")
    h = explore.anotar_busqueda(h, "m83")
    h = explore.anotar_busqueda(h, "daft   punk")          # repetida (sin distinguir mayúsculas)
    assert h == ["daft punk", "m83"]
    assert explore.anotar_busqueda(h, "x") == h             # demasiado corta
    largo = []
    for i in range(40):
        largo = explore.anotar_busqueda(largo, f"busqueda {i}")
    assert len(largo) == explore.MAX_HISTORIAL and largo[0] == "busqueda 39"


def test_textos_sugerencias():
    assert explore.textos_sugerencias(["a b", "a b", " c "]) == ["a b", "c"]
    assert explore.textos_sugerencias([{"text": "hola"}, {"runs": [{"text": "ho"}, {"text": "la 2"}]}]) == ["hola", "hola 2"]
    assert explore.textos_sugerencias(None) == []


def test_tarjetas_desde_mezcla():
    items = [
        {"title": "Chill", "params": "abc"},
        {"title": "Lista", "playlistId": "PL1", "thumbnails": [{"url": "u1"}, {"url": "u2"}]},
        {"title": "Disco", "browseId": "MPREb_1", "artists": [{"name": "Grupo"}]},
        {"title": "Tema", "videoId": "v1"},
        {"title": "Álbum con lista", "audioPlaylistId": "OLAK1", "browseId": "MPREb_2"},
        {"title": "", "playlistId": "x"}, "basura",
    ]
    t = explore.tarjetas_desde(items)
    assert [x["tipo"] for x in t] == ["categoria", "playlist", "album", "cancion", "playlist"]
    assert t[1]["img"] == "u2" and t[2]["sub"] == "Grupo" and t[4]["id"] == "OLAK1"


def test_secciones():
    exp = {"new_releases": [{"title": "A", "browseId": "MPREb_x"}],
           "trending": {"items": [{"title": "T", "videoId": "v"}]},
           "moods_and_genres": [{"title": "Relax", "params": "p"}]}
    nombres = [n for n, _ in explore.secciones_explorar(exp)]
    assert nombres == ["✨ Novedades", "🔥 Tendencias", "🎭 Estados de ánimo y géneros"]
    assert explore.secciones_moods({"Genres": [{"title": "Rock", "params": "r"}], "Vacío": []})[0][0] == "Géneros"
    assert explore.secciones_charts({"videos": [{"title": "Top", "playlistId": "PL"}]})[0][0] == "🎬 Vídeos"
    assert explore.secciones_home([{"title": "Mix", "contents": [{"title": "x", "playlistId": "RD1"}]}])[0][0] == "Mix"
    assert explore.secciones_explorar(None) == []


# --- Efectos de audio -----------------------------------------------------------------
def test_loudness_y_ganancia():
    r = {"streamingData": {"adaptiveFormats": [
        {"mimeType": "video/mp4", "loudnessDb": 99},
        {"mimeType": 'audio/mp4; codecs="mp4a"', "loudnessDb": 4.0},
        {"mimeType": "audio/webm", "loudnessDb": 6.0}]}}
    assert audio_fx.extraer_loudness(r) == 5.0
    assert audio_fx.extraer_loudness({"playerConfig": {"audioConfig": {"loudnessDb": -2.5}}}) == -2.5
    assert audio_fx.extraer_loudness({}) is None and audio_fx.extraer_loudness(None) is None
    assert audio_fx.ganancia(5.0) == -5.0
    assert audio_fx.ganancia(-10) == audio_fx.MAX_SUBIR_DB
    assert audio_fx.ganancia(30) == -audio_fx.MAX_BAJAR_DB
    assert audio_fx.ganancia(None) == 0.0


def test_modos_de_velocidad():
    assert audio_fx.VELOCIDAD["normal"] == 1.0
    assert audio_fx.VELOCIDAD["nightcore"] > 1 > audio_fx.VELOCIDAD["slowed"]


# --- Atajos globales ---------------------------------------------------------------------
def test_atajos():
    assert hotkeys.combo_valido("<ctrl>+<alt>+<right>")
    assert hotkeys.combo_valido("<ctrl>+<shift>+p")
    assert not hotkeys.combo_valido("p")
    assert not hotkeys.combo_valido("<ctrl>+<ctrl>+p")
    assert not hotkeys.combo_valido("<ctrl>+<raro>")
    n = hotkeys.normalizar({"like": "<ctrl>+<raro>", "siguiente": "<ctrl>+<shift>+n", "mostrar": "", "x": "y"})
    assert n["like"] == hotkeys.POR_DEFECTO["like"] and n["siguiente"] == "<ctrl>+<shift>+n"
    assert n["mostrar"] == "" and "x" not in n


# --- Actualizaciones ---------------------------------------------------------------------
def test_versiones():
    assert updates.numero_version("v21.3") == (21, 3)
    assert updates.es_mas_nueva("v22", "21.3")
    assert updates.es_mas_nueva("v21.10", "21.9")
    assert not updates.es_mas_nueva("v21.3", "21.3")
    assert not updates.es_mas_nueva("v21", "21.0")
    assert not updates.es_mas_nueva("beta", "21")
    assert updates.repo_valido("https://github.com/minguez/eXoticPlayer/") == "minguez/eXoticPlayer"
    assert updates.repo_valido("minguez/eXoticPlayer") == "minguez/eXoticPlayer"
    assert updates.repo_valido("no vale") is None


# --- YouTube Music -------------------------------------------------------------------------
def test_fusionar_me_gusta():
    loc = [{"videoId": "a"}, {"videoId": "b"}]
    res, n = ytm_account.fusionar_me_gusta(loc, [{"videoId": "b"}, {"videoId": "c"}, {"title": "sin id"}])
    assert n == 1 and [x["videoId"] for x in res] == ["a", "b", "c"]


def test_fusionar_playlists():
    pls = [{"id": "default", "name": "Mi música", "tracks": []},
           {"id": "p1", "name": "Rock", "tracks": [{"videoId": "viejo"}], "ytmPlaylistId": "PL1"},
           {"id": "p2", "name": "Gym", "tracks": []}]
    remotas = [{"ytmPlaylistId": "PL1", "name": "Rock", "tracks": [{"videoId": "nuevo"}]},
               {"ytmPlaylistId": "PL2", "name": "Gym", "coverUrl": "c", "tracks": [{"videoId": "g"}]}]
    nuevas, act = ytm_account.fusionar_playlists(pls, remotas, nombre_unico)
    assert (nuevas, act) == (1, 1)
    assert pls[1]["tracks"] == [{"videoId": "nuevo"}]
    assert pls[3]["name"] == "Gym (2)" and pls[3]["ytmPlaylistId"] == "PL2"


# --- Jam: votos y actividad -------------------------------------------------------------------
def test_votos():
    msgs = [{"kind": "vote", "body": "v1", "user_id": "a"}, {"kind": "vote", "body": "v1", "user_id": "a"},
            {"kind": "vote", "body": "v1", "user_id": "b"}, {"kind": "vote", "body": "v2", "user_id": "c"},
            {"kind": "chat", "body": "v1", "user_id": "d"}]
    assert jam_logic.votos_para(msgs, "v1") == {"a", "b"}
    assert [jam_logic.votos_necesarios(n) for n in (0, 1, 2, 3, 4, 5)] == [1, 1, 1, 2, 2, 3]


def test_hace_cuanto():
    from datetime import datetime, timedelta, timezone
    ahora = datetime.now(timezone.utc)
    assert social_extra.hace_cuanto(ahora.isoformat()) == "ahora"
    assert social_extra.hace_cuanto((ahora - timedelta(minutes=7)).isoformat()) == "hace 7 min"
    assert social_extra.hace_cuanto((ahora - timedelta(hours=2)).isoformat()) == "hace 2 h"
    assert social_extra.hace_cuanto("basura") == ""


def test_soundscope_escenas_nuevas():
    import pytest
    pytest.importorskip("numpy")
    import soundscope_ps1 as ss
    assert "TORRES" in ss.ESCENAS and "CUBO" in ss.ESCENAS and ss.ESCENAS[-1] == "KARAOKE"
    au = ss.AudioAnalyzer()
    r = ss.Renderer(160, 90)
    r.auto = False
    for nombre in ("TORRES", "CUBO"):
        r.ir_a(ss.ESCENAS.index(nombre))
        for _ in range(3):
            au.actualizar(True, 0.033)
            assert r.frame(0.033, au, {"estado": "play"}).size == (160, 90)
