# Private Document Gateway

**An LLM-ready private document gateway powered by MarkItDown and MCP.**

Convert, index and retrieve private documents for AI tools without sending document content to
third-party services.

Private Document Gateway is a general-purpose, self-hosted Document MCP Server for individuals and
teams that need controlled AI-tool access to documents on their own infrastructure. MarkItDown
converts supported files into reusable Markdown. The gateway then chunks and indexes that Markdown,
and MCP returns only the relevant, source-attributed chunks under server-enforced budgets.

Self-hosting keeps source documents, generated Markdown, queries, metadata, and indexes under the
operator's control. Token reduction comes from bounded retrieval and chunk selection—not from
MarkItDown alone. This project is **not** a chatbot, an LLM answer generator, a contract-analysis
product, a SaaS platform, or a user-facing document panel.

## Features

- PDF, DOCX, PPTX, XLSX, TXT, Markdown, and HTML conversion through Microsoft MarkItDown.
- Persistent Markdown cache, token-aware heading-preserving chunks, and SHA-256 deduplication.
- SQLite FTS5/BM25 lexical search in the lightweight default installation.
- Optional CPU-only multilingual semantic search and RRF hybrid retrieval using local embeddings.
- Bounded MCP responses with source/position metadata, cursors, deduplication, and neighbor limits.
- REST API-key and MCP Bearer authentication, safe UUID storage, path/symlink protections, rate
  limits, and structured content-safe logs.
- Hardened Docker Compose deployment for AMD64/ARM64, Oracle Cloud, Tailscale, or Caddy HTTPS.
- Setup helper, operational doctor/scan/reindex/backup commands, versioned SQLite schema, and CI.

## How it works

```text
REST upload or read-only inbox scan
        │
        ├─ type, signature, size, path, and free-space validation
        ├─ UUID storage + SHA-256 ── unchanged? ── reuse cached/indexed record
        │
        └─ MarkItDown ──> persistent Markdown ──> token-aware chunks
                                                   │
                              ┌────────────────────┴────────────────────┐
                              │                                         │
                    SQLite FTS5 / BM25                      optional local embeddings
                              │                                  + private Qdrant
                              └────────────────────┬────────────────────┘
                                                   │
                               ranking → dedup → token/char budget → MCP
```

The code keeps parser, storage, repository, chunking, embedding, vector-store, and retrieval
contracts behind interfaces without turning the single-server product into a distributed system.
Documents remain the primary data source; Markdown and vector indexes can be rebuilt.

## Supported formats

| Format | Extensions | Notes |
|---|---|---|
| PDF | `.pdf` | Text-based PDFs; no external OCR in `0.1.0`. |
| Word | `.docx` | Office archive structure is checked. |
| PowerPoint | `.pptx` | Slide markers are preserved when MarkItDown emits them. |
| Excel | `.xlsx` | Sheet headings are carried into chunk metadata when available. |
| Text | `.txt` | UTF-8. |
| Markdown | `.md`, `.markdown` | UTF-8 and heading aware. |
| HTML | `.html`, `.htm` | UTF-8; fetching remote URLs is intentionally unsupported. |

Encrypted, corrupted, scanned-image-only, or converter-unsupported files fail safely without
stopping other documents.

## Quick start

Requirements: Docker Engine with Compose v2 and OpenSSL. Host Python is not required.

```bash
git clone https://github.com/mustafa0zdemir/private-document-gateway.git
cd private-document-gateway
./pdg init
./pdg up
curl --fail http://127.0.0.1:8000/health
./pdg doctor
```

`./pdg init` creates persistent/inbox folders, copies `.env.example` only when `.env` does not
exist, generates separate random REST/MCP credentials without printing them, checks Docker/Compose
and the selected port, and validates Compose. It never overwrites an existing `.env`.

The equivalent manual flow is to copy `.env.example` to `.env`, replace both credential
placeholders with different `openssl rand -hex 32` values, create `documents/`, and run
`docker compose up -d`. Never commit `.env`.

Optional local semantic/hybrid retrieval is also one operation after initialization:

```bash
./pdg init --semantic
./pdg up --semantic
```

The first semantic start downloads the model into a persistent cache and then starts the gateway
offline with Qdrant on the internal Docker network. Later starts reuse both model and vector
volumes. The lexical installation does not install or run either semantic component.

## Add documents

The simplest operator workflow uses the read-only host inbox:

```bash
cp examples/documents/* documents/
./pdg scan
./pdg list-documents
```

The scan skips hidden/system/temporary files, unsupported types, directories, and symlinks. Input
files remain in `documents/`; private UUID copies are stored in the persistent source volume.
For a complete lexical→semantic/hybrid→MCP walkthrough, use the
[synthetic demo](docs/demo.md).

REST upload is available for applications:

```bash
export PDG_CLIENT_API_KEY='value-from-your-env'
curl --fail -X POST http://127.0.0.1:8000/api/v1/documents \
  -H "X-API-Key: ${PDG_CLIENT_API_KEY}" \
  -F 'file=@examples/documents/private-network-guide.md'
```

