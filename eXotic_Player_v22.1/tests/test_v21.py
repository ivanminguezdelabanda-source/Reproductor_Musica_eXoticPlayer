"""Tests de la v21: duraciones, Wrapped, Last.fm, archivos locales y paleta del Soundscope."""
import hashlib
import os
from datetime import datetime

import pytest
from PIL import Image

import duraciones
import lastfm
import local_files
import wrapped


# --- duraciones (antes había 5 copias) -------------------------------------------
@pytest.mark.parametrize("valor,clave,esperado", [
    ("3:45", None, 225), ("1:02:03", None, 3723), (225, None, 225), ("225", None, 225),
    (225000, None, 225), (225000, "duration_ms", 225), (5000, "durationMs", 5), (5000, None, 5000),
    ("", None, 0), (None, None, 0), ("hola", None, 0), ("1:2:3:4", None, 0), (True, None, 0),
])
def test_a_segundos(valor, clave, esperado):
    assert duraciones.a_segundos(valor, clave) == esperado


def test_de_pista_y_formatos():
    assert duraciones.de_pista({"duration": "", "duration_seconds": 200}) == 200
    assert duraciones.de_pista({"duration_ms": 61000}) == 61
    assert duraciones.de_pista(None) == 0
    assert duraciones.formatear_pista(0) == ""
    assert duraciones.formatear_pista(65) == "1:05"
    assert duraciones.formatear_pista(3723) == "1:02:03"
    assert duraciones.formatear_total(40) == "40 s"
    assert duraciones.formatear_total(723) == "12 min 03 s"
    assert duraciones.formatear_total(3900) == "1 h 05 min"


# --- Wrapped ------------------------------------------------------------------------
def test_wrapped_cuenta_y_resume():
    datos = {}
    f = datetime(2026, 10, 8, 21, 0)
    a = {"videoId": "a", "title": "Uno", "artist": "Daft Punk, Pharrell", "coverUrl": "http://x/a.jpg"}
    b = {"videoId": "b", "title": "Dos", "artist": "M83"}
    for _ in range(3):
        wrapped.contar_reproduccion(datos, a, f)
    wrapped.contar_reproduccion(datos, b, f)
    wrapped.sumar_tiempo(datos, 600, f)
    wrapped.sumar_tiempo(datos, 120, datetime(2026, 10, 9))
    r = wrapped.resumen(datos, "2026-10")
    assert r["reproducciones"] == 4 and r["canciones"] == 2 and r["minutos"] == 12
    assert r["top_canciones"][0][:3] == ("Uno", "Daft Punk, Pharrell", 3)
    assert r["top_artistas"][0] == ("Daft Punk", 3)
    assert r["mejor_dia"] == ("8 de octubre", 10)
    assert wrapped.resumen(datos, "2026")["reproducciones"] == 4
    assert wrapped.resumen(datos, "2025-01")["reproducciones"] == 0


def test_wrapped_poda_meses_y_canciones():
    datos = {}
    for m in range(1, 13):
        for año in (2024, 2025, 2026):
            wrapped.contar_reproduccion(datos, {"videoId": "x", "title": "x"}, datetime(año, m, 1))
    assert len(datos["monthly"]) <= wrapped.MAX_MESES
    mes = datetime(2026, 5, 1)
    for i in range(wrapped.MAX_CANCIONES_MES + 50):
        wrapped.contar_reproduccion(datos, {"videoId": f"v{i}", "title": "t"}, mes)
    assert len(datos["monthly"]["2026-05"]["songs"]) <= wrapped.MAX_CANCIONES_MES


def test_wrapped_usa_historial_si_no_hay_datos():
    hist = [{"videoId": "a", "title": "Uno", "artist": "X", "playCount": 5, "lastPlayed": "2026-10-02T10:00:00+00:00"},
            {"videoId": "b", "title": "Dos", "artist": "Y", "playCount": 2, "lastPlayed": "2026-09-02T10:00:00+00:00"}]
    r = wrapped.resumen({}, "2026-10", hist)
    assert r["aproximado"] and r["reproducciones"] == 5 and r["canciones"] == 1


def test_wrapped_imagen():
    datos = {}
    wrapped.contar_reproduccion(datos, {"videoId": "a", "title": "Una canción con un título larguísimo de verdad",
                                        "artist": "Artista"}, datetime(2026, 10, 1))
    img = wrapped.generar_imagen(wrapped.resumen(datos, "2026-10"), Image.new("RGB", (50, 50), "red"), "Minguez#0001")
    assert img.size == (1080, 1920)


