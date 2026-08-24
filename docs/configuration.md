# Configuration contract

Settings use the `CORPUSGATE_` prefix and are validated before the HTTP service starts. Secret values are
never included in validation output. Numeric ranges below are enforced by the application; default
values shown are application defaults unless Compose overrides them.

## Identity, authentication, and network

| Variable | Default | Required | Purpose and security effect | Example |
|---|---|---:|---|---|
| `CORPUSGATE_APP_NAME` | `CorpusGate` | No | OpenAPI/service display name; not a secret. | `CorpusGate` |
| `CORPUSGATE_ENVIRONMENT` | `production` | No | Environment label used for safe behavior selection. | `production` |
| `CORPUSGATE_HOST` | `0.0.0.0` | No | Container listen address; Compose still binds host loopback. | `0.0.0.0` |
| `CORPUSGATE_PORT` | `8000` | No | Internal HTTP port, range 1–65535. | `8000` |
| `CORPUSGATE_API_KEY` | none | **Yes** | REST credential, minimum 24 characters. Use a random value distinct from MCP tokens. | `openssl-random-64-hex-chars` |
| `CORPUSGATE_MCP_AUTH_TOKENS` | REST key fallback | Prod: No | Comma/newline-separated current and previous Bearer tokens for rotation. Prefer a secret file in production. | `current-token,previous-token` |
| `CORPUSGATE_MCP_AUTH_TOKEN_FILE` | none | Prod: **Yes** | Docker-secret file. When set, tokens are read at request time, enabling rotation after file replacement. | `/run/secrets/mcp_auth_token` |
| `CORPUSGATE_ALLOWED_HOSTS` | local hosts only | No | Exact Host allowlist and DNS-rebinding defense; add private/public MCP hostname. | `docs-node.ts.net,docs-node.ts.net:*` |
| `CORPUSGATE_CORS_ORIGINS` | empty | No | Comma-separated browser origins; empty disables cross-origin browser access. | `https://admin.example` |
| `CORPUSGATE_PUBLIC_BASE_URL` | empty | No | Public URL used by operational status checks; never include credentials. | `https://documents.example.com` |
| `CORPUSGATE_LOG_LEVEL` | `INFO` | No | `CRITICAL`, `ERROR`, `WARNING`, `INFO`, or `DEBUG`. Logs still omit text/query/secret data. | `INFO` |

## Persistent data and ingestion

| Variable | Default | Required | Purpose and security effect | Example |
|---|---|---:|---|---|
| `CORPUSGATE_DATA_DIR` | `data` | No | Base persistent directory. Compose sets `/data`. | `/data` |
| `CORPUSGATE_DOCUMENTS_DIR` | `<data>/uploads` | No | Private UUID source store; must be a real writable directory, not a symlink. | `/data/documents` |
| `CORPUSGATE_INBOX_DIR` | `/inbox` | No | Read-only operator inbox scanned by `./corpusgate scan`; symlinks/hidden files are skipped. | `/inbox` |
| `CORPUSGATE_CACHE_DIR` | `<data>/markdown` | No | Persistent generated Markdown cache. | `/data/cache` |
| `CORPUSGATE_BACKUP_DIR` | `<data>/backups` | No | Backup archive destination. | `/backups` |
| `CORPUSGATE_DATABASE_URL` | `sqlite:///<data>/gateway.db` | No | File-backed SQLite URL. Do not place it on an untrusted shared filesystem. | `sqlite:////data/database/gateway.db` |
| `CORPUSGATE_MAX_FILE_SIZE_MB` | `25` | No | Per-file limit, 1–1024 MiB. | `25` |
| `CORPUSGATE_MAX_REQUEST_BODY_MB` | file limit + 2 | No | HTTP body limit, 1–2048 MiB; cannot be smaller than the file limit. | `27` |
| `CORPUSGATE_MAX_ARCHIVE_UNCOMPRESSED_MB` | `250` | No | Expanded Office archive limit, 1–4096 MiB. | `250` |
| `CORPUSGATE_UPLOAD_BUFFER_BYTES` | `1048576` | No | Streaming upload buffer, 65536–8388608 bytes. | `1048576` |
| `CORPUSGATE_MIN_FREE_DISK_MB` | `100` | No | Reserved disk threshold; upload fails safely below it. | `100` |

