# eXotic Media Player v20

## Errores corregidos

- **Cierre incompleto.** `MediaKeyHook` no tenía `stop()`. Al cerrar saltaba un error y no llegaban a cerrarse ni la bandeja ni el mini modo. Ahora cada paso del cierre va por separado y la ventana desaparece al instante.
- **Congelones de la interfaz.** Al pintar la cola se consultaba YouTube Music desde el hilo de la interfaz para completar duraciones. Ahora se hace en segundo plano, y la duración real de VLC se aprovecha cuando falta.
- **Subidas a Supabase en cada canción.** Cada reproducción (historial) subía todos tus datos a la nube. Ahora los cambios automáticos se guardan en local al momento y se agrupan en una sola subida cada pocos segundos. Las acciones explícitas (crear o borrar playlists…) se siguen subiendo al instante.
- **Modo invitado sin guardar.** Sin sesión iniciada no se guardaba nada en disco y el estado de sincronización se quedaba en "Sincronizando...". Ahora el invitado se guarda en `exotic_player_data_local.json`.
- **Sesión perdida al abrir sin Internet.** Cualquier error, incluido no tener conexión, borraba la sesión guardada. Ahora solo se borra si Supabase dice que la sesión es inválida. Si falla la red, se reintenta sola.
- **Error al cambiar el nombre de usuario** en Amigos y Jam (`perfil[nombre]` → `NameError`).
- **Guardar una canción en una playlist ya no la marca como ♥** sin pedirlo.
- **La lista de la cola ya no salta arriba** con cada cambio: conserva el scroll y la selección, y resalta la canción que suena.
- **Mostrar u ocultar desde la bandeja** funciona con la ventana maximizada, y ya no la desmaximiza.
- **Código muerto eliminado**: el splash roto (`RESAMPLE` sin definir), imports sin usar y una función que no se usaba.
- **Test de estadísticas arreglado**: usaba fechas fijas y empezó a fallar con el paso de los días.

## Rendimiento

- El bucle del reproductor pasa de 30 ms a 100 ms y solo redibuja el tiempo cuando cambia.
- El visualizador va más lento cuando la ventana está en la bandeja o minimizada.
- El Soundscope reutiliza la captura de audio del panel en vez de abrir otra.

## Novedades

- **Repetir**: no / toda la cola / una canción (`Ctrl+R`).
- **🔀 Mezclar** las canciones que quedan por sonar.
- **♥ a la canción actual**: botón, `Ctrl+L`, menú de la bandeja y mini modo.
- **🌙 Temporizador para dormir**: 15 min a 2 h, o "al terminar esta canción". Baja el volumen poco a poco antes de parar. En una jam solo silencia tu altavoz.
- **📝 Letras**, sincronizadas línea a línea cuando YouTube Music las tiene (`Ctrl+T`).
- **⬇ YT: importar playlists** públicas de YouTube o YouTube Music (también álbumes) a tus playlists.
- **Seguir por donde ibas**: al abrir la app, ▶ continúa la última canción en el mismo segundo.
- **Ecualizador de verdad**: 10 bandas más preamplificador, 9 presets propios y los 18 de VLC. Se guarda en tu cuenta.
- **Visualizador real** en el panel principal, con el espectro del audio que suena (WASAPI loopback, como el Soundscope). También tiene modo simulado y apagado.
- **Temas**: Luna Azul, Olive Green, Plata, Frutiger Aero y Noche (oscuro). Configuración → Apariencia.
- **Sonidos retro**: "ding" al iniciar sesión, acorde al aceptar un amigo o entrar en una jam, aviso si tienes solicitudes y arpegio al arrancar. Se pueden desactivar.
- **Aviso "Ahora suena"** junto al reloj cuando la app está en la bandeja (opcional).
- **Silenciar** (`Ctrl+M`), porcentaje de volumen visible, y el volumen se recuerda entre sesiones.
- **⏮ vuelve al principio** de la canción si llevas más de 4 segundos, como Winamp y WMP.
- **Clic derecho en la pantalla LCD**: ♥, letra, copiar enlace, abrir en YouTube Music, Soundscope y mini modo.
- **Doble clic** en un resultado de búsqueda lo reproduce. Doble clic en el visualizador abre el Soundscope.
- **Tooltips** estilo XP en los botones nuevos.
- **Configuración en pestañas**: General, Apariencia, Cuenta y datos.
- **Atajos de teclado** (`F1` para verlos): Espacio, `Ctrl+←/→`, `Ctrl+↑/↓`, `Ctrl+F`, `Ctrl+E`… La tecla Stop multimedia también funciona.

## Archivos nuevos

`player_extras.py`, `themes.py`, `lyrics.py`, `retro_sounds.py`, `tests/test_v20.py` y este changelog.

En tu carpeta de datos aparecen dos cosas nuevas: `exotic_prefs.json` (preferencias de este ordenador) y la carpeta `sonidos/` (se genera sola).
