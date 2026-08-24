from __future__ import annotations

import asyncio

from mcp import Client

from app.mcp.server import create_mcp_server


def test_mcp_lists_read_only_tools_and_searches(
    client, auth_headers: dict[str, str], settings
) -> None:
    uploaded = client.post(
        "/api/v1/documents",
        headers=auth_headers,
        files={
            "file": (
                "mcp.md",
                b"# MCP\n\nThe gateway returns a bounded relevant chunk.",
                "text/markdown",
            )
        },
    ).json()
    server = create_mcp_server(settings, client.app.state.database.session_factory)

    async def exercise() -> None:
        async with Client(server) as mcp_client:
            tools = await mcp_client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert names == {
                "list_documents",
                "get_document_metadata",
                "search_documents",
                "search_document",
                "get_relevant_chunks",
                "get_document_section",
            }
            assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools.tools)
            metadata = await mcp_client.call_tool(
                "get_document_metadata", {"document_id": uploaded["document_id"]}
            )
            assert metadata.structured_content["document_name"] == "mcp.md"
            assert "content" not in metadata.structured_content
            result = await mcp_client.call_tool(
                "search_document",
                {
                    "document_id": uploaded["document_id"],
                    "query": "bounded relevant",
                    "top_k": 1,
                    "max_chars": 100,
                },
            )
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content["items"][0]["document_id"] == uploaded["document_id"]
            payload = result.structured_content
            assert payload["metrics"]["returned_chars"] <= 100
            assert payload["metrics"]["returned_estimated_tokens"] <= payload["max_tokens"]
            item = payload["items"][0]
            assert {
                "document_id",
                "document_name",
                "chunk_id",
                "heading",
                "position",
                "score",
                "content",
                "content_length",
            }.issubset(item)

            cross_document = await mcp_client.call_tool(
                "search_documents",
                {"query": "gateway", "top_k": 1, "max_tokens": 10},
            )
            assert (
                cross_document.structured_content["items"][0]["document_id"]
                == uploaded["document_id"]
            )
            relevant = await mcp_client.call_tool(
                "get_relevant_chunks",
                {
                    "query": "bounded",
                    "document_ids": [uploaded["document_id"]],
                    "max_tokens": 10,
                },
            )
            assert relevant.structured_content["metrics"]["returned_estimated_tokens"] <= 10
            section = await mcp_client.call_tool(
                "get_document_section",
                {
                    "document_id": uploaded["document_id"],
                    "chunk_count": 100,
                    "max_tokens": 8,
                },
            )
            assert section.structured_content["metrics"]["returned_estimated_tokens"] <= 8
            assert section.structured_content["items"][0]["score"] == 0

    asyncio.run(exercise())