### Upload CLI client variables

These variables are consumed by `./corpusgate upload`, not by the HTTP service. Command-line
options take precedence. Credential values must remain outside source control.

| Variable | Default | Purpose and security effect | Example |
|---|---|---|---|
| `CORPUSGATE_CLIENT_API_KEY` | server REST key from environment or `.env` | Optional client-only REST credential override; never printed or placed in curl arguments. | `random-client-secret` |
| `CORPUSGATE_BASE_URL` | `http://127.0.0.1:<CORPUSGATE_PORT>` | Client destination. Remote plain HTTP, URL credentials, paths, queries, and fragments are rejected. | `https://docs-node.ts.net` |
| `CORPUSGATE_UPLOAD_TIMEOUT_SECONDS` | `180` | Client upload/conversion timeout, 1–3600 seconds. | `240` |

## Chunking, retrieval, and resource limits

| Variable | Default | Range / effect | Example |
|---|---:|---|---:|
| `CORPUSGATE_CHUNK_SIZE_TOKENS` | `500` | 50–8000 estimated tokens. | `500` |
| `CORPUSGATE_CHUNK_OVERLAP_TOKENS` | `50` | 0–1000 and smaller than chunk size. | `50` |
| `CORPUSGATE_MIN_CHUNK_TOKENS` | `40` | 1–1000 and not larger than chunk size. | `40` |
| `CORPUSGATE_DEFAULT_PAGE_SIZE` | `20` | 1–100 and not above maximum. | `20` |
| `CORPUSGATE_MAX_PAGE_SIZE` | `100` | Server cap, 1–500. | `100` |
| `CORPUSGATE_DEFAULT_SEARCH_TOP_K` | `5` | 1–50 and not above maximum. | `5` |
| `CORPUSGATE_MAX_SEARCH_TOP_K` | `20` | Server cap, 1–100. | `20` |
| `CORPUSGATE_MAX_NEIGHBOR_WINDOW` | `1` | Adjacent chunks per side, 0–3. | `1` |
| `CORPUSGATE_DEFAULT_RESPONSE_MAX_CHARS` | `8000` | 200–100000 and not above maximum. | `8000` |
| `CORPUSGATE_MAX_RESPONSE_CHARS` | `24000` | Hard content cap, 500–250000. | `24000` |
| `CORPUSGATE_DEFAULT_RESPONSE_MAX_TOKENS` | `2000` | 50–32000 and not above maximum. | `2000` |
| `CORPUSGATE_MAX_RESPONSE_TOKENS` | `6000` | Hard estimated-token cap, 100–64000. | `6000` |
| `CORPUSGATE_RATE_LIMIT_REQUESTS` | `120` | Per-credential/client requests in a window, 1–100000. | `120` |
| `CORPUSGATE_RATE_LIMIT_WINDOW_SECONDS` | `60` | Window, 1–3600 seconds. | `60` |
| `CORPUSGATE_MAX_CONCURRENT_CONVERSIONS` | `1` | Heavy conversions, 1–16. | `1` |
| `CORPUSGATE_CONVERSION_TIMEOUT_SECONDS` | `120` | One conversion, 1–3600 seconds. | `120` |
| `CORPUSGATE_CONVERSION_QUEUE_TIMEOUT_SECONDS` | `5` | Capacity wait, 0–300 seconds. | `5` |
| `CORPUSGATE_SEARCH_TIMEOUT_SECONDS` | `10` | SQLite search progress timeout, 1–300 seconds. | `10` |

## Optional local semantic retrieval

These variables are optional when `CORPUSGATE_SEMANTIC_ENABLED=false`. Enabling semantic retrieval
requires the semantic image, a local model cache, and an HTTP(S) vector store URL.

