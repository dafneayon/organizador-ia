-- Consultas de ejemplo sobre el catálogo del Organizador IA.
--   /usr/bin/python3 catalogo.py
--   sqlite3 -header -column registro_local/catalogo.db < consultas.sql
.mode column
.headers on

-- 1. ¿Cuántos elementos organizó cada ejecución y de dónde venían?
SELECT ejecucion, modo, carpeta_origen, COUNT(*) AS elementos
FROM movimientos
GROUP BY ejecucion, modo, carpeta_origen
ORDER BY ejecucion;

-- 2. Categorías con más archivos y cuánto ocupan (MB)
SELECT categoria,
       COUNT(*) AS archivos,
       ROUND(SUM(COALESCE(tamano, 0)) / 1e6, 1) AS mb
FROM movimientos
WHERE tipo = 'mover' AND modo = 'general'
GROUP BY categoria
ORDER BY archivos DESC;

-- 3. Extensiones más comunes dentro de cada categoría (top 3 por categoría)
WITH por_ext AS (
    SELECT categoria, COALESCE(extension, '(carpeta)') AS extension, COUNT(*) AS n,
           ROW_NUMBER() OVER (PARTITION BY categoria ORDER BY COUNT(*) DESC) AS pos
    FROM movimientos
    WHERE tipo = 'mover' AND categoria IS NOT NULL
    GROUP BY categoria, extension
)
SELECT categoria, extension, n FROM por_ext WHERE pos <= 3 ORDER BY categoria, pos;

-- 4. Lo que se mandó a revisión y por qué
SELECT nombre, motivo, fecha FROM movimientos WHERE tipo = 'revisar' ORDER BY fecha DESC;

-- 5. Archivos que ya no están donde los dejó el organizador (los moviste a mano)
SELECT nombre, categoria, subcarpeta FROM movimientos WHERE tipo = 'mover' AND sigue_ahi = 0;

-- 6. Proyectos cuyas rutas se ajustaron, con número de archivos editados
SELECT ejecucion, COUNT(*) AS archivos_ajustados FROM ediciones GROUP BY ejecucion;
