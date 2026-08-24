# Retrieval evaluation — 24 August 2026

This report records one real run of `evaluation/dataset.json`; it is not a benchmark claim. The
run used the ARM64 Docker image, Python 3.12, FastEmbed 0.8.0,
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions), and
`qdrant/qdrant:v1.19.0-unprivileged` on Docker Desktop for Apple Silicon.

Dataset: 3 documents, 6 chunks, and 6 queries. Queries cover Turkish and English paraphrases,
exact keywords, multiple documents, and an irrelevant topic. `top_k=5`, `max_tokens=500`, and
`max_chars=2000` were applied to every mode.

| Mode | Recall@5 | MRR | Hit rate | Mean query time | Mean returned tokens |
|---|---:|---:|---:|---:|---:|
| Lexical | 0.6667 | 0.6667 | 0.8333 | 0.662 ms | 40.17 |
| Semantic | 0.8333 | 0.6667 | 0.8333 | 98.454 ms | 58.83 |
| Hybrid RRF | 1.0000 | 0.7500 | 1.0000 | 100.932 ms | 70.00 |

Observed supporting measurements:

- First cache preparation plus model load: 38,248.016 ms. This includes the initial network
  download and must not be interpreted as a warm-start load time.
- Cached model load plus batch embedding of 6 chunks across 3 documents: 955.813 ms.
- Peak evaluator process RSS: 748.93 MiB.
- All semantic/hybrid responses reported the requested actual mode; no fallback occurred.
- The final response token cap was respected in all 18 retrieval calls.

The run predates the evaluator's separate printed fields for query-embedding and vector-search
sub-timings, so only end-to-end semantic query time is reported here. The current evaluator emits
those fields on the next run. Per-collection Qdrant disk bytes were also not available through the
adapter in this run and are deliberately not estimated. Measure the deployment volume with the
documented host command.

Notable query behavior:

- The English paraphrase “How early should vacation be submitted?” was missed by lexical and hit
  at rank 1 by semantic and hybrid.
- The Turkish recovery paraphrase reached both expected chunks with semantic and hybrid; lexical
  returned one of the two.
- Exact English `full disk encryption` was rank 1 in all modes.
- The multi-document recovery query reached both expected chunks in semantic and hybrid.
- The irrelevant Mars query returned no chunks in all modes at the configured minimum semantic
  score.

Reproduce with:

```bash
docker compose -f compose.prod.yaml -f compose.semantic.yaml run --rm \
  -v "$PWD/evaluation:/evaluation:ro" gateway \
  private-document-gateway-evaluate /evaluation/dataset.json
```

Results vary with CPU, model version, Qdrant cache state, corpus, and thresholds. Re-run this
evaluation on the target Oracle VM before tuning production limits.
