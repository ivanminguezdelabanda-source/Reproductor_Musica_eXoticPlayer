"""Gestión de playlists y favoritos."""
import random
import tkinter as tk
from tkinter import messagebox, simpledialog
import uuid

import duraciones
from playlist_logic import filtrar_indices, mover_indice


class PlayerPlaylistsMixin:
    def _actualizar_selector_playlists(self):
        if not hasattr(self, "playlist_combo"):
            return
        playlists = self.cloud_data.get("playlists", [])
        nombres = [p.get("name", "Sin nombre") for p in playlists]
        if not nombres:
            nombres = ["Mi música"]
        self.playlist_combo["values"] = nombres
        if self.playlist_var.get() not in nombres:
            self.playlist_var.set(nombres[0])
        self._playlist_visible_indices = []
        self._playlist_drag_source = None
        self._refrescar_lista_playlist()
        self._refrescar_favoritos_ui()


    def _seleccionar_playlist_ui(self, event=None):
        self._refrescar_lista_playlist()
        self.queue_playlist = []
        if self._queue_mode == "playlist":
            self._activar_cola("playlist")
        self._playlist_shuffle = False
        self._playlist_shuffle_order = []
        self._playlist_shuffle_source = None
        self._actualizar_boton_aleatorio_playlist()
        self.status_var.set(f"Playlist '{self.playlist_var.get()}' seleccionada.")


    def _playlist_activa(self):
        return self._playlist_por_nombre(self.playlist_var.get())


    def _refrescar_lista_playlist(self):
        if not hasattr(self, "list_playlist_tracks"):
            return
        self.list_playlist_tracks.delete(0, tk.END)
        pl = self._playlist_activa()
        if not pl:
            self._playlist_visible_indices = []
            return
        tracks = pl.get("tracks", [])
        self._playlist_visible_indices = filtrar_indices(
            tracks, getattr(self, "playlist_search_var", tk.StringVar()).get()
        )
        for visual_i, real_i in enumerate(self._playlist_visible_indices, 1):
            t = tracks[real_i]
            titulo = str(t.get("title", "Desconocido")).strip() or "Desconocido"
            artista = str(t.get("artist", "")).strip() or "Artista desconocido"
            duracion = duraciones.formatear_pista(duraciones.de_pista(t))
            # No truncamos títulos ni artistas: el texto debe conservarse completo.
            # La columna de biblioteca se amplía para que haya espacio suficiente.
            duracion_txt = duracion or "--:--"
            fila = f" {visual_i:02d}  {titulo:<42}  {artista:<25} {duracion_txt:>5}"
            self.list_playlist_tracks.insert(tk.END, fila)
            self.list_playlist_tracks.itemconfig(
                tk.END,
                background=self.c("#FFFFFF" if visual_i % 2 else "#F4F4F4"),
                foreground=self.c("#000000", "fg"),
            )
        self._actualizar_info_playlist_ui()
        self._actualizar_portada_playlist_ui()


    def _menu_contextual_playlist(self, event=None):
        if event is not None:
            index = self.list_playlist_tracks.nearest(event.y)
            if 0 <= index < self.list_playlist_tracks.size():
                self.list_playlist_tracks.selection_clear(0, tk.END)
                self.list_playlist_tracks.selection_set(index)
                self.list_playlist_tracks.activate(index)
        pl, idx = self._pista_playlist_seleccionada()
        if pl is None:
            return
        track = pl.get("tracks", [])[idx]
        menu = tk.Menu(self.root, tearoff=0, font=("Tahoma", 9))
        menu.add_command(label="▶ Reproducir", command=self.playlist_reproducir_seleccion)
        menu.add_command(label="+ Añadir a cola", command=self.playlist_agregar_seleccion_a_cola)
        menu.add_separator()
        menu.add_command(label="✕ Quitar de esta playlist", command=self.playlist_quitar_seleccion)
        menu.add_command(
            label="♥ Me gusta",
            command=lambda: self._marcar_me_gusta_local(track)
        )
        menu.add_separator()
        menu.add_command(
            label="▶ Reproducir desde aquí",
            command=lambda: self._reproducir_playlist_desde_indice(idx)
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _reproducir_playlist_desde_indice(self, idx):
        pl = self._playlist_activa()
        if not pl or idx < 0 or idx >= len(pl.get("tracks", [])):
            return
        self.list_playlist_tracks.selection_clear(0, tk.END)
        visibles = getattr(self, "_playlist_visible_indices", [])
        if idx in visibles:
            self.list_playlist_tracks.selection_set(visibles.index(idx))
            self.list_playlist_tracks.see(visibles.index(idx))
        self.playlist_reproducir_seleccion()

    def _playlist_tecla(self, event=None):
        if event is not None and event.keysym in ("Return", "KP_Enter"):
            self.playlist_reproducir_seleccion()
            return "break"
        if event is not None and event.keysym in ("Delete", "BackSpace"):
            self.playlist_quitar_seleccion_multiple()
            return "break"

    def _filtrar_playlist_ui(self, event=None):
        self._refrescar_lista_playlist()


    def _pista_playlist_seleccionada(self):
        pl = self._playlist_activa()
        sel = self.list_playlist_tracks.curselection()
        if not pl or not sel:
            self.status_var.set("Selecciona una canción de la playlist.")
            return None, None
        visible = getattr(self, "_playlist_visible_indices", [])
        if sel[0] >= len(visible):
            return None, None
        return pl, visible[sel[0]]


    def _iniciar_arrastre_playlist(self, event=None):
        if not hasattr(self, "list_playlist_tracks"):
            return
        index = self.list_playlist_tracks.nearest(event.y)
        if 0 <= index < len(getattr(self, "_playlist_visible_indices", [])):
            self._playlist_drag_source = index
            self.list_playlist_tracks.selection_clear(0, tk.END)
            self.list_playlist_tracks.selection_set(index)


    def _arrastrar_playlist(self, event=None):
        if getattr(self, "_playlist_drag_source", None) is None:
            return
        count = self.list_playlist_tracks.size()
        if not count:
            return
        index = max(0, min(count - 1, self.list_playlist_tracks.nearest(event.y)))
        self.list_playlist_tracks.selection_clear(0, tk.END)
        self.list_playlist_tracks.selection_set(index)


    def _finalizar_arrastre_playlist(self, event=None):
        source_visual = getattr(self, "_playlist_drag_source", None)
        self._playlist_drag_source = None
        if source_visual is None:
            return
        visible = getattr(self, "_playlist_visible_indices", [])
        if not visible or source_visual >= len(visible):
            return
        target_visual = max(0, min(len(visible) - 1, self.list_playlist_tracks.nearest(event.y)))
        source_real = visible[source_visual]
        target_real = visible[target_visual]
        if source_real == target_real:
            return

        pl = self._playlist_activa()
        if not pl:
            return
        tracks = pl.get("tracks", [])
        mover_indice(tracks, source_real, target_real)
        self.cloud_data["version"] = 2
        self._refrescar_lista_playlist()
        self.list_playlist_tracks.selection_set(target_visual)
        self._subir_cloud_data_async(f"☁️ Orden actualizado en '{pl.get('name', 'Playlist')}'.")


    def _playlist_aleatorio_permitido(self):
        return not getattr(self.social, "en_jam", False)


    def _actualizar_boton_aleatorio_playlist(self):
        if not hasattr(self, "playlist_shuffle_btn"):
            return
        permitido = self._playlist_aleatorio_permitido()
        self.playlist_shuffle_btn.config(
            state=(tk.NORMAL if permitido else tk.DISABLED),
            relief=(tk.SUNKEN if permitido and self._playlist_shuffle else tk.RAISED),
            bg=self.c("#C8E8C8" if permitido and self._playlist_shuffle else "#E0DFE3")
        )
        if not permitido and self._playlist_shuffle:
            self._playlist_shuffle = False
            self._playlist_shuffle_order = []


    def _crear_orden_aleatorio_playlist(self, indice_actual=None):
        total = len(self.queue_playlist)
        indices = list(range(total))
        if not indices:
            self._playlist_shuffle_order = []
            return

        if indice_actual is not None and indice_actual in indices:
            indices.remove(indice_actual)
            random.shuffle(indices)
            self._playlist_shuffle_order = [indice_actual] + indices
        else:
            random.shuffle(indices)
            self._playlist_shuffle_order = indices


    def _alternar_aleatorio_playlist(self):
        if not self._playlist_aleatorio_permitido():
            self.status_var.set("El modo aleatorio está deshabilitado durante una Jam.")
            return
        pl = self._playlist_activa()
        if not pl or not pl.get("tracks"):
            self.status_var.set("La playlist está vacía.")
            return

        estaba_activado = self._playlist_shuffle
        self._playlist_shuffle = not estaba_activado
        self._playlist_shuffle_source = pl.get("id") or pl.get("name")

        if self._playlist_shuffle:
            indice_actual = None
            if self._queue_mode == "playlist" and 0 <= self.current_index < len(self.queue_playlist):
                indice_actual = self.current_index
            self._crear_orden_aleatorio_playlist(indice_actual)
            self.status_var.set(f"🔀 Aleatorio activado en '{pl.get('name', 'Playlist')}'.")
        else:
            self._playlist_shuffle_order = []
            self.status_var.set("▶ Orden normal de la playlist restaurado.")

        self._actualizar_boton_aleatorio_playlist()
        if self._queue_mode == "playlist":
            self.actualizar_vista_cola()


    def _preparar_cola_playlist(self, indice_inicial=None):
        if not self._playlist_aleatorio_permitido():
            self.status_var.set("El modo aleatorio está deshabilitado durante una Jam.")
            return False
        pl = self._playlist_activa()
        if not pl or not pl.get("tracks"):
            self.status_var.set("La playlist está vacía.")
            return False

        tracks = [self._normalizar_track(x) for x in pl.get("tracks", [])]
        tracks = [x for x in tracks if x]
        if not tracks:
            self.status_var.set("La playlist está vacía.")
            return False

        self.queue_playlist = [dict(t) for t in tracks]
        self._activar_cola("playlist")

        if self._playlist_shuffle:
            self._crear_orden_aleatorio_playlist(indice_inicial)
            self.current_index = indice_inicial if indice_inicial is not None else self._playlist_shuffle_order[0]
        elif indice_inicial is not None:
            self.current_index = indice_inicial
        else:
            self.current_index = 0
        return True


    def playlist_reproducir_seleccion(self):
        pl, idx = self._pista_playlist_seleccionada()
        if pl is None:
            return
        if getattr(self.social, "en_jam", False):
            track = self._normalizar_track(pl["tracks"][idx])
            if track:
                self.social.cola_agregar([track], reproducir=True)
            return
        if not self._preparar_cola_playlist(idx):
            return
        self.actualizar_vista_cola()
        self.cargar_y_reproducir_actual()


    def playlist_agregar_seleccion_a_cola(self):
        pl, idx = self._pista_playlist_seleccionada()
        if pl is None:
            return
        track = self._normalizar_track(pl["tracks"][idx])
        if not track:
            return
        if getattr(self.social, "en_jam", False):
            self.social.cola_agregar([track])
            return
        self.queue_playlist.append(dict(track))
        if self._queue_mode == "playlist":
            self.actualizar_vista_cola()
        self.status_var.set(f"Añadido a la cola de '{pl.get('name', 'Playlist')}': {track['title']}")


    def playlist_agregar_todo_a_cola(self):
        pl = self._playlist_activa()
        if not pl or not pl.get("tracks"):
            self.status_var.set("La playlist está vacía.")
            return
        nuevas = [t for t in (self._normalizar_track(x) for x in pl["tracks"]) if t]
        if getattr(self.social, "en_jam", False):
            if nuevas:
                self.social.cola_agregar(nuevas)
            return
        inicio = len(self.queue_playlist)
        self.queue_playlist.extend(dict(t) for t in nuevas)
        if self._playlist_shuffle and self._playlist_aleatorio_permitido():
            nuevos_indices = list(range(inicio, len(self.queue_playlist)))
            random.shuffle(nuevos_indices)
            self._playlist_shuffle_order.extend(nuevos_indices)
        if self._queue_mode == "playlist":
            self.actualizar_vista_cola()
        self.status_var.set(f"{len(nuevas)} canciones de '{pl.get('name')}' añadidas a su cola.")


    def _duracion_a_segundos_playlist(self, valor, clave=None):
        return duraciones.a_segundos(valor, clave)

    def _playlist_duracion_segundos(self, pl):
        return sum(duraciones.de_pista(t) for t in pl.get("tracks", []))

    def _formatear_duracion_cancion(self, valor):
        return duraciones.formatear_pista(duraciones.a_segundos(valor))

    def _formatear_duracion_playlist(self, segundos):
        return duraciones.formatear_total(segundos)

    def _actualizar_portada_playlist_ui(self):
        label = getattr(self, "playlist_cover_label", None)
        title = getattr(self, "playlist_cover_title", None)
        if label is None:
            return
        pl = self._playlist_activa()
        if not pl:
            label.config(image="", text="♪")
            label.image = None
            if title is not None:
                title.config(text="Mi música")
            return
        nombre = pl.get("name", "Playlist")
        if title is not None:
            title.config(text=nombre[:32])
        url = pl.get("coverUrl") or next((t.get("coverUrl") for t in pl.get("tracks", []) if t.get("coverUrl")), "")
        label.config(image="", text="♪")
        label.image = None
        if url:
            vigente = lambda: self._playlist_activa() is pl
            try:
                self.cargar_imagen_async(url, 68, label, vigente=vigente)
            except Exception:
                pass


    def _actualizar_info_playlist_ui(self):
        label = getattr(self, "playlist_info_label", None)
        if label is None:
            return
        pl = self._playlist_activa()
        if not pl:
            label.config(text="0 canciones")
            return
        n = len(pl.get("tracks", []))
        dur = self._playlist_duracion_segundos(pl)
        portada = pl.get("coverUrl") or next((t.get("coverUrl") for t in pl.get("tracks", []) if t.get("coverUrl")), "")
        label.config(text=f"{n} canción{'es' if n != 1 else ''}  •  {self._formatear_duracion_playlist(dur)}" + ("  •  🖼 Portada" if portada else ""))


    def playlist_renombrar(self):
        pl = self._playlist_activa()
        if not pl:
            return
        if pl.get("id") == "default":
            self.status_var.set("'Mi música' no se puede renombrar.")
            return
        nombre = simpledialog.askstring("Renombrar playlist", "Nuevo nombre:", initialvalue=pl.get("name", ""), parent=self.root)
        if nombre is None:
            return
        nombre = nombre.strip()
        if not nombre:
            self.status_var.set("El nombre no puede estar vacío.")
            return
        if any(p is not pl and p.get("name", "").casefold() == nombre.casefold() for p in self.cloud_data.get("playlists", [])):
            self.status_var.set("Ya existe una playlist con ese nombre.")
            return
        antiguo = pl.get("name", "Playlist")
        pl["name"] = nombre
        self.ytm_renombrar_playlist(pl, nombre)
        self.cloud_data["version"] = 2
        self._actualizar_selector_playlists()
        self.playlist_var.set(nombre)
        self._refrescar_lista_playlist()
        self._subir_cloud_data_async(f"☁️ Playlist renombrada: '{antiguo}' → '{nombre}'.")
        self.status_var.set(f"Playlist renombrada: {nombre}")


    def playlist_establecer_portada(self):
        pl = self._playlist_activa()
        if not pl:
            return
        url = simpledialog.askstring("Portada de playlist", "URL de la imagen (opcional):", initialvalue=pl.get("coverUrl", ""), parent=self.root)
        if url is None:
            return
        pl["coverUrl"] = url.strip()
        self.cloud_data["version"] = 2
        self._actualizar_info_playlist_ui()
        self._subir_cloud_data_async(f"☁️ Portada actualizada en '{pl.get('name', 'Playlist')}'.")
        self.status_var.set("Portada de playlist actualizada.")


    def playlist_quitar_seleccion_multiple(self):
        pl = self._playlist_activa()
        lista = getattr(self, "list_playlist_tracks", None)
        visible = getattr(self, "_playlist_visible_indices", [])
        if not pl or lista is None:
            return
        seleccion = list(lista.curselection())
        if not seleccion:
            self.status_var.set("Selecciona una o varias canciones para quitar.")
            return
        reales = sorted((visible[i] for i in seleccion if 0 <= i < len(visible)), reverse=True)
        if not reales:
            return
        if len(reales) > 1 and not messagebox.askyesno("Quitar canciones", f"¿Quitar {len(reales)} canciones de '{pl.get('name', 'Playlist')}'?", parent=self.root):
            return
        quitadas = [pl["tracks"].pop(idx) for idx in reales]
        self.ytm_quitar_de_playlist(pl, quitadas)
        self.cloud_data["version"] = 2
        self._refrescar_lista_playlist()
        self._subir_cloud_data_async(f"☁️ {len(reales)} canciones quitadas de '{pl.get('name', 'Playlist')}'.")
        self.status_var.set(f"{len(reales)} canción{'es' if len(reales) != 1 else ''} quitada{'s' if len(reales) != 1 else ''}.")


    def playlist_quitar_seleccion(self):
        pl, idx = self._pista_playlist_seleccionada()
        if pl is None:
            return
        quitada = pl["tracks"].pop(idx)
        self.ytm_quitar_de_playlist(pl, [quitada])
        self.cloud_data["version"] = 2
        self._refrescar_lista_playlist()
        self._subir_cloud_data_async(f"☁️ Quitada de '{pl.get('name')}': {quitada.get('title', '')}")


    def playlist_eliminar(self):
        pl = self._playlist_activa()
        if not pl:
            return
        if pl.get("id") == "default":
            self.status_var.set("'Mi música' no se puede eliminar.")
            return
        if not messagebox.askyesno("Eliminar playlist", f"¿Eliminar la playlist '{pl.get('name')}'?"):
            return
        self.cloud_data["playlists"] = [p for p in self.cloud_data["playlists"] if p is not pl]
        self.cloud_data["version"] = 2
        self.playlist_var.set("Mi música")
        self._actualizar_selector_playlists()
        self._subir_cloud_data_async(f"☁️ Playlist '{pl.get('name')}' eliminada.")


    def _mostrar_creador_playlist_inline(self):
        if self.playlist_create_bar.winfo_ismapped():
            self._ocultar_creador_playlist_inline()
            return
        for w in self.playlist_create_bar.winfo_children():
            w.destroy()
        self.playlist_create_bar.pack(fill=tk.X, padx=7, pady=(0, 5), before=self.playlist_tracks_frame)
        tk.Label(self.playlist_create_bar, text="Nombre:", bg=self.c(self.bg_color), font=("Tahoma", 8, "bold")).pack(side=tk.LEFT, padx=4)
        entry = tk.Entry(self.playlist_create_bar, font=("Tahoma", 8), relief=tk.SUNKEN, bd=2)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self._playlist_entry = entry
        entry.focus_set()
        entry.bind("<Return>", lambda e: self._crear_playlist_desde_entrada())
        tk.Button(self.playlist_create_bar, text="Crear", width=6, bg="#D9F2D9", bd=2, command=self._crear_playlist_desde_entrada).pack(side=tk.LEFT, padx=2)
        tk.Button(self.playlist_create_bar, text="X", width=3, bg="#F2D9D9", bd=2, command=self._ocultar_creador_playlist_inline).pack(side=tk.LEFT, padx=2)
        for w in self.playlist_create_bar.winfo_children():
            self.tematizar(w)


    def _ocultar_creador_playlist_inline(self):
        if hasattr(self, "playlist_create_bar"):
            self.playlist_create_bar.pack_forget()
        self._playlist_entry = None


    def _crear_playlist_desde_entrada(self):
        if not self._playlist_entry:
            return
        nombre = self._playlist_entry.get().strip()
        if not nombre:
            self.status_var.set("Escribe un nombre para la playlist.")
            return
        playlists = self.cloud_data.setdefault("playlists", [])
        if any(p.get("name", "").casefold() == nombre.casefold() for p in playlists):
            self.status_var.set("Ya existe una playlist con ese nombre.")
            return
        nueva = {"id": f"playlist-{uuid.uuid4().hex}", "name": nombre, "tracks": [], "coverUrl": ""}
        playlists.append(nueva)
        self.cloud_data["version"] = 2
        self._actualizar_selector_playlists()
        self.playlist_var.set(nombre)
        self._ocultar_creador_playlist_inline()
        self._subir_cloud_data_async(f"☁️ Playlist '{nombre}' guardada.")
        self.status_var.set(f"Playlist creada: {nombre}")


    def _playlist_por_nombre(self, nombre):
        return next((p for p in self.cloud_data.get("playlists", []) if p.get("name") == nombre), None)


    def _menu_guardar_en_playlist(self, cancion, boton):
        self._asegurar_playlist_principal()
        playlists = self.cloud_data.get("playlists", [])
        menu = tk.Menu(self.root, tearoff=0, font=("Tahoma", 9))
        menu.add_command(label="♥ Me gusta", command=lambda: self._marcar_me_gusta_local(cancion))
        menu.add_separator()
        menu.add_command(label="Guardar en playlist:", state=tk.DISABLED)
        for playlist in playlists:
            nombre = playlist.get("name", "Sin nombre")
            menu.add_command(label=f"  {nombre}", command=lambda p=playlist: self._guardar_cancion_en_playlist(cancion, p))
        compartidas = getattr(self.social, "compartidas", None) or []
        if compartidas and not str(cancion.get("videoId", "")).startswith("file:"):
            menu.add_separator()
            menu.add_command(label="Playlists compartidas:", state=tk.DISABLED)
            for pl in compartidas:
                menu.add_command(label=f"  👥 {pl['name']}",
                                 command=lambda p=pl: self.social.agregar_a_compartida(p, [cancion]))
        menu.add_separator()
        menu.add_command(label="+ Nueva playlist", command=self._mostrar_creador_playlist_inline)
        try:
            menu.tk_popup(boton.winfo_rootx(), boton.winfo_rooty() + boton.winfo_height())
        finally:
            menu.grab_release()


    def _alternar_me_gusta_desde_resultado(self, cancion, boton=None):
        """Activa/desactiva Me gusta directamente desde un resultado de búsqueda."""
        liked = self.cloud_data.setdefault("liked", [])
        video_id = cancion.get("videoId")
        if not video_id:
            return
        existe = any(x.get("videoId") == video_id for x in liked)
        self.ytm_me_gusta(video_id, not existe)            # también en YouTube Music (si está conectado)
        if existe:
            self.cloud_data["liked"] = [x for x in liked if x.get("videoId") != video_id]
            mensaje = "♡ Quitada de Me gusta."
            if boton is not None:
                boton.config(text="♡", bg=self.c("#E0DFE3"))
        else:
            track = self._normalizar_track(cancion)
            if track:
                liked.append(track)
            mensaje = "♥ Añadida a Me gusta."
            if boton is not None:
                boton.config(text="♥", bg=self.c("#FFDADA"))
        self.cloud_data["version"] = 2
        self._refrescar_favoritos_ui()
        self._subir_cloud_data_async("☁️ Me gusta actualizado.")
        self.status_var.set(mensaje)


    def _marcar_me_gusta_local(self, cancion, persistir=True):
        liked = self.cloud_data.setdefault("liked", [])
        if not any(x.get("videoId") == cancion.get("videoId") for x in liked):
            track = self._normalizar_track(cancion)
            if track:
                liked.append(track)
                self.ytm_me_gusta(track["videoId"], True)
        if persistir:
            self._subir_cloud_data_async("♥ Añadida a Me gusta.")
        self._refrescar_favoritos_ui()
        self.status_var.set(f"♥ {cancion.get('title', 'Canción')} añadida a Me gusta.")


    def _guardar_cancion_en_playlist(self, cancion, playlist):
        track = self._normalizar_track(cancion)
        if not track:
            return
        tracks = playlist.setdefault("tracks", [])
        nombre_pl = playlist.get("name", "Playlist")
        if any(x.get("videoId") == track.get("videoId") for x in tracks):
            self.status_var.set(f"La canción ya está en '{nombre_pl}'.")
            return
        tracks.append(track)          # (v19 además la marcaba como ♥ sin pedirlo)
        self.ytm_anadir_a_playlist(playlist, track["videoId"])
        self.cloud_data["version"] = 2
        if self.playlist_var.get() == nombre_pl:
            self._refrescar_lista_playlist()
        self._subir_cloud_data_async(f"☁️ Guardada en '{nombre_pl}'.")
        self.status_var.set(f"✓ Guardada en '{nombre_pl}'.")


    def _refrescar_favoritos_ui(self):
        lista = getattr(self, "list_liked_tracks", None)
        if lista is None:
            return
        lista.delete(0, tk.END)
        canciones = [self._normalizar_track(x) for x in self.cloud_data.get("liked", [])]
        canciones = [x for x in canciones if x]
        for track in canciones:
            lista.insert(tk.END, f"  {track.get('title', 'Desconocido')} — {track.get('artist', '')}")
        if hasattr(self, "like_btn"):
            self._actualizar_boton_like()

    def _reproducir_favorito_seleccionado(self, event=None):
        lista = getattr(self, "list_liked_tracks", None)
        if lista is None:
            return
        sel = lista.curselection()
        if not sel:
            return
        canciones = [self._normalizar_track(x) for x in self.cloud_data.get("liked", [])]
        canciones = [x for x in canciones if x]
        if sel[0] < len(canciones):
            self.reproducir_directo(dict(canciones[sel[0]]))

    def _quitar_favorito_seleccionado(self):
        lista = getattr(self, "list_liked_tracks", None)
        if lista is None:
            return
        sel = lista.curselection()
        if not sel:
            self.status_var.set("Selecciona una canción de Me gusta.")
            return
        liked = self.cloud_data.setdefault("liked", [])
        canciones = [self._normalizar_track(x) for x in liked]
        canciones = [x for x in canciones if x]
        if sel[0] >= len(canciones):
            return
        video_id = canciones[sel[0]].get("videoId")
        self.ytm_me_gusta(video_id, False)
        self.cloud_data["liked"] = [x for x in liked if x.get("videoId") != video_id]
        self.cloud_data["version"] = 2
        self._refrescar_favoritos_ui()
        self._subir_cloud_data_async("☁️ Favorito eliminado.")

    def cargar_me_gusta(self):
        canciones = [self._normalizar_track(x) for x in self.cloud_data.get("liked", [])]
        canciones = [x for x in canciones if x]
        self._search_token += 1
        self.renderizar_sugerencias(self._search_token, canciones)
        self._refrescar_favoritos_ui()
        self.status_var.set(f"♥ {len(canciones)} canciones en Me gusta.")



