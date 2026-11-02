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

## PDF y escaneos
`vistazo` lee el texto de los PDF con PDFKit y, si una página no tiene texto (un escaneo), hace OCR en español e inglés con Vision, todo dentro de tu Mac. El lector (`pdf_texto.swift`) se compila solo la primera vez en `bin/`. Si no hay `swiftc`, usa el índice de Spotlight como antes.

## Clasificador local (aprende de tus decisiones)
Un modelo pequeño aprende del historial cómo clasifica el agente, usando solo el **nombre, la extensión, el tamaño y el origen** de cada archivo, nunca su contenido.

    ~/OrganizadorIA/organizador entrenar        # reconstruye el catálogo y reentrena

- **Catálogo SQL:** `catalogo.py` convierte `registro_local/movimientos.jsonl` en `registro_local/catalogo.db` (SQLite). Hay consultas de ejemplo en `consultas.sql`:

      sqlite3 ~/OrganizadorIA/registro_local/catalogo.db < ~/OrganizadorIA/consultas.sql

- **Entrenamiento:** `entrenar.py` compara varios modelos con validación cruzada agrupada (las copias de un mismo archivo no se separan entre entrenamiento y prueba), elige una regresión logística y calcula el **umbral de confianza** con el que acierta al menos `precision_objetivo` (95%) fuera de muestra. El resultado queda en `registro_local/reporte_modelo.md`.
- **Uso:** `listar` muestra `SUGERENCIA: Destino (probabilidad)` en cada elemento, y el agente usa directamente las de `[ALTA CONFIANZA]`.
- **Decidir sin el agente:** con `"auto_mover": true` en `config.json`, lo que pasa el umbral se mueve antes de llamar a Claude. Si no queda nada, Claude no se llama. Nunca mueve archivos sensibles, proyectos de código ni posibles duplicados, y lo que mueve se puede deshacer y no se usa para reentrenar. Viene desactivado.
- `herramienta.py` predice sin scikit-learn. Solo el entrenamiento lo necesita:

      /usr/bin/python3 -m venv ~/OrganizadorIA/.venv && ~/OrganizadorIA/.venv/bin/pip install -r ~/OrganizadorIA/requirements-entrenamiento.txt

- Solo funciona en el modo general (Escritorio y Descargas), porque es la taxonomía con la que aprendió. Con `"usar": false` se desactiva por completo.
- El modelo y el reporte contienen fragmentos de tus nombres de archivo, así que viven en `registro_local/` y nunca se suben.

## Búsqueda por preguntas en tus documentos
Busca dentro de los documentos de `Organizado`: PDF (con OCR), Word, PowerPoint, Excel, LaTeX, texto y facturas CFDI en XML.

    ~/OrganizadorIA/organizador indexar                          # la primera vez tarda; después solo lo nuevo
    ~/OrganizadorIA/organizador buscar "recibo de luz"           # lista los documentos más relevantes
    ~/OrganizadorIA/organizador preguntar "¿cuándo vence mi pasaporte?"   # respuesta de Claude citando tus documentos

- **Híbrida:** combina palabras clave (SQLite FTS5, BM25) con significado (embeddings multilingües calculados **en tu Mac** con fastembed), fusionados con Reciprocal Rank Fusion. Encuentra "recibo de luz" aunque el documento diga "Comisión Federal de Electricidad", y también responde preguntas en inglés sobre documentos en español.
- **Evaluación:** `evals/evaluar_busqueda.py` mide Recall@1, Recall@3 y MRR con un corpus sintético. Los resultados están en [`evals/resultados_busqueda.md`](evals/resultados_busqueda.md).
- **Qué no se indexa:** proyectos de código, la carpeta de revisión, archivos sensibles (`.key`, `.cer`, `.pem`... incluida la e.firma del SAT), lo que esté en `busqueda.excluir` de config.json y archivos de más de `max_mb`.
- **Privacidad:** `indexar` y `buscar` no envían nada a internet. `preguntar` sí envía a Claude los fragmentos recuperados (y nada más: Claude no recibe herramientas).
- **Dependencias:** sin fastembed la búsqueda funciona solo con palabras clave. Para la búsqueda por significado:

      ~/OrganizadorIA/.venv/bin/pip install -r ~/OrganizadorIA/requirements-busqueda.txt

### Servidor MCP (Claude Desktop o Claude Code)
`mcp_servidor.py` deja que Claude consulte tus documentos con tres herramientas de solo lectura: `buscar_documentos`, `leer_documento` (solo documentos que están en el índice) y `estado_indice`. Implementa el protocolo sin dependencias. `organizador mcp-config` muestra cómo conectarlo.

## Pruebas
Las garantías de arriba se comprueban con pruebas automáticas que usan un HOME falso en una carpeta temporal, así que nunca tocan tus archivos:

    /usr/bin/python3 -m unittest discover -s tests -v

En GitHub, `.github/workflows/pruebas.yml` las corre en macOS en cada push. `registro_local/` está en `.gitignore` y nunca se sube.

## Privacidad
- Sin memoria: la memoria automática está desactivada, la sesión no se guarda en disco (`--no-session-persistence`), no se cargan tus ajustes ni tu CLAUDE.md, y la telemetría está desactivada.
- Para clasificar, los nombres de archivo y algunos extractos se envían a Anthropic. Si pones `"leer_contenido": false` en config.json, solo usará nombres y metadatos.
- Para que no se use en entrenamiento, ve a claude.ai → Configuración → Privacidad y desactiva "Ayudar a mejorar Claude". Con una API key comercial, los datos no se usan para entrenar por defecto.
- `registro_local/` vive solo en tu Mac y sirve para "deshacer". Si no lo quieres, pon `"guardar_registro_local": false`.
