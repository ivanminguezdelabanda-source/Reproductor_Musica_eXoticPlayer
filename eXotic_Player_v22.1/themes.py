"""Temas visuales intercambiables para eXotic Player.

Toda la interfaz está escrita con los colores de "Luna Azul" (Windows XP). Un tema
es un mapa  color_base -> color_nuevo  (uno para fondos y otro para textos). Al
cambiar de tema se recorre el árbol de widgets y se traduce cada color:

    color actual --(inverso del tema actual)--> color base --(tema nuevo)--> color final

Así se puede pasar de cualquier tema a cualquier otro sin guardar nada por widget,
y los widgets que se crean más tarde (resultados de búsqueda, diálogos) se tematizan
llamando otra vez a ``aplicar_arbol``.
"""
import tkinter as tk

TEMA_POR_DEFECTO = "Luna Azul (XP)"

BG_OPTS = ("background", "activebackground", "selectbackground", "highlightbackground",
           "troughcolor", "selectcolor", "readonlybackground", "disabledbackground")
FG_OPTS = ("foreground", "activeforeground", "selectforeground", "insertbackground",
           "disabledforeground")


def _tema(bg, fg, ttk_cfg):
    return {"bg": {k.upper(): v.upper() for k, v in bg.items()},
            "fg": {k.upper(): v.upper() for k, v in fg.items()},
            "ttk": ttk_cfg}


