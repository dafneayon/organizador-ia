# Evaluación de la búsqueda

Corpus sintético de 18 documentos y 30 preguntas con respuesta conocida. Modelo: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.

| Modo | Recall@1 | Recall@3 | MRR |
|---|---|---|---|
| Palabras clave (BM25) | 70% | 77% | 0.733 |
| Significado (embeddings) | 73% | 93% | 0.824 |
| Híbrida (RRF) | 90% | 97% | 0.942 |

## Recall@1 por tipo de pregunta

| Modo | palabras (n=12) | parafrasis (n=12) | ingles (n=6) |
|---|---|---|---|
| Palabras clave (BM25) | 100% | 75% | 0% |
| Significado (embeddings) | 58% | 75% | 100% |
| Híbrida (RRF) | 92% | 92% | 83% |

## Fallos de la búsqueda híbrida (Recall@1)

- "recibo de CFE": esperaba `recibo_cfe_agosto_2026.txt`, primero salió `acuse_declaracion_anual_2025.txt`
- "¿cómo elegí cuántos grupos tiene cada tumor?": esperaba `capitulo_metodologia.md`, primero salió `brain_tumor_segmentation_mri.txt`
- "plane ticket to Canada": esperaba `vuelo_gdl_calgary.txt`, primero salió `constancia_beca_elap.txt`
