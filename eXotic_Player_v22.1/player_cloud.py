"""Persistencia local/nube y sesión del reproductor."""
import json
import os
import tkinter as tk
from datetime import datetime

from player_data import LEGACY_DATA_FILE, cargar_datos_local, datos_vacios, guardar_datos_local, ruta_datos_usuario


class PlayerCloudMixin:
    def _actualizar_boton_auth(self):
        if self.sesion_iniciada:
            etiqueta = (self.email_cuenta or "Mi cuenta")[:26]
            self.auth_btn.config(text=f"🟢 {etiqueta}", bg=self.c("#2E8B57"))
        else:
            self.auth_btn.config(text="🔑 Iniciar sesión", bg=self.c("#316AC5"))


    def _marcar_sync(self, estado, mensaje):
        self._sync_status = estado
        self._sync_message = mensaje
        self._actualizar_configuracion_ui()

    def _sync_exito(self, mensaje="Sincronizado"):
        self._sync_status = "ok"
        self._sync_message = mensaje
        self._last_sync_at = datetime.now()
        self._actualizar_configuracion_ui()

    def _restaurar_sesion_async(self, intento=0):
        if not self.cloud.disponible:
            self.status_var.set("Supabase no configurado: modo local.")
            return

        def task():
            if self.cloud.restaurar_sesion():
                self.ui(self._sesion_activa)
            elif getattr(self.cloud, "ultimo_fallo_red", False) and intento < 20:
                # Sin conexión: la sesión NO se borra; se reintenta en un rato
                espera = min(300, 15 * (intento + 1))
                self.ui(self.status_var.set,
                        f"Sin conexión con tu cuenta: reintento en {espera} s (puedes seguir escuchando).")
                self.ui(self.root.after, espera * 1000, lambda: self._restaurar_sesion_async(intento + 1))

        self.pool_stream.submit(task)


    def _sesion_activa(self):
        self.sesion_iniciada = True
        self.email_cuenta = self.cloud.email
        uid = self.cloud.user_id

        archivo = ruta_datos_usuario(uid)
        if not os.path.exists(archivo) and os.path.exists(LEGACY_DATA_FILE):
            try:
                os.replace(LEGACY_DATA_FILE, archivo)
            except OSError as e:
                print(f"No se pudo migrar el archivo antiguo: {e}")
        self._cambiar_datos(cargar_datos_local(archivo), archivo)

        self.auth_btn.config(state=tk.NORMAL)
        self._actualizar_boton_auth()
        self.sonar("conectar")
        self.status_var.set(f"Sesión iniciada como {self.email_cuenta}.")
        self.lcd_title.config(text=f"*** {self.email_cuenta} ***")
        self._cargar_datos_cloud_async()
        self.social.al_iniciar_sesion()


    def _cargar_datos_cloud_async(self):
        if not self.cloud.logged_in:
            return
        uid = self.cloud.user_id
        self._marcar_sync("working", "Descargando datos de la nube...")

        def task():
            try:
                data = self.cloud.descargar_datos()
                self.ui(self._aplicar_datos_cloud, data, uid)
            except Exception as e:
                print(f"Error descargando datos: {e}")
                self.ui(self._marcar_sync, "error", "No se pudo descargar la nube")
                self.ui(self.status_var.set, "Sesión iniciada, pero no se pudieron sincronizar tus datos.")

        self.pool_stream.submit(task)


    def cerrar_sesion(self):
        self.social.al_cerrar_sesion()
        self._sincronizar_cola_en_datos()
        try:
            self._guardar_local()
        except Exception as e:
            print(e)
        data = json.loads(json.dumps(self.cloud_data, ensure_ascii=False))
        uid = self.cloud.user_id
        self.auth_btn.config(state=tk.DISABLED)

        def task():
            try:
                self.cloud.subir_datos(data, uid)
            except Exception as e:
                print(f"Error subiendo antes de salir: {e}")
            self.cloud.logout()
            self.ui(self._sesion_cerrada)

        self.pool_cloud.submit(task)


    def _sesion_cerrada(self):
        self.sesion_iniciada = False
        self.email_cuenta = None
        guest = LEGACY_DATA_FILE
        self._cambiar_datos(cargar_datos_local(guest) if os.path.exists(guest) else datos_vacios(), guest)
        self.auth_btn.config(state=tk.NORMAL)
        self._actualizar_boton_auth()
        self.lcd_title.config(text="*** Sesión cerrada (Modo Invitado) ***")
        self.status_var.set("Sesión cerrada. Tus playlists siguen guardadas en tu cuenta.")


    def _asegurar_playlist_principal(self):
        playlists = self.cloud_data.setdefault("playlists", [])
        if not any(p.get("id") == "default" or p.get("name") == "Mi música" for p in playlists):
            playlists.insert(0, {"id": "default", "name": "Mi música", "tracks": []})
        self._actualizar_selector_playlists()


    def _guardar_local(self):
        if not self._local_file:
            return
        guardar_datos_local(self.cloud_data, self._local_file)


    def _cambiar_datos(self, nuevos, archivo_local):
        self._sincronizar_cola_en_datos()
        try:
            self._guardar_local()
        except Exception as e:
            print(f"No se pudieron guardar los datos locales: {e}")

        self.detener_cancion()
        self.cloud_data = nuevos
        self._local_file = archivo_local

        self._search_token += 1
        for w in self.scroll_frame.winfo_children():
            w.destroy()

        self._reconstruir_playlist_guardada()
        self._refrescar_escuchado_reciente_ui()
        self._refrescar_favoritos_ui()
        self.actualizar_estadisticas_ui()
        self.playlist_var.set("Mi música")
        self._asegurar_playlist_principal()
        self._aplicar_ajustes()
        self._preparar_reanudar()


    def _aplicar_datos_cloud(self, data, uid):
        if uid != self.cloud.user_id:
            return

        if data is not None:
            cola_actual = [t for t in (self._normalizar_track(x) for x in self.queue_normal) if t]
            nuevo = datos_vacios()
            nuevo.update(data)
            if not isinstance(nuevo.get("settings"), dict):
                nuevo["settings"] = {}
            if cola_actual:
                nuevo["queue"] = cola_actual
            self.cloud_data = nuevo
            if not self.queue_normal:
                self._reconstruir_playlist_guardada()

        self._asegurar_playlist_principal()
        self._refrescar_escuchado_reciente_ui()
        self._refrescar_favoritos_ui()
        self.actualizar_estadisticas_ui()
        self._aplicar_ajustes()
        try:
            self._guardar_local()
        except Exception as e:
            print(f"No se pudo guardar copia local: {e}")

        if data is None:
            self._subir_cloud_data_async("☁️ Cuenta lista: datos guardados en la nube.")
        else:
            self._sync_exito("Datos descargados")
            self.status_var.set(f"Datos cargados: {len(self.cloud_data.get('playlists', []))} playlists.")


    def _subir_cloud_data_async(self, mensaje_ok="☁️ Datos guardados en tu cuenta."):
        """Guarda ya (local + nube). Para acciones explícitas del usuario."""
        self._cancelar_subida_pendiente()
        self._sincronizar_cola_en_datos()
        self.cloud_data["version"] = 2
        try:
            self._guardar_local()
        except Exception as e:
            print(f"Error guardando datos locales: {e}")
            self.status_var.set(f"No se pudo guardar en este ordenador: {e}")
            return
        if not self.cloud.logged_in:
            self._marcar_sync("local", "Guardado en este ordenador (modo invitado)")
            self.status_var.set("Guardado en este ordenador. Inicia sesión para tenerlo en la nube.")
            return
        self._marcar_sync("working", "Guardando cambios en la nube...")
        data = json.loads(json.dumps(self.cloud_data, ensure_ascii=False))
        uid = self.cloud.user_id

        def task():
            try:
                self.cloud.subir_datos(data, uid)
                self.ui(self._sync_exito, "Datos guardados")
                if mensaje_ok:
                    self.ui(self.status_var.set, mensaje_ok)
            except Exception as e:
                print(f"Error subiendo datos: {e}")
                self.ui(self._marcar_sync, "error", "Falló la subida a la nube")
                self.ui(self.status_var.set, "Guardado en este ordenador, pero falló la subida a la nube.")

        self.pool_cloud.submit(task)

    def _guardar_datos_cloud_async(self):
        """Botón "Sincronizar ahora"."""
        self._subir_cloud_data_async("☁️ Guardado en tu cuenta.")

    def _cancelar_subida_pendiente(self):
        job = getattr(self, "_subida_job", None)
        self._subida_job = None
        if job is not None:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass

    def _guardar_si_corresponde(self):
        """Cambios automáticos (historial, cola, ajustes): se guarda en local al momento y a
        la nube agrupando los cambios de los próximos segundos en UNA sola subida.
        Antes se subía todo a Supabase con cada canción reproducida."""
        self._sincronizar_cola_en_datos()
        try:
            self._guardar_local()
        except Exception as e:
            print(f"Error guardando datos locales: {e}")
        if not self.cloud.logged_in:
            self._marcar_sync("local", "Guardado en este ordenador (modo invitado)")
            return
        self._cancelar_subida_pendiente()
        self._subida_job = self.root.after(4000, lambda: self._subir_cloud_data_async(None))