REST also provides paginated metadata, Markdown, chunks, lexical search, and deletion under
`/api/v1/documents`. Interactive OpenAPI documentation is at `/docs`; protected operations still
require `X-API-Key`.

## Connect an MCP client

The remote endpoint is `https://YOUR_PRIVATE_OR_PUBLIC_HOST/mcp` and every MCP request needs:

```http
Authorization: Bearer YOUR_MCP_TOKEN
```

Use Tailscale Serve as the recommended private route. Caddy HTTPS is the public alternative; the
gateway port remains bound to host loopback in both cases. See the verified field mapping,
Inspector command, Tailscale/HTTPS examples, and troubleshooting in
[the MCP connection guide](docs/mcp-connection.md). Do not copy an unverified client-specific JSON
wrapper or save a token in source control.

## MCP tools

| Tool | Purpose | Limits and behavior |
|---|---|---|
| `list_documents` | Discover metadata without text. | `offset`, server-capped `limit`, `has_more`. |
| `get_document_metadata` | Inspect one source/status/cache record. | Returns no document content. |
| `search_documents` | Search when the source document is unknown. | Mode/filters/top-k/budgets/cursor. |
| `search_document` | Search one known document. | Optional limited neighbors. |
| `get_relevant_chunks` | Build a small context set from an allowlist. | Deduplicated and budgeted. |
| `get_document_section` | Read consecutive chunks after locating a position. | Chunk cursor and hard budgets; never raw file. |
| `refresh_document_index` | Idempotently repair one stored document's lexical/optional vector index. | Returns maintenance counts, no content; does not upload/delete/reconvert. |

Retrieval items consistently include `document_id`, `document_name`, `chunk_id`, `heading`,
`position`, relevance/rank fields, bounded `content`, `content_length`, and retrieval-mode
metadata. Empty searches return an empty `items` list, applied budgets, metrics, and no cursor.
Invalid modes, cursors, filters, document IDs, or over-limit values produce controlled tool errors.
Upload and delete remain REST-only.

Recommended flow:

```text
AI tool → search_document(query, top_k=3, max_tokens=600)
        → ranked chunks + source positions + actual retrieval mode
        → optional bounded get_document_section
```

## Lexical, semantic, and hybrid search

- `lexical` is the production default: SQLite FTS5 with heading-weighted BM25 preserves exact
  identifiers and phrases without another service.
- `semantic` embeds queries/chunks locally with the configurable multilingual CPU model and stores
  vectors in private Qdrant.
- `hybrid` merges independent lexical and semantic ranks with Reciprocal Rank Fusion; duplicate
  chunks are returned once and exact lexical matches are not discarded.
- `lexical_fallback` is reported when semantic/hybrid was requested but the optional local model,
  vector store, or index is unavailable and fallback is enabled.

