# Private semantic and hybrid search

Semantic özellik opt-in'dir. Varsayılan `lexical` mod SQLite FTS5, başlık ağırlıklı BM25 ve
token/karakter bütçesiyle Sprint 2 davranışını korur. `semantic`, query vektörü ile aynı model ve
version metadata'sına sahip chunk vektörlerini arar. `hybrid`, iki listenin rank'lerini Reciprocal
Rank Fusion ile birleştirir; aynı chunk tek kez döner.

## Bileşenler ve gizlilik

- `EmbeddingProvider`: CPU/ONNX üzerinde çalışan FastEmbed adapter'ı. Model process içinde lazy
  olarak bir kez yüklenir; chunk'lar batch halinde ve sınırlı concurrency ile embed edilir.
- `VectorStore`: Qdrant adapter'ı. Point payload'ında `document_id`, `chunk_id`, ad, dosya türü,
  heading, position, SHA-256 content hash, model/version/dimension ve `indexed_at` bulunur. Chunk
  metni Qdrant payload'ına kopyalanmaz; sonuç metni SQLite'tan okunur.
- `RetrievalStrategy`: lexical, semantic ve hybrid sıralamayı ortak kaynak/bütçe aşamasına verir.

Varsayılan model
[`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)
384 boyut üretir, 50 dili kapsar ve Apache-2.0 lisanslıdır. FastEmbed modeli CPU'da ONNX Runtime
ile çalıştırır. Query/passage prefix gerektiren başka modeller için
`PDG_EMBEDDING_QUERY_PREFIX` ve `PDG_EMBEDDING_PASSAGE_PREFIX` provider girişinde uygulanır.

Uygulamada cloud embedding istemcisi ve telemetry yoktur. `DO_NOT_TRACK=1`,
`HF_HUB_DISABLE_TELEMETRY=1` ve `SCARF_NO_ANALYTICS=true` image'da varsayılandır. Model indirme
dışında production egress gerekmez; belge ve sorgular indirme container'ına mount edilmez.

## Kurulum ve offline çalışma

Önce `.env.example` ayarlarını kopyalayın. Production gateway offline başlatıldığı için modeli
ilk kez ayrı egress ağı olan setup container'ıyla indirin:

```bash
docker compose -f compose.prod.yaml -f compose.semantic.yaml \
  --profile semantic-setup run --rm model-downloader
docker compose -f compose.prod.yaml -f compose.semantic.yaml up -d --build gateway qdrant
docker compose -f compose.prod.yaml -f compose.semantic.yaml ps
```

Air-gapped hedefte aynı `model_cache` volume içeriğini internet erişimli ve aynı mimarideki bir
hazırlık hostundan kontrollü biçimde taşıyın. Cache hedefte `/models` olarak mount edilmeli ve
gateway için okunabilir olmalıdır. Ardından `PDG_EMBEDDING_OFFLINE=true` ile başlatın. Model
dosyaları yoksa gateway kapanmaz; semantic/hybrid çağrı `lexical_fallback` döndürür.

Kapatmak için `compose.semantic.yaml` dosyasını Compose çağrısından çıkarın. Böylece Qdrant,
FastEmbed ve model ağırlıkları temel image için zorunlu olmaz.

## Ayarlar

| Değişken | Varsayılan | Anlamı |
|---|---|---|
| `PDG_SEMANTIC_ENABLED` | `false` | Semantic runtime'ı açar |
| `PDG_DEFAULT_RETRIEVAL_MODE` | `lexical` | Parametresiz arama modu |
| `PDG_SEMANTIC_FALLBACK_ENABLED` | `true` | Semantic hata durumunda lexical devam |
| `PDG_EMBEDDING_MODEL` | multilingual MiniLM | FastEmbed model adı |
| `PDG_EMBEDDING_MODEL_VERSION` | `fastembed-0.8.0-onnx-q` | Index uyumluluk etiketi |
| `PDG_EMBEDDING_DIMENSION` | `384` | Model/vector collection dimension |
| `PDG_EMBEDDING_BATCH_SIZE` | `32` | Chunk embedding batch boyutu |
| `PDG_MAX_CONCURRENT_EMBEDDINGS` | `1` | Aynı anda CPU-ağır embedding işi |
| `PDG_VECTOR_STORE_URL` | `http://qdrant:6333` | Yalnız internal Qdrant URL'si |
| `PDG_VECTOR_COLLECTION` | `pdg_chunks_v1` | Koleksiyon adı |
| `PDG_HYBRID_RRF_K` | `60` | RRF dengeleme sabiti |
| `PDG_MAX_RESULTS_PER_DOCUMENT` | `3` | Sonuç çeşitliliği; `0` limitsiz |

Model değiştirirken model adı, version etiketi ve dimension'ı birlikte güncelleyin. Collection
dimension değişiyorsa yeni bir `PDG_VECTOR_COLLECTION` adı kullanın; mevcut dimension ile
uyumsuz collection kontrollü fallback üretir. Ardından:

```bash
docker compose -f compose.prod.yaml -f compose.semantic.yaml run --rm gateway \
  private-document-gateway-semantic reindex --force
```

Normal upload/reindex yalnızca content hash'i yeni olan chunk'ları embed eder. Aynı içerik yeni
chunk UUID'si aldıysa mevcut vektör yeniden kullanılır. Tam batch başarıyla upsert edilmeden stale
vektörler silinmez. Belge silme Qdrant point'lerini de temizler; geçici Qdrant hatasında stale
point'in SQLite karşılığı olmadığı için sonuç olarak sunulmaz ve sonraki force reindex temizler.

## MCP ve fallback

`search_documents`, `search_document` ve `get_relevant_chunks` araçları `retrieval_mode` alır.
İlki ayrıca `document_ids`; tüm genel retrieval araçları `file_types` ve exact `heading` filtresi
alabilir. Aynı alanlar yapılandırılmış `filters` nesnesiyle de verilebilir. `top_k`, `max_chars`,
`max_tokens`, cursor, duplicate/overlap temizleme ve sınırlı komşu
chunk genişletmesi bütün modlardan sonra ortak ve kesin uygulanır.

Şu durumlarda, fallback açıksa, response modu `lexical_fallback` olur: model/cache yüklenememesi,
query embedding hatası, Qdrant kesintisi, collection dimension uyuşmazlığı ve semantic index'in
henüz hazır olmaması. Fallback kapalıysa kontrollü `semantic_unavailable` hatası döner. Loglarda
yalnız hata tipi bulunur; query veya belge metni bulunmaz.

## Kaynak planlaması ve ölçüm

Semantic production profili gateway için varsayılan `3g`, Qdrant için `1g` container limiti
tanımlar. Bunlar kullanım iddiası değil güvenli başlangıç limitleridir. Oracle Ampere A1 üzerinde
semantic profil için en az 4 GB yerine 6 GB RAM ile başlamak, gerçek corpus ölçümüne göre aşağı
veya yukarı ayarlamak daha güvenlidir. Model cache, vector volume ve belge/cache/database
volume'ları için ayrı disk izlemesi yapın.

Repodaki Türkçe/İngilizce değerlendirme seti exact, paraphrase, çoklu belge ve alakasız sorgular
içerir. Gerçek local model ve Qdrant ile rapor üretin:

```bash
docker compose -f compose.prod.yaml -f compose.semantic.yaml run --rm \
  -v "$PWD/evaluation:/evaluation:ro" gateway \
  private-document-gateway-evaluate /evaluation/dataset.json
```

Production image evaluation klasörünü kopyalamaz; yukarıdaki komut dataset'i bakım container'ına
read-only mount eder. Alternatif olarak repo checkout'unda `pip install -e '.[semantic,dev]'`
sonrası komutu çalıştırın. Rapor Recall@5, MRR, hit rate, ortalama sorgu süresi, ortalama dönen
yaklaşık token, batch embedding süresi ve peak RSS ölçer. Adapter per-collection disk byte
vermediği için vector volume boyutunu ayrıca ölçün:

```bash
docker system df -v
sudo du -sh /var/lib/docker/volumes/private-document-gateway_vector_data/_data
```

Rapor üretilmeden bu doküman tasarruf, latency veya kalite yüzdesi iddia etmez.
