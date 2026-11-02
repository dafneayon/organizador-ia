#!/usr/bin/env python3
"""Entrena el clasificador local con el historial del Organizador IA.

Aprende a imitar las decisiones que ya tomó el agente (Claude), usando solo el
nombre, la extensión, el tamaño y el origen de cada elemento (nunca su contenido).

1. Lee los ejemplos de la vista v_entrenamiento del catálogo SQLite.
2. Compara varios modelos con validación cruzada estratificada y AGRUPADA:
   las versiones de un mismo archivo (cv.pdf, cv (1).pdf) caen siempre en el
   mismo pliegue, para no inflar la precisión.
3. Elige el umbral de confianza: el más bajo con el que, fuera de muestra, la
   precisión de lo que el modelo decide solo es al menos la objetivo.
4. Exporta la regresión logística a registro_local/modelo.json, que
   herramienta.py usa sin scikit-learn.

    .venv/bin/python entrenar.py
"""
import datetime as dt
import json
import sqlite3
import sys
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import make_pipeline
from sklearn.svm import LinearSVC

import catalogo
from rasgos import Modelo, grupo, rasgos

AQUI = Path(__file__).resolve().parent
CONF = catalogo.CONFIG.get("clasificador", {})
PRECISION_OBJETIVO = float(CONF.get("precision_objetivo", 0.95))
MIN_EJEMPLOS_CLASE = int(CONF.get("min_ejemplos_clase", 3))
MODELO = AQUI / "registro_local" / "modelo.json"
REPORTE = AQUI / "registro_local" / "reporte_modelo.md"
PLIEGUES, REPETICIONES = 5, 3

warnings.filterwarnings("ignore", category=UserWarning)  # clases con pocos ejemplos por pliegue


def cargar(db):
    con = sqlite3.connect(db)
    filas = con.execute("SELECT nombre, es_dir, tamano, carpeta_origen, etiqueta FROM v_entrenamiento").fetchall()
    cuenta = Counter(f[4] for f in filas)
    fuera = {e: n for e, n in cuenta.items() if n < MIN_EJEMPLOS_CLASE}
    filas = [f for f in filas if f[4] not in fuera]
    X = [{r: 1 for r in rasgos(n, bool(d), t, o)} for n, d, t, o, _ in filas]
    y = np.array([f[4] for f in filas])
    g = np.array([grupo(f[0], bool(f[1])) for f in filas])
    return X, y, g, fuera


def solo_extension(X):
    return [{k: v for k, v in x.items() if k.startswith(("ext:", "dir"))} for x in X]


def candidatos():
    lr = lambda c, w=None: make_pipeline(DictVectorizer(), LogisticRegression(C=c, max_iter=5000, class_weight=w))
    return {
        "Clase mayoritaria (referencia)": (lambda: make_pipeline(DictVectorizer(), DummyClassifier()), False),
        "Solo extensión + reg. logística": (lambda: lr(3), True),
        "Naive Bayes complementario": (lambda: make_pipeline(DictVectorizer(), ComplementNB(alpha=0.3)), False),
        "SVM lineal": (lambda: make_pipeline(DictVectorizer(), LinearSVC(C=0.5)), False),
        "Random forest": (lambda: make_pipeline(DictVectorizer(), RandomForestClassifier(
            n_estimators=300, random_state=0, class_weight="balanced_subsample")), False),
        **{f"Reg. logística C={c}{' balanceada' if w else ''}": ((lambda c=c, w=w: lr(c, w)), False)
           for c in (0.3, 1, 3, 10) for w in (None, "balanced")},
    }


def validar(hacer, X, y, g, semilla):
    """Predicciones fuera de muestra (y probabilidades si el modelo las da)."""
    pred = np.empty(len(y), dtype=object)
    proba = np.zeros(len(y))
    cv = StratifiedGroupKFold(n_splits=PLIEGUES, shuffle=True, random_state=semilla)
    for tr, te in cv.split(X, y, g):
        m = hacer().fit([X[i] for i in tr], y[tr])
        Xte = [X[i] for i in te]
        pred[te] = m.predict(Xte)
        if hasattr(m, "predict_proba"):
            proba[te] = m.predict_proba(Xte).max(axis=1)
    return pred, proba


