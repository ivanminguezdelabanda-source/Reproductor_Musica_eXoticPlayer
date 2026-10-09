# eXotic Media Player v22

## Escuchar música

- **🧭 Explorar**, junto al buscador. Tiene cuatro secciones:
  - Novedades, Tendencias, Estados de ánimo y géneros.
  - Éxitos de España.
  - Para ti.
  - Al abrir una playlist o un álbum puedes darle a ▶ Reproducir todo, + Cola o ⬇ Guardar como playlist. ← Volver deshace el camino.
- **Buscador con sugerencias:**
  - Mientras escribes, salen sugerencias de YouTube Music.
  - Con la caja vacía, salen tus últimas búsquedas.
  - Se maneja con las flechas, Intro y Esc.
- **▶ Tu cuenta de YouTube Music** (Configuración → Cuenta y datos):
  - Tus playlists aparecen en eXotic, enlazadas, y tus "Me gusta" se suman a los de eXotic.
  - Dar o quitar ♥, añadir o quitar canciones de una playlist enlazada y renombrarla se hace también en YouTube Music.
  - Borrar una playlist en eXotic no la borra en YouTube Music, por seguridad.
  - Se conecta pegando una vez las cabeceras del navegador (vienen instrucciones). Se guardan solo en tu PC.
- **🎚 Efectos:**
  - Slowed (−15 %), Muy slowed (−25 %), Speed up (+15 %) y Nightcore (+25 %). Velocidad y tono cambian juntos.
  - En una jam siempre suena a velocidad normal, para que todos oigan lo mismo.
  - La reverb no se puede añadir: libVLC no deja activar sus filtros de audio desde un programa.
- **Volumen igualado:** cada canción de YouTube Music se ajusta con su dato de sonoridad (`loudnessDb`), como hace YouTube. Las canciones del ordenador suenan tal cual.

## Comodidad

- **Atajos globales:** funcionan aunque estés en otro programa. Se pueden cambiar en Configuración → General.
  - Por defecto: Ctrl+Alt+Espacio (pausa), Ctrl+Alt+→ / ← (siguiente / anterior), Ctrl+Alt+↑ / ↓ (volumen), Ctrl+Alt+L (♥) y Ctrl+Alt+E (mostrar u ocultar).
- **Abrir con Windows:** eXotic arranca minimizado en la bandeja, sin animación.
- **Cola:**
  - Arrastrar y soltar para reordenar.
  - Ctrl+Z deshace quitar, mover, limpiar, mezclar o arrastrar, hasta 20 pasos.
- **Mini modo:** ahora con carátula y un visualizador pequeño.
- **Configuración en pestañas con barra de desplazamiento**, para pantallas pequeñas.

## Amigos y jam

Todo esto necesita `supabase_actualizacion_v22.sql` en Supabase.

- **💬 Chat de la jam**, en una pestaña nueva.
  - Reacciones (🔥 ❤ 😂 👏 🎉 😮) que salen flotando sobre el visualizador de todos.
  - Votar para saltar: si vota la mitad de la jam, la canción se salta.
- **🎧 Actividad de amigos:**
  - En "Mis amigos" se ve qué escucha cada uno ahora. Doble clic, o ▶ Poner lo que escucha, para ponerla tú.
  - Se puede desactivar con "Mostrar a mis amigos lo que estoy escuchando".
  - Solo la ven tus amigos.
- **📀 Playlists colaborativas** (pestaña Compartidas):
  - Se crean y se invita a amigos, y todos pueden añadir y quitar canciones.
  - También aparecen en el menú 📁 de cada canción.
  - El dueño la borra para todos; los demás solo salen de ella.

## Visual

- **Temas nuevos:** PlayStation 2, GameCube y Dreamcast.
- **Soundscope, 2 escenas nuevas:**
  - **TORRES:** el campo de torres azules en la niebla del menú de la PS2.
  - **CUBO:** un cubo de 3×3×3 cubitos que se abre con el ritmo.
  - Teclas 1–9 para ir a cada escena.

## Mantenimiento

- **Avisos de versión nueva:** pon tu repositorio de GitHub en Configuración → Cuenta y datos → Mantenimiento. eXotic avisa una vez al día si hay una versión publicada más nueva.
- **GitHub Actions** (`.github/workflows/windows.yml`). En cada cambio, en un Windows real:
  - Instala VLC, pasa los tests, abre el programa de verdad y comprueba que la ventana y la animación de inicio se ven (`tests/smoke_app.py`).
  - Compila el .exe y lo vuelve a probar.
  - Al subir una etiqueta `vX` publica la versión, que es lo que detectan los avisos.
- **Errores de la interfaz** que antes se perdían ahora quedan en el log.
- **SQL:** `supabase_schema.sql` arrancaba con error en una base de datos nueva ("relation jam_members does not exist") y no se podía volver a ejecutar entero. Ya funciona y se puede repetir. Está probado contra PostgreSQL 16.

## Archivos nuevos

`explore.py`, `audio_fx.py`, `hotkeys.py`, `ytm_account.py`, `updates.py`, `social_extra.py`, `supabase_actualizacion_v22.sql`, `.github/workflows/windows.yml`, `tests/smoke_app.py`, `tests/test_v22.py` y este changelog.

## v22.1

- **Arreglo:** en Explorar no se veían las carátulas de álbumes, playlists y canciones. El hueco de la imagen medía 4×2 píxeles: el tamaño estaba puesto en caracteres y, al poner la imagen, Tk lo tomaba como píxeles. Ahora va en un marco fijo de 50×50.
- Las carátulas que YouTube da sin `https:` delante (`//…`) ahora también se cargan, en todo el programa y en el Soundscope.
