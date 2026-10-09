"""Amigos y jams sobre Supabase.

Es un "mixin": SupabaseCloud hereda de SocialMixin y reutiliza su cliente, su sesión
y su lock. Todos los métodos son BLOQUEANTES: llámalos desde un hilo, nunca desde Tk.
"""
import re

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
_BUSQUEDA_RE = re.compile(r"^[A-Za-z0-9_]{1,20}(#[0-9]{0,4})?$")


def con_tag(fila):
    """Añade 'nombre' = 'Juan#4821' a una fila de perfil (sin tocar 'username')."""
    if fila is not None:
        fila["nombre"] = f"{fila.get('username', '?')}#{fila.get('tag') or '????'}"
    return fila


class SocialError(RuntimeError):
    """Error con mensaje ya listo para enseñar al usuario."""


class JamPerdida(SocialError):
    """La jam ya no existe (el anfitrión la cerró) o ya no tienes acceso."""


def err_msg(e):
    """Mensaje corto y legible de cualquier excepción (postgrest, red, SocialError...)."""
    if isinstance(e, SocialError):
        return str(e)
    msg = getattr(e, "message", None) or str(e)
    low = str(msg).lower()
    if "does not exist" in low or "pgrst205" in low or "could not find the table" in low:
        return "Faltan tablas en Supabase: ejecuta supabase_schema.sql (o supabase_actualizacion_v22.sql)."
    return str(msg).replace("\n", " ")[:200]


def _es_duplicado(e):
    txt = (str(getattr(e, "code", "")) + " " + str(e)).lower()
    return "23505" in txt or "duplicate key" in txt


def _es_rls(e):
    txt = (str(getattr(e, "code", "")) + " " + str(e)).lower()
    return "42501" in txt or "row-level security" in txt