def curva_umbral(acierto, proba):
    """Para cada umbral: qué fracción decide el modelo solo y con qué precisión."""
    filas = []
    for t in np.round(np.arange(0.30, 1.00, 0.05), 2):
        sel = proba >= t
        if sel.sum():
            filas.append((float(t), float(sel.mean()), float(acierto[sel].mean()), int(sel.sum())))
    return filas


def wilson(p, n, z=1.96):
    """Intervalo de confianza del 95% de una proporción (Wilson), útil con pocos casos."""
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    m = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, c - m), min(1.0, c + m)


def elegir_umbral(curva):
    for t, cobertura, precision, n in curva:
        # Pide un mínimo de casos para que la precisión estimada no sea casualidad
        if precision >= PRECISION_OBJETIVO and n >= 20:
            return t, cobertura, precision
    return 1.01, 0.0, float("nan")  # nunca decide solo


def calibracion(acierto, proba, cubetas=5):
    """Error de calibración esperado (ECE): cuánto se aleja la confianza de la precisión real."""
    bordes = np.linspace(0, 1, cubetas + 1)
    ece = 0.0
    for a, b in zip(bordes[:-1], bordes[1:]):
        sel = (proba > a) & (proba <= b)
        if sel.any():
            ece += sel.mean() * abs(acierto[sel].mean() - proba[sel].mean())
    return float(ece)


def exportar(m, n_ejemplos, umbral, metricas):
    vec, lr = m.named_steps["dictvectorizer"], m.named_steps["logisticregression"]
    coef, sesgo = lr.coef_, lr.intercept_
    if len(lr.classes_) == 2:  # softmax de [-z/2, z/2] = sigmoide(z)
        coef, sesgo = np.vstack([-coef / 2, coef / 2]), np.array([-sesgo[0] / 2, sesgo[0] / 2])
    pesos = {f: [round(float(w), 6) for w in coef[:, i]] for f, i in vec.vocabulary_.items()}
    datos = {"clases": [str(c) for c in lr.classes_], "pesos": pesos,
             "sesgo": [round(float(b), 6) for b in sesgo], "umbral": umbral,
             "info": {"entrenado": dt.datetime.now().isoformat(timespec="seconds"),
                      "ejemplos": n_ejemplos, "rasgos": len(pesos), **metricas}}
    MODELO.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return datos


