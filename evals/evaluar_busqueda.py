#!/usr/bin/env python3
"""Evalúa la búsqueda con un corpus sintético (evals/corpus) y preguntas con respuesta conocida.

Compara palabras clave (BM25), significado (embeddings) e híbrida (RRF) con
Recall@1, Recall@3 y MRR, en total y por tipo de pregunta:
- palabras:   comparte palabras con el documento
- parafrasis: dice lo mismo con otras palabras
- ingles:     pregunta en inglés por un documento en español

    .venv/bin/python evals/evaluar_busqueda.py            # escribe evals/resultados_busqueda.md
"""
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

EVALS = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS.parent))
import busqueda  # noqa: E402


def evaluar(modos=("bm25", "vector", "hibrido")):
    preguntas = [json.loads(l) for l in (EVALS / "preguntas.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "indice.db"
        busqueda.CONF["carpetas"] = [str(EVALS / "corpus")]
        busqueda.indexar(con=busqueda.conectar(db), salida=open("/dev/null", "w"))
        b = busqueda.Buscador(db)
        resultados = {}
        for modo in modos:
            por_tipo = defaultdict(lambda: {"r1": 0, "r3": 0, "rr": 0.0, "n": 0})
            fallos = []
            for q in preguntas:
                nombres = [r["nombre"] for r in b.buscar(q["pregunta"], 10, modo)]
                pos = nombres.index(q["esperado"]) + 1 if q["esperado"] in nombres else None
                for t in (q["tipo"], "total"):
                    m = por_tipo[t]
                    m["n"] += 1
                    m["r1"] += pos == 1
                    m["r3"] += bool(pos and pos <= 3)
                    m["rr"] += 1 / pos if pos else 0
                if pos != 1:
                    fallos.append((q["pregunta"], q["esperado"], nombres[:1]))
            resultados[modo] = ({t: {"recall@1": m["r1"] / m["n"], "recall@3": m["r3"] / m["n"],
                                     "mrr": m["rr"] / m["n"], "n": m["n"]} for t, m in por_tipo.items()}, fallos)
        return resultados, len(preguntas)


def main():
    if not busqueda.embeddings_disponibles():
        sys.exit("Necesita fastembed: .venv/bin/pip install -r requirements-busqueda.txt")
    resultados, n = evaluar()
    nombres = {"bm25": "Palabras clave (BM25)", "vector": "Significado (embeddings)", "hibrido": "Híbrida (RRF)"}
    tipos = ["total", "palabras", "parafrasis", "ingles"]
    lineas = ["# Evaluación de la búsqueda", "",
              f"Corpus sintético de {len(list((EVALS / 'corpus').rglob('*.*')))} documentos y {n} preguntas "
              f"con respuesta conocida. Modelo: `{busqueda.MODELO_EMB}`.", "",
              "| Modo | Recall@1 | Recall@3 | MRR |", "|---|---|---|---|"]
    for modo, (m, _) in resultados.items():
        t = m["total"]
        lineas.append(f"| {nombres[modo]} | {t['recall@1']:.0%} | {t['recall@3']:.0%} | {t['mrr']:.3f} |")
    lineas += ["", "## Recall@1 por tipo de pregunta", "",
               "| Modo | " + " | ".join(f"{t} (n={resultados['bm25'][0][t]['n']})" for t in tipos[1:]) + " |",
               "|---|" + "---|" * (len(tipos) - 1)]
    for modo, (m, _) in resultados.items():
        lineas.append(f"| {nombres[modo]} | " + " | ".join(f"{m[t]['recall@1']:.0%}" for t in tipos[1:]) + " |")
    lineas += ["", "## Fallos de la búsqueda híbrida (Recall@1)", ""]
    fallos = resultados["hibrido"][1]
    lineas += [f"- \"{p}\": esperaba `{e}`, primero salió `{(t or ['nada'])[0]}`" for p, e, t in fallos] or ["- Ninguno"]
    salida = EVALS / "resultados_busqueda.md"
    salida.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("\n".join(lineas))


if __name__ == "__main__":
    main()
