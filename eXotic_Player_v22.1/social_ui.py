"""Amigos y Jam para eXoticPlayer: ventana Tk + sincronización de la reproducción.

Modelo de jam ("escucha sincronizada con control compartido"): cada persona reproduce la canción
en su propio VLC y TODOS los miembros aceptados controlan la jam por igual.
- El estado compartido (cola, canción actual, play/pausa, posición) vive en Supabase (jams.state)
  y lleva un número de revisión ("rev").
- La COLA se modifica con operaciones atómicas del servidor (añadir / quitar / limpiar, ver
  social_schema_4.sql): cualquier miembro puede hacerlo y dos personas que añaden a la vez no se
  pisan. Las canciones llevan un "uid" para poder quitar una concreta. Las publicaciones de
  reproducción (play/pausa/siguiente/posición) NO mandan la cola: el servidor conserva la suya.
- Cada cliente compara lo que hace su reproductor con el último estado compartido que conoce.
  Si el usuario cambia algo (añade una canción, pausa, salta, mueve la barra...), lo publica
  partiendo de esa revisión. Si alguien se adelantó, el servidor lo rechaza y el cliente adopta
  el estado nuevo (gana el primero que llega).
- Cada segundo se consulta la jam: si la revisión cambió, se adopta el estado nuevo; si no, solo se
  corrige el desvío de la posición.
- Jam privada: quien entra queda 'pending' hasta que el anfitrión lo acepta. Pública: entra directo.
  El anfitrión además puede aceptar/rechazar/expulsar y terminar la jam.

Reglas de hilos (las mismas que el resto de la app): la red va en self.pool, Tk solo se toca
desde el hilo principal (app.ui(...)).
"""
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import ttk, messagebox

import vlc  # ya cargado por exotic_player: app_paths.preparar_entorno() se llama antes

from social_supabase import USERNAME_RE, JamPerdida, SocialError, err_msg
from social_extra import SocialDialogExtrasMixin, SocialExtrasMixin
from jam_logic import (
    SEEK_PENDIENTE_MAX_S,
    TICK_MS,
    clasificar_revision,
    crear_objetivo,
    destino,
    hay_cambio,
    necesita_seek,
    seek_pendiente_activo,
    tick_acciones,
)

REINTENTO_PUBLICAR_S = 3.0    # tras un fallo de red, espera antes de volver a publicar
DESVIO_PLAY_MS = 2500         # a partir de este desvío se hace seek para volver a sincronizar
DESVIO_PAUSA_MS = 1000
MAX_INTENTOS_CARGA = 3
MAX_COLA_JAM = 300            # mismo límite que el servidor (social_schema_4.sql)

_ESTADOS_SONANDO = (vlc.State.Playing, vlc.State.Opening, vlc.State.Buffering)
_ESTADOS_MUERTO = (vlc.State.Stopped, vlc.State.Error, vlc.State.NothingSpecial)


