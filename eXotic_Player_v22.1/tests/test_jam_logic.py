
from jam_logic import (
    clasificar_revision,
    crear_objetivo,
    destino,
    hay_cambio,
    necesita_seek,
    seek_pendiente_activo,
    tick_acciones,
)


def test_crear_objetivo_normaliza_cola_e_indice():
    estado = {
        "queue": [
            {"videoId": "a", "title": "A"},
            {"title": "sin id"},
            "no es dict",
            {"videoId": "b", "title": "B"},
        ],
        "index": "2",
        "playing": True,
        "position_ms": "1250",
        "by": "ana",
    }

    objetivo = crear_objetivo(estado, 350.5, 10.0)

    assert [x["videoId"] for x in objetivo["queue"]] == ["a", "b"]
    assert objetivo["index"] == -1  # el índice remoto 2 ya no es válido tras normalizar
    assert objetivo["vid"] is None
    assert objetivo["playing"] is True
    assert objetivo["pos"] == 1250.0
    assert objetivo["age"] == 350.5
    assert objetivo["by"] == "ana"


def test_crear_objetivo_rechaza_indices_no_validos():
    for indice in (-1, 99, "abc", None):
        objetivo = crear_objetivo({"queue": [{"videoId": "a"}], "index": indice}, 0, 1)
        assert objetivo["index"] == -1
        assert objetivo["vid"] is None


def test_destino_avanza_solo_si_la_jam_esta_reproduciendo():
    objetivo = crear_objetivo(
        {"queue": [{"videoId": "a"}], "index": 0, "playing": True, "position_ms": 1000},
        age=250,
        t=10.0,
    )
    assert destino(objetivo, now=11.0) == 2250.0

    objetivo["playing"] = False
    assert destino(objetivo, now=99.0) == 1000.0


def test_revisiones_identifican_respuesta_vieja_nueva_y_actual():
    assert clasificar_revision(5, 4, True) == "stale"
    assert clasificar_revision(5, 6, True) == "new"
    assert clasificar_revision(5, 5, True) == "same"
    # Una revisión mayor sin estado no puede adoptarse.
    assert clasificar_revision(5, 6, False) == "same"


def test_cambio_local_detecta_indice_seek_y_play_pause():
    assert hay_cambio(2, 1, False, False, False, True, True)
    assert hay_cambio(1, 1, True, False, False, True, True)
    assert hay_cambio(1, 1, False, False, False, False, True)
    assert not hay_cambio(1, 1, False, False, False, True, True)
    # Mientras se carga no se publica un cambio de play/pausa todavía inestable.
    assert not hay_cambio(1, 1, False, True, False, False, True)
    assert not hay_cambio(1, 1, False, False, True, False, True)
    # Si el estado local no se puede determinar, no se publica nada.
    assert not hay_cambio(1, 1, False, False, False, None, True)


def test_seek_pendiente_expira():
    assert seek_pendiente_activo(True, 100.0, now=129.9)
    assert not seek_pendiente_activo(True, 100.0, now=130.0)
    assert not seek_pendiente_activo(False, 0.0, now=1000.0)


def test_tick_de_miembro_controla_poll_latido_y_solicitudes():
    assert tick_acciones(1, "guest") == {"poll": False, "heartbeat": False, "requests": False}
    assert tick_acciones(2, "guest") == {"poll": True, "heartbeat": False, "requests": False}
    assert tick_acciones(40, "guest") == {"poll": True, "heartbeat": True, "requests": False}
    assert tick_acciones(20, "host") == {"poll": True, "heartbeat": False, "requests": True}
    assert tick_acciones(40, "host") == {"poll": True, "heartbeat": True, "requests": True}


def test_tick_pendiente_solo_consulta_aprobacion():
    assert tick_acciones(3, "pending") == {"poll": False, "heartbeat": False, "requests": False}
    assert tick_acciones(4, "pending") == {"poll": True, "heartbeat": False, "requests": False}
    assert tick_acciones(40, "pending") == {"poll": True, "heartbeat": False, "requests": False}


def test_necesita_seek_solo_si_supera_la_tolerancia():
    assert not necesita_seek(1000, 1200, 250)
    assert not necesita_seek(1200, 1000, 250)
    assert necesita_seek(1301, 1000, 250)
    assert necesita_seek(-1, 1000, 250) is False
