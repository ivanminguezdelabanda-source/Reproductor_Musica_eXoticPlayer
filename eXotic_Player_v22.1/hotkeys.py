"""Atajos globales (funcionan aunque eXotic esté en segundo plano) y arranque con Windows.

Formato de los atajos (el de pynput): ``<ctrl>+<alt>+<right>``, ``<ctrl>+<shift>+p``...
"""
import os
import sys

try:
    from pynput import keyboard
except Exception:          # sin pynput: no hay atajos globales, la app sigue igual
    keyboard = None

ACCIONES = (
    ("play_pausa", "Reproducir / pausar", "<ctrl>+<alt>+<space>"),
    ("siguiente", "Siguiente canción", "<ctrl>+<alt>+<right>"),
    ("anterior", "Canción anterior", "<ctrl>+<alt>+<left>"),
    ("subir", "Subir volumen", "<ctrl>+<alt>+<up>"),
    ("bajar", "Bajar volumen", "<ctrl>+<alt>+<down>"),
    ("like", "♥ Me gusta a la actual", "<ctrl>+<alt>+l"),
    ("mostrar", "Mostrar / ocultar eXotic", "<ctrl>+<alt>+e"),
)
POR_DEFECTO = {k: c for k, _, c in ACCIONES}
NOMBRE_RUN = "eXoticPlayer"


_MODIFICADORES = {"<ctrl>", "<alt>", "<shift>", "<cmd>", "<alt_gr>"}
_TECLAS = {"<space>", "<left>", "<right>", "<up>", "<down>", "<home>", "<end>", "<page_up>",
           "<page_down>", "<insert>", "<delete>", "<backspace>", "<enter>", "<tab>", "<esc>",
           "<pause>", "<print_screen>"} | {f"<f{i}>" for i in range(1, 25)}


def combo_valido(texto):
    """True si el atajo tiene al menos un modificador y una tecla final válida
    (formato de pynput: '<ctrl>+<alt>+<right>', '<ctrl>+<shift>+p'...)."""
    partes = [p.strip() for p in (texto or "").strip().lower().split("+")]
    if len(partes) < 2 or any(not p for p in partes):
        return False
    *mods, tecla = partes
    if not mods or any(m not in _MODIFICADORES for m in mods) or len(set(mods)) != len(mods):
        return False
    return (len(tecla) == 1 and tecla.isprintable() and tecla != "+") or tecla in _TECLAS


def normalizar(atajos):
    """Mezcla lo guardado con los valores por defecto; descarta los que no valen."""
    out = dict(POR_DEFECTO)
    for k, v in (atajos or {}).items():
        if k in out and isinstance(v, str):
            v = v.strip().lower()
            out[k] = v if (v == "" or combo_valido(v)) else out[k]
    return out


class AtajosGlobales:
    def __init__(self, acciones):
        """acciones: {clave: función} (se llaman desde el hilo de pynput: usa app.ui)."""
        self.acciones = acciones
        self._oyente = None
        self.error = None

    def iniciar(self, atajos):
        self.detener()
        if keyboard is None:
            self.error = "pynput no está instalado"
            return False
        mapa = {}
        for clave, combo in atajos.items():
            fn = self.acciones.get(clave)
            if fn and combo and combo_valido(combo) and combo not in mapa:
                mapa[combo] = fn
        if not mapa:
            return False
        try:
            self._oyente = keyboard.GlobalHotKeys(mapa)
            self._oyente.daemon = True
            self._oyente.start()
            self.error = None
            return True
        except Exception as e:
            self.error = str(e)
            self._oyente = None
            print(f"Atajos globales: {e}")
            return False

    def detener(self):
        o, self._oyente = self._oyente, None
        if o is not None:
            try:
                o.stop()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Arrancar con Windows (minimizado en la bandeja)
# ---------------------------------------------------------------------------
def comando_arranque():
    """Línea de comandos con la que Windows abrirá eXotic al iniciar sesión."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --bandeja'
    py = sys.executable
    pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
    if os.path.exists(pyw):
        py = pyw
    script = os.path.abspath(sys.argv[0] if sys.argv and sys.argv[0].endswith(".py")
                             else os.path.join(os.path.dirname(__file__), "exotic_player.py"))
    return f'"{py}" "{script}" --bandeja'


def autoarranque_disponible():
    return sys.platform.startswith("win")


def autoarranque_activo():
    if not autoarranque_disponible():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            winreg.QueryValueEx(k, NOMBRE_RUN)
        return True
    except OSError:
        return False


def poner_autoarranque(activo):
    """Activa o quita el arranque con Windows. Devuelve True si quedó como se pidió."""
    if not autoarranque_disponible():
        return False
    import winreg
    ruta = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ruta, 0, winreg.KEY_SET_VALUE) as k:
            if activo:
                winreg.SetValueEx(k, NOMBRE_RUN, 0, winreg.REG_SZ, comando_arranque())
            else:
                try:
                    winreg.DeleteValue(k, NOMBRE_RUN)
                except FileNotFoundError:
                    pass
        return True
    except OSError as e:
        print(f"Arranque con Windows: {e}")
        return False
