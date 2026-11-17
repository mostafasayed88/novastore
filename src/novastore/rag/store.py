"""Vector store: in-memory similarity search over knowledge chunks.

Tiny by design - the whole store corpus fits in RAM (~30 chunks). The
interface (``search`` returning scored chunks) is what a real vector DB
would expose, so scaling up later means replacing this file, not the app.
"""

from __future__ import annotations

from dataclasses import dataclass

from novastore.rag.chunker import Chunk
from novastore.rag.embeddings import TfidfIndex, cosine, embed_corpus, embed_query


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk plus its similarity score, ready to cite."""

    doc: str
    title: str
    text: str
    score: float
    chunk_id: str


class VectorStore:
    """Chunks + their vectors, searched by cosine similarity."""

    def __init__(self, chunks: list[Chunk]):
        if not chunks:
            raise ValueError("VectorStore needs at least one chunk - check your knowledge directory.")
        self.chunks = chunks
        self.index: TfidfIndex = embed_corpus(chunks)

    def search(self, query: str, top_k: int = 4) -> list[RetrievedChunk]:
        """Return the ``top_k`` most similar chunks, best first.

        Score range is [0, 1] for TF-IDF cosine (both vectors are
        non-negative and normalized).
        """
        query_vec = embed_query(query, self.index)
        scored = [
            RetrievedChunk(
                doc=chunk.doc,
                title=chunk.title,
                text=chunk.text,
                score=round(cosine(query_vec, vec), 4),
                chunk_id=chunk.chunk_id,
            )
            for chunk, vec in zip(self.chunks, self.index.vectors)
        ]
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:top_k]
