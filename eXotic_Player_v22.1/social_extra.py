"""Amigos y Jam · funciones de la v22.

  💬 Chat de la jam, reacciones que flotan sobre el reproductor y "votar para saltar"
     (si vota la mitad de la jam, la canción se salta).
  🎧 Actividad de amigos: qué está escuchando cada uno ahora (doble clic para ponerla).
  📀 Playlists colaborativas: playlists que editas con tus amigos.

Necesita ``supabase_actualizacion_v22.sql`` en Supabase.
"""
import random
import time
import tkinter as tk
from datetime import datetime, timezone
from tkinter import messagebox, simpledialog

from jam_logic import votos_necesarios, votos_para

REACCIONES = ("🔥", "❤", "😂", "👏", "🎉", "😮")
MAX_MENSAJES = 200


def hace_cuanto(iso):
    """'ahora', 'hace 3 min', 'hace 1 h'…"""
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        s = (datetime.now(timezone.utc) - t).total_seconds()
    except (TypeError, ValueError):
        return ""
    if s < 90:
        return "ahora"
    if s < 3600:
        return f"hace {int(s // 60)} min"
    return f"hace {int(s // 3600)} h"


# ===========================================================================
# Lógica (se mezcla en SocialManager)
# ===========================================================================
class SocialExtrasMixin:
    def _reset_extras(self):
        self.mensajes = []
        self._ultimo_msg = 0
        self._msg_en_curso = False
        self._saltadas = set()
        self._n_miembros = 1

    # ------------------------------------------------------------ chat / reacciones / votos
    def _poll_mensajes(self):
        if self._msg_en_curso or not self.en_jam:
            return
        self._msg_en_curso = True
        jam_id, desde = self.jam_id, self._ultimo_msg

        def ok(filas):
            self._msg_en_curso = False
            if jam_id != self.jam_id:
                return
            self._mensajes_recibidos(filas or [], primera=(desde == 0))

        def err(_e):
            self._msg_en_curso = False

        self.run(lambda: self.app.cloud.jam_mensajes(jam_id, desde), ok, err=err)

    def _mensajes_recibidos(self, filas, primera=False):
        if not filas:
            self._comprobar_votos()
            return
        yo = self.app.cloud.user_id
        self.mensajes.extend(filas)
        del self.mensajes[:-MAX_MENSAJES]
        self._ultimo_msg = max(int(f.get("id") or 0) for f in filas)
        for f in filas:
            if primera:
                continue                        # al entrar no repetimos lo antiguo
            if f.get("kind") == "reaction":
                self.app.mostrar_reaccion(f.get("body", "✨"))
            elif f.get("kind") == "chat" and f.get("user_id") != yo:
                self.app.status_var.set(f"💬 {f.get('nombre', '?').split('#')[0]}: {f.get('body', '')}"[:160])
                d = self._dialogo()
                if d is None or not d.chat_visible():
                    self.app.sonar("aviso")
            elif f.get("kind") == "vote" and f.get("user_id") != yo:
                self.app.status_var.set(f"⏭ {f.get('nombre', '?').split('#')[0]} quiere saltar esta canción.")
        d = self._dialogo()
        if d:
            d.pintar_chat()
        self._comprobar_votos()

    def _vid_jam(self):
        o = getattr(self, "_objetivo", None)
        return (o or {}).get("vid") or self._vid_cargado

    def votos_actuales(self):
        vid = self._vid_jam()
        return (len(votos_para(self.mensajes, vid)) if vid else 0), votos_necesarios(self._n_miembros)

    def _comprobar_votos(self):
        vid = self._vid_jam()
        if not vid or not self.en_jam:
            return
        n, necesarios = self.votos_actuales()
        d = self._dialogo()
        if d:
            d.pintar_votos()
        # solo el anfitrión salta (así no lo hacen dos personas a la vez)
        if self.jam_rol == "host" and n >= necesarios and vid not in self._saltadas:
            self._saltadas.add(vid)
            self.app.status_var.set(f"⏭ Canción saltada por votación ({n}/{self._n_miembros}).")
            self.app.siguiente_cancion()

    def enviar(self, tipo, texto):
        if not self.en_jam:
            self.app.status_var.set("Entra en una jam para usar el chat.")
            return
        jam_id = self.jam_id
        self.run(lambda: self.app.cloud.jam_mensaje(jam_id, tipo, texto), lambda _r: self._poll_mensajes())

    def enviar_chat(self, texto):
        texto = (texto or "").strip()
        if texto:
            self.enviar("chat", texto[:300])

    def reaccionar(self, emoji):
        self.app.mostrar_reaccion(emoji)       # se ve al momento en tu pantalla
        self.enviar("reaction", emoji)

    def votar_saltar(self):
        vid = self._vid_jam()
        if not vid:
            self.app.status_var.set("No suena nada en la jam.")
            return
        self.enviar("vote", vid)
        self.app.status_var.set("⏭ Has votado saltar esta canción.")

    # ------------------------------------------------------------ actividad de amigos
    def publicar_actividad(self, cancion):
        """Lo llama el reproductor al empezar una canción (o con None al parar)."""
        a = self.app
        if not a.cloud.logged_in or not self.perfil or not a.prefs.get("share_activity", True):
            return
        datos = None
        if cancion:
            vid = cancion.get("videoId") or ""
            datos = {"title": cancion.get("title", ""), "artist": cancion.get("artist", ""),
                     "videoId": None if vid.startswith("file:") else vid,
                     "coverUrl": cancion.get("coverUrl") if str(cancion.get("coverUrl") or "").startswith("http") else None}
        clave = (datos or {}).get("videoId"), (datos or {}).get("title")
        ahora = time.time()
        if clave == getattr(self, "_act_ultima", None) and ahora - getattr(self, "_act_t", 0) < 600:
            return
        self._act_ultima, self._act_t = clave, ahora
        self.run(lambda: a.cloud.actividad_publicar(datos), err=lambda e: None)

    def refrescar_actividad(self):
        def ok(filas):
            self.actividad = {f["user_id"]: f for f in filas or [] if f.get("user_id")}
            d = self._dialogo()
            if d:
                d.repintar_amigos()
        self.run(self.app.cloud.actividad_amigos, ok, err=lambda e: None)

    # ------------------------------------------------------------ playlists colaborativas
    def refrescar_compartidas(self, al_terminar=None):
        def ok(filas):
            self.compartidas = filas or []
            d = self._dialogo()
            if d:
                d.pintar_compartidas()
            if al_terminar:
                al_terminar()
        self.run(self.app.cloud.pl_mias, ok, err=lambda e: None)

    def agregar_a_compartida(self, pl, canciones):
        def ok(n):
            self.app.status_var.set(f"📀 {n} canción(es) añadidas a «{pl['name']}».")
            self.refrescar_compartidas()
            d = self._dialogo()
            if d:
                d.ver_compartida(pl["id"], forzar=True)
        self.run(lambda: self.app.cloud.pl_agregar(pl["id"], canciones), ok)


