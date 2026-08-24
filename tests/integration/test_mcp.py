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
            assert result.structured_content["returned_chars"] <= 100

    asyncio.run(exercise())
