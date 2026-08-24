from __future__ import annotations

import pytest

from app.mcp.server import _merge_filters


def test_structured_filters_merge_without_overriding_explicit_values() -> None:
    document_ids, file_types, heading = _merge_filters(
        {
            "document_ids": ["from-object"],
            "file_types": ["pdf"],
            "heading": "Object heading",
        },
        document_ids=["explicit"],
        file_types=None,
        heading=None,
    )
    assert document_ids == ["explicit"]
    assert file_types == ["pdf"]
    assert heading == "Object heading"


@pytest.mark.parametrize(
    "filters",
    [
        {"unknown": "value"},
        {"document_ids": "not-a-list"},
        {"file_types": [42]},
        {"heading": ["not-a-string"]},
    ],
)
def test_structured_filters_reject_unknown_or_invalid_values(filters) -> None:
    with pytest.raises(ValueError):
        _merge_filters(filters, document_ids=None, file_types=None, heading=None)