The default model is Apache-2.0-licensed
[`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2),
a 384-dimensional multilingual model used through FastEmbed/ONNX on CPU. See model replacement,
offline transfer, reindex rules, measurements, and Oracle memory guidance in
[semantic search](docs/semantic-search.md).

## Token optimization

MarkItDown makes diverse files consistently parseable; it does not by itself guarantee fewer
tokens. The gateway reduces returned context by caching conversion once, ranking chunks, omitting
duplicates, enforcing `top_k`, `max_chars`, and estimated `max_tokens`, limiting neighbors, and
paginating long result sets. It never exposes a default MCP tool that returns a complete document
or raw file.

Token counts are a local deterministic estimate, not a provider-specific billing tokenizer. The
repeatable synthetic measurement and its exact scope are in
[the retrieval report](docs/retrieval-evaluation-2026-08-24.md); no universal saving percentage is
claimed.

## Security and privacy

- No telemetry, document text, query text, cloud embedding API, or required LLM provider.
- Source files use UUID paths; filename traversal, absolute paths, symlink escapes, hidden/temp
  files, MIME/signature mismatches, archive expansion, upload size, and low disk are checked.
- REST uses API keys; remote MCP uses constant-time compared Bearer tokens from environment or a
  Docker secret. Multiple current/previous tokens allow rotation.
- Structured logs contain allowlisted operation metadata, never document content, credentials,
  complete queries, or client-visible stack traces.
- The gateway container is non-root, capability-free, `no-new-privileges`, read-only-root, and has
  explicit writable volumes/tmpfs plus resource/log limits.
- Base Compose publishes only `127.0.0.1:8000`; Qdrant is internal-only. Public deployment requires
  Caddy TLS and keeps Bearer authentication/rate/response limits.

Stored data comprises private UUID source copies, generated Markdown, SQLite metadata/chunks/FTS,
optional local vectors/model cache, backups, and operator configuration. To erase data, delete
documents through REST first; remove persistent volumes only after an explicit backup and shutdown.
See [SECURITY.md](SECURITY.md) for private vulnerability reporting.

## Oracle Cloud deployment

The recommended Oracle Ubuntu deployment binds the app to loopback and uses Tailscale Serve for
tailnet-only HTTPS. A Caddy `public` profile is documented for cases that require a domain. Oracle
Security Lists/NSGs must never expose TCP 8000 or Qdrant 6333.

VM preparation, AMD64/Ampere ARM64 notes, Docker installation, filesystem ownership, secrets,
firewalls, Tailscale/Caddy, logging, update, backup, restore, and troubleshooting are in the
[Oracle deployment guide](docs/oracle-deployment.md).

## Configuration

All application environment variables, defaults, requirements, ranges, examples, and security
effects are listed in [the configuration contract](docs/configuration.md) and `.env.example`.
Startup rejects missing/short credentials, invalid ports/paths, impossible chunk/budget
relationships, unsupported retrieval modes, and invalid semantic vector-store configuration
without echoing secret values.

Operational commands:

```bash
./pdg version
./pdg status
./pdg doctor
./pdg mcp-smoke
./pdg scan
./pdg reindex
./pdg reindex --semantic
./pdg list-documents --limit 20 --offset 0
```

## Backup and restore

```bash
./pdg backup
./pdg restore /backups/pdg-backup-TIMESTAMP.tar.gz --confirm-restore
```

Restore replaces current persistent data and therefore requires an explicit confirmation flag and
a stopped writer in production. Backups include private source storage, Markdown cache, a
transactionally copied SQLite database, manifest, and secret-free config example. Keep `.env` and
token files in a separate encrypted secret backup. Vector data is rebuildable from chunks.

## Update and rollback

Learn the current version, backup, select the reviewed tag/image, run the versioned idempotent
migration, restart, check ready/MCP, and retain the backup until validation completes. A database
created by a newer incompatible application is rejected instead of silently modified.

Exact commands and the safe rollback/restore path are in
[update and rollback](docs/update-and-rollback.md). Never run `docker compose down -v` during a
normal update.

The repository also contains a manual, approval-gated GHCR workflow. Stable tag, moving minor, and
`latest` behavior are defined in [the container publishing policy](docs/container-publishing.md);
no image has been published by this sprint.

## Troubleshooting

- `./pdg doctor`: validates config, storage permissions, SQLite/schema, disk, optional model/vector
  state, service readiness, and version without dumping secrets.
- `401`: use REST `X-API-Key` or MCP `Authorization: Bearer`, not the other credential type.
- Host rejection: add the exact Tailscale/domain host to `PDG_ALLOWED_HOSTS` and recreate gateway.
- `507`: free disk or review the reserved disk threshold before retrying ingestion.
- `lexical_fallback`: inspect model cache and Qdrant health; lexical retrieval remains available.
- Conversion failure: confirm supported extension, MIME/signature, UTF-8/Office archive integrity,
  size, encryption, and whether the PDF contains text.
- Logs: `./pdg logs --tail=100`; sanitize output before sharing.

See [SUPPORT.md](SUPPORT.md) and the deployment-specific troubleshooting guide before opening an
issue.

## Compatibility

| Environment | v0.1.0 status |
|---|---|
| Python | Runtime image uses Python 3.12; automated tests target 3.12. |
| `linux/arm64` | Runtime and semantic image build/run validated on an ARM64 Docker host. |
| `linux/amd64` | Multi-architecture Buildx CI target; release requires checklist validation. |
| Oracle Cloud Ubuntu | Deployment contract targets Ubuntu 24.04/Ampere; fresh VM validation remains a release checklist item. |
| Docker / Compose | ARM64 flow tested with Engine 29.6.2 and Compose 5.3.1; Compose v2 is required. |
| Lexical search | Default image; no semantic service required. |
| Semantic search | Optional image/Qdrant/model volumes; CPU-only tested on ARM64. |
| Offline mode | Lexical is offline; semantic is offline after the one-time model cache fill. |

Untested platforms are not presented as supported. Review [the release checklist](docs/release-checklist.md)
before publishing artifacts.

## Limitations

- Single-node SQLite is not a high-availability or multi-writer database.
- Upload conversion is synchronous in `0.1.0`; large documents may need longer client/proxy
  timeouts.
- No OCR, cloud storage adapter, user accounts, UI, answer generation, reranker, fine-tuning, or
  SaaS control plane.
- Approximate token budgets may differ from a specific LLM tokenizer.
- Semantic model download needs temporary outbound access unless the cache is transferred offline.

## Roadmap

- Background conversion jobs without making Redis mandatory for single-node users.
- Optional PostgreSQL/pgvector and object-storage adapters behind existing interfaces.
- More converter metadata extraction and operator-controlled OCR adapter.
- Signed releases, SBOM/provenance, expanded cross-architecture and upgrade fixtures.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md), follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), add tests,
and use only synthetic non-sensitive fixtures. Security reports must use the private route in
[SECURITY.md](SECURITY.md), never a public issue.

## License

Private Document Gateway is available under the existing [MIT License](LICENSE). Third-party
libraries and the optional embedding model retain their own licenses.