def main():
    con = catalogo.construir()
    X, y, g, fuera = cargar(catalogo.DB)
    if len(set(y)) < 2 or len(y) < 30:
        sys.exit(f"Muy pocos ejemplos para entrenar ({len(y)}). Organiza más archivos primero.")
    if len(set(g)) < 2 * PLIEGUES:
        sys.exit(f"Muy pocos archivos distintos para validar ({len(set(g))} grupos). Organiza más archivos primero.")
    print(f"{len(y)} ejemplos, {len(set(y))} clases, {len(set(g))} grupos")
    if fuera:
        print(f"Sin suficientes ejemplos (se dejan al agente): {fuera}")

    resultados = {}
    for nombre, (hacer, ext_sola) in candidatos().items():
        Xm = solo_extension(X) if ext_sola else X
        acc, f1 = [], []
        for s in range(REPETICIONES):
            pred, _ = validar(hacer, Xm, y, g, s)
            acc.append(accuracy_score(y, pred))
            f1.append(f1_score(y, pred, average="macro"))
        resultados[nombre] = (np.mean(acc), np.std(acc), np.mean(f1), np.std(f1))
        print(f"  {nombre:38s} exactitud {np.mean(acc):.3f} ± {np.std(acc):.3f}   F1 macro {np.mean(f1):.3f}")

    # Solo la regresión logística se exporta (es lineal y da probabilidades)
    mejor = max((n for n in resultados if n.startswith("Reg. logística C")), key=lambda n: resultados[n][2])
    hacer = candidatos()[mejor][0]
    pred, proba = validar(hacer, X, y, g, 0)
    acierto = (pred == y)
    acierto_cat = np.array([p.split("/")[0] == v.split("/")[0] for p, v in zip(pred, y)])
    curva = curva_umbral(acierto, proba)
    umbral, cobertura, precision = elegir_umbral(curva)
    ece = calibracion(acierto, proba)

    modelo = hacer().fit(X, y)
    metricas = {"modelo": mejor, "exactitud_cv": round(resultados[mejor][0], 4),
                "f1_macro_cv": round(resultados[mejor][2], 4),
                "exactitud_categoria_cv": round(float(acierto_cat.mean()), 4),
                "cobertura_umbral": round(cobertura, 4), "precision_umbral": round(precision, 4),
                "ece": round(ece, 4)}
    exportado = exportar(modelo, len(y), umbral, metricas)

    # La predicción sin scikit-learn debe coincidir con la de scikit-learn
    m = Modelo(exportado)
    ref = modelo.predict_proba(X)
    dif = max(abs(a - b) for x, fila in zip(X, ref) for a, b in zip(m.probabilidades(list(x)), fila))
    assert dif < 1e-4, f"la predicción exportada no coincide con scikit-learn (dif {dif})"

    lineas = [
        "# Reporte del clasificador local", "",
        f"Entrenado: {exportado['info']['entrenado']} · {len(y)} ejemplos · {len(set(y))} clases · "
        f"{PLIEGUES} pliegues agrupados × {REPETICIONES} repeticiones", "",
        "La etiqueta es lo que decidió el agente, así que la exactitud mide cuánto coincide el modelo con él.", "",
        "## Comparación de modelos", "",
        "| Modelo | Exactitud | F1 macro |", "|---|---|---|",
        *[f"| {n}{' **(elegido)**' if n == mejor else ''} | {a:.3f} ± {sa:.3f} | {f:.3f} ± {sf:.3f} |"
          for n, (a, sa, f, sf) in resultados.items()], "",
        f"Exactitud solo en la categoría principal: {acierto_cat.mean():.3f}", "",
        f"Error de calibración (ECE): {ece:.3f}", "",
        "## Umbral de confianza", "",
        f"Objetivo: precisión ≥ {PRECISION_OBJETIVO:.0%} en lo que el modelo decide solo.", "",
        "| Umbral | Decide solo | Precisión | IC 95% | Casos |", "|---|---|---|---|---|",
        *[f"| {t:.2f}{' **←**' if t == umbral else ''} | {c:.1%} | {p:.1%} | "
          f"{wilson(p, n)[0]:.0%}–{wilson(p, n)[1]:.0%} | {n} |" for t, c, p, n in curva], "",
        (f"**Umbral elegido: {umbral:.2f}.** El modelo decidiría solo el {cobertura:.0%} de los casos "
         f"con {precision:.1%} de precisión (IC 95%: {wilson(precision, round(cobertura * len(y)))[0]:.0%}–"
         f"{wilson(precision, round(cobertura * len(y)))[1]:.0%}); el resto sigue yendo al agente."
         if umbral <= 1 else "**Ningún umbral alcanza el objetivo:** el modelo solo sugiere, no decide."), "",
        "## Detalle por clase (validación cruzada)", "", "```",
        classification_report(y, pred, zero_division=0), "```",
    ]
    if fuera:
        lineas += ["", f"Clases con menos de {MIN_EJEMPLOS_CLASE} ejemplos (no se aprenden): "
                   + ", ".join(f"{e} ({n})" for e, n in sorted(fuera.items()))]
    REPORTE.write_text("\n".join(lineas) + "\n", encoding="utf-8")

    print(f"\nElegido: {mejor} · exactitud {metricas['exactitud_cv']:.3f} · categoría {metricas['exactitud_categoria_cv']:.3f}"
          f" · ECE {ece:.3f}")
    print(f"Umbral {umbral:.2f}: decide solo el {cobertura:.0%} con precisión {precision:.1%}")
    print(f"Modelo: {MODELO}\nReporte: {REPORTE}")
    con.close()


if __name__ == "__main__":
    main()