# ======================================================================
# Lógica: sesión social + jam
# ======================================================================
class SocialManager(SocialExtrasMixin):
    def __init__(self, app):
        self.app = app
        self.pool = ThreadPoolExecutor(max_workers=1)   # toda la red social, en orden
        self.dialog = None
        self.perfil = None          # {'id', 'username', 'tag', 'nombre'} o None si aún no lo ha creado
        self.pendientes = 0         # solicitudes de amistad recibidas
        self._tick_job = None
        self._reset_jam()

    def _reset_jam(self):
        self.jam_id = None
        self.jam_rol = None         # None | 'pending' | 'guest' | 'host'
        self.jam_nombre = ""
        self.jam_anfitrion = ""
        self.jam_publica = False
        self.solicitudes_jam = 0    # solicitudes de entrada pendientes (solo las ve el anfitrión)
        self.sonando_txt = ""
        self._backup = None         # (modo de cola, índice, autoplay) del usuario, se restaura al salir
        self._repoll = False        # hay que volver a consultar en cuanto acabe la consulta en curso
        self._rev = -1              # última revisión del estado compartido que conocemos
        self._objetivo = None       # último estado compartido conocido (ver _crear_objetivo)
        self._publicando = False
        self._no_publicar_hasta = 0.0
        self._poll_en_curso = False
        self._fallos = 0
        self._aplicando = False     # True mientras la propia jam mueve el reproductor
        self._vid_cargado = None    # videoId que el reproductor tiene cargado o cargando
        self._parada = False        # el usuario pulsó Stop
        self._seek_usuario = False  # el usuario movió la barra de tiempo
        self._seek_pendiente = False
        self._seek_pendiente_t = 0.0
        self._ultimo_seek = 0.0
        self._intentos = (None, 0)
        self._n = 0
        self._reset_extras()            # chat, votos (v22)

    @property
    def en_jam(self):
        """Miembro aceptado (anfitrión o invitado): tiene control de la jam."""
        return self.jam_rol in ("host", "guest")

    # ------------------------------------------------------------ utilidades
    def run(self, fn, ok=None, err=None):
        """Ejecuta fn() en el hilo de red y entrega el resultado en el hilo de Tk."""
        def task():
            try:
                res = fn()
            except Exception as e:
                self.app.ui(err or self._error, err_msg(e) if err is None else e)
                return
            if ok:
                self.app.ui(ok, res)
        try:
            self.pool.submit(task)
        except RuntimeError:
            pass  # la app se está cerrando

    def _dialogo(self):
        d = self.dialog
        return d if d is not None and d.vivo() else None

    def _error(self, msg):
        self.app.status_var.set(f"Amigos/Jam: {msg}")
        d = self._dialogo()
        if d:
            d.estado(msg, error=True)

    def _actualizar_boton(self):
        b = getattr(self.app, "social_btn", None)
        if b is None:
            return
        if self.jam_rol == "host":
            txt = "🎧 Jam (anfitrión)"
            if self.solicitudes_jam:
                txt += f" · {self.solicitudes_jam} 🔔"
            bg = "#C0392B" if self.solicitudes_jam else "#B5651D"
        elif self.jam_rol == "guest":
            txt, bg = "🎧 En una jam", "#B5651D"
        elif self.jam_rol == "pending":
            txt, bg = "⏳ Esperando entrar", "#8A6D3B"
        elif self.pendientes:
            txt, bg = f"👥 Amigos ({self.pendientes})", "#C0392B"
        else:
            txt, bg = "👥 Amigos y Jam", "#7B4FA3"
        b.config(text=txt, bg=self.app.c(bg))

    def _txt(self, s):
        self.sonando_txt = s
        d = self._dialogo()
        if d:
            d.pintar_sonando()

    def _refrescar_dialogo(self):
        d = self._dialogo()
        if d:
            d.refrescar_todo()

    # ------------------------------------------------------------ ganchos de la app
    def abrir(self):
        if not self.app.sesion_iniciada:
            messagebox.showinfo("Amigos y Jam", "Inicia sesión para usar amigos y jams.")
            return
        d = self._dialogo()
        if d:
            d.lift()
            return
        self.dialog = SocialDialog(self)

    def al_iniciar_sesion(self):
        self.perfil = None
        self.pendientes = 0
        self._actualizar_boton()

        def fn():
            perfil = self.app.cloud.mi_perfil()
            pend = len(self.app.cloud.listar_amistades()["recibidas"]) if perfil else 0
            return perfil, pend

        def ok(res):
            self.perfil, self.pendientes = res
            if self.perfil:
                self.refrescar_compartidas()     # para el menú 📁 de las canciones
            if self.pendientes:
                self.app.sonar("aviso")          # tienes solicitudes de amistad esperando
            self._actualizar_boton()

        self.run(fn, ok)

    def al_cerrar_sesion(self):
        """Se llama ANTES de hacer logout: sale de la jam y restaura la cola del usuario."""
        if self.jam_rol:
            self.salir_jam(sincrono=True)
        d = self._dialogo()
        if d:
            d.cerrar()
        self.perfil = None
        self.pendientes = 0
        self._actualizar_boton()

    def al_cerrar_app(self):
        try:
            if self.jam_rol:
                self.salir_jam(sincrono=True)
        except Exception as e:
            print(f"Jam: error al cerrar: {e}")
        try:                                    # "ya no estoy escuchando nada"
            if self.app.cloud.logged_in and self.perfil and self.app.prefs.get("share_activity", True):
                self.app.cloud.actividad_publicar(None)
        except Exception:
            pass
        self.pool.shutdown(wait=False, cancel_futures=True)

    # Estos tres los llama el reproductor (exotic_player.py) para que la jam sepa qué hace el usuario
    def al_cargar(self, video_id):
        """cargar_y_reproducir_actual(): hay una canción cargándose (por el usuario o por la jam)."""
        self._vid_cargado = video_id
        self._parada = False

    def al_detener(self):
        """detener_cancion(): Stop del usuario, o parada interna."""
        self._vid_cargado = None
        if not self._aplicando:
            self._parada = True

    def al_seek(self):
        """El usuario soltó la barra de tiempo."""
        if self.en_jam:
            self._seek_usuario = True

    # ------------------------------------------------------------ crear / unirse / salir
    def crear_jam(self, nombre, publica=False):
        if self.jam_rol or not self.perfil:
            return
        a = self.app
        nombre = (nombre or "").strip() or f"Jam de {self.perfil['username']}"
        t = time.monotonic()
        if len(a.queue) > MAX_COLA_JAM:
            a.status_var.set(f"Tu cola tiene más de {MAX_COLA_JAM} canciones: quita algunas antes de crear la jam.")
            return
        # La jam arranca con lo que el anfitrión tiene ahora en la cola
        payload = self._payload_local(None, con_cola=True)
        self.run(lambda: a.cloud.jam_crear(nombre, publica, payload),
                 lambda res: self._jam_creada(res, nombre, bool(publica), payload, t))

    def _jam_creada(self, res, nombre, publica, payload, t):
        a = self.app
        if self.jam_rol or not a.sesion_iniciada:
            return
        self._reset_jam()
        self.jam_id, self.jam_rol = res["id"], "host"
        self.jam_nombre, self.jam_publica = nombre, publica
        self._rev = int(res.get("rev", 1))
        # El servidor devuelve el estado con los uid de cada canción (hacen falta para quitarlas)
        st = res.get("state") if isinstance(res.get("state"), dict) else payload
        self._objetivo = self._crear_objetivo(st, 0.0, t)
        # El anfitrión sigue con su música: la jam empieza con su cola actual, en una cola
        # aparte (su cola personal no se toca y se recupera al terminar la jam)
        self._entrar_modo_jam(self._objetivo["queue"], self._objetivo["index"], detener=False)
        vid = self._objetivo["vid"]
        if vid and a.player.get_state() in _ESTADOS_SONANDO + (vlc.State.Paused,):
            self._vid_cargado = vid
        a.status_var.set(
            f"🎧 Jam '{nombre}' creada ({'pública' if publica else 'privada: aceptarás tú a quien entre'})."
        )
        self._iniciar_tick()
        self._actualizar_boton()
        self._refrescar_dialogo()

    def unirse(self, j):
        """j = fila de jams_activas()."""
        if self.jam_rol:
            return
        jam_id, nombre, anfitrion = j["id"], j["name"], j["host_username"]
        publica = bool(j.get("is_public"))
        self.run(lambda: self.app.cloud.jam_unirse(jam_id),
                 lambda st: self._union_resuelta(st, jam_id, nombre, anfitrion, publica))

    def _union_resuelta(self, estado, jam_id, nombre, anfitrion, publica):
        if self.jam_rol or not self.app.sesion_iniciada:
            return
        if estado == "accepted":
            self._unido(jam_id, nombre, anfitrion, publica)
            return
        # Jam privada: hay que esperar a que el anfitrión acepte
        self._reset_jam()
        self.jam_id, self.jam_rol = jam_id, "pending"
        self.jam_nombre, self.jam_anfitrion, self.jam_publica = nombre, anfitrion, publica
        self.app.status_var.set(f"⏳ Solicitud enviada: {anfitrion} tiene que aceptarte en «{nombre}».")
        self._iniciar_tick()
        self._actualizar_boton()
        self._poll()
        self._refrescar_dialogo()

    def _aceptado(self):
        self._unido(self.jam_id, self.jam_nombre, self.jam_anfitrion, self.jam_publica,
                    aviso=f"✅ {self.jam_anfitrion} te ha aceptado en «{self.jam_nombre}».")

    def _unido(self, jam_id, nombre, anfitrion, publica, aviso=None):
        a = self.app
        if self.jam_rol not in (None, "pending") or not a.sesion_iniciada:
            return
        self._parar_tick()
        self._reset_jam()
        # Durante la jam solo suena la cola compartida; la cola personal queda intacta
        self._entrar_modo_jam([], -1, detener=True)
        self.jam_id, self.jam_rol = jam_id, "guest"
        self.jam_nombre, self.jam_anfitrion, self.jam_publica = nombre, anfitrion, publica
        self._txt("Sincronizando con la jam…")
        a.status_var.set(aviso or f"🎧 Te has unido a la jam de {anfitrion}.")
        a.sonar("amigo")
        self._iniciar_tick()
        self._actualizar_boton()
        self._poll()
        self._refrescar_dialogo()

    def salir_jam(self, sincrono=False, aviso=None):
        if not self.jam_rol:
            return
        rol, jam_id = self.jam_rol, self.jam_id
        self._parar_tick()
        cloud = self.app.cloud

        def remoto():
            try:
                if rol == "host":
                    cloud.jam_terminar(jam_id)
                else:
                    cloud.jam_salir(jam_id)   # también cancela una solicitud pendiente
            except Exception as e:
                print(f"Jam: no se pudo cerrar en la nube: {e}")

        if sincrono:
            remoto()
        else:
            try:
                self.pool.submit(remoto)
            except RuntimeError:
                remoto()
        if self._backup is not None:
            self._restaurar_local()
        self._reset_jam()
        self.app.status_var.set(
            aviso or ("Jam terminada." if rol == "host"
                      else "Solicitud cancelada." if rol == "pending" else "Has salido de la jam.")
        )
        self._actualizar_boton()
        self._refrescar_dialogo()

    def _entrar_modo_jam(self, cola, indice, detener):
        """Pasa el reproductor a la cola de la jam (lista propia, aparte de las personales)."""
        a = self.app
        self._backup = (a._queue_mode, a.current_index, a.autoplay_var.get())
        if detener:
            self._aplicando = True
            try:
                a.detener_cancion()
            finally:
                self._aplicando = False
        a.autoplay_var.set(False)   # las recomendaciones automáticas las pondría cada cliente por su cuenta
        a.queue_jam[:] = [dict(x) for x in cola]
        a._activar_cola("jam", refrescar=False)
        a.current_index = indice if 0 <= indice < len(a.queue_jam) else -1
        a.actualizar_vista_cola()

    def _poner_cola(self, cola):
        """Sustituye el CONTENIDO de la cola de la jam sin cambiar de lista (nunca se reasigna
        a.queue: así el alias con la cola activa no se rompe)."""
        a = self.app
        if a.queue is not a.queue_jam:
            a._activar_cola("jam", refrescar=False)
        a.queue_jam[:] = [dict(x) for x in cola]

    def _restaurar_local(self):
        """Al salir de la jam: vuelve la cola personal tal y como estaba."""
        if self._backup is None:
            return
        a = self.app
        modo, idx, autoplay = self._backup
        self._backup = None
        self._aplicando = True
        try:
            a.detener_cancion()
        finally:
            self._aplicando = False
        a.queue_jam.clear()
        a._activar_cola(modo if modo in ("normal", "playlist") else "normal", refrescar=False)
        a.current_index = idx if 0 <= idx < len(a.queue) else -1
        a.autoplay_var.set(autoplay)
        a.actualizar_vista_cola()

    # ------------------------------------------------------------ cola compartida (cualquier miembro)
    def _op_cola(self, fn, aviso):
        """Ejecuta una operación de cola en el servidor y trae el estado nuevo enseguida."""
        if not self.en_jam:
            return False
        jam_id = self.jam_id
        self.app.status_var.set(aviso)

        def ok(_res):
            if jam_id != self.jam_id or not self.en_jam:
                return
            if self._poll_en_curso:
                self._repoll = True      # la consulta en curso pudo empezar antes del cambio
            else:
                self._poll()

        def err(e):
            if jam_id != self.jam_id:
                return
            if isinstance(e, JamPerdida):
                self.salir_jam(aviso="La jam terminó o ya no formas parte de ella.")
            else:
                self._error(err_msg(e))

        self.run(lambda: fn(jam_id), ok, err)
        return True

    def cola_agregar(self, items, reproducir=False):
        """Añade canciones a la cola compartida (y, si reproducir, empieza por la primera)."""
        locales = [x for x in items if str(x.get("videoId", "")).startswith("file:")]
        if locales:
            items = [x for x in items if x not in locales]
            self.app.status_var.set("Las canciones de tu ordenador no se pueden poner en una jam "
                                    "(los demás no tienen el archivo).")
            if not items:
                return False
        if len(self.app.queue) + len(items) > MAX_COLA_JAM:
            self.app.status_var.set(f"La cola de la jam admite como máximo {MAX_COLA_JAM} canciones.")
            return False
        cloud = self.app.cloud
        n = len(items)
        txt = (f"Añadiendo «{items[0].get('title', '')}» a la jam…" if n == 1
               else f"Añadiendo {n} canciones a la jam…")
        return self._op_cola(lambda j: cloud.jam_cola_agregar(j, items, reproducir), txt)

    def cola_quitar(self, uid_cancion):
        cloud = self.app.cloud
        return self._op_cola(lambda j: cloud.jam_cola_quitar(j, uid_cancion), "Quitando de la jam…")

    def cola_limpiar(self):
        cloud = self.app.cloud
        return self._op_cola(lambda j: cloud.jam_cola_limpiar(j), "Vaciando la cola de la jam…")

    def resincronizar(self):
        """Descarta lo que haya pendiente y vuelve a adoptar el estado de la jam."""
        if not self.en_jam:
            return
        self._rev = -1
        self._intentos = (None, 0)
        self._ultimo_seek = 0.0
        self._seek_usuario = False
        self._poll()

    # ------------------------------------------------------------ bucle
    def _iniciar_tick(self):
        self._parar_tick()
        self._n = 0
        self._tick_job = self.app.root.after(TICK_MS, self._tick)

    def _parar_tick(self):
        if self._tick_job is not None:
            try:
                self.app.root.after_cancel(self._tick_job)
            except Exception:
                pass
            self._tick_job = None

    def _tick(self):
        self._tick_job = None
        if not self.jam_rol:
            return
        self._n += 1
        try:
            if self.jam_rol == "pending":
                if tick_acciones(self._n, "pending")["poll"]:
                    self._poll()
            else:
                self._tick_miembro()
        except Exception as e:
            print(f"Jam: error en el bucle: {e}")
        if self.jam_rol:
            self._tick_job = self.app.root.after(TICK_MS, self._tick)

    def _tick_miembro(self):
        a = self.app
        o = self._objetivo
        if o is not None:
            if self._vid_cargado == o["vid"] and a.player.get_state() == vlc.State.Playing:
                self._intentos = (o["vid"], 0)
            if self._seek_pendiente_activo():
                self._resolver_seek_pendiente(o)
            self._revisar_local()
        acciones = tick_acciones(self._n, self.jam_rol)
        if acciones["poll"]:
            self._poll()
        if acciones["heartbeat"]:
            self._latido()
        if acciones["requests"]:
            self.revisar_solicitudes()
        if self._n % 2 == 0:
            self._poll_mensajes()               # chat, reacciones y votos (v22)
        if self.jam_rol == "guest" and self._n % 40 == 1:
            jam_id = self.jam_id

            def contar(miembros):
                if jam_id == self.jam_id:
                    self._n_miembros = max(1, sum(1 for m in miembros if m.get("status") == "accepted"))
            self.run(lambda: self.app.cloud.jam_miembros(jam_id), contar, err=lambda e: None)

    def _latido(self):
        jam_id = self.jam_id

        def task():
            try:
                self.app.cloud.jam_latido(jam_id)
            except Exception as e:
                print(f"Jam: latido fallido: {e}")

        try:
            self.pool.submit(task)
        except RuntimeError:
            pass

    def revisar_solicitudes(self):
        """Anfitrión: cuenta las solicitudes de entrada pendientes (y avisa si llegó alguna)."""
        jam_id = self.jam_id

        def ok(miembros):
            if jam_id != self.jam_id or self.jam_rol != "host":
                return
            n = sum(1 for m in miembros if m["status"] == "pending")
            self._n_miembros = max(1, sum(1 for m in miembros if m["status"] == "accepted"))
            if n > self.solicitudes_jam:
                self.app.status_var.set("🔔 Alguien quiere entrar en tu jam.")
            if n != self.solicitudes_jam:
                self.solicitudes_jam = n
                self._actualizar_boton()
            d = self._dialogo()
            if d:
                d.pintar_miembros(miembros)

        self.run(lambda: self.app.cloud.jam_miembros(jam_id), ok, err=lambda e: None)

    # ------------------------------------------------------------ estado local <-> compartido
    @staticmethod
    def _crear_objetivo(st, age, t):
        return crear_objetivo(st, age, t)

    @staticmethod
    def _destino(o):
        return destino(o)

    def _cola_local(self):
        return [
            {"title": t.get("title", ""), "artist": t.get("artist", ""),
             "videoId": t["videoId"], "coverUrl": t.get("coverUrl"), "uid": t.get("uid")}
            for t in self.app.queue
        ]

    def _playing_local(self):
        """True/False según lo que hace el reproductor; None si no se sabe (cargando un
        error, canción que acaba de terminar...): en ese caso no se toca el estado compartido."""
        a = self.app
        if a._cargando:
            return True
        st = a.player.get_state()
        if st in _ESTADOS_SONANDO:
            return True
        if st == vlc.State.Paused or self._parada:
            return False
        return None

    def _seek_pendiente_activo(self):
        return seek_pendiente_activo(self._seek_pendiente, self._seek_pendiente_t,
                                     max_s=SEEK_PENDIENTE_MAX_S)

    def _hay_cambio(self):
        """¿El usuario ha hecho algo en local que aún no está en el estado compartido?"""
        o = self._objetivo
        if o is None:
            return False
        a = self.app
        p = self._playing_local()
        return hay_cambio(
            a.current_index, o["index"], self._seek_usuario,
            a._cargando, self._seek_pendiente_activo(), p, o["playing"]
        )

    def _payload_local(self, o, con_cola=False):
        """Estado local listo para publicar. o = estado compartido actual (None al crear la jam).
        Solo al crear la jam se manda la cola; después el servidor conserva la suya."""
        a = self.app
        n = len(a.queue)
        idx = a.current_index if 0 <= a.current_index < n else -1
        vid = a.queue[idx]["videoId"] if idx >= 0 else None
        p = self._playing_local()
        playing = (o["playing"] if o else False) if p is None else p
        st = a.player.get_state()
        if idx < 0:
            pos, playing = 0, False
        elif vid == self._vid_cargado and not a._cargando and st in (vlc.State.Playing, vlc.State.Paused):
            pos = max(0, a.player.get_time())
        elif o is not None and idx == o["index"] and vid == o["vid"] and not self._seek_usuario:
            pos = self._destino(o)      # no hemos tocado la posición: se conserva la de la jam
        else:
            pos = 0
        out = {"index": idx, "playing": bool(playing), "position_ms": int(pos)}
        if con_cola:
            out["queue"] = self._cola_local()
        return out

    def _revisar_local(self):
        if (self._publicando or self._aplicando or self._objetivo is None
                or time.monotonic() < self._no_publicar_hasta):
            return
        if not self._hay_cambio():
            return
        self._publicar_local()

    def _publicar_local(self):
        ahora = time.monotonic()
        payload = self._payload_local(self._objetivo)
        base, jam_id = self._rev, self.jam_id
        self._publicando = True
        self._seek_usuario = False

        def task():
            try:
                res = self.app.cloud.jam_publicar(jam_id, payload, base)
                self.app.ui(self._publicado, jam_id, payload, ahora, res, None)
            except Exception as e:
                self.app.ui(self._publicado, jam_id, payload, ahora, None, e)

        try:
            self.pool.submit(task)
        except RuntimeError:
            self._publicando = False

    def _publicado(self, jam_id, payload, t, res, error):
        self._publicando = False
        if jam_id != self.jam_id or not self.en_jam:
            return
        if error is not None:
            if isinstance(error, JamPerdida):
                self.salir_jam(aviso="La jam terminó o ya no formas parte de ella.")
            elif isinstance(error, SocialError):
                # Rechazo definitivo del servidor: reintentar no serviría, se vuelve al estado compartido
                self.app.status_var.set(f"Jam: {error}")
                self.resincronizar()
            else:
                print(f"Jam: no se pudo publicar el cambio: {error}")
                self._no_publicar_hasta = time.monotonic() + REINTENTO_PUBLICAR_S  # se reintenta solo
            return
        if res.get("ok"):
            self._rev = int(res["rev"])
            # El servidor conservó su cola (rev igual a la base): el nuevo objetivo la reutiliza
            st = dict(payload)
            st["queue"] = self._objetivo["queue"] if self._objetivo else []
            st["by"] = (self.perfil or {}).get("username")
            self._objetivo = self._crear_objetivo(st, 0.0, t)
        else:
            # Otra persona cambió la jam a la vez y ganó: se trae su estado y se adopta
            self._poll()

    # ------------------------------------------------------------ recibir el estado compartido
    def _poll(self):
        if self._poll_en_curso or not self.jam_rol:
            return
        self._poll_en_curso = True
        jam_id, rev = self.jam_id, self._rev

        def task():
            try:
                est = self.app.cloud.jam_estado(jam_id, rev)
                self.app.ui(self._estado_recibido, jam_id, est, time.monotonic(), None)
            except Exception as e:
                self.app.ui(self._estado_recibido, jam_id, None, time.monotonic(), err_msg(e))

        try:
            self.pool.submit(task)
        except RuntimeError:
            self._poll_en_curso = False

    def _estado_recibido(self, jam_id, est, t_recv, error):
        self._poll_en_curso = False
        try:
            self._procesar_estado(jam_id, est, t_recv, error)
        finally:
            if self._repoll:
                self._repoll = False
                if self.jam_rol:
                    self._poll()

    def _procesar_estado(self, jam_id, est, t_recv, error):
        if jam_id != self.jam_id or not self.jam_rol:
            return
        if error:
            self._fallos += 1
            if self._fallos >= 5 and self.jam_rol != "pending":
                self._txt("⚠ Sin conexión con la jam…")
            return
        self._fallos = 0
        if not est:
            self.salir_jam(aviso="La jam terminó o te han sacado de ella.")
            return
        if self.jam_rol == "pending":
            if est.get("mi_estado") == "accepted":
                self._aceptado()
            return
        if est.get("mi_estado") != "accepted":
            return
        rev = int(est.get("rev") or 0)
        st = est.get("state")
        age = float(est.get("age_ms") or 0)
        decision = clasificar_revision(self._rev, rev, st is not None)
        if decision == "stale":
            return                       # respuesta vieja (ya conocemos una revisión más nueva)
        if decision == "new":
            self._adoptar(st, rev, age, t_recv)
            return
        # Sin cambios en el estado: solo se refresca el reloj para corregir el desvío
        o = self._objetivo
        if o is None:
            return
        o["age"], o["t"] = age, t_recv
        if not self._hay_cambio():
            self._sincronizar(False)

    def _adoptar(self, st, rev, age, t_recv):
        a = self.app
        perdia_algo = self._hay_cambio()
        idx_local, play_local = a.current_index, self._playing_local()
        seek_local = self._seek_usuario
        self._rev = rev
        self._objetivo = o = self._crear_objetivo(st, age, t_recv)
        self._seek_usuario = False
        self._poner_cola(o["queue"])
        a.current_index = o["index"]
        a.actualizar_vista_cola()
        if 0 <= o["index"] < len(o["queue"]):
            t = o["queue"][o["index"]]
            txt = f"{'▶' if o['playing'] else '⏸'} {t.get('title') or 'Desconocido'} — {t.get('artist') or ''}"
        else:
            txt = "Esperando a que alguien ponga música…"
        if o.get("by"):
            txt += f"\nÚltimo cambio: {o['by']}"
        self._txt(txt)
        # Solo se avisa si lo que el usuario quería es distinto de lo que quedó (al acabar una
        # canción todos avanzan a la vez y gana el primero: ahí no hay nada que avisar)
        if perdia_algo and (idx_local != o["index"] or seek_local
                            or (play_local is not None and play_local != o["playing"])):
            a.status_var.set("Alguien cambió la jam a la vez que tú y se ha aplicado su cambio. "
                             "Repite tu acción si hace falta.")
        self._sincronizar(True)

    # ------------------------------------------------------------ mover el reproductor
    def _parar_local(self):
        self._aplicando = True
        try:
            self.app.detener_cancion()
        finally:
            self._aplicando = False

    def _sincronizar(self, completo):
        """Lleva el reproductor local al estado compartido.
        completo=True: hay una revisión nueva (cambiar de canción, recargar si falló...).
        completo=False: solo pausa/reanuda y corrige el desvío de la posición."""
        o = self._objetivo
        a = self.app
        if not o or not self.en_jam:
            return
        if o["index"] < 0:                       # nada que sonar
            if self._vid_cargado is not None or a._cargando:
                self._parar_local()
            return
        if self._vid_cargado != o["vid"]:        # otra canción distinta: cargarla
            self._cargar_objetivo(o)
            return
        if a._cargando or self._seek_pendiente_activo():
            return
        estado = a.player.get_state()
        if estado in _ESTADOS_MUERTO:
            # Falló o se paró en este PC. Solo se recarga ante una revisión nueva (o Resincronizar);
            # si es Ended, la app ya está pasando sola a la siguiente canción.
            if completo and o["playing"]:
                self._cargar_objetivo(o)
            return
        if estado not in (vlc.State.Playing, vlc.State.Paused):
            return                               # Opening/Buffering/Ended: esperar
        if o["playing"] and estado == vlc.State.Paused:
            a.player.set_pause(0)
        elif not o["playing"] and estado == vlc.State.Playing:
            a.player.set_pause(1)
        if time.monotonic() - self._ultimo_seek > 3.0:
            ahora = a.player.get_time()
            largo = a.player.get_length()
            destino = self._destino(o)
            tolerancia = DESVIO_PLAY_MS if o["playing"] else DESVIO_PAUSA_MS
            if largo > 0 and necesita_seek(ahora, destino, tolerancia):
                a.player.set_time(int(min(max(destino, 0), max(largo - 1000, 0))))
                self._ultimo_seek = time.monotonic()

    def _cargar_objetivo(self, o):
        n = self._intentos[1] + 1 if self._intentos[0] == o["vid"] else 1
        if n > MAX_INTENTOS_CARGA:
            self._txt("No se pudo cargar la canción de la jam (pulsa Resincronizar).")
            return
        self._intentos = (o["vid"], n)
        a = self.app
        self._poner_cola(o["queue"])
        a.current_index = o["index"]
        a.actualizar_vista_cola()
        self._seek_pendiente = True
        self._seek_pendiente_t = time.monotonic()
        a.cargar_y_reproducir_actual()           # llama a al_cargar()

    def _resolver_seek_pendiente(self, o):
        """Tras cargar la canción, salta a la posición de la jam (y pausa si la jam está en pausa)."""
        a = self.app
        if a.player.get_state() != vlc.State.Playing:
            return
        largo = a.player.get_length()
        if largo <= 0:
            return
        destino = self._destino(o)
        if destino > 1500:
            a.player.set_time(int(min(destino, max(largo - 1000, 0))))
            self._ultimo_seek = time.monotonic()
        if not o["playing"]:
            a.player.set_pause(1)
        self._seek_pendiente = False


