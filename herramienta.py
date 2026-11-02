#!/usr/bin/env python3
"""Herramienta segura del Organizador IA.

Es la UNICA via por la que el agente puede tocar el sistema de archivos.
Solo puede: listar, echar un vistazo (lectura), crear carpetas, MOVER sin
sobrescribir, RENOMBRAR CARPETAS (nunca archivos) y poner etiquetas/colores de Finder.

Unica excepcion a "no editar": al mover o renombrar una carpeta de PROYECTO, esta
herramienta (no el agente) sustituye la ruta absoluta antigua por la nueva en los
archivos de texto de ese proyecto. Cada archivo se respalda antes y 'deshacer' lo restaura. No existe ninguna orden
para editar contenido ni borrar archivos.

Uso:
  herramienta.py listar [--duplicados]
  herramienta.py vistazo <archivo>
  herramienta.py mover --destino "Categoria[/Subcarpeta]" <archivo> [<archivo> ...]
  herramienta.py revisar --motivo "texto" <archivo> [<archivo> ...]
  herramienta.py renombrar --nuevo-nombre "Nombre" <carpeta>   (solo carpetas, nunca archivos)
  herramienta.py etiquetar --etiqueta "Nombre" [--color rojo] <ruta> [<ruta> ...]
  herramienta.py deshacer            (solo para uso manual, revierte la ultima ejecucion)
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
CONFIG = json.loads((AQUI / "config.json").read_text(encoding="utf-8"))

ORIGENES = [Path(os.path.expanduser(p)).resolve() for p in CONFIG["origenes"]]
BASE = Path(os.path.expanduser(CONFIG["carpeta_destino"])).resolve()
REVISAR = CONFIG["carpeta_revisar"]

# Modo carpeta especifica: se organiza ESA carpeta en su propio lugar
# (las categorias se crean dentro de ella). Lo activa el comando 'organizador'.
CARPETA_ESPECIFICA = os.environ.get("ORGANIZADOR_CARPETA", "")
MODO_LOCAL = bool(CARPETA_ESPECIFICA)
if MODO_LOCAL:
    ORIGENES = [Path(os.path.expanduser(CARPETA_ESPECIFICA)).resolve()]
    BASE = ORIGENES[0]
EXCLUIR = set(CONFIG.get("excluir_nombres", []))
MOVER_CARPETAS = bool(CONFIG.get("mover_carpetas", False))
RENOMBRAR_CARPETAS = bool(CONFIG.get("renombrar_carpetas", False))
PROTEGER_PROYECTOS = bool(CONFIG.get("proteger_proyectos", True))
MARCADORES = CONFIG.get("marcadores_proyecto", [".git"])
AJUSTAR_RUTAS = bool(CONFIG.get("ajustar_rutas_proyectos", False))
RESPALDOS = AQUI / "registro_local" / "respaldos"
# Dentro de un proyecto no se recorren estas carpetas (salvo los archivos puntuales de ENTORNO)
NO_RECORRER = {".git", "node_modules", "__pycache__", ".venv", "venv", "env", ".tox",
               ".mypy_cache", ".pytest_cache", ".ipynb_checkpoints", "site-packages"}
MAX_BYTES_AJUSTE = 5 * 1024 * 1024
LEER_CONTENIDO = bool(CONFIG.get("leer_contenido", True))
GUARDAR_REGISTRO = bool(CONFIG.get("guardar_registro_local", True))
SIMULACRO = os.environ.get("ORGANIZADOR_SIMULACRO") == "1"
EJECUCION = os.environ.get("ORGANIZADOR_EJECUCION", dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
REGISTRO = AQUI / "registro_local" / "movimientos.jsonl"

# Numeros de color de Finder
COLORES = {"ninguno": 0, "gris": 1, "verde": 2, "morado": 3, "azul": 4,
           "amarillo": 5, "rojo": 6, "naranja": 7}
EN_DESCARGA = {".crdownload", ".download", ".part", ".partial", ".tmp"}
SENSIBLES = {".pem", ".key", ".p12", ".pfx", ".keychain", ".kdbx", ".ovpn", ".gpg", ".asc"}
TEXTO = {".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".html", ".htm", ".py", ".r",
         ".m", ".tex", ".bib", ".log", ".yaml", ".yml", ".ini", ".sh", ".js", ".css", ".rtf"}
OFFICE = {".docx": "word/document.xml", ".pptx": "ppt/slides/", ".xlsx": "xl/sharedStrings.xml"}


def fallar(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)


def es_excluido(p: Path) -> bool:
    n = p.name
    r = p.resolve()
    if (n.startswith(".") or n in EXCLUIR or p.suffix.lower() in EN_DESCARGA
            or n.endswith(".app") or r == AQUI):
        return True
    if MODO_LOCAL:
        return n == REVISAR
    return r == BASE or BASE in r.parents


def es_categoria(p: Path) -> bool:
    """Modo carpeta especifica: subcarpeta creada antes por el organizador (lleva su propia etiqueta)."""
    if not MODO_LOCAL or not p.is_dir() or p.is_symlink() or p.parent.resolve() != BASE:
        return False
    return p.name in {t.split("\n")[0] for t in leer_etiquetas(p)}


def validar_carpeta_especifica():
    t = BASE
    home = Path.home().resolve()
    prohibidas = [home, home / "Library", Path("/"), AQUI]
    if not t.is_dir():
        fallar(f"la carpeta no existe: {t}")
    if home not in t.parents:
        fallar(f"solo se pueden organizar carpetas dentro de {home}: {t}")
    if t in prohibidas or (home / "Library") in t.parents or AQUI in t.parents or t in AQUI.parents:
        fallar(f"carpeta no permitida: {t}")
    if any(parte.startswith(".") for parte in t.relative_to(home).parts):
        fallar(f"no se organizan carpetas ocultas: {t}")
    if es_proyecto(t) or any(es_proyecto(x) for x in t.parents if home in x.parents):
        fallar(f"es (o esta dentro de) un proyecto de codigo; organizarla romperia su estructura: {t}")


def es_proyecto(p: Path) -> bool:
    """Carpeta de proyecto (git, entorno virtual, etc.): tiene rutas internas que pueden romperse."""
    if not p.is_dir() or p.is_symlink():
        return False
    return any(any(p.glob(m)) for m in MARCADORES)


def proyecto_bloqueado(p: Path) -> bool:
    return PROTEGER_PROYECTOS and es_proyecto(p)


def validar_origen(ruta: str) -> Path:
    p = Path(os.path.expanduser(ruta))
    if not p.exists() and not p.is_symlink():
        fallar(f"no existe: {ruta}")
    padre = p.parent.resolve()
    if padre not in ORIGENES:
        fallar(f"solo se pueden mover elementos sueltos de {', '.join(map(str, ORIGENES))}: {ruta}")
    if es_excluido(p):
        fallar(f"elemento excluido, no se toca: {p.name}")
    if p.is_dir() and not p.is_symlink() and not MOVER_CARPETAS:
        fallar(f"mover carpetas esta desactivado en config.json: {p.name}")
    if proyecto_bloqueado(p):
        fallar(f"carpeta de proyecto protegida, no se mueve: {p.name}")
    if es_categoria(p):
        fallar(f"es una categoria ya organizada, no se mueve: {p.name}")
    return p


def limpiar_destino(destino: str) -> Path:
    partes = [s.strip() for s in destino.replace("\\", "/").split("/") if s.strip()]
    if not partes or len(partes) > 2:
        fallar("--destino debe ser 'Categoria' o 'Categoria/Subcarpeta'")
    for s in partes:
        if s in (".", "..") or s.startswith(".") or re.search(r'[:\x00]', s):
            fallar(f"nombre de carpeta no valido: {s!r}")
    return BASE.joinpath(*partes)


def nombre_libre(carpeta: Path, nombre: str) -> Path:
    """Nunca sobrescribe: si ya existe, agrega ' (2)', ' (3)', ..."""
    destino = carpeta / nombre
    if not destino.exists():
        return destino
    stem, suf = Path(nombre).stem, Path(nombre).suffix
    if Path(nombre).is_dir() or not suf:
        stem, suf = nombre, ""
    i = 2
    while (carpeta / f"{stem} ({i}){suf}").exists():
        i += 1
    return carpeta / f"{stem} ({i}){suf}"


def leer_etiquetas(p: Path):
    r = subprocess.run(["xattr", "-px", "com.apple.metadata:_kMDItemUserTags", str(p)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return []
    try:
        return plistlib.loads(bytes.fromhex(r.stdout.replace("\n", "").replace(" ", "")))
    except Exception:
        return []


def poner_etiqueta(p: Path, etiqueta: str, color: str):
    """Agrega una etiqueta de Finder (metadato), sin tocar el contenido del archivo."""
    num = COLORES.get(color.lower(), 0) if color else 0
    actuales = leer_etiquetas(p)
    nombres = {t.split("\n")[0] for t in actuales}
    if etiqueta in nombres:
        return
    nuevas = actuales + [f"{etiqueta}\n{num}"]
    hexdata = plistlib.dumps(nuevas, fmt=plistlib.FMT_BINARY).hex()
    if SIMULACRO:
        return
    subprocess.run(["xattr", "-wx", "com.apple.metadata:_kMDItemUserTags", hexdata, str(p)],
                   check=False, capture_output=True)


def color_de(categoria: str) -> str:
    return CONFIG.get("categorias", {}).get(categoria, {}).get("color", "")


def asegurar_carpeta(carpeta: Path):
    if not carpeta.exists() and not SIMULACRO:
        carpeta.mkdir(parents=True, exist_ok=True)
    rel = carpeta.relative_to(BASE).parts
    if rel and rel[0] != REVISAR and (BASE / rel[0]).exists():
        # La etiqueta con su propio nombre marca la carpeta como categoria del organizador
        poner_etiqueta(BASE / rel[0], rel[0], color_de(rel[0]))


def registrar(origen: Path, destino: Path, motivo=""):
    if not GUARDAR_REGISTRO or SIMULACRO:
        return
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRO.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ejecucion": EJECUCION, "origen": str(origen.absolute()),
                            "destino": str(destino.absolute()), "motivo": motivo}, ensure_ascii=False) + "\n")


def registrar_edicion(archivo: Path, respaldo: Path):
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRO.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ejecucion": EJECUCION, "tipo": "edicion", "archivo": str(archivo),
                            "respaldo": str(respaldo)}, ensure_ascii=False) + "\n")


def especiales(d: Path):
    """Archivos de entornos y repositorios de la carpeta d que guardan rutas absolutas."""
    for env in ("venv", ".venv", "env"):
        e = d / env
        if (e / "pyvenv.cfg").exists():
            yield e / "pyvenv.cfg"
            if (e / "bin").is_dir():
                yield from (x for x in (e / "bin").iterdir() if x.is_file() and not x.is_symlink())
            for sp in e.glob("lib/python*/site-packages"):
                yield from sp.glob("*.pth")
                yield from sp.glob("*.dist-info/direct_url.json")
                yield from sp.glob("__editable__*")
    if (d / ".git" / "config").is_file():
        yield d / ".git" / "config"
    yield from (d / ".git").glob("worktrees/*/gitdir")


def archivos_a_revisar(raiz: Path):
    """Archivos de texto donde puede haber rutas absolutas (incluye proyectos anidados)."""
    for dirpath, dirnames, filenames in os.walk(raiz):
        d = Path(dirpath)
        yield from especiales(d)
        dirnames[:] = [x for x in dirnames if x not in NO_RECORRER]
        for f in filenames:
            yield d / f


def contiene_proyecto(raiz: Path, profundidad=4) -> bool:
    for dirpath, dirnames, _ in os.walk(raiz):
        d = Path(dirpath)
        if es_proyecto(d):
            return True
        if len(d.relative_to(raiz).parts) >= profundidad:
            dirnames[:] = []
        dirnames[:] = [x for x in dirnames if x not in NO_RECORRER]
    return False


def variantes(ruta: Path):
    """Formas en que puede aparecer una ruta: absoluta, con ~ y con $HOME."""
    abs_ = str(ruta)
    v = [abs_]
    home = str(Path.home())
    if abs_.startswith(home + "/"):
        resto = abs_[len(home):]
        v += ["~" + resto, "$HOME" + resto, "${HOME}" + resto]
    return v


def ajustar_rutas(viejo: Path, nuevo: Path, raiz_actual: Path):
    """Sustituye la ruta vieja por la nueva en el proyecto. Respaldo previo de cada archivo."""
    pares = list(zip(variantes(viejo), variantes(nuevo)))
    # (?![\w.\-]) evita tocar rutas que solo empiezan igual (p. ej. 'proyecto2')
    patrones = [(re.compile(re.escape(a) + r"(?![\w.\-])"), b) for a, b in pares]
    cambiados, vistos = [], set()
    lote = RESPALDOS / EJECUCION
    n_lote = len(list(lote.iterdir())) if lote.exists() else 0
    lote = lote / f"{n_lote:03d}-{nuevo.name}"
    for f in archivos_a_revisar(raiz_actual):
        if f in vistos:
            continue
        vistos.add(f)
        try:
            if f.is_symlink() or not f.is_file() or f.stat().st_size > MAX_BYTES_AJUSTE:
                continue
            datos = f.read_bytes()
            if b"\x00" in datos[:8192]:
                continue
            texto = datos.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        nuevo_texto, n = texto, 0
        for pat, rep_ in patrones:
            nuevo_texto, k = pat.subn(lambda m: rep_, nuevo_texto)
            n += k
        if not n:
            continue
        rel = f.relative_to(raiz_actual)
        cambiados.append((rel, n))
        if SIMULACRO:
            continue
        respaldo = lote / rel
        respaldo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, respaldo)
        modo = f.stat().st_mode
        f.write_text(nuevo_texto, encoding="utf-8")
        os.chmod(f, modo)
        registrar_edicion(f, respaldo)
    pre = "[SIMULACRO] " if SIMULACRO else ""
    if cambiados:
        print(f"{pre}RUTAS AJUSTADAS en {len(cambiados)} archivo(s) de '{nuevo.name}' (respaldo en registro_local/respaldos):")
        for rel, n in cambiados[:50]:
            print(f"   - {rel} ({n} reemplazo(s))")
        if len(cambiados) > 50:
            print(f"   ... y {len(cambiados) - 50} mas")
    else:
        print(f"{pre}Sin rutas absolutas que ajustar en '{nuevo.name}'.")
    externas = [l for l in buscar_relativas_externas(raiz_actual)][:10]
    if externas:
        print("   AVISO: rutas relativas que salen del proyecto (no se cambian, revisalas):")
        for e in externas:
            print(f"   - {e}")


def buscar_relativas_externas(raiz: Path):
    """Solo lectura: detecta '../' en codigo, que puede romperse al mover el proyecto."""
    pat = re.compile(r"""["'](\.\./[^"'\n]*)["']""")
    for f in archivos_a_revisar(raiz):
        if f.suffix.lower() not in {".py", ".r", ".m", ".sh", ".ipynb", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".js", ".ts"}:
            continue
        try:
            if f.stat().st_size > MAX_BYTES_AJUSTE:
                continue
            for i, linea in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                m = pat.search(linea)
                if m:
                    destino = (f.parent / m.group(1)).resolve()
                    if raiz.resolve() not in destino.parents and destino != raiz.resolve():
                        yield f"{f.relative_to(raiz)}:{i}  {m.group(1)}"
        except (OSError, UnicodeDecodeError):
            continue


def tras_mover(viejo: Path, nuevo: Path):
    """Si es un proyecto y esta permitido, ajusta sus rutas internas."""
    raiz = viejo if SIMULACRO else nuevo
    if AJUSTAR_RUTAS and raiz.is_dir() and not raiz.is_symlink() and contiene_proyecto(raiz):
        ajustar_rutas(viejo.absolute(), nuevo.absolute(), raiz)


def mover_uno(p: Path, carpeta: Path, etiqueta: str, color: str, motivo=""):
    if p.is_dir() and not p.is_symlink() and (carpeta == p.resolve() or p.resolve() in carpeta.parents):
        fallar(f"no se puede mover una carpeta dentro de si misma: {p.name}")
    asegurar_carpeta(carpeta)
    destino = nombre_libre(carpeta, p.name)
    pre = "[SIMULACRO] " if SIMULACRO else ""
    if not SIMULACRO:
        # os.rename es atomico y no copia; si son volumenes distintos, shutil.move
        # copia y luego retira el original (sigue siendo un movimiento, no un borrado de datos).
        if destino.exists():
            fallar(f"destino ocupado, no se sobrescribe: {destino}")
        try:
            os.rename(p, destino)
        except OSError:
            shutil.move(str(p), str(destino))
        if etiqueta:
            poner_etiqueta(destino, etiqueta, color)
        registrar(p, destino, motivo)
    print(f"{pre}MOVIDO: {p.name} -> {destino.relative_to(BASE)}")
    tras_mover(p.absolute(), destino)


# ---------------------------------------------------------------- ordenes

def cmd_listar(a):
    if MODO_LOCAL:
        print(f"MODO CARPETA ESPECIFICA: se organiza {BASE} en su propio lugar")
    print(f"DESTINO: {BASE}")
    if MODO_LOCAL:
        cats = sorted(d.name for d in BASE.iterdir() if es_categoria(d))
    else:
        cats = sorted(d.name for d in BASE.iterdir() if d.is_dir()) if BASE.exists() else []
    print(f"CATEGORIAS EXISTENTES: {cats}")
    hoy = dt.datetime.now().timestamp()
    elementos = []
    for o in ORIGENES:
        if not o.exists():
            continue
        for p in sorted(o.iterdir(), key=lambda x: x.name.lower()):
            if es_excluido(p):
                continue
            try:
                st = p.lstat()
            except OSError:
                continue
            es_dir = p.is_dir() and not p.is_symlink()
            if es_dir and not MOVER_CARPETAS:
                continue
            tam = st.st_size
            if es_dir and not proyecto_bloqueado(p):
                tam = sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())
            elementos.append((p, es_dir, tam, int((hoy - st.st_mtime) / 86400)))
    for p, es_dir, tam, dias in elementos:
        marca = " [POSIBLE SENSIBLE]" if p.suffix.lower() in SENSIBLES else ""
        if es_dir and es_categoria(p):
            marca = " [CATEGORIA ya organizada: no mover]"
        elif es_dir and proyecto_bloqueado(p):
            marca = " [PROYECTO PROTEGIDO: no mover ni renombrar]"
        elif es_dir and es_proyecto(p):
            marca = " [PROYECTO: al moverlo/renombrarlo se ajustan sus rutas internas]" if AJUSTAR_RUTAS else " [PROYECTO: sus rutas internas NO se ajustan]"
        print(f"{'DIR ' if es_dir else 'FILE'} | {p} | {tam/1e6:.2f} MB | {dias} dias sin modificar{marca}")
    print(f"TOTAL: {len(elementos)} elementos")
    if a.duplicados:
        por_tam = {}
        for p, es_dir, tam, _ in elementos:
            if not es_dir and tam > 0:
                por_tam.setdefault(tam, []).append(p)
        grupos = {}
        for lista in por_tam.values():
            if len(lista) < 2:
                continue
            for p in lista:
                h = hashlib.sha256()
                with p.open("rb") as f:
                    for bloque in iter(lambda: f.read(1 << 20), b""):
                        h.update(bloque)
                grupos.setdefault(h.hexdigest(), []).append(p)
        dup = [g for g in grupos.values() if len(g) > 1]
        print(f"DUPLICADOS EXACTOS: {len(dup)} grupos")
        for g in dup:
            print("  = " + " | ".join(str(x) for x in g))


def lector_pdf():
    """Compila pdf_texto.swift en bin/ la primera vez (o si cambio). None si no hay swiftc."""
    fuente, binario = AQUI / "pdf_texto.swift", AQUI / "bin" / "pdf_texto"
    if binario.exists() and binario.stat().st_mtime >= fuente.stat().st_mtime:
        return binario
    if not shutil.which("swiftc"):
        return None
    binario.parent.mkdir(exist_ok=True)
    r = subprocess.run(["swiftc", "-O", "-o", str(binario), str(fuente)],
                       capture_output=True, text=True)
    return binario if r.returncode == 0 else None


def texto_pdf(p: Path, n: int) -> str:
    """Capa de texto con PDFKit, OCR con Vision si es un escaneo; si falla, indice de Spotlight."""
    lector = lector_pdf()
    if lector:
        try:
            r = subprocess.run([str(lector), str(p), str(n), "2"],
                               capture_output=True, text=True, timeout=60)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()[:n]
        except subprocess.TimeoutExpired:
            pass
    r = subprocess.run(["mdls", "-raw", "-name", "kMDItemTextContent", str(p)],
                       capture_output=True, text=True).stdout
    return "" if r.strip() == "(null)" else r[:n]


def cmd_vistazo(a):
    p = Path(os.path.expanduser(a.archivo))
    if p.parent.resolve() not in ORIGENES:
        fallar("solo se puede mirar elementos sueltos de las carpetas de origen")
    print(f"NOMBRE: {p.name}")
    md = subprocess.run(["mdls", "-name", "kMDItemKind", "-name", "kMDItemWhereFroms",
                         "-name", "kMDItemTitle", "-name", "kMDItemNumberOfPages", str(p)],
                        capture_output=True, text=True).stdout
    print(md.strip())
    if p.is_dir():
        hijos = sorted(x.name for x in p.iterdir())[:30]
        print("CONTENIDO DE LA CARPETA (primeros 30):", hijos)
        return
    suf = p.suffix.lower()
    if suf in SENSIBLES:
        print("ARCHIVO POSIBLEMENTE SENSIBLE: no se lee su contenido.")
        return
    if not LEER_CONTENIDO:
        print("Lectura de contenido desactivada en config.json: clasifica por nombre y metadatos.")
        return
    n = int(CONFIG.get("max_caracteres_vistazo", 1200))
    texto = ""
    try:
        if suf in TEXTO:
            texto = p.read_text(encoding="utf-8", errors="ignore")[:n]
        elif suf in OFFICE:
            with zipfile.ZipFile(p) as z:
                nombres = [x for x in z.namelist() if x.startswith(OFFICE[suf])][:3]
                xml = " ".join(z.read(x).decode("utf-8", "ignore") for x in nombres)
                texto = re.sub(r"<[^>]+>", " ", xml)
                texto = re.sub(r"\s+", " ", texto)[:n]
        elif suf == ".pdf":
            texto = texto_pdf(p, n)
            if not texto:
                texto = "(sin texto legible: clasifica por nombre, fecha y metadatos)"
        else:
            texto = "(tipo binario: clasifica por nombre, extension y metadatos)"
    except Exception as e:
        texto = f"(no se pudo leer: {e})"
    print("EXTRACTO:", texto)


def cmd_mover(a):
    carpeta = limpiar_destino(a.destino)
    if carpeta.relative_to(BASE).parts[0] == REVISAR:
        fallar(f"para '{REVISAR}' usa la orden 'revisar'")
    cat = carpeta.relative_to(BASE).parts[0]
    for r in a.archivos:
        mover_uno(validar_origen(r), carpeta, cat, color_de(cat))


def cmd_revisar(a):
    carpeta = BASE / REVISAR
    for r in a.archivos:
        p = validar_origen(r)
        mover_uno(p, carpeta, "Revisar", "rojo", a.motivo)
        if not SIMULACRO:
            with (carpeta / "LEEME - motivos.txt").open("a", encoding="utf-8") as f:
                f.write(f"{dt.date.today()} | {p.name} | {a.motivo}\n")


def nombre_valido(n: str) -> str:
    n = n.strip()
    if not n or n in (".", "..") or n.startswith(".") or re.search(r'[/:\x00]', n) or len(n) > 120:
        fallar(f"nombre no valido: {n!r}")
    return n


def cmd_renombrar(a):
    if not RENOMBRAR_CARPETAS:
        fallar("renombrar carpetas esta desactivado en config.json")
    p = Path(os.path.expanduser(a.carpeta))
    if p.is_symlink() or not p.is_dir():
        fallar(f"solo se renombran carpetas (nunca archivos): {a.carpeta}")
    r = p.resolve()
    en_origen = r.parent in ORIGENES and not es_excluido(p)
    en_destino = BASE in r.parents and r != BASE / REVISAR
    if not (en_origen or en_destino):
        fallar("solo se renombran carpetas sueltas de las carpetas de origen o carpetas dentro de Organizado")
    if proyecto_bloqueado(r):
        fallar(f"carpeta de proyecto protegida, no se renombra: {p.name}")
    nuevo = r.parent / nombre_valido(a.nuevo_nombre)
    if nuevo.exists():
        fallar(f"ya existe una carpeta con ese nombre, no se sobrescribe: {nuevo.name}")
    pre = "[SIMULACRO] " if SIMULACRO else ""
    if not SIMULACRO:
        os.rename(r, nuevo)
        if nuevo.parent == BASE and color_de(nuevo.name):
            poner_etiqueta(nuevo, nuevo.name, color_de(nuevo.name))
        registrar(r, nuevo, "renombrado")
    print(f"{pre}RENOMBRADO: {r.name} -> {nuevo.name}")
    tras_mover(r, nuevo)


def cmd_etiquetar(a):
    for r in a.rutas:
        p = Path(os.path.expanduser(r)).resolve()
        if BASE not in p.parents:
            fallar(f"solo se etiquetan elementos ya organizados dentro de {BASE}")
        poner_etiqueta(p, a.etiqueta, a.color or "")
        print(f"{'[SIMULACRO] ' if SIMULACRO else ''}ETIQUETADO: {p.relative_to(BASE)} -> {a.etiqueta}")


def cmd_deshacer(a):
    if not REGISTRO.exists():
        fallar("no hay registro de movimientos")
    filas = [json.loads(l) for l in REGISTRO.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not filas:
        fallar("registro vacio")
    ultima = a.ejecucion or filas[-1]["ejecucion"]
    objetivo = [f for f in filas if f["ejecucion"] == ultima]
    restantes = [f for f in filas if f["ejecucion"] != ultima]
    for f in reversed(objetivo):
        if f.get("tipo") == "edicion":
            a, b = Path(f["archivo"]), Path(f["respaldo"])
            if a.exists() and b.exists():
                shutil.copy2(b, a)
                print(f"RESTAURADO: {a.name} (contenido original)")
            else:
                print(f"OMITIDO (no esta el archivo o su respaldo): {a}")
                restantes.append(f)
            continue
        o, d = Path(f["origen"]), Path(f["destino"])
        if d.exists() and not o.exists():
            os.rename(d, o)
            print(f"DEVUELTO: {d.name} -> {o}")
        else:
            print(f"OMITIDO (ya no esta o el origen esta ocupado): {d}")
            restantes.append(f)
    REGISTRO.write_text("".join(json.dumps(f, ensure_ascii=False) + "\n" for f in restantes),
                        encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="orden", required=True)
    s = sub.add_parser("listar"); s.add_argument("--duplicados", action="store_true"); s.set_defaults(f=cmd_listar)
    s = sub.add_parser("vistazo"); s.add_argument("archivo"); s.set_defaults(f=cmd_vistazo)
    s = sub.add_parser("mover"); s.add_argument("--destino", required=True); s.add_argument("archivos", nargs="+"); s.set_defaults(f=cmd_mover)
    s = sub.add_parser("revisar"); s.add_argument("--motivo", required=True); s.add_argument("archivos", nargs="+"); s.set_defaults(f=cmd_revisar)
    s = sub.add_parser("renombrar"); s.add_argument("--nuevo-nombre", required=True); s.add_argument("carpeta"); s.set_defaults(f=cmd_renombrar)
    s = sub.add_parser("etiquetar"); s.add_argument("--etiqueta", required=True); s.add_argument("--color"); s.add_argument("rutas", nargs="+"); s.set_defaults(f=cmd_etiquetar)
    s = sub.add_parser("validar"); s.set_defaults(f=lambda a: print(f"OK: {BASE}"))
    s = sub.add_parser("deshacer"); s.add_argument("--ejecucion"); s.set_defaults(f=cmd_deshacer)
    a = ap.parse_args()
    if MODO_LOCAL and a.orden != "deshacer":
        validar_carpeta_especifica()
    if a.orden == "deshacer" and os.environ.get("ORGANIZADOR_AGENTE") == "1":
        fallar("'deshacer' es solo para uso manual")
    a.f(a)


if __name__ == "__main__":
    main()
