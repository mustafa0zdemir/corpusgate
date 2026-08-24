from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


@dataclass(frozen=True, slots=True)
class TokenSpan:
    start: int
    end: int


class TokenEstimator(ABC):
    """Model-neutral token estimate used to enforce local retrieval budgets."""

    @abstractmethod
    def spans(self, text: str) -> list[TokenSpan]:
        raise NotImplementedError

    def estimate(self, text: str) -> int:
        return len(self.spans(text))

    def truncate(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            return ""
        spans = self.spans(text)
        if len(spans) <= max_tokens:
            return text
        return text[: spans[max_tokens - 1].end].rstrip()


class ApproximateTokenEstimator(TokenEstimator):
    """Deterministic approximation without binding the product to one LLM tokenizer."""

    def spans(self, text: str) -> list[TokenSpan]:
        spans: list[TokenSpan] = []
        for match in TOKEN_RE.finditer(text):
            value = match.group(0)
            if len(value) == 1 and not value.isalnum() and value != "_":
                spans.append(TokenSpan(match.start(), match.end()))
                continue

            width = 3 if any(ord(character) > 127 for character in value) else 4
            for offset in range(0, len(value), width):
                spans.append(
                    TokenSpan(
                        start=match.start() + offset,
                        end=min(match.start() + offset + width, match.end()),
                    )
                )
        return spans
