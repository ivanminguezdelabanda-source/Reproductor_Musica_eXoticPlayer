"""eXotic Wrapped: resumen mensual/anual de lo que has escuchado, como imagen vertical.

Datos: ``cloud_data["monthly"]["2026-10"] = {
    "plays": 123, "secs": 23456,
    "songs": {videoId: [veces, título, artista, portada]},
    "artists": {artista: veces},
    "days": {"08": segundos, ...}}``
Se guarda poco (un resumen por mes, máx. 24 meses y 400 canciones por mes), así la
sincronización con la nube sigue siendo ligera.
"""
import calendar
from collections import Counter
from datetime import datetime

MESES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre")
MAX_MESES = 24
MAX_CANCIONES_MES = 400


def _mes(datos, fecha):
    meses = datos.setdefault("monthly", {})
    if not isinstance(meses, dict):
        meses = datos["monthly"] = {}
    clave = fecha.strftime("%Y-%m")
    m = meses.get(clave)
    if not isinstance(m, dict):
        m = meses[clave] = {"plays": 0, "secs": 0, "songs": {}, "artists": {}, "days": {}}
        for viejo in sorted(meses)[:-MAX_MESES]:          # poda: últimos 24 meses
            meses.pop(viejo, None)
    for k, v in (("plays", 0), ("secs", 0), ("songs", {}), ("artists", {}), ("days", {})):
        m.setdefault(k, v)
    return m


def primer_artista(artista):
    return (str(artista or "").split(",")[0].split(" & ")[0].strip()) or "Desconocido"


def contar_reproduccion(datos, cancion, fecha=None):
    """Una canción empieza a sonar."""
    fecha = fecha or datetime.now()
    vid = (cancion or {}).get("videoId")
    if not vid:
        return
    m = _mes(datos, fecha)
    m["plays"] += 1
    fila = m["songs"].get(vid)
    if not isinstance(fila, list) or len(fila) < 4:
        fila = [0, cancion.get("title", ""), cancion.get("artist", ""), cancion.get("coverUrl")]
    fila[0] += 1
    m["songs"][vid] = fila
    art = primer_artista(cancion.get("artist"))
    m["artists"][art] = m["artists"].get(art, 0) + 1
    if len(m["songs"]) > MAX_CANCIONES_MES:
        sobran = sorted(m["songs"].items(), key=lambda kv: kv[1][0])[:len(m["songs"]) - MAX_CANCIONES_MES]
        for k, _ in sobran:
            m["songs"].pop(k, None)


def sumar_tiempo(datos, segundos, fecha=None):
    """Tiempo realmente escuchado (solo cuenta mientras suena)."""
    if segundos <= 0:
        return
    fecha = fecha or datetime.now()
    m = _mes(datos, fecha)
    m["secs"] = int(m["secs"] + segundos)
    dia = fecha.strftime("%d")
    m["days"][dia] = int(m["days"].get(dia, 0) + segundos)


def periodos_disponibles(ahora=None):
    ahora = ahora or datetime.now()
    este = ahora.strftime("%Y-%m")
    anterior = (ahora.replace(day=1) - __import__("datetime").timedelta(days=1)).strftime("%Y-%m")
    return [(este, f"{MESES[ahora.month - 1]} {ahora.year}"),
            (anterior, f"{MESES[int(anterior[5:]) - 1]} {anterior[:4]}"),
            (str(ahora.year), f"Todo {ahora.year}")]