# ======================================================================
# Ventana
# ======================================================================
class SocialDialog(SocialDialogExtrasMixin, tk.Toplevel):
    def __init__(self, mgr):
        app = mgr.app
        super().__init__(app.root)
        self.mgr = mgr
        self.app = app
        self.bg = app.bg_color
        self.title("Amigos y Jam")
        self.configure(bg=self.bg)
        self.resizable(False, False)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self.cerrar)

        self._job = None
        self._main_listo = False
        self._busqueda, self._jams, self._miembros = [], [], []
        self._datos = {"amigos": [], "recibidas": [], "enviadas": []}

        self.lbl_estado = tk.Label(self, text="", bg=self.bg, fg="#A00000", anchor="w",
                                   justify="left", wraplength=450, font=("Tahoma", 8))
        self.lbl_estado.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 6))
        self.body = tk.Frame(self, bg=self.bg)
        self.body.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.update_idletasks()
        r = app.root
        self.geometry(f"540x760+{r.winfo_rootx() + 60}+{r.winfo_rooty() + 30}")

        if mgr.perfil:
            self._construir_principal()
        else:
            tk.Label(self.body, text="Cargando…", bg=self.bg, font=("Tahoma", 9)).pack(pady=30)
            mgr.run(app.cloud.mi_perfil, self._perfil_cargado)
        app.tematizar(self)

    # ------------------------------------------------------------ utilidades
    def vivo(self):
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def estado(self, msg, error=False):
        if self.vivo():
            self.lbl_estado.config(text=msg, fg=self.app.c("#A00000" if error else "#1F5F1F", "fg"))

    def cerrar(self):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        if self.mgr.dialog is self:
            self.mgr.dialog = None
        try:
            self.destroy()
        except tk.TclError:
            pass

    def _limpiar_body(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _lista(self, parent, alto):
        marco = tk.Frame(parent, bg="#FFFFFF", relief=tk.SUNKEN, bd=2)
        marco.pack(fill=tk.X, padx=6, pady=(0, 4))
        sb = tk.Scrollbar(marco)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        lb = tk.Listbox(marco, height=alto, font=("Tahoma", 9), bd=0, highlightthickness=0,
                        exportselection=False, yscrollcommand=sb.set,
                        selectbackground="#316AC5", selectforeground="white")
        lb.pack(fill=tk.X, expand=True)
        sb.config(command=lb.yview)
        return lb

    def _boton(self, parent, texto, cmd, bg="#E0DFE3", **pack):
        b = tk.Button(parent, text=texto, command=cmd, bg=bg, bd=2, cursor="hand2",
                      font=("Tahoma", 8, "bold"))
        b.pack(**pack)
        return b

    @staticmethod
    def _sel(lb, datos):
        s = lb.curselection()
        return datos[s[0]] if s and s[0] < len(datos) else None

    # ------------------------------------------------------------ perfil
    def _perfil_cargado(self, perfil):
        if not self.vivo():
            return
        self.mgr.perfil = perfil
        self._limpiar_body()
        if perfil:
            self._construir_principal()
        else:
            self._construir_setup()
        self.app.tematizar(self.body)

    def _construir_setup(self):
        bg = self.bg
        tk.Label(self.body, text="Elige tu nombre de usuario", bg=bg,
                 font=("Tahoma", 10, "bold")).pack(pady=(30, 4))
        tk.Label(self.body, bg=bg, font=("Tahoma", 8), justify="center",
                 text="Es el que verán tus amigos (nunca tu email).\n"
                      "3-20 caracteres: letras, números o _.\n"
                      "Se te asignará un # único de 4 cifras (ej. Juan#0007), por\n"
                      "orden de registro. El nombre podrás cambiarlo; el # no.").pack()
        self.e_user = tk.Entry(self.body, width=26, font=("Tahoma", 10), relief=tk.SUNKEN, bd=2)
        self.e_user.pack(pady=10)
        self.e_user.bind("<Return>", lambda e: self._guardar_perfil())
        self.e_user.focus_set()
        self._boton(self.body, "Guardar", self._guardar_perfil, bg="#D9F2D9")

    def _guardar_perfil(self):
        nombre = self.e_user.get().strip()
        if not USERNAME_RE.match(nombre):
            self.estado("Usa 3-20 caracteres: letras, números o _.", error=True)
            return
        self.estado("Guardando…")
        self.mgr.run(lambda: self.app.cloud.crear_perfil(nombre), self._perfil_cargado)

    # ------------------------------------------------------------ pantalla principal
    def _construir_principal(self):
        cab = tk.Frame(self.body, bg=self.bg)
        cab.pack(fill=tk.X, padx=8, pady=(6, 2))
        tk.Label(cab, text="👤 Tu perfil:", bg=self.bg, font=("Tahoma", 8)).pack(side=tk.LEFT)
        self.lbl_nombre = tk.Label(cab, text=self.mgr.perfil["nombre"], bg=self.bg, fg="#1F4E9E",
                                   font=("Tahoma", 10, "bold"))
        self.lbl_nombre.pack(side=tk.LEFT, padx=(4, 8))
        self._boton(cab, "📋 Copiar", self._copiar_nombre, bg="#D6E4FF", side=tk.LEFT)
        self._boton(cab, "✏ Cambiar nombre", self._cambiar_nombre, bg="#FFF3C4", side=tk.LEFT, padx=(4, 0))
        nb = self.nb = ttk.Notebook(self.body)
        nb.pack(fill=tk.BOTH, expand=True)
        t_amigos = tk.Frame(nb, bg=self.bg)
        t_jam = tk.Frame(nb, bg=self.bg)
        t_chat = tk.Frame(nb, bg=self.bg)
        t_comp = tk.Frame(nb, bg=self.bg)
        nb.add(t_amigos, text=" 👥 Amigos ")
        nb.add(t_jam, text=" 🎧 Jam ")
        nb.add(t_chat, text=" 💬 Chat ")
        nb.add(t_comp, text=" 📀 Compartidas ")
        self._tab_amigos(t_amigos)
        self._tab_jam(t_jam)
        self._tab_chat(t_chat)
        self._tab_compartidas(t_comp)
        self._main_listo = True
        self.estado(f"Tu nombre de usuario: {self.mgr.perfil['nombre']}")
        self.refrescar_todo()
        self._job = self.after(8000, self._auto)

    def _cambiar_nombre(self):
        """Ventanita propia: 'Introduce el nuevo nombre'. El # no se toca."""
        previa = getattr(self, "_dlg_nombre", None)
        if previa is not None:
            try:
                if previa.winfo_exists():
                    previa.lift()
                    previa.focus_force()
                    return
            except tk.TclError:
                pass

        actual = self.mgr.perfil["username"]
        tag = self.mgr.perfil.get("tag") or "????"
        dlg = self._dlg_nombre = tk.Toplevel(self)
        dlg.title("Cambiar nombre")
        dlg.configure(bg=self.bg)
        dlg.resizable(False, False)
        dlg.transient(self)

        tk.Label(dlg, text="Introduce tu nuevo nombre de usuario", bg=self.bg,
                 font=("Tahoma", 10, "bold")).pack(padx=20, pady=(16, 4))
        tk.Label(dlg, bg=self.bg, font=("Tahoma", 8), justify="center",
                 text=f"3-20 caracteres: letras, números o _.\n"
                      f"Tu # ({tag}) no cambia.").pack(padx=20)

        fila = tk.Frame(dlg, bg=self.bg)
        fila.pack(pady=10)
        entrada = tk.Entry(fila, width=22, font=("Tahoma", 10), relief=tk.SUNKEN, bd=2)
        entrada.pack(side=tk.LEFT)
        tk.Label(fila, text=f"#{tag}", bg=self.bg, fg="#666666",
                 font=("Tahoma", 10, "bold")).pack(side=tk.LEFT, padx=(4, 0))
        entrada.insert(0, actual)
        entrada.select_range(0, tk.END)

        lbl_err = tk.Label(dlg, text="", bg=self.bg, fg="#A00000", font=("Tahoma", 8))
        lbl_err.pack()

        def cerrar():
            try:
                dlg.grab_release()
            except tk.TclError:
                pass
            dlg.destroy()

        def aceptar(_e=None):
            nuevo = entrada.get().strip()
            if nuevo == actual:
                cerrar()
                return
            if not USERNAME_RE.match(nuevo):
                lbl_err.config(text="Usa 3-20 caracteres: letras, números o _.")
                return
            cerrar()
            self.estado("Cambiando nombre…")
            self.mgr.run(lambda: self.app.cloud.cambiar_username(nuevo), self._nombre_cambiado)

        botones = tk.Frame(dlg, bg=self.bg)
        botones.pack(pady=(4, 14))
        self._boton(botones, "Guardar", aceptar, bg="#D9F2D9", side=tk.LEFT, padx=6)
        self._boton(botones, "Cancelar", cerrar, side=tk.LEFT, padx=6)

        entrada.bind("<Return>", aceptar)
        dlg.bind("<Escape>", lambda e: cerrar())
        dlg.protocol("WM_DELETE_WINDOW", cerrar)

        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_width()) // 2
        y = self.winfo_rooty() + 90
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
        dlg.lift()
        dlg.grab_set()
        entrada.focus_force()

    def _nombre_cambiado(self, perfil):
        if not self.vivo():
            return
        self.mgr.perfil = perfil
        self.lbl_nombre.config(text=perfil["nombre"])
        self.estado(f"Ahora eres {perfil['nombre']}")

    def _copiar_nombre(self):
        self.clipboard_clear()
        self.clipboard_append(self.mgr.perfil["nombre"])
        self.estado("Copiado: pásaselo a tus amigos para que te encuentren.")

    def _auto(self):
        self._job = None
        if not self.vivo():
            return
        self.refrescar_todo()
        self._job = self.after(8000, self._auto)

    def refrescar_todo(self):
        if not (self._main_listo and self.vivo()):
            return
        self.mgr.run(self.app.cloud.listar_amistades, self._pintar_amigos)
        self.mgr.refrescar_actividad()
        if hasattr(self, "lb_compartidas"):
            self.mgr.refrescar_compartidas()
        if hasattr(self, "txt_chat"):
            self.pintar_chat()
        self._refrescar_jam()

    # ------------------------------------------------------------ pestaña amigos
    def _tab_amigos(self, p):
        bg = self.bg
        f = tk.LabelFrame(p, text=" Buscar usuarios ", bg=bg, font=("Tahoma", 8, "bold"))
        f.pack(fill=tk.X, padx=6, pady=(8, 4))
        fila = tk.Frame(f, bg=bg)
        fila.pack(fill=tk.X, padx=6, pady=4)
        self.e_buscar = tk.Entry(fila, font=("Tahoma", 9), relief=tk.SUNKEN, bd=2)
        self.e_buscar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.e_buscar.bind("<Return>", lambda e: self._buscar())
        self._boton(fila, "Buscar", self._buscar, bg="#D6E4FF", side=tk.LEFT, padx=(4, 0))
        self.lb_busqueda = self._lista(f, 4)
        self._boton(f, "➕ Enviar solicitud de amistad", self._enviar_solicitud,
                    bg="#D9F2D9", pady=(0, 6))

        f2 = tk.LabelFrame(p, text=" Solicitudes recibidas ", bg=bg, font=("Tahoma", 8, "bold"))
        f2.pack(fill=tk.X, padx=6, pady=4)
        self.lb_recibidas = self._lista(f2, 3)
        fb = tk.Frame(f2, bg=bg)
        fb.pack(pady=(0, 6))
        self._boton(fb, "✔ Aceptar", lambda: self._responder(True), bg="#D9F2D9", side=tk.LEFT, padx=3)
        self._boton(fb, "✖ Rechazar", lambda: self._responder(False), bg="#F2D9D9", side=tk.LEFT, padx=3)

        f3 = tk.LabelFrame(p, text=" Mis amigos ", bg=bg, font=("Tahoma", 8, "bold"))
        f3.pack(fill=tk.X, padx=6, pady=4)
        self.lb_amigos = self._lista(f3, 6)
        self.lbl_enviadas = tk.Label(f3, text="", bg=bg, fg="#555555", anchor="w",
                                     wraplength=420, justify="left", font=("Tahoma", 8))
        self.lbl_enviadas.pack(fill=tk.X, padx=8)
        self.lb_amigos.bind("<Double-Button-1>", self._poner_cancion_amigo)
        fila_am = tk.Frame(f3, bg=bg)
        fila_am.pack(pady=(2, 2))
        self._boton(fila_am, "▶ Poner lo que escucha", self._poner_cancion_amigo, bg="#D6E4FF", side=tk.LEFT, padx=3)
        self._boton(fila_am, "Quitar amigo", self._quitar_amigo, bg="#F2D9D9", side=tk.LEFT, padx=3)
        self.var_compartir = tk.BooleanVar(value=bool(self.app.prefs.get("share_activity", True)))

        def compartir():
            self.app.prefs["share_activity"] = bool(self.var_compartir.get())
            self.app._guardar_prefs()
            if not self.var_compartir.get():
                self.mgr.run(lambda: self.app.cloud.actividad_publicar(None), err=lambda e: None)
        tk.Checkbutton(f3, text="Mostrar a mis amigos lo que estoy escuchando", variable=self.var_compartir,
                       command=compartir, bg=bg, activebackground=bg, font=("Tahoma", 8),
                       highlightthickness=0).pack(anchor="w", padx=6, pady=(0, 6))

    def _buscar(self):
        q = self.e_buscar.get().strip()
        if not q:
            return
        self.estado("Buscando…")
        self.mgr.run(lambda: self.app.cloud.buscar_usuarios(q), self._pintar_busqueda)

    def _pintar_busqueda(self, filas):
        if not self.vivo():
            return
        self._busqueda = filas
        self.lb_busqueda.delete(0, tk.END)
        for u in filas:
            self.lb_busqueda.insert(tk.END, u["nombre"])
        self.estado("" if filas else "No hay nadie con ese nombre.", error=not filas)

    def _enviar_solicitud(self):
        u = self._sel(self.lb_busqueda, self._busqueda)
        if not u:
            self.estado("Selecciona a alguien de los resultados.", error=True)
            return

        def ok(_):
            self.estado(f"Solicitud enviada a {u['nombre']}.")
            self.refrescar_todo()

        self.mgr.run(lambda: self.app.cloud.enviar_solicitud(u["id"]), ok)

    def _responder(self, aceptar):
        s = self._sel(self.lb_recibidas, self._datos["recibidas"])
        if not s:
            return

        def ok(_):
            self.estado(f"{s['nombre']} y tú ahora sois amigos." if aceptar else "Solicitud rechazada.")
            if aceptar:
                self.app.sonar("amigo")
            self.refrescar_todo()

        self.mgr.run(lambda: self.app.cloud.responder_solicitud(s["fid"], aceptar), ok)

    def _quitar_amigo(self):
        s = self._sel(self.lb_amigos, self._datos["amigos"])
        if not s:
            return
        if not messagebox.askyesno("Quitar amigo", f"¿Dejar de ser amigo de {s['nombre']}?", parent=self):
            return

        def ok(_):
            self.estado(f"{s['nombre']} ya no está en tu lista.")
            self.refrescar_todo()

        self.mgr.run(lambda: self.app.cloud.quitar_amistad(s["fid"]), ok)

    def _pintar_amigos(self, datos):
        if not self.vivo():
            return
        self._datos = datos
        for lb, clave in ((self.lb_recibidas, "recibidas"), (self.lb_amigos, "amigos")):
            lb.delete(0, tk.END)
            for x in datos[clave]:
                lb.insert(tk.END, x["nombre"])
        env = ", ".join(x["nombre"] for x in datos["enviadas"])
        self.lbl_enviadas.config(text=f"Solicitudes enviadas (pendientes): {env}" if env else "")
        self.mgr.pendientes = len(datos["recibidas"])
        self.mgr._actualizar_boton()
        self.repintar_amigos()                  # con lo que escucha cada uno (v22)

    # ------------------------------------------------------------ pestaña jam
    def _tab_jam(self, p):
        bg = self.bg
        # --- sin jam ---
        self.f_sin = tk.Frame(p, bg=bg)
        f = tk.LabelFrame(self.f_sin, text=" Crear una jam ", bg=bg, font=("Tahoma", 8, "bold"))
        f.pack(fill=tk.X, padx=6, pady=(8, 4))
        tk.Label(f, bg=bg, font=("Tahoma", 8), justify="left", wraplength=420,
                 text="Todos los que estén en la jam controlan la música por igual: play, pausa, "
                      "cola, canciones… Tú, como anfitrión, decides quién entra y puedes terminarla.").pack(
            anchor="w", padx=6, pady=(4, 2))
        fila = tk.Frame(f, bg=bg)
        fila.pack(fill=tk.X, padx=6, pady=4)
        self.e_jam = tk.Entry(fila, font=("Tahoma", 9), relief=tk.SUNKEN, bd=2)
        self.e_jam.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.e_jam.insert(0, f"Jam de {self.mgr.perfil['username']}")
        self._boton(fila, "🎧 Crear jam", self._crear_jam,
                    bg="#D9F2D9", side=tk.LEFT, padx=(4, 0))
        self.var_publica = tk.BooleanVar(value=False)
        tk.Checkbutton(f, text="🌐 Jam pública: cualquiera puede entrar sin que tengas que aceptarlo",
                       variable=self.var_publica, bg=bg, activebackground=bg, anchor="w",
                       font=("Tahoma", 8), wraplength=420, justify="left").pack(
            fill=tk.X, padx=6, pady=(0, 2))
        tk.Label(f, bg=bg, fg="#555555", font=("Tahoma", 8), justify="left", wraplength=420,
                 text="Si no la marcas, es privada: solo tus amigos pueden pedir entrar y tú aceptas o "
                      "rechazas cada solicitud.").pack(anchor="w", padx=6, pady=(0, 6))

        f2 = tk.LabelFrame(self.f_sin, text=" Jams disponibles ", bg=bg, font=("Tahoma", 8, "bold"))
        f2.pack(fill=tk.X, padx=6, pady=4)
        self.lb_jams = self._lista(f2, 6)
        tk.Label(f2, bg=bg, fg="#555555", font=("Tahoma", 8), anchor="w",
                 text="🌐 pública (entras directo)   🔒 privada (te tiene que aceptar el anfitrión)").pack(
            fill=tk.X, padx=8)
        fb = tk.Frame(f2, bg=bg)
        fb.pack(pady=(2, 6))
        self._boton(fb, "▶ Unirse / Pedir entrar", self._unirse, bg="#D6E4FF", side=tk.LEFT, padx=3)
        self._boton(fb, "↻ Actualizar", self._refrescar_jam, side=tk.LEFT, padx=3)

        # --- en jam (o esperando aprobación) ---
        self.f_en = tk.Frame(p, bg=bg)
        self.lbl_rol = tk.Label(self.f_en, bg=bg, font=("Tahoma", 10, "bold"), wraplength=440,
                                justify="left", anchor="w")
        self.lbl_rol.pack(fill=tk.X, padx=8, pady=(12, 2))
        self.lbl_sonando = tk.Label(self.f_en, bg="#FFFFFF", fg="#0A246A",
                                    font=("Tahoma", 9, "bold"), wraplength=500,
                                    justify="left", anchor="w", relief=tk.GROOVE, bd=1)
        self.lbl_sonando.pack(fill=tk.X, padx=8, pady=(0, 6), ipady=7)

        self.lbl_sync = tk.Label(self.f_en, bg=bg, fg="#1F5F1F",
                                 font=("Tahoma", 7, "bold"), anchor="w")
        self.lbl_sync.pack(fill=tk.X, padx=10, pady=(0, 3))

        f3 = tk.LabelFrame(self.f_en, text=" 👥 Personas en la jam ", bg=bg, font=("Tahoma", 8, "bold"))
        f3.pack(fill=tk.X, padx=6, pady=(2, 4))
        self.lb_miembros = self._lista(f3, 5)
        # botones solo para el anfitrión (se colocan justo antes de fb_en)
        self.fb_host = tk.Frame(self.f_en, bg=bg)
        self._boton(self.fb_host, "✔ Aceptar", self._aceptar_miembro, bg="#D9F2D9", side=tk.LEFT, padx=3)
        self._boton(self.fb_host, "✖ Rechazar / Expulsar", self._expulsar_miembro, bg="#F2D9D9",
                    side=tk.LEFT, padx=3)
        f4 = tk.LabelFrame(self.f_en, text=" 🎵 Cola compartida ", bg=bg, font=("Tahoma", 8, "bold"))
        f4.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        marco_cola = tk.Frame(f4, bg="#FFFFFF", relief=tk.SUNKEN, bd=2)
        marco_cola.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        sb_cola = tk.Scrollbar(marco_cola)
        sb_cola.pack(side=tk.RIGHT, fill=tk.Y)
        self.lb_cola_jam = tk.Listbox(marco_cola, height=6, font=("Tahoma", 8), bd=0,
                                       highlightthickness=0, exportselection=False,
                                       yscrollcommand=sb_cola.set, selectbackground="#316AC5",
                                       selectforeground="white")
        self.lb_cola_jam.pack(fill=tk.BOTH, expand=True)
        sb_cola.config(command=self.lb_cola_jam.yview)
        fila_cola = tk.Frame(f4, bg=bg)
        fila_cola.pack(fill=tk.X, padx=6, pady=(0, 5))
        self._boton(fila_cola, "✕ Quitar seleccionada", self._quitar_cancion_jam,
                    bg="#F2D9D9", side=tk.LEFT, padx=2)
        self._boton(fila_cola, "🗑 Vaciar cola", self._vaciar_cola_jam,
                    bg="#F2D9D9", side=tk.LEFT, padx=2)
        self._boton(fila_cola, "↻ Actualizar", self._refrescar_jam,
                    side=tk.RIGHT, padx=2)

        self.fb_en = tk.Frame(self.f_en, bg=bg)
        self.fb_en.pack(pady=5)
        self.b_resync = self._boton(self.fb_en, "🔄 Resincronizar", self.mgr.resincronizar,
                                    bg="#D6E4FF", side=tk.LEFT, padx=3)
        self.b_salir = self._boton(self.fb_en, "Salir", self._salir_jam, bg="#F2D9D9",
                                   side=tk.LEFT, padx=3)

    def _crear_jam(self):
        self.mgr.crear_jam(self.e_jam.get(), self.var_publica.get())

    def _refrescar_jam(self):
        if not (self._main_listo and self.vivo()):
            return
        m = self.mgr
        if m.jam_rol is None:
            self.f_en.pack_forget()
            self.f_sin.pack(fill=tk.BOTH, expand=True)
            self.mgr.run(self.app.cloud.jams_activas, self._pintar_jams)
            return
        self.f_sin.pack_forget()
        self.f_en.pack(fill=tk.BOTH, expand=True)
        tipo = "pública" if m.jam_publica else "privada"
        if m.jam_rol == "host":
            self.lbl_rol.config(text=f"🎧 Eres el anfitrión de «{m.jam_nombre}» ({tipo})")
            self.fb_host.pack(pady=(0, 2), before=self.fb_en)
            self.b_salir.config(text="Terminar jam")
        else:
            self.fb_host.pack_forget()
            if m.jam_rol == "pending":
                self.lbl_rol.config(text=f"⏳ Esperando a que {m.jam_anfitrion} te acepte en «{m.jam_nombre}»…")
                self.b_salir.config(text="Cancelar solicitud")
            else:
                self.lbl_rol.config(text=f"🎧 Estás en la jam de {m.jam_anfitrion} ({tipo})")
                self.b_salir.config(text="Salir de la jam")
        if m.jam_rol == "pending":
            self.b_resync.pack_forget()
            self._pintar_miembros_texto(["  Aún no formas parte de la jam."])
        else:
            if not self.b_resync.winfo_ismapped():
                self.b_resync.pack(side=tk.LEFT, padx=3, before=self.b_salir)
            self.lbl_sync.config(text="🟢  Sincronización activa · los cambios se comparten automáticamente")
            jam_id = m.jam_id
            self.mgr.run(lambda: self.app.cloud.jam_miembros(jam_id), self.pintar_miembros)
            self._pintar_cola_jam()
        self.pintar_sonando()

    def pintar_sonando(self):
        if not (self._main_listo and self.vivo()):
            return
        m = self.mgr
        if m.jam_rol == "pending":
            self.lbl_sonando.config(text="")
            self.lbl_sync.config(text="🟡  Esperando aprobación del anfitrión…", fg=self.app.c("#8A6D3B", "fg"))
        else:
            self.lbl_sonando.config(
                text=m.sonando_txt or "🎧 Todo lo que hagas (añadir, pausar, saltar…) lo oirán todos, y viceversa.")
            self.lbl_sync.config(text="🟢  Sincronización activa · cambios compartidos en tiempo real", fg=self.app.c("#1F5F1F", "fg"))

    def _pintar_jams(self, filas):
        if not (self.vivo() and self.mgr.jam_rol is None):
            return
        self._jams = filas
        self.lb_jams.delete(0, tk.END)
        for j in filas:
            icono = "🌐" if j.get("is_public") else "🔒"
            extra = "   — solicitud enviada" if j.get("mi_estado") == "pending" else ""
            self.lb_jams.insert(tk.END, f"{icono} {j['name']}   (de {j['host_username']}){extra}")
        if not filas:
            self.lb_jams.insert(tk.END, "  No hay ninguna jam abierta ahora.")

    def _pintar_cola_jam(self):
        """Muestra una vista compacta de la cola que realmente está compartida."""
        if not self.vivo() or not hasattr(self, "lb_cola_jam"):
            return
        if self.mgr.jam_rol not in ("host", "guest"):
            self.lb_cola_jam.delete(0, tk.END)
            return
        cola = list(getattr(self.app, "queue", []) or [])
        self.lb_cola_jam.delete(0, tk.END)
        if not cola:
            self.lb_cola_jam.insert(tk.END, "  La cola está vacía. Añade canciones desde Buscar música.")
            return
        idx = self.app.current_index
        for i, item in enumerate(cola):
            marca = "▶ " if i == idx else "   "
            titulo = item.get("title", "Desconocido")
            artista = item.get("artist", "")
            self.lb_cola_jam.insert(tk.END, f"{marca}{i + 1}. {titulo} — {artista}")

    def _quitar_cancion_jam(self):
        if not self.mgr.en_jam:
            return
        sel = self.lb_cola_jam.curselection()
        if not sel:
            self.estado("Selecciona una canción de la cola.", error=True)
            return
        idx = sel[0]
        cola = list(getattr(self.app, "queue", []) or [])
        if not (0 <= idx < len(cola)):
            return
        uid = cola[idx].get("uid")
        if not uid:
            self.estado("No se puede quitar esa canción todavía; espera a sincronizar.", error=True)
            return
        self.mgr.cola_quitar(uid)

    def _vaciar_cola_jam(self):
        if not self.mgr.en_jam:
            return
        if not messagebox.askyesno("Vaciar cola", "¿Vaciar la cola compartida para todos?", parent=self):
            return
        self.mgr.cola_limpiar()

    def _pintar_miembros_texto(self, lineas):
        self._miembros = []
        self.lb_miembros.delete(0, tk.END)
        for t in lineas:
            self.lb_miembros.insert(tk.END, t)

    def pintar_miembros(self, miembros):
        """miembros = jam_miembros(): dicts con user_id, username, status, es_host."""
        if not (self.vivo() and self.mgr.jam_rol in ("host", "guest")):
            return
        yo = (self.mgr.perfil or {}).get("id")
        sel = self._sel(self.lb_miembros, self._miembros)
        self._miembros = miembros
        self.lb_miembros.delete(0, tk.END)
        for mb in miembros:
            tu = "  (tú)" if mb["user_id"] == yo else ""
            if mb["es_host"]:
                txt = f"👑 {mb['nombre']}  (anfitrión){tu}"
            elif mb["status"] == "pending":
                txt = f"⏳ {mb['nombre']}  — quiere entrar{tu}"
            else:
                txt = f"     {mb['nombre']}{tu}"
            self.lb_miembros.insert(tk.END, txt)
            if sel and sel["user_id"] == mb["user_id"]:
                self.lb_miembros.selection_set(tk.END)
        if self.mgr.jam_rol == "host":
            n = sum(1 for mb in miembros if mb["status"] == "pending")
            if n != self.mgr.solicitudes_jam:
                self.mgr.solicitudes_jam = n
                self.mgr._actualizar_boton()

    def _unirse(self):
        j = self._sel(self.lb_jams, self._jams)
        if not j:
            self.estado("Selecciona una jam de la lista.", error=True)
            return
        if j.get("mi_estado") == "pending":
            self.estado("Ya has pedido entrar en esa jam: espera a que el anfitrión te acepte.")
        self.mgr.unirse(j)

    def _miembro_seleccionado(self):
        s = self._sel(self.lb_miembros, self._miembros)
        if not s:
            self.estado("Selecciona a alguien de la lista.", error=True)
        return s

    def _aceptar_miembro(self):
        s = self._miembro_seleccionado()
        if not s:
            return
        if s["status"] != "pending":
            self.estado(f"{s['nombre']} ya está dentro.", error=True)
            return
        jam_id = self.mgr.jam_id

        def ok(_):
            self.estado(f"{s['nombre']} ya está en la jam.")
            self._refrescar_jam()
            self.mgr.revisar_solicitudes()

        self.mgr.run(lambda: self.app.cloud.jam_responder(jam_id, s["user_id"], True), ok)

    def _expulsar_miembro(self):
        s = self._miembro_seleccionado()
        if not s:
            return
        if s["es_host"]:
            self.estado("No puedes echarte a ti mismo: usa «Terminar jam».", error=True)
            return
        if s["status"] != "pending" and not messagebox.askyesno(
                "Expulsar", f"¿Sacar a {s['nombre']} de la jam?", parent=self):
            return
        jam_id = self.mgr.jam_id

        def ok(_):
            self.estado(f"{s['nombre']} ya no está en la jam." if s["status"] != "pending"
                        else f"Solicitud de {s['nombre']} rechazada.")
            self._refrescar_jam()
            self.mgr.revisar_solicitudes()

        self.mgr.run(lambda: self.app.cloud.jam_responder(jam_id, s["user_id"], False), ok)

    def _salir_jam(self):
        m = self.mgr
        if m.jam_rol == "host" and not messagebox.askyesno(
                "Terminar jam", "La jam se cerrará para todos los miembros. ¿Terminarla?", parent=self):
            return
        m.salir_jam()