TEMAS = {
    "Luna Azul (XP)": _tema({}, {}, {
        "bg": "#ECE9D8", "campo": "#FFFFFF", "texto": "#000000", "pestana": "#E0DFE3",
        "pestana_sel": "#FFFFFF", "canal": "#B0B0B0", "acento": "#316AC5"}),

    "Olive Green (XP)": _tema({
        "#0A246A": "#56662A", "#316AC5": "#7F9446", "#D6E4FF": "#E3EBC8",
        "#DCE6F7": "#E6EDD2", "#C8E8C8": "#CFE3A8", "#E0DFE3": "#E4E2D4",
        "#D4D0C8": "#D6D3C2",
    }, {
        "#0A246A": "#3F4F1A", "#1F4E9E": "#4E6322",
    }, {"bg": "#ECE9D8", "campo": "#FFFFFF", "texto": "#000000", "pestana": "#E4E2D4",
        "pestana_sel": "#FFFFFF", "canal": "#B5B39E", "acento": "#7F9446"}),

    "Plata (XP)": _tema({
        "#ECE9D8": "#EEEEF3", "#0A246A": "#666A85", "#316AC5": "#8D90AB",
        "#E0DFE3": "#E4E4EC", "#D4D0C8": "#D5D5DF", "#D6E4FF": "#E1E2EE",
        "#DCE6F7": "#E3E4EE", "#F0F0F0": "#EEEEF4", "#D9D9D9": "#EEEEF5",
    }, {
        "#0A246A": "#3A3D58", "#1F4E9E": "#4A4E70",
    }, {"bg": "#EEEEF3", "campo": "#FFFFFF", "texto": "#000000", "pestana": "#E4E4EC",
        "pestana_sel": "#FFFFFF", "canal": "#B4B5C4", "acento": "#8D90AB"}),

    "Frutiger Aero": _tema({
        "#ECE9D8": "#E3F3FB", "#0A246A": "#1270B3", "#316AC5": "#2C9AD8",
        "#E0DFE3": "#D2ECF8", "#D4D0C8": "#BFE2F3", "#FAFAFA": "#F5FBFE",
        "#F4F4F4": "#EEF7FC", "#E8E8E8": "#DDEFF8", "#C8E8C8": "#BCE899",
        "#D9F2D9": "#CDEFB1", "#D6E4FF": "#CDE8FA", "#DCE6F7": "#D7EEFA",
        "#050B05": "#04131D", "#101010": "#06182A", "#B0B0B0": "#9CCBE3",
        "#F0F0F0": "#E3F3FC", "#D9D9D9": "#E3F3FD", "#7B4FA3": "#5C7FD6",
        "#B03A8C": "#2BB3A4", "#C0763A": "#E0893A",
    }, {
        "#0A246A": "#0B5A8E", "#1F4E9E": "#0F6AA6", "#00FF66": "#71E4FF",
    }, {"bg": "#E3F3FB", "campo": "#FFFFFF", "texto": "#05324F", "pestana": "#D2ECF8",
        "pestana_sel": "#FFFFFF", "canal": "#9CCBE3", "acento": "#2C9AD8"}),

    "Noche (oscuro)": _tema({
        "#ECE9D8": "#26272B", "#0A246A": "#141519", "#316AC5": "#3E5FB8",
        "#E0DFE3": "#3A3B41", "#D4D0C8": "#2F3036", "#FFFFFF": "#1C1D21",
        "#FAFAFA": "#202126", "#F4F4F4": "#232429", "#E8E8E8": "#33343A",
        "#C8E8C8": "#2F5A3A", "#F2D9D9": "#5A2F33", "#D9F2D9": "#2E5A3B",
        "#D6E4FF": "#2F3F66", "#FFDADA": "#663039", "#F3DFC8": "#5C4430",
        "#DCE6F7": "#2A2F3A", "#B0B0B0": "#55565C", "#F0F0F0": "#27282C",
        "#D9D9D9": "#27282D", "#FFF3C4": "#5A5230", "#ECECEC": "#3A3B42",
    }, {
        "#000000": "#E8E8EA", "#111111": "#EDEDED", "#222222": "#E0E0E0",
        "#333333": "#D0D0D0", "#444444": "#C4C4C4", "#555555": "#A8A8B0",
        "#666666": "#9A9AA2", "#0A246A": "#8FB2FF", "#1F4E9E": "#8FB3FF",
        "#A00000": "#FF7A7A", "#1F5F1F": "#7AD97A",
    }, {"bg": "#26272B", "campo": "#1C1D21", "texto": "#E8E8EA", "pestana": "#3A3B41",
        "pestana_sel": "#26272B", "canal": "#55565C", "acento": "#3E5FB8"}),

    "PlayStation 2": _tema({
        "#ECE9D8": "#0E1631", "#0A246A": "#04081A", "#316AC5": "#2F5FC4",
        "#E0DFE3": "#1C2A57", "#D4D0C8": "#141F44", "#FFFFFF": "#0A1128",
        "#FAFAFA": "#0C142E", "#F4F4F4": "#0F1834", "#E8E8E8": "#1A2650",
        "#C8E8C8": "#1F4E8C", "#F2D9D9": "#4A2340", "#D9F2D9": "#1E4A86",
        "#D6E4FF": "#22397A", "#FFDADA": "#5A2448", "#F3DFC8": "#3A3364",
        "#DCE6F7": "#1B3266", "#B0B0B0": "#2B3A6E", "#F0F0F0": "#0E1632",
        "#D9D9D9": "#0E1633", "#FFF3C4": "#3B3F6E", "#ECECEC": "#1C2A58", "#050B05": "#02040C",
        "#101010": "#03060F", "#7B4FA3": "#4B3FA8", "#B03A8C": "#2E6FD0",
        "#C0763A": "#3B5BB8", "#2E9E4F": "#2C8AD8", "#2E8B57": "#2A7BC4",
    }, {
        "#000000": "#DCE5FF", "#111111": "#E4EBFF", "#222222": "#D2DCFA",
        "#333333": "#C2CDF0", "#444444": "#B4C0E6", "#555555": "#93A2CF",
        "#666666": "#8796C4", "#0A246A": "#8FB6FF", "#1F4E9E": "#8FB7FF",
        "#A00000": "#FF8FA8", "#1F5F1F": "#8FE0FF", "#00FF66": "#7FB8FF",
    }, {"bg": "#0E1631", "campo": "#0A1128", "texto": "#DCE5FF", "pestana": "#1C2A57",
        "pestana_sel": "#0E1631", "canal": "#2B3A6E", "acento": "#2F5FC4"}),

    "GameCube": _tema({
        "#ECE9D8": "#E7E3F6", "#0A246A": "#3F2F8F", "#316AC5": "#6550C4",
        "#E0DFE3": "#D8D1F1", "#D4D0C8": "#C9C0EA", "#FAFAFA": "#F7F5FD",
        "#F4F4F4": "#F0EDFA", "#E8E8E8": "#E2DCF5", "#C8E8C8": "#BDB0F2",
        "#D9F2D9": "#CFC6F5", "#D6E4FF": "#D3CCF6", "#DCE6F7": "#DDD6F7",
        "#050B05": "#0E0822", "#101010": "#120B2A", "#B0B0B0": "#A79BD6",
        "#F0F0F0": "#E7E3F7", "#D9D9D9": "#E7E3F8", "#7B4FA3": "#8A3FB0",
        "#B03A8C": "#C2408F", "#C0763A": "#D88A2E",
    }, {
        "#0A246A": "#3A2A86", "#1F4E9E": "#4A35A0", "#00FF66": "#C9B8FF",
    }, {"bg": "#E7E3F6", "campo": "#FFFFFF", "texto": "#1A1238", "pestana": "#D8D1F1",
        "pestana_sel": "#FFFFFF", "canal": "#A79BD6", "acento": "#6550C4"}),

    "Dreamcast": _tema({
        "#ECE9D8": "#F3F3F1", "#0A246A": "#E1601C", "#316AC5": "#EE8432",
        "#E0DFE3": "#E9E9E6", "#D4D0C8": "#DCDCD8", "#C8E8C8": "#FFD2AE",
        "#D9F2D9": "#FFDCC0", "#D6E4FF": "#FFE4CF", "#DCE6F7": "#FDE8D8",
        "#050B05": "#1A0A02", "#101010": "#1C0D04", "#B0B0B0": "#C9C5BE",
        "#F0F0F0": "#F3F3F2", "#D9D9D9": "#F3F3F3", "#7B4FA3": "#3D6CC0",
        "#B03A8C": "#2E8FC0", "#C0763A": "#D9481C",
    }, {
        "#0A246A": "#B5470F", "#1F4E9E": "#C2551A", "#00FF66": "#FF9A3C",
    }, {"bg": "#F3F3F1", "campo": "#FFFFFF", "texto": "#2A1A10", "pestana": "#E9E9E6",
        "pestana_sel": "#FFFFFF", "canal": "#C9C5BE", "acento": "#EE8432"}),
}