# ===========================================================================
# Interfaz (se mezcla en SocialDialog)
# ===========================================================================
class SocialDialogExtrasMixin:
    # ------------------------------------------------------------ pestaña chat
    def _tab_chat(self, p):
        bg = self.bg
        self.lbl_chat_info = tk.Label(p, bg=bg, fg="#555555", font=("Tahoma", 8), anchor="w", justify="left",
                                      wraplength=480)
        self.lbl_chat_info.pack(fill=tk.X, padx=8, pady=(8, 2))
        marco = tk.Frame(p, bg="#FFFFFF", relief=tk.SUNKEN, bd=2)
        marco.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        sb = tk.Scrollbar(marco)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt_chat = tk.Text(marco, height=16, font=("Tahoma", 9), wrap="word", relief=tk.FLAT,
                                yscrollcommand=sb.set, state=tk.DISABLED, cursor="arrow")
        self.txt_chat.pack(fill=tk.BOTH, expand=True)
        sb.config(command=self.txt_chat.yview)
        self.txt_chat.tag_configure("nombre", font=("Tahoma", 9, "bold"), foreground=self.app.c("#0A246A", "fg"))
        self.txt_chat.tag_configure("yo", font=("Tahoma", 9, "bold"), foreground=self.app.c("#1F5F1F", "fg"))
        self.txt_chat.tag_configure("sistema", foreground=self.app.c("#666666", "fg"),
                                    font=("Tahoma", 8, "italic"))
        fila = tk.Frame(p, bg=bg)
        fila.pack(fill=tk.X, padx=6, pady=(2, 4))
        self.e_chat = tk.Entry(fila, font=("Tahoma", 9), relief=tk.SUNKEN, bd=2)
        self.e_chat.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.e_chat.bind("<Return>", lambda e: self._enviar_chat())
        self._boton(fila, "Enviar", self._enviar_chat, bg="#D6E4FF", side=tk.LEFT, padx=(4, 0))
        reac = tk.Frame(p, bg=bg)
        reac.pack(fill=tk.X, padx=6, pady=(0, 6))
        for emoji in REACCIONES:
            tk.Button(reac, text=emoji, font=("Segoe UI Emoji", 12), width=3, bd=2, bg="#E0DFE3", cursor="hand2",
                      command=lambda e=emoji: self.mgr.reaccionar(e)).pack(side=tk.LEFT, padx=1)
        self.b_votar = self._boton(reac, "⏭ Votar saltar", self.mgr.votar_saltar, bg="#FFF3C4", side=tk.RIGHT)
        self._nb_chat_frame = p
        self.pintar_chat()

    def chat_visible(self):
        try:
            return self.vivo() and str(self.nb.select()) == str(self._nb_chat_frame)
        except (tk.TclError, AttributeError):
            return False

    def _enviar_chat(self):
        texto = self.e_chat.get().strip()
        if texto:
            self.e_chat.delete(0, tk.END)
            self.mgr.enviar_chat(texto)

    def pintar_chat(self):
        if not self.vivo() or not hasattr(self, "txt_chat"):
            return
        en_jam = self.mgr.en_jam
        self.lbl_chat_info.config(text=(f"💬 Chat de «{self.mgr.jam_nombre}». Las reacciones salen flotando en el "
                                        "reproductor de todos." if en_jam else
                                        "Entra en una jam (pestaña 🎧 Jam) para chatear y reaccionar con los demás."))
        for w in (self.e_chat, self.b_votar):
            w.config(state=tk.NORMAL if en_jam else tk.DISABLED)
        yo = self.app.cloud.user_id
        t = self.txt_chat
        t.config(state=tk.NORMAL)
        t.delete("1.0", tk.END)
        for m in self.mgr.mensajes[-120:] if en_jam else []:
            nombre = str(m.get("nombre", "?")).split("#")[0]
            hora = str(m.get("created_at", ""))[11:16]
            if m.get("kind") == "chat":
                t.insert(tk.END, f"{nombre}: ", "yo" if m.get("user_id") == yo else "nombre")
                t.insert(tk.END, f"{m.get('body', '')}\n")
            elif m.get("kind") == "reaction":
                t.insert(tk.END, f"{hora} {nombre} reacciona {m.get('body', '')}\n", "sistema")
            elif m.get("kind") == "vote":
                t.insert(tk.END, f"{hora} {nombre} ha votado saltar ⏭\n", "sistema")
        t.config(state=tk.DISABLED)
        t.see(tk.END)
        self.pintar_votos()

    def pintar_votos(self):
        if not self.vivo() or not hasattr(self, "b_votar"):
            return
        n, necesarios = self.mgr.votos_actuales()
        self.b_votar.config(text=f"⏭ Votar saltar ({n}/{necesarios})" if self.mgr.en_jam else "⏭ Votar saltar")

    # ------------------------------------------------------------ amigos con actividad
    def repintar_amigos(self):
        if not self.vivo() or not hasattr(self, "lb_amigos"):
            return
        act = getattr(self.mgr, "actividad", {}) or {}
        sel = self.lb_amigos.curselection()
        self.lb_amigos.delete(0, tk.END)
        for x in self._datos.get("amigos", []):
            a = act.get(x["user_id"])
            if a and a.get("song"):
                s = a["song"]
                linea = f"{x['nombre']}   🎵 {s.get('title', '')} — {s.get('artist', '')}  ({hace_cuanto(a.get('updated_at'))})"
            else:
                linea = x["nombre"]
            self.lb_amigos.insert(tk.END, linea)
        for i in sel:
            if i < self.lb_amigos.size():
                self.lb_amigos.selection_set(i)

    def _poner_cancion_amigo(self, _e=None):
        x = self._sel(self.lb_amigos, self._datos.get("amigos", []))
        a = (getattr(self.mgr, "actividad", {}) or {}).get((x or {}).get("user_id"))
        s = (a or {}).get("song") or {}
        if not s.get("videoId"):
            self.estado("Esa persona no está escuchando nada que puedas poner." if x else "Elige un amigo.", error=True)
            return
        self.app.reproducir_directo({"title": s.get("title", ""), "artist": s.get("artist", ""),
                                     "videoId": s["videoId"], "coverUrl": s.get("coverUrl"), "duration": 0})
        self.estado(f"▶ Poniendo lo que escucha {x['nombre']}.")

    # ------------------------------------------------------------ playlists compartidas
    def _tab_compartidas(self, p):
        bg = self.bg
        tk.Label(p, bg=bg, fg="#555555", font=("Tahoma", 8), anchor="w", justify="left", wraplength=480,
                 text="Playlists que editáis entre varios amigos: todos pueden añadir y quitar canciones.").pack(
            fill=tk.X, padx=8, pady=(8, 2))
        f = tk.LabelFrame(p, text=" 📀 Mis playlists compartidas ", bg=bg, font=("Tahoma", 8, "bold"))
        f.pack(fill=tk.X, padx=6, pady=4)
        self.lb_compartidas = self._lista(f, 5)
        self.lb_compartidas.bind("<<ListboxSelect>>", lambda e: self._ver_seleccionada())
        fb = tk.Frame(f, bg=bg)
        fb.pack(pady=(0, 6))
        self._boton(fb, "➕ Nueva", self._nueva_compartida, bg="#D9F2D9", side=tk.LEFT, padx=2)
        self._boton(fb, "👥 Invitar amigo", self._invitar_compartida, bg="#D6E4FF", side=tk.LEFT, padx=2)
        self._boton(fb, "Salir / Borrar", self._salir_compartida, bg="#F2D9D9", side=tk.LEFT, padx=2)
        f2 = tk.LabelFrame(p, text=" Canciones ", bg=bg, font=("Tahoma", 8, "bold"))
        f2.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        self.lbl_pl_miembros = tk.Label(f2, bg=bg, fg="#555555", font=("Tahoma", 8), anchor="w", wraplength=470,
                                        justify="left")
        self.lbl_pl_miembros.pack(fill=tk.X, padx=8)
        self.lb_pl_canciones = self._lista(f2, 9)
        self.lb_pl_canciones.bind("<Double-Button-1>", lambda e: self._pl_reproducir(desde_sel=True))
        fc = tk.Frame(f2, bg=bg)
        fc.pack(pady=(0, 6))
        self._boton(fc, "▶ Reproducir", lambda: self._pl_reproducir(), bg="#D6E4FF", side=tk.LEFT, padx=2)
        self._boton(fc, "+ Cola", self._pl_a_cola, side=tk.LEFT, padx=2)
        self._boton(fc, "➕ La que suena", self._pl_anadir_actual, bg="#D9F2D9", side=tk.LEFT, padx=2)
        self._boton(fc, "✕ Quitar", self._pl_quitar, bg="#F2D9D9", side=tk.LEFT, padx=2)
        self._boton(fc, "⬇ Copiar a mis playlists", self._pl_copiar, side=tk.LEFT, padx=2)
        self._pl_actual = None
        self.pintar_compartidas()
        self.mgr.refrescar_compartidas()

    def pintar_compartidas(self):
        if not self.vivo() or not hasattr(self, "lb_compartidas"):
            return
        sel_id = (self._pl_actual or {}).get("id")
        lb = self.lb_compartidas
        lb.delete(0, tk.END)
        filas = getattr(self.mgr, "compartidas", []) or []
        for i, pl in enumerate(filas):
            dueno = "" if pl.get("es_duenio") else f" · de {pl.get('duenio', '?')}"
            lb.insert(tk.END, f"{pl['name']}  ({pl.get('canciones', 0)} canciones, {pl.get('miembros', 1)} personas){dueno}")
            if pl["id"] == sel_id:
                lb.selection_set(i)
                if (self._pl_actual or {}).get("rev") != pl.get("rev"):
                    self.ver_compartida(pl["id"], forzar=True)

    def _seleccionada(self):
        return self._sel(self.lb_compartidas, getattr(self.mgr, "compartidas", []) or [])

    def _ver_seleccionada(self):
        pl = self._seleccionada()
        if pl:
            self.ver_compartida(pl["id"])

    def ver_compartida(self, pl_id, forzar=False):
        if not forzar and (self._pl_actual or {}).get("id") == pl_id:
            return

        def ok(datos):
            if not self.vivo() or not datos:
                return
            self._pl_actual = datos
            self.lbl_pl_miembros.config(text="👥 " + ", ".join(datos.get("miembros") or []))
            self.lb_pl_canciones.delete(0, tk.END)
            for t in datos.get("tracks") or []:
                self.lb_pl_canciones.insert(tk.END, f"{t.get('title', '')} — {t.get('artist', '')}   · {str(t.get('by', '')).split('#')[0]}")
        self.mgr.run(lambda: self.app.cloud.pl_ver(pl_id), ok)

    def _nueva_compartida(self):
        nombre = simpledialog.askstring("Nueva playlist compartida", "Nombre:", parent=self)
        if not nombre or not nombre.strip():
            return

        def ok(pl_id):
            self.estado(f"Playlist «{nombre.strip()}» creada. Invita a tus amigos con 👥.")
            self._pl_actual = {"id": pl_id}
            self.mgr.refrescar_compartidas()
        self.mgr.run(lambda: self.app.cloud.pl_crear(nombre), ok)

    def _invitar_compartida(self):
        pl = self._seleccionada()
        amigos = self._datos.get("amigos", [])
        if not pl:
            self.estado("Elige primero una playlist compartida.", error=True)
            return
        if not amigos:
            self.estado("Todavía no tienes amigos a los que invitar.", error=True)
            return
        win = tk.Toplevel(self)
        win.title("Invitar a la playlist")
        win.configure(bg=self.bg)
        win.transient(self)
        tk.Label(win, text=f"¿A quién invitas a «{pl['name']}»?", bg=self.bg,
                 font=("Tahoma", 9, "bold")).pack(padx=10, pady=(10, 4))
        lb = tk.Listbox(win, height=min(10, len(amigos)), font=("Tahoma", 9), exportselection=False)
        lb.pack(fill=tk.BOTH, padx=10)
        for a in amigos:
            lb.insert(tk.END, a["nombre"])

        def invitar():
            s = lb.curselection()
            if not s:
                return
            amigo = amigos[s[0]]
            win.destroy()
            self.mgr.run(lambda: self.app.cloud.pl_invitar(pl["id"], amigo["user_id"]),
                         lambda _r: (self.estado(f"{amigo['nombre']} ya puede editar «{pl['name']}»."),
                                     self.mgr.refrescar_compartidas()))
        self._boton(win, "Invitar", invitar, bg="#D9F2D9", pady=8)
        self.app.tematizar(win)

    def _salir_compartida(self):
        pl = self._seleccionada()
        if not pl:
            return
        pregunta = (f"¿Borrar «{pl['name']}» para todos?" if pl.get("es_duenio")
                    else f"¿Salir de «{pl['name']}»? (los demás la siguen teniendo)")
        if not messagebox.askyesno("Playlist compartida", pregunta, parent=self):
            return
        self._pl_actual = None
        self.lb_pl_canciones.delete(0, tk.END)
        self.mgr.run(lambda: self.app.cloud.pl_salir(pl["id"]), lambda _r: self.mgr.refrescar_compartidas())

    def _pl_pistas(self):
        return list((self._pl_actual or {}).get("tracks") or [])

    def _pl_reproducir(self, desde_sel=False):
        pistas = self._pl_pistas()
        if not pistas:
            return
        inicio = 0
        if desde_sel and self.lb_pl_canciones.curselection():
            inicio = self.lb_pl_canciones.curselection()[0]
        a = self.app
        if a._en_jam():
            a.social.cola_agregar([a._normalizar_track(t) for t in pistas[inicio:]], reproducir=True)
            return
        a._activar_cola("normal")
        base = len(a.queue_normal)
        a.queue_normal.extend(a._normalizar_track(t) for t in pistas[inicio:])
        a.current_index = base
        a.actualizar_vista_cola()
        a._guardar_si_corresponde()
        a.cargar_y_reproducir_actual()

    def _pl_a_cola(self):
        pistas = self._pl_pistas()
        for t in pistas:
            self.app.agregar_cancion_a_cola(self.app._normalizar_track(t))
        self.estado(f"{len(pistas)} canciones a la cola.")

    def _pl_anadir_actual(self):
        pl = self._seleccionada()
        c = self.app._cancion_actual()
        if not pl or not c:
            self.estado("Elige una playlist y pon una canción.", error=True)
            return
        self.mgr.agregar_a_compartida(pl, [c])

    def _pl_quitar(self):
        pl = self._seleccionada()
        s = self.lb_pl_canciones.curselection()
        pistas = self._pl_pistas()
        if not pl or not s or s[0] >= len(pistas):
            return
        uid = pistas[s[0]].get("uid")
        self.mgr.run(lambda: self.app.cloud.pl_quitar(pl["id"], uid),
                     lambda _r: (self.ver_compartida(pl["id"], forzar=True), self.mgr.refrescar_compartidas()))

    def _pl_copiar(self):
        datos = self._pl_actual
        if not datos or not datos.get("tracks"):
            return
        self.app._playlist_importada(datos.get("name", "Compartida"),
                                     [dict(t, highCoverUrl=t.get("coverUrl")) for t in datos["tracks"]], "")


def lanzar_reaccion(canvas, emoji):
    """Emoji que sube flotando por el visualizador y se desvanece (≈1,6 s)."""
    try:
        w, h = canvas.winfo_width(), canvas.winfo_height()
    except tk.TclError:
        return
    if w < 20:
        return
    x = random.randint(20, max(21, w - 20))
    item = canvas.create_text(x, h - 4, text=emoji, font=("Segoe UI Emoji", random.choice((14, 16, 18))),
                              fill="#FFFFFF", anchor="s")
    pasos = 26

    def mover(i=0):
        try:
            if i >= pasos:
                canvas.delete(item)
                return
            canvas.move(item, random.choice((-1, 0, 1)), -max(1, h // pasos + 1))
            canvas.after(60, lambda: mover(i + 1))
        except tk.TclError:
            pass
    mover()