class SocialMixin:
    # ---------------------------------------------------------------- utilidades
    def _uid(self):
        self._need()
        if not self.user_id:
            raise SocialError("Inicia sesión primero.")
        return self.user_id

    def _tabla(self, nombre):
        return self.client.table(nombre)

    # ---------------------------------------------------------------- perfil
    def mi_perfil(self):
        uid = self._uid()
        with self._lock:
            res = self._tabla("profiles").select("id,username,tag").eq("id", uid).limit(1).execute()
        filas = res.data or []
        return con_tag(filas[0]) if filas else None

    def crear_perfil(self, username):
        uid = self._uid()
        username = (username or "").strip()
        if not USERNAME_RE.match(username):
            raise SocialError("Usa entre 3 y 20 caracteres: letras, números o _.")
        try:
            with self._lock:
                res = self._tabla("profiles").insert({"id": uid, "username": username}).execute()
        except Exception as e:
            if "tags_agotados" in str(e) or "nombre_agotado" in str(e):
                raise SocialError("Ya no quedan números # libres (límite 9999 usuarios).") from e
            if _es_duplicado(e):
                raise SocialError("Ya tienes un perfil creado.") from e
            raise
        filas = res.data or []
        if filas:                      # el # lo asigna el servidor
            return con_tag(filas[0])
        return self.mi_perfil()

    def cambiar_username(self, nuevo):
        """Cambia el nombre de usuario. El # NO cambia nunca (lo garantiza el servidor).
        Devuelve el perfil actualizado."""
        self._uid()
        nuevo = (nuevo or "").strip()
        if not USERNAME_RE.match(nuevo):
            raise SocialError("Usa entre 3 y 20 caracteres: letras, números o _.")
        res = self._rpc("perfil_cambiar_username", {"p_username": nuevo})
        if not isinstance(res, dict):
            raise SocialError("No se pudo cambiar el nombre.")
        return con_tag(res)

    def buscar_usuarios(self, texto, limite=10):
        """Busca por 'nombre' (prefijo) o por 'nombre#1234' (exacto; con menos cifras, prefijo)."""
        uid = self._uid()
        texto = (texto or "").strip()
        if not _BUSQUEDA_RE.match(texto):
            return []
        nombre, sep, tag = texto.partition("#")
        patron = nombre.replace("_", "\\_") + ("" if tag else "%")
        with self._lock:
            q = (
                self._tabla("profiles")
                .select("id,username,tag")
                .ilike("username", patron)
                .neq("id", uid)
            )
            if tag:
                q = q.eq("tag", tag) if len(tag) == 4 else q.like("tag", tag + "%")
            res = q.order("username").order("tag").limit(limite).execute()
        return [con_tag(f) for f in (res.data or [])]

    # ---------------------------------------------------------------- amigos
    def listar_amistades(self):
        """{'amigos': [...], 'recibidas': [...], 'enviadas': [...]}; cada item:
        {'fid', 'user_id', 'username'}."""
        uid = self._uid()
        with self._lock:
            filas = (
                self._tabla("friendships").select("id,requester,addressee,status").execute().data
                or []
            )
            ids = {f["addressee"] if f["requester"] == uid else f["requester"] for f in filas}
            nombres = {}
            if ids:
                perfiles = (
                    self._tabla("profiles").select("id,username,tag").in_("id", list(ids)).execute().data
                    or []
                )
                nombres = {p["id"]: con_tag(p)["nombre"] for p in perfiles}
        out = {"amigos": [], "recibidas": [], "enviadas": []}
        for f in filas:
            yo_pedi = f["requester"] == uid
            otro = f["addressee"] if yo_pedi else f["requester"]
            item = {"fid": f["id"], "user_id": otro, "username": nombres.get(otro, "?")}
            item["nombre"] = item["username"]
            if f["status"] == "accepted":
                out["amigos"].append(item)
            elif yo_pedi:
                out["enviadas"].append(item)
            else:
                out["recibidas"].append(item)
        for lista in out.values():
            lista.sort(key=lambda x: x["nombre"].lower())
        return out

    def enviar_solicitud(self, otro_id):
        uid = self._uid()
        try:
            with self._lock:
                self._tabla("friendships").insert(
                    {"requester": uid, "addressee": otro_id, "status": "pending"}
                ).execute()
        except Exception as e:
            if _es_duplicado(e):
                raise SocialError("Ya hay una solicitud o una amistad con esa persona.") from e
            raise

    def responder_solicitud(self, fid, aceptar):
        self._uid()
        with self._lock:
            if aceptar:
                self._tabla("friendships").update({"status": "accepted"}).eq("id", fid).execute()
            else:
                self._tabla("friendships").delete().eq("id", fid).execute()

    def quitar_amistad(self, fid):
        self._uid()
        with self._lock:
            self._tabla("friendships").delete().eq("id", fid).execute()

    # ---------------------------------------------------------------- jams
    # Todas las escrituras de jams van por funciones SQL (social_schema_3.sql): ellas validan
    # permisos y controlan las revisiones para que dos personas no se pisen.
    @staticmethod
    def _error_rpc(e):
        txt = str(e).lower()
        if "no_permitido" in txt:
            return SocialError("No puedes hacer eso en esta jam.")
        if "jam_no_existe" in txt:
            return JamPerdida("Esa jam ya no existe.")
        if "nombre_invalido" in txt:
            return SocialError("Usa entre 3 y 20 caracteres: letras, números o _.")
        if "sin_perfil" in txt:
            return SocialError("Todavía no tienes perfil.")
        if "cola_demasiado_grande" in txt:

            return SocialError("La cola de la jam es demasiado grande (máximo 300 canciones).")
        if "demasiados_mensajes" in txt:
            return SocialError("Vas muy rápido: espera unos segundos.")
        if "playlist_llena" in txt:
            return SocialError("La playlist compartida ya tiene 500 canciones.")
        if "demasiadas_playlists" in txt:
            return SocialError("Ya tienes 30 playlists compartidas.")
        if "demasiados_miembros" in txt:
            return SocialError("Esa playlist ya tiene 20 personas.")
        if "could not find the function" in txt or "pgrst202" in txt:
            return SocialError("Falta actualizar la base de datos: ejecuta supabase_actualizacion_v22.sql en Supabase.")
        return None

    def _rpc(self, nombre, params=None):
        try:
            with self._lock:
                return self.client.rpc(nombre, params or {}).execute().data
        except Exception as e:
            mapeado = self._error_rpc(e)
            if mapeado:
                raise mapeado from e
            raise

    def jam_crear(self, nombre, publica=False, estado=None):
        """Crea la jam (una por anfitrión). Devuelve {'id': ..., 'rev': ...}."""
        self._uid()
        nombre = ((nombre or "").strip() or "Jam")[:40]
        res = self._rpc(
            "jam_crear",
            {"p_nombre": nombre, "p_publica": bool(publica), "p_estado": estado or {}},
        )
        if not isinstance(res, dict) or "id" not in res:
            raise SocialError("No se pudo crear la jam.")
        return res

    def jams_activas(self):
        """Jams que puedes ver (de amigos o públicas) con alguien conectado. Cada una trae
        is_public y mi_estado (None | 'pending' | 'accepted')."""
        self._uid()
        return self._rpc("jams_activas") or []

    def jam_unirse(self, jam_id):
        """Devuelve 'accepted' (entras ya: jam pública) o 'pending' (espera al anfitrión)."""
        self._uid()
        res = self._rpc("jam_unirse", {"j": jam_id})
        if res not in ("accepted", "pending"):
            raise SocialError("No puedes unirte a esa jam.")
        return res

    def jam_responder(self, jam_id, user_id, aceptar):
        """Solo el anfitrión. aceptar=False rechaza una solicitud o expulsa a un miembro."""
        self._uid()
        self._rpc("jam_responder", {"j": jam_id, "u": user_id, "aceptar": bool(aceptar)})

    def jam_salir(self, jam_id):
        """Salir de la jam o cancelar tu solicitud pendiente."""
        uid = self._uid()
        with self._lock:
            self._tabla("jam_members").delete().eq("jam_id", jam_id).eq("user_id", uid).execute()

    def jam_terminar(self, jam_id):
        self._uid()
        with self._lock:
            self._tabla("jams").delete().eq("id", jam_id).execute()

    def jam_miembros(self, jam_id):
        """[{'user_id', 'username', 'status', 'es_host'}], anfitrión primero y pendientes al final.
        Las solicitudes pendientes solo las ve el anfitrión."""
        self._uid()
        with self._lock:
            filas = (
                self._tabla("jam_members")
                .select("user_id,status,profiles(username,tag)")
                .eq("jam_id", jam_id)
                .execute()
                .data
                or []
            )
            j = self._tabla("jams").select("host").eq("id", jam_id).limit(1).execute().data or []
        host = j[0]["host"] if j else None
        out = []
        for r in filas:
            p = r.get("profiles") or {}
            out.append(
                {
                    "user_id": r["user_id"],
                    "username": p.get("username", "?"),
                    "nombre": con_tag(dict(p))["nombre"] if p else "?",
                    "status": r.get("status", "accepted"),
                    "es_host": r["user_id"] == host,
                }
            )
        out.sort(key=lambda m: (not m["es_host"], m["status"] != "accepted", m["nombre"].lower()))
        return out

    def jam_publicar(self, jam_id, estado, base_rev):
        """Cualquier miembro aceptado publica un cambio partiendo de la revisión base_rev.
        Devuelve {'ok': True, 'rev': n} o {'ok': False, 'rev': n} si alguien se adelantó.
        Lanza JamPerdida si la jam ya no existe o ya no eres miembro."""
        self._uid()
        res = self._rpc(
            "jam_publicar", {"j": jam_id, "p_estado": estado, "p_base_rev": int(base_rev)}
        )
        if not isinstance(res, dict):
            raise JamPerdida("La jam ya no existe o ya no formas parte de ella.")
        return res

    def jam_cola_agregar(self, jam_id, items, reproducir=False):
        """Añade canciones al final de la cola compartida (cualquier miembro aceptado).
        Si reproducir=True, la primera pasa a sonar ya para todos. Devuelve {'rev': n}.
        Lanza JamPerdida si la jam ya no existe o ya no eres miembro."""
        self._uid()
        limpios = [
            {"title": t.get("title", ""), "artist": t.get("artist", ""),
             "videoId": t["videoId"], "coverUrl": t.get("coverUrl")}
            for t in items if t.get("videoId")
        ]
        if not limpios:
            raise SocialError("No hay canciones que añadir.")
        res = self._rpc("jam_cola_agregar",
                        {"j": jam_id, "p_items": limpios, "p_reproducir": bool(reproducir)})
        if not isinstance(res, dict):
            raise JamPerdida("La jam ya no existe o ya no formas parte de ella.")
        return res

    def jam_cola_quitar(self, jam_id, uid_cancion):
        """Quita una canción de la cola compartida por su uid (cualquier miembro aceptado)."""
        self._uid()
        res = self._rpc("jam_cola_quitar", {"j": jam_id, "p_uid": str(uid_cancion)})
        if not isinstance(res, dict):
            raise JamPerdida("La jam ya no existe o ya no formas parte de ella.")
        return res

    def jam_cola_limpiar(self, jam_id):
        """Vacía la cola compartida y para la reproducción (cualquier miembro aceptado)."""
        self._uid()
        res = self._rpc("jam_cola_limpiar", {"j": jam_id})
        if not isinstance(res, dict):
            raise JamPerdida("La jam ya no existe o ya no formas parte de ella.")
        return res

    def jam_estado(self, jam_id, rev_conocida=-1):
        """None si la jam ya no existe o te han sacado. Si no: {'mi_estado', 'rev', 'age_ms',
        'state'...}. 'state' llega a None si tu revisión ya es la actual (así no se baja la cola
        entera cada segundo). age_ms = tiempo (reloj del SERVIDOR) desde que se publicó."""
        self._uid()
        return self._rpc("jam_estado", {"j": jam_id, "p_rev": int(rev_conocida)}) or None

    def jam_latido(self, jam_id):
        """'Sigo aquí': mantiene la jam visible en la lista de jams activas."""
        self._uid()
        self._rpc("jam_latido", {"j": jam_id})

    # ---------------------------------------------------------------- v22: chat de la jam
    def jam_mensaje(self, jam_id, tipo, texto):
        self._uid()
        return self._rpc("jam_mensaje", {"j": jam_id, "p_kind": tipo, "p_body": str(texto)[:300]})

    def jam_mensajes(self, jam_id, desde=0):
        self._uid()
        return self._rpc("jam_mensajes", {"j": jam_id, "p_desde": int(desde or 0)}) or []

    # ---------------------------------------------------------------- v22: actividad de amigos
    def actividad_publicar(self, cancion):
        """cancion: dict {title, artist, videoId, coverUrl} o None para "no estoy escuchando"."""
        self._uid()
        return self._rpc("actividad_publicar", {"p_song": cancion})

    def actividad_amigos(self):
        self._uid()
        return self._rpc("actividad_amigos") or []

    # ---------------------------------------------------------------- v22: playlists colaborativas
    def pl_crear(self, nombre):
        self._uid()
        return self._rpc("pl_crear", {"p_nombre": (nombre or "").strip()[:60]})

    def pl_mias(self):
        self._uid()
        return self._rpc("pl_mias") or []

    def pl_ver(self, pl_id):
        self._uid()
        return self._rpc("pl_ver", {"pl": pl_id})

    def pl_invitar(self, pl_id, user_id):
        self._uid()
        return self._rpc("pl_invitar", {"pl": pl_id, "u": user_id})

    def pl_agregar(self, pl_id, items):
        self._uid()
        limpios = [{k: it.get(k) for k in ("videoId", "title", "artist", "coverUrl", "duration")}
                   for it in items if it.get("videoId") and not str(it["videoId"]).startswith("file:")]
        if not limpios:
            raise SocialError("Las canciones de tu ordenador no se pueden compartir.")
        return self._rpc("pl_agregar", {"pl": pl_id, "p_items": limpios})

    def pl_quitar(self, pl_id, uid_cancion):
        self._uid()
        return self._rpc("pl_quitar", {"pl": pl_id, "p_uid": str(uid_cancion)})

    def pl_salir(self, pl_id):
        self._uid()
        return self._rpc("pl_salir", {"pl": pl_id})
