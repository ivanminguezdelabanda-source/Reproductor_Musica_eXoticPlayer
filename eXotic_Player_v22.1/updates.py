"""Avisos de versión nueva (GitHub Releases).

En Configuración → Cuenta y datos → Mantenimiento se pone el repositorio de GitHub
(usuario/repositorio). Si allí hay una versión publicada más nueva que la tuya, eXotic
avisa al abrirse (una vez al día) con un botón para descargarla.
El flujo de GitHub Actions (.github/workflows/windows.yml) publica esas versiones solo
al subir una etiqueta vX.Y.
"""
import json
import re
import time
import urllib.request

API = "https://api.github.com/repos/{repo}/releases/latest"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def numero_version(texto):
    """'v21.3' -> (21, 3); 'eXotic 22' -> (22,). Tupla vacía si no hay números."""
    m = re.search(r"\d+(?:\.\d+)*", str(texto or ""))
    return tuple(int(x) for x in m.group(0).split(".")) if m else ()


def es_mas_nueva(remota, local):
    a, b = numero_version(remota), numero_version(local)
    if not a:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def repo_valido(repo):
    repo = (repo or "").strip().strip("/")
    if repo.startswith("https://github.com/"):
        repo = repo[len("https://github.com/"):].strip("/")
    return repo if REPO_RE.match(repo) else None


def ultima_version(repo, timeout=8):
    """{'version', 'url', 'notas', 'zip'} de la última versión publicada (lanza si falla)."""
    req = urllib.request.Request(API.format(repo=repo), headers={"Accept": "application/vnd.github+json",
                                                                  "User-Agent": "eXoticPlayer"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        datos = json.load(r)
    zip_url = next((a.get("browser_download_url") for a in datos.get("assets") or []
                    if str(a.get("name", "")).lower().endswith(".zip")), None)
    return {"version": datos.get("tag_name") or datos.get("name") or "",
            "url": datos.get("html_url") or f"https://github.com/{repo}/releases",
            "notas": (datos.get("body") or "")[:1500], "zip": zip_url}


class PlayerUpdatesMixin:
    def comprobar_actualizaciones(self, manual=False):
        repo = repo_valido(self.prefs.get("update_repo"))
        if not repo:
            if manual:
                self.status_var.set("Pon el repositorio de GitHub (usuario/repositorio) para buscar versiones nuevas.")
            return
        if not manual and time.time() - float(self.prefs.get("update_last", 0) or 0) < 20 * 3600:
            return
        self.prefs["update_last"] = time.time()
        self._guardar_prefs()
        if manual:
            self.status_var.set("Buscando versiones nuevas…")

        def task():
            try:
                info = ultima_version(repo)
            except Exception as e:
                print(f"[actualizaciones] {e}")
                if manual:
                    self.ui(self.status_var.set, "No se pudo comprobar si hay versión nueva.")
                return
            self.ui(self._version_encontrada, info, manual)

        self.pool_img.submit(task)

    def _version_encontrada(self, info, manual):
        from tkinter import messagebox
        import webbrowser
        local = getattr(self, "APP_VERSION", "")
        if not es_mas_nueva(info["version"], local):
            if manual:
                self.status_var.set(f"Tienes la última versión (v{local}).")
            return
        if not manual and info["version"] == self.prefs.get("update_skip"):
            return
        notas = info["notas"].strip()
        texto = (f"Hay una versión nueva de eXotic Player: {info['version']} (tienes la v{local}).\n\n"
                 + (notas[:600] + ("…" if len(notas) > 600 else "") + "\n\n" if notas else "")
                 + "¿Abrir la página de descarga?\n(«No» = no volver a avisar de esta versión)")
        r = messagebox.askyesnocancel("Versión nueva", texto, parent=self.root)
        if r:
            webbrowser.open(info["zip"] or info["url"])
        elif r is False:
            self.prefs["update_skip"] = info["version"]
            self._guardar_prefs()
