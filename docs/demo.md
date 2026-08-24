# Synthetic end-to-end demo

This demo uses only repository-generated, non-sensitive files.

## Lexical installation

```bash
./corpusgate init
./corpusgate up
cp examples/documents/* documents/
./corpusgate scan
./corpusgate list-documents
./corpusgate mcp-smoke
```

To upload one selected local file directly, without copying it into the inbox first:

```bash
./corpusgate upload examples/documents/private-network-guide.md
```

The CLI streams bytes to CorpusGate's REST endpoint; an AI tool invoking this command does not need
to place document content in its prompt or MCP arguments.

Copy a returned Markdown `document_id`, read the REST key from your private `.env`, and run a
bounded lexical search:

```bash
export CORPUSGATE_CLIENT_API_KEY='value-from-your-private-env'
curl --fail --get http://127.0.0.1:8000/api/v1/documents/DOCUMENT_ID/search \
  -H "X-API-Key: ${CORPUSGATE_CLIENT_API_KEY}" \
  --data-urlencode 'q=private network access' \
  --data 'top_k=2' \
  --data 'max_tokens=40'
```

The response shows `retrieval_mode=lexical`, source IDs/position, returned chunk count, estimated
tokens, elapsed search time, and cache use. The returned estimated token count cannot exceed 40.

## Semantic/hybrid installation

```bash
./corpusgate down
./corpusgate init --semantic
./corpusgate up --semantic
./corpusgate reindex --semantic
./corpusgate doctor
```

Connect MCP Inspector using [the connection guide](mcp-connection.md), call `search_document` with
the same document/query/budget and `retrieval_mode: "hybrid"`, then compare the actual mode/ranks
with the lexical response. The first semantic start needs model-download network access; later
starts use the persistent offline cache. If the semantic service is unavailable, the response
reports `lexical_fallback` instead of failing the lexical gateway.

Optional synthetic DOCX/XLSX files can be generated without external data:

```bash
python scripts/generate_demo_documents.py documents
./corpusgate scan
```

Generation is a contributor/test convenience and requires local Python; product installation does
not.
