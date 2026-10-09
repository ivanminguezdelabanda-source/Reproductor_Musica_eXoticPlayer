# eXotic Media Player v21

## Soundscope

- **3 escenas nuevas:**
  - **FEEDBACK**, estilo Milkdrop: cada fotograma se dibuja sobre el anterior ampliado y girado, con un anillo de onda que "respira" con el bombo.
  - **TÚNEL** PS1 con la portada de la canción como textura. Si no hay portada, usa un tablero de colores.
  - **KARAOKE**: la letra sincronizada con la tipografía de los menús de PlayStation. Línea actual grande, la anterior y las siguientes más tenues.
- **Colores de la portada:** cada canción tiene su paleta, sacada de los colores de su carátula. Cambia suave al pasar de canción.
- **Cambio automático con la música:** salta de escena en un golpe fuerte cuando la energía sube de golpe (un "drop"), o al rato si no pasa. Si la canción no tiene letra, se salta el karaoke.
- **Transiciones PS1:** disolución con tramado entre escenas.
- **Tarjeta "TRACK 03 / 12"** al cambiar de canción, como el reproductor de CD de la PlayStation.
- **Rendimiento:**
  - El dibujo va en un hilo aparte, así que la interfaz no se traba con el Soundscope abierto.
  - Las scanlines se hornean al escalar (unos 3 ms) en vez de ser cientos de rectángulos en el lienzo.
- **Error corregido:** el efecto de destello al cambiar de escena lanzaba una excepción en cada fotograma (`IndexError` en `_fx`). Por eso la imagen se congelaba un momento en cada cambio.
- **Teclas:** `1`–`7` van a cada escena, `L` al karaoke, `A` activa o desactiva el modo automático y `H` muestra u oculta el HUD.

## Novedades

- **📂 Mi música:** reproduce MP3, FLAC, WAV, M4A, OGG… de tu ordenador, por archivos sueltos o por carpeta entera.
  - Título, artista, duración y carátula se leen con VLC.
  - Funcionan con cola, playlists, ♥, historial y estadísticas. No se pueden meter en jams, porque los demás no tienen tus archivos.
- **🌊 Fundido entre canciones** de 3, 5, 8 o 12 segundos (Configuración → General).
  - Usa dos reproductores de VLC a la vez.
  - No se usa en jams, ni con videoclips, ni con Repetir una.
- **Discord** muestra la carátula de la canción, la barra de tiempo y un botón "Escuchar en YouTube Music".
- **🎁 eXotic Wrapped:** imagen vertical 1080×1920 (formato historia) con estética XP. Incluye minutos escuchados, top 5 canciones, top 5 artistas y tu día más musical.
  - Puede ser de este mes, del mes pasado o del año. Está en Ver ▾ y en la pestaña Estadísticas.
  - Los datos se van guardando por meses, de forma muy compacta. Hasta tener un mes completo se calcula con tu historial (aproximado).
- **🎵 Last.fm:** registra lo que escuchas (Configuración → Cuenta y datos).
  - Necesitas una API key gratuita. La contraseña solo se usa para conectar y no se guarda.
  - Si no hay red, los registros se guardan y se envían más tarde.

## Simplificado

- **Cabecera:** Soundscope, Mini, Letra, Ecualizador, Wrapped y Atajos van ahora en el menú **🖥 Ver ▾**. Antes eran cuatro botones sueltos.
- **Duraciones:** un solo módulo (`duraciones.py`) en vez de cinco copias casi iguales.
- **SQL:** un solo `supabase_schema.sql` en vez de seis archivos `social_schema*.sql`, con el mismo contenido y en el mismo orden. Si tu base ya funciona, no hay que ejecutar nada.
- **Comprobaciones innecesarias:** se ha quitado la que se repetía cada medio segundo para el botón Aleatorio; ahora se actualiza al cambiar de cola.
- **Botones que sobraban:**
  - Fuera el botón "Actualizar estadísticas", que ya se actualizan solas. En su sitio está el Wrapped.
  - Fuera la animación aleatoria antigua del visualizador.

## Archivos nuevos

`player_media.py`, `local_files.py`, `wrapped.py`, `lastfm.py`, `duraciones.py`, `supabase_schema.sql`, `tests/test_v21.py` y este changelog.

## v21.1 · Animación de arranque

Animación de arranque estilo Windows XP:

- El mono aterriza con un rebote y el nombre se escribe solo.
- Aparece "versión 21.1" en naranja.
- La barra de carga tiene los tres bloques azules deslizándose, con un ecualizador de fondo y frases de carga ("Soplando el cartucho…").
- Al final, fundido de salida y sale la ventana principal. El sonido de inicio suena con la animación.
- Mientras el programa carga, la animación espera en el logo, así que no añade espera de más.
- Se salta con un clic, Espacio, Intro o Esc, y se desactiva en Configuración → Apariencia.
- Archivo nuevo: `splash.py`.

## v21.2 · Animación de arranque rediseñada

La animación es más bonita y más limpia:

- **Fondo:** azul estilo Aero en lugar de negro, con haces de luz, brillo de cristal, curvas luminosas y burbujas que suben despacio.
- **Logo:** el mono queda con las esquinas redondeadas limpias (el icono traía esquinas blancas), con un halo suave, sombra y reflejo.
- **Título:** "**eXotic** Media Player" con letra fina y negrita y sombra suave. Un barrido de luz lo recorre.
- **Versión** en una pastilla naranja brillante.
- **Barra de carga:** cápsula de cristal con los tres bloques azules de XP.
- **Menos elementos:** fuera el ecualizador de fondo y las frases cambiando.
- **Esquinas redondeadas** también en la ventana de la animación (en Windows).
- Cada fotograma se dibuja con PIL y tarda unos 5 ms en generarse.

## v21.3 · Arreglo de la animación de arranque

Problema: en Windows, la animación aparecía un instante y desaparecía. Cambios:

- La ventana ya no usa las transparencias de Windows (`-alpha` y `-transparentcolor`), que en algunos equipos la dejaban invisible. Ahora los fundidos de entrada y salida se hacen dentro de la propia imagen.
- Un clic o Esc en el primer segundo ya no la salta, para que el clic o la tecla con la que abres el programa no la corte sin querer. Espacio e Intro ya no la saltan.
- Al terminar de cargar el programa, la animación se vuelve a traer al frente por si algo la tapó.
- Deja rastro en el log (`[splash] …`) para poder ver qué pasa si vuelve a fallar.
- Las esquinas de la ventana de la animación vuelven a ser rectas.