def resumen(datos, periodo, historial=None):
    """Junta los meses del periodo ("2026-10" o "2026"). Si no hay datos mensuales todavía,
    usa el historial (aproximado) para que el primer Wrapped no salga vacío."""
    meses = datos.get("monthly") if isinstance(datos.get("monthly"), dict) else {}
    claves = [k for k in meses if k == periodo or (len(periodo) == 4 and k.startswith(periodo + "-"))]
    canciones = {}
    artistas = Counter()
    dias = Counter()
    plays = secs = 0
    for clave in claves:
        m = meses[clave]
        plays += int(m.get("plays", 0))
        secs += int(m.get("secs", 0))
        for vid, fila in (m.get("songs") or {}).items():
            if vid in canciones:
                canciones[vid][0] += fila[0]
            else:
                canciones[vid] = list(fila)
        artistas.update(m.get("artists") or {})
        for d, s in (m.get("days") or {}).items():
            dias[f"{clave}-{d}"] += s
    aproximado = False
    if not canciones and historial:
        aproximado = True
        for h in historial:
            if str(h.get("lastPlayed", "")).startswith(periodo):
                n = int(h.get("playCount", 0) or 0)
                canciones[h.get("videoId")] = [n, h.get("title", ""), h.get("artist", ""), h.get("coverUrl")]
                artistas[primer_artista(h.get("artist"))] += n
                plays += n
        secs = plays * 210                                   # ~3,5 min por canción
    top = sorted(canciones.values(), key=lambda f: -f[0])
    mejor_dia = None
    if dias:
        clave, s = dias.most_common(1)[0]
        try:
            f = datetime.strptime(clave, "%Y-%m-%d")
            mejor_dia = (f"{f.day} de {MESES[f.month - 1].lower()}", int(s // 60))
        except ValueError:
            pass
    return {
        "periodo": periodo,
        "minutos": int(secs // 60),
        "reproducciones": plays,
        "canciones": len(canciones),
        "artistas": len(artistas),
        "top_canciones": [(f[1], f[2], f[0], f[3]) for f in top[:5]],
        "top_artistas": artistas.most_common(5),
        "mejor_dia": mejor_dia,
        "aproximado": aproximado,
    }


def nombre_periodo(periodo):
    if len(periodo) == 4:
        return f"Todo {periodo}"
    año, mes = periodo.split("-")
    return f"{MESES[int(mes) - 1]} {año}"


# ---------------------------------------------------------------------------
# Imagen 1080×1920 (formato historia) con estética Windows XP
# ---------------------------------------------------------------------------
def _fuente(tam, negrita=False):
    from PIL import ImageFont
    nombres = (["tahomabd.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"] if negrita
               else ["tahoma.ttf", "segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"])
    for n in nombres:
        try:
            return ImageFont.truetype(n, tam)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=tam)
    except TypeError:
        return ImageFont.load_default()


def _recortar(d, texto, fuente, ancho):
    texto = str(texto or "")
    if d.textlength(texto, font=fuente) <= ancho:
        return texto
    while texto and d.textlength(texto + "…", font=fuente) > ancho:
        texto = texto[:-1]
    return texto.rstrip() + "…"


def generar_imagen(res, portada=None, usuario=""):
    """Devuelve una imagen PIL 1080×1920 con el resumen."""
    from PIL import Image, ImageDraw
    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), (58, 110, 165))
    d = ImageDraw.Draw(img)
    # fondo "Bliss" simplificado: cielo + colina
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=(int(40 + 90 * k), int(100 + 90 * k), int(200 + 40 * k)))
    d.ellipse([-400, 1450, 1500, 2600], fill=(70, 150, 40))
    d.ellipse([-200, 1520, 1300, 2500], fill=(95, 175, 55))

    # ventana XP
    x0, y0, x1, y1 = 60, 110, W - 60, H - 150
    d.rounded_rectangle([x0 + 8, y0 + 10, x1 + 8, y1 + 10], 18, fill=(20, 40, 80))     # sombra
    d.rounded_rectangle([x0, y0, x1, y1], 18, fill=(236, 233, 216), outline=(0, 60, 180), width=4)
    for i in range(90):                                                               # barra de título
        k = i / 90
        col = (int(0 + 60 * (1 - abs(k - 0.25) * 2)), int(84 + 60 * (1 - k)), int(227 - 30 * k))
        d.line([(x0 + 4, y0 + 4 + i), (x1 - 4, y0 + 4 + i)], fill=col)
    d.text((x0 + 30, y0 + 22), "eXotic Wrapped", font=_fuente(44, True), fill="white")
    for i, c in enumerate(((60, 120, 255), (60, 120, 255), (225, 70, 40))):           # botones _ □ ×
        bx = x1 - 70 - (2 - i) * 62
        d.rounded_rectangle([bx, y0 + 20, bx + 52, y0 + 72], 8, fill=c, outline="white", width=3)
    d.text((x1 - 54, y0 + 22), "×", font=_fuente(40, True), fill="white")

    cx = x0 + 50
    y = y0 + 130
    d.text((cx, y), nombre_periodo(res["periodo"]), font=_fuente(70, True), fill=(10, 36, 106))
    y += 92
    sub = f"La música de {usuario}" if usuario else "Tu música en eXotic Player"
    d.text((cx, y), sub, font=_fuente(36), fill=(80, 80, 80))
    y += 80

    # tarjetas de números
    tarjetas = (("minutos", "minutos escuchados"), ("reproducciones", "reproducciones"),
                ("canciones", "canciones distintas"), ("artistas", "artistas"))
    tw = (x1 - x0 - 100 - 30) // 2
    for i, (clave, texto) in enumerate(tarjetas):
        tx = cx + (i % 2) * (tw + 30)
        ty = y + (i // 2) * 190
        d.rounded_rectangle([tx, ty, tx + tw, ty + 170], 12, fill="white", outline=(127, 157, 185), width=3)
        d.text((tx + 28, ty + 18), f"{res[clave]:,}".replace(",", "."), font=_fuente(72, True), fill=(0, 84, 227))
        d.text((tx + 30, ty + 112), texto, font=_fuente(32), fill=(70, 70, 70))
    y += 400

    # top canciones
    d.text((cx, y), "Tus canciones más escuchadas", font=_fuente(40, True), fill=(10, 36, 106))
    y += 64
    caja_x1 = x1 - 50
    if portada is not None:
        p = portada.convert("RGB").resize((210, 210))
        img.paste(p, (caja_x1 - 210, y + 6))
        d.rectangle([caja_x1 - 212, y + 4, caja_x1 + 2, y + 218], outline=(127, 157, 185), width=3)
        ancho_txt = caja_x1 - 230 - cx - 80
    else:
        ancho_txt = caja_x1 - cx - 80
    if not res["top_canciones"]:
        d.text((cx, y), "Aún no hay datos de este periodo.", font=_fuente(34), fill=(90, 90, 90))
    for i, (titulo, artista, veces, _) in enumerate(res["top_canciones"]):
        d.text((cx, y), f"{i + 1}", font=_fuente(52, True), fill=(0, 84, 227))
        d.text((cx + 64, y + 2), _recortar(d, titulo, _fuente(36, True), ancho_txt), font=_fuente(36, True), fill=(20, 20, 20))
        d.text((cx + 64, y + 46), _recortar(d, f"{artista} · {veces}×", _fuente(28), ancho_txt), font=_fuente(28), fill=(100, 100, 100))
        y += 98
    y = max(y, y0 + 1290) + 10

    # top artistas
    d.text((cx, y), "Tus artistas", font=_fuente(40, True), fill=(10, 36, 106))
    y += 64
    for i, (art, veces) in enumerate(res["top_artistas"][:5]):
        maximo = res["top_artistas"][0][1] or 1
        largo = int((x1 - x0 - 420) * veces / maximo)
        d.rounded_rectangle([cx + 330, y + 8, cx + 330 + max(20, largo), y + 40], 8, fill=(80, 170, 60))
        d.text((cx, y), _recortar(d, art, _fuente(32, True), 310), font=_fuente(32, True), fill=(20, 20, 20))
        y += 56
    if res.get("mejor_dia") and res["mejor_dia"][1] > 0:
        dia, mins = res["mejor_dia"]
        d.text((cx, y1 - 110), f"Tu día más musical: {dia} ({mins} min)", font=_fuente(30), fill=(70, 70, 70))
    if res.get("aproximado"):
        d.text((cx, y1 - 64), "* Calculado con tu historial (aproximado)", font=_fuente(24), fill=(120, 120, 120))

    # barra de tareas
    d.rectangle([0, H - 80, W, H], fill=(36, 94, 220))
    d.rounded_rectangle([0, H - 80, 250, H], 20, fill=(60, 160, 60))
    d.text((40, H - 66), "inicio", font=_fuente(44, True), fill="white")
    d.text((W - 360, H - 62), "eXotic Media Player", font=_fuente(32, True), fill="white")
    return img


def ultimo_dia(periodo):
    año, mes = int(periodo[:4]), int(periodo[5:7])
    return calendar.monthrange(año, mes)[1]
