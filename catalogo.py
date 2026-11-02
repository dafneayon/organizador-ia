#!/usr/bin/env python3
"""Catálogo SQLite del Organizador IA (solo biblioteca estándar).

Reconstruye registro_local/catalogo.db a partir de registro_local/movimientos.jsonl,
que sigue siendo la fuente de verdad (la usa 'deshacer'). El catálogo sirve para
consultar el historial con SQL y para entrenar el clasificador local.

    /usr/bin/python3 catalogo.py            # reconstruye y muestra un resumen
    sqlite3 registro_local/catalogo.db < consultas.sql
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from configuracion import cargar  # noqa: E402

CONFIG = cargar(AQUI)
REGISTRO = AQUI / "registro_local" / "movimientos.jsonl"
DB = AQUI / "registro_local" / "catalogo.db"
BASE = Path(os.path.expanduser(CONFIG["carpeta_destino"]))
REVISAR = CONFIG["carpeta_revisar"]
ORIGENES = {Path(os.path.expanduser(o)) for o in CONFIG["origenes"]}
# Una subcarpeta solo se aprende como clase propia si tiene al menos estos ejemplos
MIN_SUBCARPETA = int(CONFIG.get("clasificador", {}).get("min_ejemplos_subcarpeta", 5))

ESQUEMA = """
DROP VIEW IF EXISTS v_entrenamiento;
DROP TABLE IF EXISTS movimientos;
DROP TABLE IF EXISTS ediciones;

CREATE TABLE movimientos (
    id             INTEGER PRIMARY KEY,
    ejecucion      TEXT NOT NULL,
    fecha          TEXT NOT NULL,          -- AAAA-MM-DD de la ejecución
    tipo           TEXT NOT NULL CHECK (tipo IN ('mover', 'revisar', 'renombrar')),
    modo           TEXT NOT NULL CHECK (modo IN ('general', 'carpeta')),
    origen         TEXT NOT NULL,
    destino        TEXT NOT NULL,
    carpeta_origen TEXT NOT NULL,          -- Desktop, Downloads o la carpeta específica
    nombre         TEXT NOT NULL,          -- nombre original
    extension      TEXT,
    es_dir         INTEGER NOT NULL,
    tamano         INTEGER,                -- bytes; NULL en carpetas o si ya no existe
    categoria      TEXT,
    subcarpeta     TEXT,
    motivo         TEXT,
    sigue_ahi      INTEGER NOT NULL        -- 1 si el destino todavía existe
);
CREATE INDEX idx_mov_categoria ON movimientos (categoria, subcarpeta);
CREATE INDEX idx_mov_ejecucion ON movimientos (ejecucion);

CREATE TABLE ediciones (
    id        INTEGER PRIMARY KEY,
    ejecucion TEXT NOT NULL,
    archivo   TEXT NOT NULL,
    respaldo  TEXT NOT NULL
);

-- Ejemplos para el clasificador: movimientos del agente en el modo general.
-- La etiqueta es 'Categoria/Subcarpeta' si esa subcarpeta tiene suficientes
-- ejemplos, y solo 'Categoria' si no.
CREATE VIEW v_entrenamiento AS
WITH conteo AS (
    SELECT *, COUNT(*) OVER (PARTITION BY categoria, subcarpeta) AS n_sub
    FROM movimientos
    WHERE tipo = 'mover' AND modo = 'general' AND categoria IS NOT NULL
      -- Lo que movió el propio clasificador no se usa para reentrenarlo
      AND COALESCE(motivo, '') NOT LIKE 'clasificador local%'
)
SELECT id, ejecucion, nombre, extension, es_dir, tamano, carpeta_origen, categoria,
       CASE WHEN subcarpeta IS NOT NULL AND n_sub >= {min_sub}
            THEN categoria || '/' || subcarpeta ELSE categoria END AS etiqueta
FROM conteo;
"""


def fila(r: dict):
    origen, destino = Path(r["origen"]), Path(r["destino"])
    carpeta = origen.parent
    if BASE == destino or BASE in destino.parents:
        modo, partes = "general", destino.relative_to(BASE).parts
    elif carpeta in ORIGENES:  # carpeta renombrada en Escritorio o Descargas
        modo, partes = "general", ()
    else:
        modo = "carpeta"
        try:
            partes = destino.relative_to(carpeta).parts
        except ValueError:
            partes = ()
    if r.get("motivo") == "renombrado":
        tipo, partes = "renombrar", ()
    elif partes and partes[0] == REVISAR:
        tipo = "revisar"
    else:
        tipo = "mover"
    carpetas = partes[:-1]  # el último elemento es el propio archivo
    existe = destino.exists() or destino.is_symlink()
    es_dir = destino.is_dir() and not destino.is_symlink()
    nombre = origen.name
    ext = None if es_dir or "." not in nombre.strip(".") else nombre.rsplit(".", 1)[1].lower()
    tamano = destino.stat().st_size if existe and not es_dir else None
    e = r["ejecucion"]
    return (e, f"{e[:4]}-{e[4:6]}-{e[6:8]}", tipo, modo, str(origen), str(destino), str(carpeta),
            nombre, ext, int(es_dir), tamano,
            carpetas[0] if carpetas and tipo == "mover" else None,
            carpetas[1] if len(carpetas) > 1 and tipo == "mover" else None,
            r.get("motivo") or None, int(existe))


def construir(registro=REGISTRO, db=DB):
    db.parent.mkdir(parents=True, exist_ok=True)
    filas = []
    if registro.exists():
        filas = [json.loads(l) for l in registro.read_text(encoding="utf-8").splitlines() if l.strip()]
    con = sqlite3.connect(db)
    with con:
        con.executescript(ESQUEMA.replace("{min_sub}", str(MIN_SUBCARPETA)))
        con.executemany(
            "INSERT INTO movimientos (ejecucion, fecha, tipo, modo, origen, destino, carpeta_origen, nombre,"
            " extension, es_dir, tamano, categoria, subcarpeta, motivo, sigue_ahi)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [fila(r) for r in filas if r.get("tipo") != "edicion"])
        con.executemany("INSERT INTO ediciones (ejecucion, archivo, respaldo) VALUES (?,?,?)",
                        [(r["ejecucion"], r["archivo"], r["respaldo"]) for r in filas if r.get("tipo") == "edicion"])
    return con


def resumen(con):
    total, = con.execute("SELECT COUNT(*) FROM movimientos").fetchone()
    ed, = con.execute("SELECT COUNT(*) FROM ediciones").fetchone()
    print(f"CATALOGO: {DB}")
    print(f"{total} movimientos y {ed} ajustes de rutas")
    for tipo, n in con.execute("SELECT tipo, COUNT(*) FROM movimientos GROUP BY tipo ORDER BY 2 DESC"):
        print(f"  {tipo}: {n}")
    print("Ejemplos para el clasificador por etiqueta:")
    for etiqueta, n in con.execute(
            "SELECT etiqueta, COUNT(*) FROM v_entrenamiento GROUP BY etiqueta ORDER BY 2 DESC, 1"):
        print(f"  {n:4d}  {etiqueta}")


if __name__ == "__main__":
    con = construir()
    if "--silencio" not in sys.argv:
        resumen(con)
