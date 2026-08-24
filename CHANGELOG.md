# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-08-24

### Added

- REST upload, metadata, Markdown cache, chunks, lexical search, pagination, and deletion.
- MarkItDown conversion for PDF, DOCX, PPTX, XLSX, TXT, Markdown, and HTML.
- Token-aware Markdown chunking, SHA-256 deduplication, SQLite metadata, and FTS5/BM25 search.
- Bounded MCP retrieval tools with source metadata, character/token limits, and cursors.
- Optional local multilingual embeddings, Qdrant storage, semantic search, hybrid RRF, and lexical
  fallback.
- Bearer authentication, API-key authentication, rate limits, path/symlink protection, structured
  content-safe logging, hardened containers, Caddy/Tailscale deployment guidance, and backup.
- Unified setup/operations helper, startup configuration validation, schema version checks,
  synthetic demo documents, open-source governance files, and release-ready CI workflows.

### Security

- Containers run as UID/GID `10001`, drop Linux capabilities, use `no-new-privileges`, and keep
  the root filesystem read-only in Compose.
- MCP HTTP requests require constant-time compared Bearer tokens; secrets and document content are
  excluded from responses and structured logs.

[Unreleased]: https://github.com/mustafa0zdemir/private-document-gateway/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mustafa0zdemir/private-document-gateway/releases/tag/v0.1.0
