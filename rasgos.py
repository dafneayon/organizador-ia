"""Rasgos y predicción del clasificador local (solo biblioteca estándar).

Lo comparten entrenar.py (que usa scikit-learn para entrenar) y herramienta.py
(que predice sin dependencias). Como los dos usan la misma función `rasgos`,
la predicción en herramienta.py es idéntica a la del modelo entrenado.

El modelo es una regresión logística exportada a JSON: para cada rasgo, un peso
por clase. Predecir es sumar los pesos de los rasgos presentes y aplicar softmax.
"""
import json
import math
import re
import unicodedata
from pathlib import Path

CAPTURA = re.compile(r"^(captura de pantalla|screenshot|screen shot|cleanshot)", re.I)
RFC = re.compile(r"\b[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}\b")
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
FECHA = re.compile(r"(19|20)\d{2}[-_. ]?(0[1-9]|1[0-2])([-_. ]?\d{2})?")
COPIA = re.compile(r"(\(\d+\)|-\d|copia|copy)$", re.I)


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos y con los dígitos convertidos en '#'."""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\d", "#", t.lower())


def separar_nombre(nombre: str, es_dir: bool):
    if es_dir or "." not in nombre.strip("."):
        return nombre, ""
    base, ext = nombre.rsplit(".", 1)
    return base, ext.lower()


def grupo(nombre: str, es_dir=False) -> str:
    """Clave para agrupar versiones del mismo archivo (cv.pdf, cv (1).pdf, cv_v2.pdf)
    en la validación cruzada, para que no se filtren de entrenamiento a prueba."""
    base, ext = separar_nombre(nombre, es_dir)
    base = COPIA.sub("", normalizar(base).strip())
    base = re.sub(r"[#\s_\-.()]+", " ", base)
    base = re.sub(r"\b(v|ver|version|final|ok|nuevo|new)\b", " ", base)
    return " ".join(base.split()) + "|" + ext


def rasgos(nombre: str, es_dir=False, tamano=None, origen=""):
    """Rasgos binarios de un elemento a partir de su nombre y metadatos (nunca del contenido)."""
    base, ext = separar_nombre(nombre, es_dir)
    r = {"dir" if es_dir else "ext:" + (ext or "(sin)")}
    norm = normalizar(base)
    for palabra in re.findall(r"[a-z#]+", norm):
        if len(palabra) >= 2 and set(palabra) != {"#"}:
            r.add("pal:" + palabra)
    texto = " " + re.sub(r"[^a-z#]+", " ", norm).strip() + " "
    for n in (3, 4):
        for i in range(len(texto) - n + 1):
            g = texto[i:i + n]
            if g.strip():
                r.add("cg:" + g)
    if CAPTURA.search(base):
        r.add("patron:captura")
    if RFC.search(base.upper()):
        r.add("patron:rfc")
    if UUID.search(base):
        r.add("patron:uuid")
    if FECHA.search(base):
        r.add("patron:fecha")
    if COPIA.search(base.strip()):
        r.add("patron:copia")
    if tamano is not None:
        # Cubetas logarítmicas: <1 KB, ~10 KB, ~100 KB, ~1 MB...
        r.add("tam:%d" % min(9, int(math.log10(max(tamano, 1)))))
    if origen:
        r.add("origen:" + Path(origen).name.lower())
    return sorted(r)


class Modelo:
    def __init__(self, datos: dict):
        self.clases = datos["clases"]
        self.pesos = datos["pesos"]
        self.sesgo = datos["sesgo"]
        self.umbral = float(datos.get("umbral", 1.01))
        self.info = datos.get("info", {})

    @classmethod
    def cargar(cls, ruta: Path):
        try:
            return cls(json.loads(Path(ruta).read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError):
            return None

    def probabilidades(self, lista_rasgos):
        z = list(self.sesgo)
        for f in lista_rasgos:
            w = self.pesos.get(f)
            if w:
                for k, v in enumerate(w):
                    z[k] += v
        m = max(z)
        e = [math.exp(v - m) for v in z]
        s = sum(e)
        return [v / s for v in e]

    def predecir(self, nombre, es_dir=False, tamano=None, origen=""):
        """(clase, probabilidad) de la clase más probable."""
        p = self.probabilidades(rasgos(nombre, es_dir, tamano, origen))
        k = max(range(len(p)), key=p.__getitem__)
        return self.clases[k], p[k]
