"""Modelo y persistencia de datos locales del reproductor."""
import json
import os

import app_paths

DATA_DIR = app_paths.DATA_DIR
LEGACY_DATA_FILE = os.path.join(DATA_DIR, "exotic_player_data_local.json")


def datos_vacios():
    return {"version": 2, "playlists": [], "liked": [], "history": [], "settings": {}}


def ruta_datos_usuario(user_id):
    return os.path.join(DATA_DIR, f"exotic_player_data_{user_id}.json")


def cargar_datos_local(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    base = datos_vacios()
    base.update(data)
    if not isinstance(base.get("playlists"), list):
        base["playlists"] = []
    if not isinstance(base.get("liked"), list):
        base["liked"] = []
    if not isinstance(base.get("history"), list):
        base["history"] = []
    return base


def guardar_datos_local(data, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
