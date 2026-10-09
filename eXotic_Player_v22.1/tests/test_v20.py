"""Tests de las piezas nuevas de la v20 (sin Tk, sin red)."""
import random
import wave

import pytest

from cloud_supabase import sesion_invalida
from integrations import PRESETS_PROPIOS, normalizar_eq
from lyrics import linea_actual, normalizar_letra
from playlist_logic import extraer_id_playlist, mezclar_desde, nombre_unico
from retro_sounds import ruta_sonido, sintetizar
import themes


# --- playlists -------------------------------------------------------------
@pytest.mark.parametrize("texto,esperado", [
    ("https://music.youtube.com/playlist?list=PLabc123XYZ", "PLabc123XYZ"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=OLAK5uy_kq1z&index=2", "OLAK5uy_kq1z"),
    ("music.youtube.com/playlist?list=RDCLAK5uy_x", "RDCLAK5uy_x"),
    ("VLPLxyz12", "PLxyz12"),
    ("PLxyz12", "PLxyz12"),
    ("hola que tal", None),
    ("", None),
    (None, None),
])
def test_extraer_id_playlist(texto, esperado):
    assert extraer_id_playlist(texto) == esperado


def test_nombre_unico():
    assert nombre_unico("Mix", []) == "Mix"
    assert nombre_unico("Mix", ["mix"]) == "Mix (2)"
    assert nombre_unico("Mix", ["Mix", "Mix (2)"]) == "Mix (3)"
    assert nombre_unico("  ", []) == "Playlist importada"


def test_mezclar_desde_no_toca_lo_ya_sonado():
    pistas = list(range(10))
    n = mezclar_desde(pistas, 3, random.Random(1))
    assert n == 6
    assert pistas[:4] == [0, 1, 2, 3]
    assert sorted(pistas[4:]) == [4, 5, 6, 7, 8, 9]


def test_mezclar_desde_sin_cancion_actual():
    pistas = list(range(5))
    assert mezclar_desde(pistas, -1, random.Random(2)) == 5
    assert sorted(pistas) == list(range(5))


# --- ecualizador ---------------------------------------------------------------
def test_normalizar_eq_limita_y_rellena():
    c = normalizar_eq({"enabled": 1, "preamp": 99, "bands": [30, -30] + [0] * 8, "preset": "Flat"})
    assert c["enabled"] is True
    assert c["preamp"] == 20.0
    assert c["bands"][:2] == [20.0, -20.0]
    assert c["preset"] == "Plano"          # nombre antiguo traducido
    assert normalizar_eq(None)["bands"] == [0.0] * 10
    assert normalizar_eq({"bands": [1, 2]})["bands"] == [0.0] * 10


def test_presets_tienen_10_bandas():
    for nombre, (pre, bandas) in PRESETS_PROPIOS.items():
        assert len(bandas) == 10, nombre
        assert -20 <= pre <= 20


# --- letras ------------------------------------------------------------------------
class _Linea:
    def __init__(self, text, start_time):
        self.text, self.start_time, self.end_time = text, start_time, start_time + 1000


def test_letra_sincronizada_objetos():
    res = {"lyrics": [_Linea("b", 2000), _Linea("a", 500)], "source": "LyricFind", "hasTimestamps": True}
    letra = normalizar_letra(res)
    assert letra["lineas"] == [(500, "a"), (2000, "b")]
    assert letra["fuente"] == "LyricFind"


def test_letra_texto_plano():
    letra = normalizar_letra({"lyrics": "hola\nadiós", "source": "x"})
    assert letra["lineas"] == []
    assert "adiós" in letra["texto"]
    assert normalizar_letra({"lyrics": "   "}) is None
    assert normalizar_letra(None) is None


def test_linea_actual():
    lineas = [(0, "a"), (1000, "b"), (5000, "c")]
    assert linea_actual(lineas, -10) == -1
    assert linea_actual(lineas, 0) == 0
    assert linea_actual(lineas, 4999) == 1
    assert linea_actual(lineas, 99999) == 2
    assert linea_actual([], 100) == -1


# --- temas ----------------------------------------------------------------------------
def test_temas_mapas_sin_colisiones():
    """Cada color base debe ir a un color distinto: si no, al cambiar de tema se perdería."""
    for nombre, t in themes.TEMAS.items():
        for tipo in ("bg", "fg"):
            valores = list(t[tipo].values())
            assert len(valores) == len(set(valores)), (nombre, tipo)
            # un color nuevo no puede ser a la vez un color base de otro widget
            assert not (set(valores) & set(t[tipo]) - {k for k, v in t[tipo].items() if k == v}), (nombre, tipo)


def test_traducir_ida_y_vuelta():
    for a in themes.TEMAS:
        for b in themes.TEMAS:
            for base in ("#ECE9D8", "#0A246A", "#FFFFFF", "#E0DFE3", "#123456"):
                en_a = themes.traducir(base, "bg", themes.TEMA_POR_DEFECTO, a)
                en_b = themes.traducir(en_a, "bg", a, b)
                assert en_b == themes.obtener(b)["bg"].get(base, base)


def test_color_tema_desconocido_usa_luna():
    assert themes.color("#ECE9D8", "No existe") == "#ECE9D8"


# --- sonidos ----------------------------------------------------------------------------
def test_sonidos_se_generan(tmp_path):
    muestras = sintetizar("conectar")
    assert len(muestras) > 1000
    assert max(abs(m) for m in muestras) <= 32767
    ruta = ruta_sonido("amigo", str(tmp_path))
    with wave.open(ruta) as w:
        assert w.getframerate() == 22050 and w.getnframes() > 1000


# --- sesión -------------------------------------------------------------------------------
class AuthApiError(Exception):
    def __init__(self, msg, status):
        super().__init__(msg)
        self.status = status


class AuthRetryableError(Exception):
    pass


def test_sesion_invalida_solo_con_errores_de_auth():
    assert sesion_invalida(AuthApiError("Invalid Refresh Token", 400))
    assert sesion_invalida(KeyError("access_token"))
    assert not sesion_invalida(AuthRetryableError("timeout"))
    assert not sesion_invalida(ConnectionError("sin red"))
    assert not sesion_invalida(OSError("[Errno 11001] getaddrinfo failed"))
    assert not sesion_invalida(AuthApiError("server", 503))