# --- Last.fm --------------------------------------------------------------------------
def test_firma_lastfm():
    p = {"method": "track.scrobble", "api_key": "k", "sk": "s", "artist[0]": "A", "format": "json"}
    esperado = hashlib.md5(("api_keykartist[0]Amethodtrack.scrobblesks" + "SECRET").encode()).hexdigest()
    assert lastfm.firma(p, "SECRET") == esperado


def test_limpiar_titulo():
    assert lastfm.limpiar("One More Time (Official Video)", "Daft Punk, X") == ("One More Time", "Daft Punk")
    assert lastfm.limpiar("Canción [Lyric Video]", "A") == ("Canción", "A")
    assert lastfm.limpiar("Live Forever (Remastered 2014)", "Oasis")[0] == "Live Forever"


def test_reglas_scrobble():
    assert not lastfm.debe_scrobblear(100, 30)
    assert lastfm.debe_scrobblear(100, 200)
    assert not lastfm.debe_scrobblear(99, 200)
    assert lastfm.debe_scrobblear(240, 900)
    assert not lastfm.debe_scrobblear(239, 0)


class _ClienteFalso:
    listo = True

    def __init__(self, falla=False):
        self.enviados, self.ahora, self.falla = [], [], falla

    def ahora_suena(self, *a):
        self.ahora.append(a)

    def scrobble(self, lote):
        if self.falla:
            raise OSError("sin red")
        self.enviados.extend(lote)


def test_scrobbler_registra_una_vez():
    c = _ClienteFalso()
    s = lastfm.Scrobbler(c)
    s.empezar({"title": "Tema (Official Audio)", "artist": "Grupo"}, 200)
    assert c.ahora == [("Grupo", "Tema", 200)]
    assert not s.escuchado(60)
    assert s.escuchado(45)
    assert not s.escuchado(500)
    assert len(c.enviados) == 1 and c.enviados[0]["track"] == "Tema" and not s.pendientes


def test_scrobbler_guarda_pendientes_sin_red():
    c = _ClienteFalso(falla=True)
    s = lastfm.Scrobbler(c)
    s.empezar({"title": "T", "artist": "A"}, 100)
    s.escuchado(60)
    assert len(s.pendientes) == 1
    c.falla = False
    s.vaciar()
    assert not s.pendientes and len(c.enviados) == 1


# --- archivos locales -------------------------------------------------------------------------
def test_titulo_desde_nombre():
    assert local_files.titulo_desde_nombre("/m/03 - Daft Punk - One More Time.mp3") == ("One More Time", "Daft Punk")
    assert local_files.titulo_desde_nombre("/m/cancion_suelta.flac") == ("cancion suelta", "")
    assert local_files.es_local("file:/x.mp3") and not local_files.es_local("dQw4w9WgXcQ")
    assert local_files.ruta_de(local_files.id_local("/tmp/a.mp3")) == os.path.abspath("/tmp/a.mp3")


def test_buscar_audio(tmp_path):
    (tmp_path / "b").mkdir()
    for n in ("a.mp3", "b/c.FLAC", "nota.txt", "b/d.wav"):
        (tmp_path / n).write_bytes(b"x")
    res = [os.path.relpath(p, tmp_path).replace(os.sep, "/") for p in local_files.buscar_audio(str(tmp_path))]
    assert res == ["a.mp3", "b/c.FLAC", "b/d.wav"]
    assert len(local_files.buscar_audio(str(tmp_path), limite=1)) == 1


# --- Soundscope ---------------------------------------------------------------------------------
def test_paleta_desde_portada():
    np = pytest.importorskip("numpy")
    import soundscope_ps1 as ss
    img = Image.new("RGB", (64, 64), (200, 40, 40))
    img.paste((40, 40, 200), (32, 0, 64, 64))
    pal = ss.paleta_desde_imagen(img)
    assert pal.shape == (256, 3) and float(pal.min()) >= 0 and float(pal.max()) <= 1
    gris = ss.paleta_desde_imagen(Image.new("RGB", (8, 8), (128, 128, 128)))
    assert gris.shape == (256, 3)
    assert ss.textura_desde_imagen(img).shape == (ss.TEX, ss.TEX, 3)
    assert np.isfinite(pal).all()


def test_renderer_todas_las_escenas():
    pytest.importorskip("numpy")
    import soundscope_ps1 as ss
    au = ss.AudioAnalyzer()
    r = ss.Renderer(160, 90)
    r.auto = False
    info = {"estado": "play", "pos_ms": 5000, "len_ms": 60000, "titulo": "T", "artista": "A",
            "pista": 2, "total": 5, "letra": {"lineas": [(0, "hola"), (3000, "adiós")], "texto": ""}}
    for i in range(len(ss.ESCENAS)):
        r.ir_a(i)
        for _ in range(3):
            au.actualizar(True, 0.033)
            img = r.frame(0.033, au, info)
        assert img.size == (160, 90)