def nombres():
    return list(TEMAS)


def obtener(nombre):
    return TEMAS.get(nombre) or TEMAS[TEMA_POR_DEFECTO]


def _inverso(mapa):
    return {v: k for k, v in mapa.items()}


def traducir(color_hex, tipo, actual, nuevo):
    """Traduce un color (#RRGGBB en mayúsculas) del tema ``actual`` al ``nuevo``.

    tipo: "bg" o "fg". Función pura (se prueba sin Tk).
    """
    base = _inverso(obtener(actual)[tipo]).get(color_hex, color_hex)
    return obtener(nuevo)[tipo].get(base, base)


def color(base, nombre_tema, tipo="bg"):
    """Color equivalente a ``base`` (un color de Luna) en el tema indicado."""
    b = str(base).upper()
    return obtener(nombre_tema)[tipo].get(b, base)


class Tematizador:
    """Aplica temas a árboles de widgets Tk (y a los estilos ttk)."""

    def __init__(self, root, nombre=TEMA_POR_DEFECTO):
        self.root = root
        self.nombre = nombre if nombre in TEMAS else TEMA_POR_DEFECTO
        self._hex = {}
        self._inv = {"bg": {}, "fg": {}}
        self._actualizar_inversos()

    def _actualizar_inversos(self):
        t = obtener(self.nombre)
        self._inv = {"bg": _inverso(t["bg"]), "fg": _inverso(t["fg"])}

    def _a_hex(self, valor):
        h = self._hex.get(valor)
        if h is None:
            try:
                r, g, b = self.root.winfo_rgb(valor)
                h = f"#{r >> 8:02X}{g >> 8:02X}{b >> 8:02X}"
            except tk.TclError:
                h = ""
            self._hex[valor] = h
        return h

    def c(self, base, tipo="bg"):
        """Color del tema actual para un color base de Luna."""
        return color(base, self.nombre, tipo)

    def aplicar_arbol(self, widget, desde=None):
        """Traduce los colores de ``widget`` y sus hijos desde el tema ``desde`` (por
        defecto Luna: sirve para widgets recién creados con los colores base)."""
        if widget is None:
            return
        desde = desde or TEMA_POR_DEFECTO          # widgets nuevos: tienen colores de Luna
        origen = obtener(desde)
        actual_inv = {"bg": _inverso(origen["bg"]), "fg": _inverso(origen["fg"])}
        destino = obtener(self.nombre)
        if not destino["bg"] and not destino["fg"] and not origen["bg"] and not origen["fg"]:
            return          # Luna -> Luna: nada que hacer
        pila = [widget]
        while pila:
            w = pila.pop()
            try:
                pila.extend(w.winfo_children())
            except tk.TclError:
                continue
            cambios = {}
            for tipo, opciones in (("bg", BG_OPTS), ("fg", FG_OPTS)):
                for opt in opciones:
                    try:
                        val = w.cget(opt)
                    except (tk.TclError, AttributeError):
                        continue
                    if not val:
                        continue
                    actual = self._a_hex(str(val))
                    if not actual:
                        continue
                    base = actual_inv[tipo].get(actual, actual)
                    nuevo = destino[tipo].get(base, base)
                    if nuevo != actual:
                        cambios[opt] = nuevo
            if cambios:
                try:
                    w.configure(**cambios)
                except tk.TclError:
                    pass

    def cambiar(self, nombre, raices, style=None):
        """Cambia al tema ``nombre`` y lo aplica a todas las ventanas de ``raices``."""
        if nombre not in TEMAS:
            nombre = TEMA_POR_DEFECTO
        anterior = self.nombre
        self.nombre = nombre
        self._actualizar_inversos()
        for r in raices:
            try:
                if r is not None and r.winfo_exists():
                    self.aplicar_arbol(r, desde=anterior)
            except tk.TclError:
                pass
        if style is not None:
            self.estilo_ttk(style)

    def estilo_ttk(self, style):
        t = obtener(self.nombre)["ttk"]
        try:
            style.configure("TScale", background=t["bg"], troughcolor=t["canal"])
            style.configure("Horizontal.TScale", background=t["bg"], troughcolor=t["canal"])
            style.configure("TNotebook", background=t["bg"], borderwidth=1)
            style.configure("TNotebook.Tab", background=t["pestana"], foreground=t["texto"],
                            padding=(8, 3))
            style.map("TNotebook.Tab",
                      background=[("selected", t["pestana_sel"])],
                      foreground=[("selected", t["texto"])])
            style.configure("TCombobox", fieldbackground=t["campo"], background=t["pestana"],
                            foreground=t["texto"], arrowcolor=t["texto"])
            style.map("TCombobox", fieldbackground=[("readonly", t["campo"])],
                      foreground=[("readonly", t["texto"])],
                      selectbackground=[("readonly", t["campo"])],
                      selectforeground=[("readonly", t["texto"])])
            style.configure("TProgressbar", background=t["acento"], troughcolor=t["canal"])
            style.configure("TCheckbutton", background=t["bg"], foreground=t["texto"])
        except tk.TclError:
            pass
        try:   # la lista desplegable del Combobox es un Listbox clásico
            self.root.option_add("*TCombobox*Listbox.background", t["campo"])
            self.root.option_add("*TCombobox*Listbox.foreground", t["texto"])
        except tk.TclError:
            pass
