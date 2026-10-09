"""Gestión de las colas de reproducción."""
import tkinter as tk

import duraciones


class PlayerQueueMixin:
    def _normalizar_track(self, item):
        if not item or not item.get("videoId"):
            return None
        return {
            "title": item.get("title", "Desconocido"),
            "artist": item.get("artist", ""),
            "videoId": item["videoId"],
            "coverUrl": item.get("coverUrl"),
            "duration": item.get("duration", item.get("duration_ms", 0)) or 0,
        }


    def _activar_cola(self, modo="normal", refrescar=True):
        if modo == "jam":
            self._queue_mode = "jam"
            self.queue = self.queue_jam
        elif modo == "playlist":
            self._queue_mode = "playlist"
            self.queue = self.queue_playlist
        else:
            self._queue_mode = "normal"
            self.queue = self.queue_normal
        self.current_index = -1
        self._actualizar_botones_modo_cola()
        if hasattr(self, "_actualizar_boton_aleatorio_playlist"):
            self._actualizar_boton_aleatorio_playlist()   # (antes se comprobaba cada medio segundo)
        if hasattr(self, "aplicar_velocidad"):
            self.aplicar_velocidad()                      # en una jam, siempre velocidad normal
        if refrescar and hasattr(self, "list_queue"):
            self.actualizar_vista_cola()


    def _elegir_cola(self, modo):
        if getattr(self.social, "en_jam", False):
            self.status_var.set("Durante una jam solo suena la cola compartida.")
            return
        self._activar_cola(modo)


    def _actualizar_botones_modo_cola(self):
        if not hasattr(self, "queue_normal_btn"):
            return
        for modo, boton in (("normal", self.queue_normal_btn), ("playlist", self.queue_playlist_btn)):
            activo = self._queue_mode == modo
            boton.config(
                relief=tk.SUNKEN if activo else tk.RAISED,
                bg=self.c("#C8E8C8" if activo else "#E0DFE3"),
            )


    def _sincronizar_cola_en_datos(self):
        self.cloud_data["queue"] = [
            t for t in (self._normalizar_track(x) for x in self.queue_normal) if t
        ]


    def _reconstruir_playlist_guardada(self):
        self.queue_normal = [
            t for t in (self._normalizar_track(x) for x in self.cloud_data.get("queue", [])) if t
        ]
        self.queue_playlist = []
        self._activar_cola("normal")


    def _duracion_cancion_para_cola(self, cancion):
        """Duración en segundos sin usar la red (la red va aparte, en segundo plano)."""
        try:
            return self._obtener_duracion_cancion(cancion, red=False)
        except Exception as e:
            print(f"[cola] error obteniendo duración: {e}")
            return duraciones.de_pista(cancion)

    def agregar_cancion_a_cola(self, cancion):
        item = {
            'title': cancion['title'],
            'artist': cancion['artist'],
            'videoId': cancion['videoId'],
            'coverUrl': cancion.get('highCoverUrl') or cancion.get('coverUrl'),
            'duration': self._duracion_cancion_para_cola(cancion),
        }
        if getattr(self.social, "en_jam", False):
            self.social.cola_agregar([item])      # lo añade el servidor: dos personas a la vez no se pisan
            return
        self.queue_normal.append(item)
        if self._queue_mode == "normal":
            self.actualizar_vista_cola()
        self.status_var.set(f"Añadido a la cola normal: {item['title']}")
        self._guardar_si_corresponde()


    def reproducir_directo(self, cancion):
        if getattr(self.social, "en_jam", False):
            self.social.cola_agregar([{
                'title': cancion['title'], 'artist': cancion['artist'], 'videoId': cancion['videoId'],
                'coverUrl': cancion.get('highCoverUrl') or cancion.get('coverUrl'),
                'duration': self._duracion_cancion_para_cola(cancion),
            }], reproducir=True)                  # suena ya para todos
            return
        self._activar_cola("normal")
        self.agregar_cancion_a_cola(cancion)
        self.current_index = len(self.queue_normal) - 1
        self.actualizar_vista_cola()
        self.cargar_y_reproducir_actual()


    def reproducir_desde_cola(self):
        sel = self.list_queue.curselection()
        if not sel:
            return
        self.current_index = sel[0]
        self.cargar_y_reproducir_actual()


    def quitar_de_cola(self):
        seleccion = list(self.list_queue.curselection())
        if not seleccion:
            return
        if getattr(self.social, "en_jam", False):
            if len(seleccion) > 1:
                self.status_var.set("En una jam solo se puede quitar una canción cada vez.")
                return
            uid = self.queue[seleccion[0]].get("uid")
            if uid:
                self.social.cola_quitar(uid)
            return
        self._apuntar_deshacer("quitar")
        cola = self.queue
        indice_actual = self.current_index
        actual = cola[indice_actual] if 0 <= indice_actual < len(cola) else None
        for idx in reversed(seleccion):
            if 0 <= idx < len(cola):
                del cola[idx]
        if actual is not None and actual in cola:
            self.current_index = cola.index(actual)
        elif actual is not None:
            self.detener_cancion()
            self.current_index = -1
        else:
            self.current_index = -1
        self.actualizar_vista_cola()
        self._guardar_si_corresponde()
        self.status_var.set(f"{len(seleccion)} canción(es) quitada(s) de la cola.")


    def mover_seleccion_cola(self, direccion):
        """Mueve una o varias canciones arriba/abajo conservando la selección."""
        if getattr(self.social, "en_jam", False):
            self.status_var.set("La cola compartida de una jam se gestiona entre todos los participantes.")
            return
        seleccion = list(self.list_queue.curselection())
        if not seleccion or not self.queue:
            return
        seleccion_set = set(seleccion)
        if direccion < 0 and min(seleccion) == 0:
            return
        if direccion > 0 and max(seleccion) == len(self.queue) - 1:
            return
        self._apuntar_deshacer("mover")

        actual = self.queue[self.current_index] if 0 <= self.current_index < len(self.queue) else None
        seleccion_items = [self.queue[i] for i in seleccion]
        if direccion < 0:
            for idx in seleccion:
                if idx > 0 and idx - 1 not in seleccion_set:
                    self.queue[idx - 1], self.queue[idx] = self.queue[idx], self.queue[idx - 1]
        else:
            for idx in reversed(seleccion):
                if idx < len(self.queue) - 1 and idx + 1 not in seleccion_set:
                    self.queue[idx + 1], self.queue[idx] = self.queue[idx], self.queue[idx + 1]

        nuevos = [self.queue.index(item) for item in seleccion_items]
        if actual is not None:
            self.current_index = self.queue.index(actual)
        self.actualizar_vista_cola()
        for idx in nuevos:
            self.list_queue.selection_set(idx)
        if nuevos:
            self.list_queue.see(nuevos[0])
        self._guardar_si_corresponde()


    def limpiar_cola(self):
        if getattr(self.social, "en_jam", False):
            self.social.cola_limpiar()            # vacía la cola y para la música de todos
            return
        if self.queue:
            self._apuntar_deshacer("limpiar")
        self.detener_cancion()
        if self._queue_mode == "playlist":
            self.queue_playlist.clear()
        else:
            self.queue_normal.clear()
            self._guardar_si_corresponde()
        self.current_index = -1
        self.actualizar_vista_cola()


    # ------------------------------------------------------------------
    # Deshacer (Ctrl+Z) y arrastrar para reordenar
    # ------------------------------------------------------------------
    def _apuntar_deshacer(self, accion):
        """Guarda cómo estaba la cola antes de un cambio (máx. 20 pasos)."""
        if getattr(self.social, "en_jam", False):
            return
        pila = self.__dict__.setdefault("_pila_deshacer", [])
        actual = self.queue[self.current_index] if 0 <= self.current_index < len(self.queue) else None
        pila.append({"modo": self._queue_mode, "cola": list(self.queue), "actual": actual,
                     "indice": self.current_index, "accion": accion})
        del pila[:-20]

    def deshacer_cola(self):
        pila = self.__dict__.get("_pila_deshacer") or []
        if getattr(self.social, "en_jam", False) or not pila:
            self.status_var.set("No hay nada que deshacer en la cola.")
            return
        paso = pila.pop()
        if paso["modo"] != self._queue_mode:
            self.status_var.set("Ese cambio era de la otra cola: cámbiate a ella para deshacerlo.")
            pila.append(paso)
            return
        sonando = self.queue[self.current_index] if 0 <= self.current_index < len(self.queue) else None
        self.queue[:] = paso["cola"]                     # misma lista: queue_normal/queue_playlist siguen enlazadas
        if sonando is not None and any(t is sonando for t in self.queue):
            self.current_index = next(i for i, t in enumerate(self.queue) if t is sonando)
        elif paso["actual"] is not None and any(t is paso["actual"] for t in self.queue):
            self.current_index = next(i for i, t in enumerate(self.queue) if t is paso["actual"])
        else:
            self.current_index = min(paso["indice"], len(self.queue) - 1)
        if self._queue_mode == "playlist" and self._playlist_shuffle:
            self._playlist_shuffle_order = []
        self.actualizar_vista_cola()
        if self._queue_mode == "normal":
            self._guardar_si_corresponde()
        nombres = {"quitar": "quitar", "mover": "mover", "limpiar": "limpiar la cola", "siguiente": "poner como siguiente",
                   "mezclar": "mezclar", "arrastrar": "arrastrar"}
        self.status_var.set(f"↶ Deshecho: {nombres.get(paso['accion'], 'último cambio')}.")

    def _cola_arrastre_inicio(self, event):
        if getattr(self.social, "en_jam", False) or event.state & 0x0005:   # Shift/Ctrl: selección múltiple
            self._cola_drag = None
            return
        idx = self.list_queue.nearest(event.y)
        self._cola_drag = {"origen": idx, "y": event.y, "activo": False} if 0 <= idx < len(self.queue) else None

    def _cola_arrastre_mover(self, event):
        d = getattr(self, "_cola_drag", None)
        if not d:
            return
        if not d["activo"] and abs(event.y - d["y"]) < 6:
            return
        d["activo"] = True
        destino = max(0, min(len(self.queue) - 1, self.list_queue.nearest(event.y)))
        self.list_queue.selection_clear(0, tk.END)
        self.list_queue.selection_set(destino)
        self.list_queue.config(cursor="sb_v_double_arrow")
        return "break"

    def _cola_arrastre_fin(self, event):
        d, self._cola_drag = getattr(self, "_cola_drag", None), None
        self.list_queue.config(cursor="")
        if not d or not d["activo"]:
            return
        origen = d["origen"]
        destino = max(0, min(len(self.queue) - 1, self.list_queue.nearest(event.y)))
        if origen == destino or not (0 <= origen < len(self.queue)):
            return
        self._apuntar_deshacer("arrastrar")
        sonando = self.queue[self.current_index] if 0 <= self.current_index < len(self.queue) else None
        item = self.queue.pop(origen)
        self.queue.insert(destino, item)
        if sonando is not None:
            self.current_index = next(i for i, t in enumerate(self.queue) if t is sonando)
        if self._queue_mode == "playlist" and self._playlist_shuffle:
            self._playlist_shuffle_order = []
        self.actualizar_vista_cola()
        self.list_queue.selection_clear(0, tk.END)
        self.list_queue.selection_set(destino)
        if self._queue_mode == "normal":
            self._guardar_si_corresponde()
        self.status_var.set("↕ Canción movida (Ctrl+Z para deshacer).")
        return "break"

    def _duracion_cola_segundos(self):
        return sum(duraciones.de_pista(item) for item in self.queue)

    def _formatear_duracion_item(self, valor):
        """Formatea la duración de una canción, aceptando segundos o milisegundos."""
        return duraciones.formatear_pista(duraciones.a_segundos(valor))

    def _formatear_duracion_cola(self, segundos):
        return duraciones.formatear_total(segundos)

    def poner_seleccion_siguiente(self):
        if getattr(self.social, "en_jam", False):
            self.status_var.set("La cola compartida de una jam se gestiona entre todos los participantes.")
            return
        seleccion = list(self.list_queue.curselection())
        if not seleccion or not self.queue:
            return
        actual = self.current_index
        if 0 <= actual < len(self.queue):
            self._apuntar_deshacer("siguiente")
        if actual < 0 or actual >= len(self.queue):
            self.status_var.set("Reproduce primero una canción para poder poner otra como siguiente.")
            return
        if actual in seleccion:
            seleccion = [i for i in seleccion if i != actual]
        if not seleccion:
            return
        items = [self.queue[i] for i in seleccion]
        for idx in sorted(seleccion, reverse=True):
            del self.queue[idx]
            if idx < self.current_index:
                self.current_index -= 1
        destino = self.current_index + 1
        for offset, item in enumerate(items):
            self.queue.insert(destino + offset, item)
        self.actualizar_vista_cola()
        for idx in range(destino, destino + len(items)):
            self.list_queue.selection_set(idx)
        self.list_queue.see(destino)
        self._guardar_si_corresponde()
        self.status_var.set(f"{len(items)} canción(es) puesta(s) como siguiente(s).")

    def menu_contextual_cola(self, event):
        if getattr(self.social, "en_jam", False):
            return
        indice = self.list_queue.nearest(event.y)
        if indice < 0 or indice >= len(self.queue):
            return
        if indice not in self.list_queue.curselection():
            self.list_queue.selection_clear(0, tk.END)
            self.list_queue.selection_set(indice)
            self.list_queue.activate(indice)
        menu = tk.Menu(self.root, tearoff=0, font=("Tahoma", 8))
        menu.add_command(label="▶ Reproducir ahora", command=self.reproducir_desde_cola)
        menu.add_command(label="⏭ Poner como siguiente", command=self.poner_seleccion_siguiente)
        menu.add_separator()
        menu.add_command(label="✕ Quitar de la cola", command=self.quitar_de_cola)
        menu.add_command(label="↑ Subir", command=lambda: self.mover_seleccion_cola(-1))
        menu.add_command(label="↓ Bajar", command=lambda: self.mover_seleccion_cola(1))
        menu.add_separator()
        cancion = self.queue[indice]
        menu.add_command(label="♥ Me gusta", command=lambda: self._marcar_me_gusta_local(cancion))
        menu.add_command(label="🔗 Copiar enlace", command=lambda: self.copiar_enlace(cancion))
        menu.add_command(label="🔀 Mezclar lo que queda", command=self.mezclar_cola)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _completar_duraciones_cola(self):
        """Completa en SEGUNDO PLANO las duraciones que falten (antes se consultaba
        YouTube Music desde la interfaz y la ventana se quedaba congelada)."""
        cambios = False
        faltan = []
        for item in self.queue:
            valor = item.get("duration", item.get("duration_ms", 0)) or 0
            if self._formatear_duracion_item(valor):
                continue
            duracion = self._duracion_cancion_para_cola(item)     # sin red
            if duracion > 0:
                item["duration"] = duracion
                cambios = True
            elif item.get("videoId") and item["videoId"] not in self._duraciones_en_curso:
                faltan.append(dict(item))
        if faltan:
            for it in faltan:
                self._duraciones_en_curso.add(it["videoId"])

            def task():
                encontradas = {}
                for it in faltan[:25]:
                    try:
                        d = self._obtener_duracion_cancion(it, red=True)
                    except Exception:
                        d = 0
                    if d > 0:
                        encontradas[it["videoId"]] = d
                self.ui(self._duraciones_recibidas, encontradas)

            self.pool_img.submit(task)
        return cambios

    def _duraciones_recibidas(self, encontradas):
        if not encontradas:
            return
        for cola in (self.queue_normal, self.queue_playlist, self.queue_jam):
            for item in cola:
                d = encontradas.get(item.get("videoId"))
                if d and not item.get("duration"):
                    item["duration"] = d
        self.actualizar_vista_cola()

    def _apuntar_duracion_vlc(self, length_ms):
        """Cuando VLC conoce la duración real de la pista, se guarda si faltaba."""
        if length_ms <= 0 or not (0 <= self.current_index < len(self.queue)):
            return
        item = self.queue[self.current_index]
        if not self._formatear_duracion_item(item.get("duration", 0)):
            item["duration"] = int(length_ms / 1000)
            self.actualizar_vista_cola()

    def actualizar_vista_cola(self):
        if not hasattr(self, "list_queue"):
            return
        cambios_duracion = self._completar_duraciones_cola()
        lista = self.list_queue
        cambio_pista = getattr(self, "_cola_vista_indice", None) != (self._queue_mode, self.current_index)
        self._cola_vista_indice = (self._queue_mode, self.current_index)
        vista = lista.yview()
        seleccion = lista.curselection()
        lista.delete(0, tk.END)
        for i, item in enumerate(self.queue):
            prefix = "▶ " if i == self.current_index else "  "
            marca = "  ✨" if item.get('auto') else ""
            duracion = self._formatear_duracion_item(item.get('duration', item.get('duration_ms', 0)))
            texto_duracion = f"  [{duracion}]" if duracion else ""
            lista.insert(tk.END, f"{prefix}{i + 1}. {item['title']} — {item['artist']}{texto_duracion}{marca}")
        if 0 <= self.current_index < len(self.queue):
            lista.itemconfig(self.current_index, background=self.c("#DCE6F7"),
                             foreground=self.c("#0A246A", "fg"))
        # conserva el scroll y la selección (antes saltaba arriba con cada cambio)
        for i in seleccion:
            if i < lista.size():
                lista.selection_set(i)
        lista.yview_moveto(vista[0])
        if cambio_pista and 0 <= self.current_index < lista.size():
            lista.see(self.current_index)
        if hasattr(self, "queue_box"):
            nombre = {"normal": "Cola de reproducción", "playlist": "Cola de playlist",
                      "jam": "Cola compartida (jam)"}.get(self._queue_mode, "Cola")
            self.queue_box.config(text=f" {nombre} ")
        if hasattr(self, "queue_summary_var"):
            cantidad = len(self.queue)
            duracion = self._formatear_duracion_cola(self._duracion_cola_segundos())
            self.queue_summary_var.set(f"{cantidad} canción(es)  •  Duración total: {duracion}")
        if cambios_duracion and self._queue_mode == "normal":
            self._guardar_si_corresponde()