| Variable | Default | Purpose | Example |
|---|---|---|---|
| `CORPUSGATE_SEMANTIC_ENABLED` | `false` | Enables local semantic/hybrid behavior. | `true` |
| `CORPUSGATE_SEMANTIC_FALLBACK_ENABLED` | `true` | Falls back to lexical when local semantic components fail. | `true` |
| `CORPUSGATE_DEFAULT_RETRIEVAL_MODE` | `lexical` | Must be `lexical`, `semantic`, or `hybrid`. | `hybrid` |
| `CORPUSGATE_EMBEDDING_MODEL` | multilingual MiniLM | FastEmbed model identifier. | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| `CORPUSGATE_EMBEDDING_MODEL_VERSION` | `fastembed-0.8.0-onnx-q` | Operator-managed compatibility marker. | `fastembed-0.8.0-onnx-q` |
| `CORPUSGATE_EMBEDDING_DIMENSION` | `384` | Must match the model, 32–8192. | `384` |
| `CORPUSGATE_EMBEDDING_QUERY_PREFIX` | empty | Model-specific query prefix, handled locally. | `query: ` |
| `CORPUSGATE_EMBEDDING_PASSAGE_PREFIX` | empty | Model-specific passage prefix. | `passage: ` |
| `CORPUSGATE_EMBEDDING_CACHE_DIR` | `/models` | Persistent local model cache. | `/models` |
| `CORPUSGATE_EMBEDDING_OFFLINE` | `true` | Disallows runtime model download after setup. | `true` |
| `CORPUSGATE_EMBEDDING_BATCH_SIZE` | `32` | Batch size, 1–512. | `32` |
| `CORPUSGATE_EMBEDDING_THREADS` | `2` | CPU threads, 1–64. | `2` |
| `CORPUSGATE_MAX_CONCURRENT_EMBEDDINGS` | `1` | Embedding jobs, 1–8. | `1` |
| `CORPUSGATE_EMBEDDING_TIMEOUT_SECONDS` | `180` | Embedding timeout, 1–3600 seconds. | `180` |
| `CORPUSGATE_EMBEDDING_QUEUE_TIMEOUT_SECONDS` | `5` | Capacity wait, 0–300 seconds. | `5` |
| `CORPUSGATE_VECTOR_STORE_URL` | `http://qdrant:6333` | Internal HTTP(S) endpoint; required when semantic is enabled. | `http://qdrant:6333` |
| `CORPUSGATE_VECTOR_COLLECTION` | `corpusgate_chunks_v1` | Non-empty collection name. | `corpusgate_chunks_v1` |
| `CORPUSGATE_VECTOR_STORE_TIMEOUT_SECONDS` | `10` | Vector request timeout, 1–300 seconds. | `10` |
| `CORPUSGATE_SEMANTIC_MIN_SCORE` | `0.25` | Minimum cosine score, -1.0–1.0. | `0.25` |
| `CORPUSGATE_HYBRID_RRF_K` | `60` | Reciprocal Rank Fusion constant, 1–1000. | `60` |
| `CORPUSGATE_MAX_RESULTS_PER_DOCUMENT` | `3` | Diversity cap; `0` disables it. | `3` |

## Compose-only variables

`CORPUSGATE_BIND_PORT`, `CORPUSGATE_*_HOST_PATH`, `CORPUSGATE_MCP_AUTH_TOKEN_HOST_FILE`, `CORPUSGATE_IMAGE_TAG`, CPU/RAM/log
limits, `CORPUSGATE_PUBLIC_DOMAIN`, `CADDY_EMAIL`, and `CORPUSGATE_PROXY_MAX_BODY_SIZE` configure Docker or
Caddy rather than application logic. Their documented examples are in `.env.example`. Host paths
must exist before production Compose starts; writable paths need UID/GID `10001:10001` on Linux.

Use `./corpusgate doctor` after each configuration change. It reports names and safe status metadata,
never credential values.
