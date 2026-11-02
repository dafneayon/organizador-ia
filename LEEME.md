# Organizador IA

Ordena los archivos sueltos de **Escritorio** y **Descargas** en `~/Documents/Organizado`, con carpetas por tema y etiquetas de color de Finder.

## Comandos (en Terminal)
    ~/OrganizadorIA/organizador simulacro              # muestra qué haría, sin mover nada
    ~/OrganizadorIA/organizador ahora                  # organiza Escritorio y Descargas
    ~/OrganizadorIA/organizador programar 8 10:00      # el día 8 de cada mes a las 10:00
    ~/OrganizadorIA/organizador programar-una 2026-11-08 10:00   # una sola vez
    ~/OrganizadorIA/organizador estado | cancelar
    ~/OrganizadorIA/organizador deshacer               # devuelve todo lo de la última ejecución

### Carpetas específicas
Agrega una o varias carpetas al final de cualquier comando. Cada una se organiza **en su propio lugar**: las categorías se crean dentro de ella, no en Organizado.

    ~/OrganizadorIA/organizador simulacro ~/Documents/Universidad
    ~/OrganizadorIA/organizador ahora ~/Documents/Universidad ~/Pictures/Escaneos
    ~/OrganizadorIA/organizador programar 1 09:00 ~/Documents/Trabajo

Truco: escribe `organizador ahora ` y arrastra la carpeta desde Finder a la Terminal para pegar su ruta.

- Las subcarpetas que crea el organizador quedan marcadas como categoría (etiqueta con su nombre) y no se mueven en ejecuciones futuras.
- Tus subcarpetas existentes se respetan. Solo se mueven o renombran si es claramente necesario.
- No se permite organizar tu carpeta personal completa, `~/Library`, carpetas ocultas, carpetas fuera de tu usuario ni carpetas que sean (o estén dentro de) un proyecto de código como `Piloto`.
- Si programas carpetas, la programación organiza solo esas. Sin carpetas, organiza Escritorio y Descargas.

## Garantías
- El agente solo tiene Read, Glob y Bash, y Bash está limitado a `herramienta.py`. No puede usar Write ni Edit, ni `rm`, `mv` o `cp`.
- `herramienta.py` no tiene ninguna orden para editar o borrar (la única edición es el ajuste automático de rutas en proyectos, descrito abajo). Solo mueve elementos sueltos de Escritorio y Descargas, sin sobrescribir nunca: si el nombre ya existe, agrega " (2)".
- Lo que podría sobrar va a `_Para revisar (posible eliminar)`, con una etiqueta roja y su motivo en `LEEME - motivos.txt`. Ahí decides tú.
- Puede mover carpetas completas y **renombrar carpetas** (nunca archivos). Lo controlan `mover_carpetas` y `renombrar_carpetas` en config.json.
- **Carpetas de proyecto** (con `.git`, `.venv`, `package.json`, etc.): se pueden mover y renombrar. Al hacerlo, `herramienta.py` (no el agente) sustituye la ruta absoluta antigua por la nueva en los archivos de texto del proyecto, incluidos los proyectos anidados. Esto abarca scripts, notebooks, el `.venv` (activate, pip, `.pth` de instalaciones editables) y `.git/config`.
  - Antes de cambiar un archivo, guarda una copia en `registro_local/respaldos/`. `deshacer` restaura los originales.
  - Reemplaza solo la ruta exacta, en sus formas `/Users/...`, `~/...` y `$HOME/...`. Una ruta parecida como `proyecto2` no se toca.
  - Las rutas relativas que salen del proyecto (`../algo`) no se cambian: se avisan para que las revises.
  - En un repositorio git, los archivos ajustados aparecerán como modificados en `git status`.
  - Con `"ajustar_rutas_proyectos": false` no se ajusta nada. Con `"proteger_proyectos": true` los proyectos no se mueven en absoluto.
- No se tocan los archivos ocultos, las descargas incompletas ni lo que esté en `excluir_nombres` (por ejemplo, `Piloto`).
- `deshacer` también revierte los renombrados y los ajustes de rutas.

## Privacidad
- Sin memoria: la memoria automática está desactivada, la sesión no se guarda en disco (`--no-session-persistence`), no se cargan tus ajustes ni tu CLAUDE.md, y la telemetría está desactivada.
- Para clasificar, los nombres de archivo y algunos extractos se envían a Anthropic. Si pones `"leer_contenido": false` en config.json, solo usará nombres y metadatos.
- Para que no se use en entrenamiento, ve a claude.ai → Configuración → Privacidad y desactiva "Ayudar a mejorar Claude". Con una API key comercial, los datos no se usan para entrenar por defecto.
- `registro_local/` vive solo en tu Mac y sirve para "deshacer". Si no lo quieres, pon `"guardar_registro_local": false`.
