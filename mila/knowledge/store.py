from dataclasses import dataclass
from typing import Any


@dataclass
class RetrievedChunk:
    document: Any
    relevance: float


def retrieve(
    store: Any,
    query: str,
    *,
    top_k: int,
) -> list[RetrievedChunk]:
    matches = store.similarity_search_with_relevance_scores(query, k=top_k)
    return [
        RetrievedChunk(document=document, relevance=float(score))
        for document, score in matches
    ]

