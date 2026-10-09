import datetime
import json
import os
import threading

import app_paths
from social_supabase import SocialMixin

SESSION_FILE = os.path.join(app_paths.DATA_DIR, "supabase_session.json")
_CONFIG_CANDIDATOS = [
    os.path.join(app_paths.DATA_DIR, "supabase_config.json"),      # el usuario puede sobrescribirlo
    os.path.join(app_paths.RESOURCE_DIR, "supabase_config.json"),  # el que va dentro del programa
    os.path.join(app_paths.INSTALL_DIR, "supabase_config.json"),
]
CONFIG_FILE = next((p for p in _CONFIG_CANDIDATOS if os.path.exists(p)), _CONFIG_CANDIDATOS[0])


class CloudError(RuntimeError):
    pass


def sesion_invalida(e):
    """True si el error dice que la sesión ya no vale (hay que volver a iniciar sesión).

    False para errores de red o del servidor, en los que NO hay que borrar la sesión
    guardada (antes se borraba y había que volver a meter la contraseña tras abrir la
    app sin Internet)."""
    if isinstance(e, (KeyError, ValueError, TypeError)):       # archivo de sesión corrupto
        return True
    nombre = type(e).__name__
    if "Retryable" in nombre:
        return False
    estado = getattr(e, "status", None) or getattr(e, "status_code", None)
    try:
        estado = int(estado)
    except (TypeError, ValueError):
        estado = None
    if nombre.startswith("Auth") or "SessionMissing" in nombre:
        return estado is None or 400 <= estado < 500
    texto = str(e).lower()
    return any(t in texto for t in ("invalid refresh token", "refresh token not found",
                                    "already used", "session_not_found", "jwt expired"))


class SupabaseCloud(SocialMixin):
    """Nunca lanza excepciones al crearse: si falla, queda 'no disponible'."""

    def __init__(self):
        self._lock = threading.RLock()
        self.client = None
        self.user = None
        self.error_init = None
        self.ultimo_fallo_red = False
        try:
            from supabase import create_client

            url = os.environ.get("SUPABASE_URL")
            key = os.environ.get("SUPABASE_ANON_KEY")
            if not (url and key):
                with open(CONFIG_FILE, encoding="utf-8") as f:
                    cfg = json.load(f)
                url, key = cfg["url"], cfg["anon_key"]
            url = url.strip().rstrip("/")
            if url.endswith("/rest/v1"):
                url = url[: -len("/rest/v1")]
            self.client = create_client(url, key.strip())
        except Exception as e:
            self.error_init = str(e)
            print(f"Supabase no disponible: {e}")

    # --- estado ---
    @property
    def disponible(self):
        return self.client is not None

    @property
    def logged_in(self):
        return self.user is not None

    @property
    def email(self):
        return getattr(self.user, "email", "") if self.user else ""

    @property
    def user_id(self):
        return self.user.id if self.user else None

    def _need(self):
        if not self.client:
            raise CloudError("Supabase no está configurado: " + (self.error_init or ""))

    # --- sesión ---
    def _guardar_sesion(self, session):
        if not session:
            return
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "access_token": session.access_token,
                    "refresh_token": session.refresh_token,
                },
                f,
            )

    def _borrar_sesion_local(self):
        try:
            os.remove(SESSION_FILE)
        except OSError:
            pass

    def login(self, email, password):
        self._need()
        with self._lock:
            res = self.client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            self.user = res.user
            self._guardar_sesion(res.session)
        return self.user

    def registrar(self, email, password):
        """True si quedó con sesión iniciada; False si requiere confirmar el email."""
        self._need()
        with self._lock:
            res = self.client.auth.sign_up({"email": email, "password": password})
            if res.session is None:
                return False
            self.user = res.user
            self._guardar_sesion(res.session)
        return True

    def restaurar_sesion(self):
        if not self.client or not os.path.exists(SESSION_FILE):
            return False
        try:
            self.ultimo_fallo_red = False
            with open(SESSION_FILE, encoding="utf-8") as f:
                s = json.load(f)
            with self._lock:
                res = self.client.auth.set_session(s["access_token"], s["refresh_token"])
                self.user = res.user
                self._guardar_sesion(res.session)
            return self.user is not None
        except Exception as e:
            self.user = None
            if sesion_invalida(e):
                print(f"Sesión caducada o inválida: {e}")
                self._borrar_sesion_local()
                self.ultimo_fallo_red = False
            else:
                # sin Internet / servidor caído: se conserva la sesión para reintentar
                print(f"No se pudo restaurar la sesión (se reintentará): {e}")
                self.ultimo_fallo_red = True
            return False

    def logout(self):
        try:
            if self.client:
                self.client.auth.sign_out()
        except Exception:
            pass
        self.user = None
        self._borrar_sesion_local()

    # --- datos ---
    def descargar_datos(self):
        self._need()
        with self._lock:
            res = (
                self.client.table("user_data")
                .select("data")
                .eq("user_id", self.user_id)
                .limit(1)
                .execute()
            )
        rows = res.data or []
        if not rows:
            return None  # cuenta nueva: todavía no hay datos en la nube
        data = rows[0]["data"]
        base = {"version": 2, "playlists": [], "liked": [], "settings": {}}
        if isinstance(data, dict):
            base.update(data)
        return base

    def subir_datos(self, data, user_id=None):
        """user_id evita subir datos de una cuenta a otra si la sesión cambió."""
        self._need()
        with self._lock:
            if self.user_id is None or (user_id is not None and user_id != self.user_id):
                raise CloudError("La sesión cambió; subida cancelada.")
            self.client.table("user_data").upsert(
                {
                    "user_id": self.user_id,
                    "data": data,
                    "updated_at": datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat(),
                }
            ).execute()
            try:  # guarda los tokens por si se renovaron
                self._guardar_sesion(self.client.auth.get_session())
            except Exception:
                pass
