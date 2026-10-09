"""Animación de arranque de eXotic Player (estilo Aero / Windows XP, versión limpia).

Cada fotograma se compone con PIL (degradados, brillos y transparencias suaves) y se
pinta en un único lienzo, así queda mucho más fino que con formas de Tk.

Secuencia:
  1. Fundido de entrada: fondo azul con luz y burbujas, y el mono aterriza con un rebote.
  2. Se construye el programa (la animación espera en el logo, sin añadir tiempo).
  3. El nombre sube con un fundido, un destello de luz lo recorre, aparece la versión
     y la barra de carga de XP con sus tres bloques.
  4. Fundido de salida y aparece la ventana principal.

Se salta con un clic o Esc (a partir del primer segundo). Se desactiva en
Configuración → Apariencia.
"""
import math
import random
import tkinter as tk

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageTk

try:
    _RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:
    _RESAMPLE = Image.LANCZOS

W, H = 600, 360
FONDO_RGB = (7, 26, 74)          # azul marino de la ventana (desde aquí se hacen los fundidos)
FONDO_TK = "#071A4A"
EVENTOS = []                     # (instante, qué) — lo usa la prueba automática de arranque
FRASES = ("Preparando tu música…", "Afinando los auriculares…", "Buscando joyitas ocultas…",
          "Calentando los altavoces…")


# ---------------------------------------------------------------------------
# utilidades
# ---------------------------------------------------------------------------
def _suave(k):
    k = max(0.0, min(1.0, k))
    return k * k * (3 - 2 * k)


def _rebote(k):
    """easeOutBack: llega a 1 pasándose un poco."""
    k = max(0.0, min(1.0, k))
    c = 1.70158
    return 1 + (c + 1) * (k - 1) ** 3 + c * (k - 1) ** 2


def _fuente(tam, peso="normal"):
    nombres = {
        "negrita": ["segoeuib.ttf", "tahomabd.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
        "fina": ["segoeuil.ttf", "segoeui.ttf", "tahoma.ttf", "arial.ttf", "DejaVuSans.ttf"],
        "normal": ["segoeui.ttf", "tahoma.ttf", "arial.ttf", "DejaVuSans.ttf"],
    }[peso]
    for n in nombres:
        try:
            return ImageFont.truetype(n, tam)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=tam)
    except TypeError:
        return ImageFont.load_default()


def _con_alpha(img, k):
    """Copia de una imagen RGBA con su opacidad multiplicada por k."""
    if k >= 0.999:
        return img
    r, g, b, a = img.split()
    a = a.point(lambda v: int(v * max(0.0, k)))
    return Image.merge("RGBA", (r, g, b, a))


def _fondo():
    """Degradado azul Aero con haces de luz, brillo superior y una curva luminosa abajo."""
    import numpy as np
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    k = np.clip((xx / W) * 0.35 + (yy / H) * 0.65, 0, 1)[:, :, None]
    arriba = np.array([18, 74, 178], dtype=np.float32)
    abajo = np.array([6, 26, 82], dtype=np.float32)
    rgb = arriba * (1 - k) + abajo * k
    # luz suave arriba a la izquierda
    d = np.sqrt(((xx - W * 0.28) / W) ** 2 + ((yy - H * 0.05) / H) ** 2)
    rgb += (np.exp(-d * 3.2) * 70)[:, :, None] * np.array([0.6, 0.85, 1.0], dtype=np.float32)
    img = Image.fromarray(np.clip(rgb, 0, 255).astype("uint8"), "RGB").convert("RGBA")

    capa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dc = ImageDraw.Draw(capa)
    # haces de luz diagonales
    for x, ancho, a in ((120, 60, 26), (230, 34, 20), (420, 80, 16)):
        dc.polygon([(x, -10), (x + ancho, -10), (x + ancho - 220, H + 10), (x - 220, H + 10)],
                   fill=(255, 255, 255, a))
    # curvas luminosas (estilo fondo de Vista/XP)
    dc.ellipse([-260, H - 120, W + 260, H + 360], outline=(140, 210, 255, 90), width=3)
    dc.ellipse([-200, H - 92, W + 320, H + 400], outline=(110, 230, 190, 60), width=2)
    capa = capa.filter(ImageFilter.GaussianBlur(6))
    img = Image.alpha_composite(img, capa)
    # brillo de cristal arriba que se desvanece hacia abajo (sin cortes)
    alfa = np.clip(1 - yy / (H * 0.55), 0, 1) ** 1.6 * 22
    brillo = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    brillo.putalpha(Image.fromarray(alfa.astype("uint8"), "L"))
    img = Image.alpha_composite(img, brillo)
    # borde fino
    ImageDraw.Draw(img).rectangle([0, 0, W - 1, H - 1], outline=(150, 200, 255, 140), width=1)
    return img


