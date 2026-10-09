"""Historial de reproducción y canciones escuchadas recientemente."""
from datetime import datetime, timezone


HISTORY_LIMIT = 200


class PlayerHistoryMixin:
    """Mantiene un historial compacto dentro de ``cloud_data['history']``."""

    def _asegurar_historial(self):
        history = self.cloud_data.setdefault("history", [])
        if not isinstance(history, list):
            history = []
            self.cloud_data["history"] = history
        return history

    def _registrar_reproduccion(self, cancion):
        """Registra una reproducción cuando VLC empieza realmente la canción.

        La entrada más reciente queda primero. Las reproducciones repetidas no
        crean filas infinitas: actualizan ``lastPlayed`` e incrementan
        ``playCount``. Esto deja una base sencilla para futuras estadísticas.
        """
        video_id = (cancion or {}).get("videoId")
        if not video_id:
            return

        settings = self.cloud_data.get("settings") or {}
        if not bool(settings.get("save_history", True)):
            return

        history = self._asegurar_historial()
        ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        existente = next((x for x in history if x.get("videoId") == video_id), None)

        if existente is None:
            existente = {
                "title": cancion.get("title", "Desconocido"),
                "artist": cancion.get("artist", ""),
                "videoId": video_id,
                "coverUrl": cancion.get("coverUrl") or cancion.get("highCoverUrl"),
                "lastPlayed": ahora,
                "playCount": 1,
            }
            history.insert(0, existente)
        else:
            existente["title"] = cancion.get("title", existente.get("title", "Desconocido"))
            existente["artist"] = cancion.get("artist", existente.get("artist", ""))
            existente["coverUrl"] = cancion.get("coverUrl") or cancion.get("highCoverUrl") or existente.get("coverUrl")
            existente["lastPlayed"] = ahora
            existente["playCount"] = int(existente.get("playCount", 0) or 0) + 1
            history.remove(existente)
            history.insert(0, existente)

        del history[HISTORY_LIMIT:]
        self.cloud_data["version"] = 2
        self._refrescar_escuchado_reciente_ui()
        if hasattr(self, "actualizar_estadisticas_ui"):
            self.actualizar_estadisticas_ui()
        self._guardar_si_corresponde()

    def _filtrar_recientes_ui(self, event=None):
        self._refrescar_escuchado_reciente_ui()

    def _refrescar_escuchado_reciente_ui(self):
        """Actualiza la lista de recientes respetando el filtro de texto."""
        lista = getattr(self, "list_recent_tracks", None)
        if lista is None:
            return

        filtro = ""
        if hasattr(self, "recent_search_var"):
            filtro = self.recent_search_var.get().strip().lower()

        history = self._asegurar_historial()
        visibles = []
        for track in history:
            texto = f"{track.get('title', '')} {track.get('artist', '')}".lower()
            if not filtro or filtro in texto:
                visibles.append(track)
            if len(visibles) >= 50:
                break

        self._recent_visible_tracks = visibles
        lista.delete(0, "end")
        for track in visibles:
            titulo = track.get("title", "Desconocido")
            artista = track.get("artist", "")
            reproducciones = int(track.get("playCount", 0) or 0)
            sufijo = f"  · {reproducciones}×" if reproducciones > 1 else ""
            lista.insert("end", f"  {titulo} — {artista}{sufijo}")

        total = len(history)
        plays = sum(int(x.get("playCount", 0) or 0) for x in history)
        if hasattr(self, "recent_info_label"):
            self.recent_info_label.config(
                text=f"{total} canciones · {plays} reproducciones"
            )

    def _seleccionar_reciente_ui(self, event=None):
        lista = getattr(self, "list_recent_tracks", None)
        if lista is None:
            return
        sel = lista.curselection()
        visibles = getattr(self, "_recent_visible_tracks", [])
        if not sel or sel[0] >= len(visibles):
            return
        track = visibles[sel[0]]
        if hasattr(self, "recent_selected_label"):
            self.recent_selected_label.config(
                text=f"{track.get('title', 'Desconocido')}\n{track.get('artist', '')}"
            )
        if hasattr(self, "recent_play_count_label"):
            n = int(track.get("playCount", 0) or 0)
            self.recent_play_count_label.config(text=f"Escuchada {n}×")

    def _reproducir_escuchado_seleccionado(self, event=None):
        lista = getattr(self, "list_recent_tracks", None)
        if lista is None:
            return
        sel = lista.curselection()
        visibles = getattr(self, "_recent_visible_tracks", [])
        if not sel or sel[0] >= len(visibles):
            return
        self.reproducir_directo(dict(visibles[sel[0]]))

    def _anadir_reciente_a_cola(self):
        lista = getattr(self, "list_recent_tracks", None)
        visibles = getattr(self, "_recent_visible_tracks", [])
        if lista is None:
            return
        sel = lista.curselection()
        if not sel or sel[0] >= len(visibles):
            self.status_var.set("Selecciona una canción reciente.")
            return
        track = dict(visibles[sel[0]])
        self.agregar_cancion_a_cola(track)
        self.status_var.set(f"➕ Añadida a la cola: {track.get('title', 'Desconocido')}")

    def _borrar_historial(self):
        from tkinter import messagebox
        history = self._asegurar_historial()
        if not history:
            self.status_var.set("El historial ya está vacío.")
            return
        if not messagebox.askyesno("Borrar historial", "¿Quieres borrar todo el historial de reproducción?"):
            return
        history.clear()
        self.cloud_data["version"] = 2
        self._refrescar_escuchado_reciente_ui()
        if hasattr(self, "actualizar_estadisticas_ui"):
            self.actualizar_estadisticas_ui()
        self._guardar_si_corresponde()
        self.status_var.set("🗑 Historial borrado.")

    def obtener_escuchado_recientemente(self, limite=20):
        """Devuelve las canciones más recientemente reproducidas."""
        history = self._asegurar_historial()
        return history[:max(0, int(limite))]
