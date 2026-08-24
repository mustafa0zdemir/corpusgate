# Synthetic end-to-end demo

This demo uses only repository-generated, non-sensitive files.

## Lexical installation

```bash
./pdg init
./pdg up
cp examples/documents/* documents/
./pdg scan
./pdg list-documents
./pdg mcp-smoke
```

Copy a returned Markdown `document_id`, read the REST key from your private `.env`, and run a
bounded lexical search:

```bash
export PDG_CLIENT_API_KEY='value-from-your-private-env'
curl --fail --get http://127.0.0.1:8000/api/v1/documents/DOCUMENT_ID/search \
  -H "X-API-Key: ${PDG_CLIENT_API_KEY}" \
  --data-urlencode 'q=private network access' \
  --data 'top_k=2' \
  --data 'max_tokens=40'
```

The response shows `retrieval_mode=lexical`, source IDs/position, returned chunk count, estimated
tokens, elapsed search time, and cache use. The returned estimated token count cannot exceed 40.

## Semantic/hybrid installation

```bash
./pdg down
./pdg init --semantic
./pdg up --semantic
./pdg reindex --semantic
./pdg doctor
```

Connect MCP Inspector using [the connection guide](mcp-connection.md), call `search_document` with
the same document/query/budget and `retrieval_mode: "hybrid"`, then compare the actual mode/ranks
with the lexical response. The first semantic start needs model-download network access; later
starts use the persistent offline cache. If the semantic service is unavailable, the response
reports `lexical_fallback` instead of failing the lexical gateway.

Optional synthetic DOCX/XLSX files can be generated without external data:

```bash
python scripts/generate_demo_documents.py documents
./pdg scan
```

Generation is a contributor/test convenience and requires local Python; product installation does
not.