def _burbuja(diam):
    b = Image.new("RGBA", (diam, diam), (0, 0, 0, 0))
    d = ImageDraw.Draw(b)
    d.ellipse([0, 0, diam - 1, diam - 1], fill=(255, 255, 255, 22), outline=(255, 255, 255, 70))
    r = max(2, diam // 4)
    d.ellipse([diam * 0.22, diam * 0.16, diam * 0.22 + r, diam * 0.16 + r * 0.7], fill=(255, 255, 255, 120))
    return b.filter(ImageFilter.GaussianBlur(0.6))


def _texto(texto, fuente, color=(255, 255, 255, 255), sombra=True):
    caja = fuente.getbbox(texto)
    w, h = caja[2] - caja[0] + 12, caja[3] - caja[1] + 14
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if sombra:
        s = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(s).text((6 - caja[0], 8 - caja[1]), texto, font=fuente, fill=(0, 20, 60, 150))
        img = Image.alpha_composite(img, s.filter(ImageFilter.GaussianBlur(2.5)))
        d = ImageDraw.Draw(img)
    d.text((6 - caja[0], 6 - caja[1]), texto, font=fuente, fill=color)
    return img


# ---------------------------------------------------------------------------
class SplashXP:
    FPS_MS = 16

    def __init__(self, root, icono, version=""):
        self.root = root
        self.icono = icono
        self.version = version
        self._terminado = False
        self._saltar = False
        self.win = None

    # ------------------------------------------------------------------
    def iniciar(self, cargar, al_terminar, sonido=None):
        """cargar(): construye la app (bloquea un momento). al_terminar(): muestra la principal."""
        self._cargar, self._al_terminar, self._sonido = cargar, al_terminar, sonido
        try:
            self._preparar()
            self._crear_ventana()
        except Exception as e:                      # si algo falla, se arranca sin animación
            print(f"Splash: {e}")
            self._destruir()
            cargar()
            al_terminar()
            return
        self._fase_entrada()

    def _preparar(self):
        self.bg = _fondo()
        # logo + halo
        try:
            base = Image.open(self.icono)
            try:
                base.size = max(base.ico.sizes())
            except Exception:
                pass
            base = base.convert("RGBA")
        except Exception:
            base = Image.new("RGBA", (128, 128), (31, 79, 209, 255))
        # el icono trae esquinas blancas: se recorta con esquinas redondeadas limpias
        lado = base.width
        m = Image.new("L", (lado * 4, lado * 4), 0)
        ImageDraw.Draw(m).rounded_rectangle([lado * 0.04 * 4, lado * 0.04 * 4, lado * 0.96 * 4, lado * 0.96 * 4],
                                            lado * 0.22 * 4, fill=255)
        m = m.resize((lado, lado), _RESAMPLE)                  # borde suavizado
        base.putalpha(ImageChops.multiply(base.getchannel("A"), m))
        brillo = Image.new("RGBA", base.size, (0, 0, 0, 0))     # reflejo de cristal arriba
        ImageDraw.Draw(brillo).rounded_rectangle([lado * 0.08, lado * 0.06, lado * 0.92, lado * 0.42],
                                                 lado * 0.16, fill=(255, 255, 255, 38))
        brillo.putalpha(ImageChops.multiply(brillo.getchannel("A"), m))
        base = Image.alpha_composite(base, brillo)
        self.logo_base = base
        self.lado_logo = 124
        halo = Image.new("RGBA", (220, 220), (0, 0, 0, 0))
        ImageDraw.Draw(halo).ellipse([30, 30, 190, 190], fill=(160, 220, 255, 120))
        self.halo = halo.filter(ImageFilter.GaussianBlur(26))
        sombra = Image.new("RGBA", (180, 40), (0, 0, 0, 0))
        ImageDraw.Draw(sombra).ellipse([30, 12, 150, 30], fill=(0, 10, 40, 110))
        self.sombra = sombra.filter(ImageFilter.GaussianBlur(6))
        self._logos = {}
        # textos
        self.t_eXotic = _texto("eXotic", _fuente(40, "negrita"))
        self.t_media = _texto(" Media Player", _fuente(40, "fina"), (220, 236, 255, 255))
        titulo = Image.new("RGBA", (self.t_eXotic.width + self.t_media.width - 12,
                                    max(self.t_eXotic.height, self.t_media.height)), (0, 0, 0, 0))
        titulo.alpha_composite(self.t_eXotic, (0, 0))
        titulo.alpha_composite(self.t_media, (self.t_eXotic.width - 12, 0))
        self.titulo = titulo
        # pastilla de versión
        txt = _texto(f"versión {self.version}" if self.version else "Pro", _fuente(13, "negrita"),
                     (255, 255, 255, 255), sombra=False)
        pill = Image.new("RGBA", (txt.width + 16, txt.height), (0, 0, 0, 0))
        dp = ImageDraw.Draw(pill)
        dp.rounded_rectangle([0, 0, pill.width - 1, pill.height - 1], pill.height // 2,
                             fill=(245, 150, 30, 235), outline=(255, 210, 140, 255))
        dp.rounded_rectangle([3, 2, pill.width - 4, pill.height // 2], pill.height // 3, fill=(255, 255, 255, 50))
        pill.alpha_composite(txt, (8, -2))
        self.version_img = pill
        # barra de carga (cápsula de cristal)
        self.barra_w, self.barra_h = 200, 16
        cap = Image.new("RGBA", (self.barra_w, self.barra_h), (0, 0, 0, 0))
        dcap = ImageDraw.Draw(cap)
        dcap.rounded_rectangle([0, 0, self.barra_w - 1, self.barra_h - 1], 8,
                               fill=(4, 18, 60, 170), outline=(170, 210, 255, 200))
        self.barra = cap
        mascara = Image.new("L", (self.barra_w, self.barra_h), 0)
        ImageDraw.Draw(mascara).rounded_rectangle([2, 2, self.barra_w - 3, self.barra_h - 3], 6, fill=255)
        self.barra_mascara = mascara
        bloque = Image.new("RGBA", (11, self.barra_h - 4), (0, 0, 0, 0))
        db = ImageDraw.Draw(bloque)
        for y in range(bloque.height):
            k = y / max(1, bloque.height - 1)
            col = (int(70 + 60 * (1 - k)), int(150 + 80 * (1 - k)), 255, 255)
            db.line([(0, y), (10, y)], fill=col)
        db.line([(1, 1), (9, 1)], fill=(255, 255, 255, 170))
        self.bloque = bloque
        # burbujas
        self.sprites = {d: _burbuja(d) for d in (10, 16, 24, 34)}
        self.burbujas = [[random.uniform(0, W), random.uniform(0, H), random.choice(list(self.sprites)),
                          random.uniform(8, 22), random.uniform(0, 6.28)] for _ in range(10)]
        self.fuente_frase = _fuente(12)
        self._frase_img = None
        self._frase_txt = None
        self.liso = Image.new("RGB", (W, H), FONDO_RGB)

    def _logo(self, lado):
        lado = max(8, int(lado))
        img = self._logos.get(lado)
        if img is None:
            img = self.logo_base.resize((lado, lado), _RESAMPLE)
            self._logos[lado] = img
        return img

    def _crear_ventana(self):
        # Sin transparencias de ventana (-alpha / -transparentcolor): en algunos Windows hacían
        # que la animación se viera un instante y desapareciera. Los fundidos se hacen dentro
        # de la propia imagen, que funciona igual en todos los equipos.
        w = self.win = tk.Toplevel(self.root)
        w.overrideredirect(True)
        try:
            w.attributes("-topmost", True)
        except tk.TclError:
            pass
        w.configure(bg=FONDO_TK)
        x = (w.winfo_screenwidth() - W) // 2
        y = (w.winfo_screenheight() - H) // 2
        w.geometry(f"{W}x{H}+{x}+{y}")
        self.c = tk.Canvas(w, width=W, height=H, highlightthickness=0, bd=0, bg=FONDO_TK)
        self.c.pack()
        self.foto = ImageTk.PhotoImage(Image.new("RGB", (W, H), FONDO_RGB))
        self.c.create_image(0, 0, image=self.foto, anchor="nw")
        # Solo clic o Esc, y nunca en el primer segundo: la tecla/clic con el que se abrió
        # el programa no debe saltarse la animación sin querer.
        import time as _time
        self._t_creada = _time.monotonic()

        def saltar(_e=None):
            if _time.monotonic() - self._t_creada > 1.0:
                self._saltar = True
        for ev in ("<ButtonRelease-1>", "<Escape>"):
            w.bind(ev, saltar)
        w.deiconify()
        w.lift()
        try:
            w.focus_force()
        except tk.TclError:
            pass
        self.t = 0.0
        self.fundido = 0.0           # 0 = todo del color de fondo, 1 = imagen completa
        self._log("ventana creada")

    # ------------------------------------------------------------------ dibujo
    def _componer(self, logo_k=1.0, logo_escala=1.0, titulo_k=0.0, version_k=0.0, barra_k=0.0,
                  destello=None, frase=None, frase_k=0.0, latido=0.0):
        img = self.bg.copy()
        # burbujas que suben despacio
        for b in self.burbujas:
            x = b[0] + math.sin(self.t * 0.9 + b[4]) * 6
            y = b[1] - (self.t * b[3]) % (H + 60)
            if y < -40:
                y += H + 60
            img.alpha_composite(self.sprites[b[2]], (int(x), int(y)))
        cx, cy = W // 2, 118
        # halo + sombra + logo
        if logo_k > 0:
            halo = _con_alpha(self.halo, logo_k * (0.75 + 0.25 * math.sin(self.t * 2.2)))
            img.alpha_composite(halo, (cx - halo.width // 2, cy - halo.height // 2))
            sombra = _con_alpha(self.sombra, logo_k)
            img.alpha_composite(sombra, (cx - sombra.width // 2, cy + 50))
            lado = self.lado_logo * logo_escala * (1 + 0.025 * latido)
            logo = _con_alpha(self._logo(lado), logo_k)
            img.alpha_composite(logo, (int(cx - logo.width / 2), int(cy - logo.height / 2)))
        # título (sube 14 px mientras aparece) + destello de luz
        if titulo_k > 0:
            ty = int(212 + 14 * (1 - _suave(titulo_k)))
            tx = (W - self.titulo.width) // 2
            img.alpha_composite(_con_alpha(self.titulo, _suave(titulo_k)), (tx, ty))
            if destello is not None and 0 <= destello <= 1:
                # barrido de luz por toda la tarjeta, a la altura del título
                k = math.sin(destello * math.pi)
                bx = int(-80 + (W + 160) * _suave(destello))
                luz = Image.new("L", (W, H), 0)
                ImageDraw.Draw(luz).polygon([(bx, 150), (bx + 46, 150), (bx - 34, 330), (bx - 80, 330)],
                                            fill=int(70 * k))
                luz = luz.filter(ImageFilter.GaussianBlur(14))
                blanco = Image.new("RGBA", (W, H), (255, 255, 255, 0))
                blanco.putalpha(luz)
                img.alpha_composite(blanco)
        if version_k > 0:
            v = _con_alpha(self.version_img, _suave(version_k))
            img.alpha_composite(v, ((W - v.width) // 2, 266))
        if barra_k > 0:
            bx, by = (W - self.barra_w) // 2, 300
            barra = self.barra.copy()
            ancho, hueco = self.bloque.width, 3
            recorrido = self.barra_w + 3 * (ancho + hueco)
            cabeza = -3 * (ancho + hueco) + (self.t * 170) % recorrido
            bloques = Image.new("RGBA", barra.size, (0, 0, 0, 0))
            for i in range(3):
                self._bloque_recortado(bloques, int(cabeza + i * (ancho + hueco)))
            bloques.putalpha(ImageChops.multiply(bloques.getchannel("A"), self.barra_mascara))
            barra.alpha_composite(bloques)
            img.alpha_composite(_con_alpha(barra, _suave(barra_k)), (bx, by))
        if frase and frase_k > 0:
            if frase != self._frase_txt:
                self._frase_txt = frase
                self._frase_img = _texto(frase, self.fuente_frase, (190, 220, 255, 255), sombra=False)
            f = _con_alpha(self._frase_img, frase_k)
            img.alpha_composite(f, ((W - f.width) // 2, H - 36))
        rgb = img.convert("RGB")
        if self.fundido < 0.999:
            rgb = Image.blend(self.liso, rgb, max(0.0, self.fundido))
        self.foto.paste(rgb)

    def _bloque_recortado(self, destino, x):
        """Bloque que entra o sale por los bordes de la barra."""
        ancho = self.bloque.width
        if x + ancho <= 0 or x >= self.barra_w:
            return
        izq = max(0, -x)
        der = min(ancho, self.barra_w - x)
        destino.alpha_composite(self.bloque.crop((izq, 0, der, self.bloque.height)), (x + izq, 2))

    def _alpha(self, a):
        """Fundido de toda la imagen (sustituye a la transparencia de ventana)."""
        self.fundido = max(0.0, min(1.0, a))

    @staticmethod
    def _log(msg):
        import time as _time
        EVENTOS.append((round(_time.monotonic(), 3), msg))
        print(f"[splash] {msg}")

    def _vivo(self):
        try:
            return self.win is not None and self.win.winfo_exists()
        except tk.TclError:
            return False

    def _paso(self):
        self.t += self.FPS_MS / 1000.0

    # ------------------------------------------------------------------ fases
    def _fase_entrada(self, paso=0):
        """~0,5 s: fundido de entrada y el mono aterriza con un rebote."""
        if not self._vivo():
            return
        pasos = 30
        k = paso / pasos
        self._paso()
        self._alpha(_suave(k * 1.5))
        self._componer(logo_k=_suave(k * 1.4), logo_escala=0.55 + 0.45 * _rebote(k),
                       frase="Cargando eXotic…", frase_k=_suave(k))
        if paso < pasos and not self._saltar:
            self.win.after(self.FPS_MS, lambda: self._fase_entrada(paso + 1))
            return
        self._alpha(1.0)
        self._componer(logo_k=1.0, frase="Cargando eXotic…", frase_k=1.0)
        self.win.update_idletasks()
        self._log("entrada terminada, cargando la app")
        self.win.after(10, self._fase_carga)

    def _fase_carga(self):
        """Aquí se construye la app (la animación espera quieta en el logo)."""
        try:
            self._cargar()
        except Exception:
            self._destruir()
            raise
        if self._sonido:
            try:
                self._sonido()
            except Exception:
                pass
        if not self._vivo():
            self._log("la ventana desapareció durante la carga")
            self._fin()
            return
        if self._saltar:
            self._log("saltada por el usuario")
            self._fin()
            return
        try:                                  # por si algo de la app la tapó al cargar
            self.win.deiconify()
            self.win.lift()
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass
        self._log("app cargada, sigue la animación")
        self._frase = random.choice(FRASES)
        self._fase_titulo()

    def _fase_titulo(self, paso=0):
        """~1,6 s: título, destello, versión y barra de carga."""
        if not self._vivo():
            self._fin()
            return
        self._paso()
        total = 96
        self._componer(
            logo_k=1.0,
            titulo_k=paso / 22,
            destello=(paso - 26) / 30 if 26 <= paso <= 56 else None,
            version_k=(paso - 30) / 14,
            barra_k=(paso - 36) / 12,
            frase=self._frase,
            frase_k=1.0,
            latido=max(0.0, math.sin(self.t * 8.0)) if paso > 30 else 0.0,
        )
        if paso < total and not self._saltar:
            self.win.after(self.FPS_MS, lambda: self._fase_titulo(paso + 1))
        else:
            self._fase_salida()

    def _fase_salida(self, paso=0):
        if not self._vivo():
            self._fin()
            return
        pasos = 16
        self._paso()
        self._alpha(1 - _suave(paso / pasos))
        self._componer(logo_k=1.0, titulo_k=1.0, version_k=1.0, barra_k=1.0,
                       frase=self._frase, frase_k=1.0)
        if paso < pasos and not self._saltar:
            self.win.after(self.FPS_MS, lambda: self._fase_salida(paso + 1))
        else:
            self._fin()

    def _fin(self):
        if self._terminado:
            return
        self._terminado = True
        self._log("fin")
        self._destruir()
        self._al_terminar()

    def _destruir(self):
        try:
            if self.win is not None:
                self.win.destroy()
        except tk.TclError:
            pass
        self.win = None
