"""Retriever: the RAG entrypoint the rest of the app uses.

``Retriever.retrieve(question)`` returns the top chunks whose score passes
``RETRIEVAL_MIN_SCORE``. If nothing passes, the handler MUST answer "I don't
know" - that is the "retrieve before answering store-owned facts" rule from
the brief, enforced at this single choke point.
"""

from __future__ import annotations

from pathlib import Path

from novastore.logging_setup import get_logger
from novastore.rag.chunker import load_and_chunk_dir
from novastore.rag.store import RetrievedChunk, VectorStore

logger = get_logger(__name__)


class Retriever:
    """Owns the index; rebuilds it from the knowledge directory."""

    def __init__(self, knowledge_dir: Path, top_k: int = 4, min_score: float = 0.05):
        self.knowledge_dir = knowledge_dir
        self.top_k = top_k
        self.min_score = min_score
        self._store = self._build()

    def _build(self) -> VectorStore:
        chunks = load_and_chunk_dir(self.knowledge_dir)
        logger.info("RAG index built: %d chunks from %s", len(chunks), self.knowledge_dir)
        return VectorStore(chunks)

    def reload(self) -> int:
        """Re-read the docs (after you edit a .md file) without restarting."""
        self._store = self._build()
        return len(self._store.chunks)

    def retrieve(self, question: str) -> list[RetrievedChunk]:
        """Top chunks above the minimum score, best first. May be empty."""
        results = self._store.search(question, top_k=self.top_k)
        return [c for c in results if c.score >= self.min_score]

    @property
    def chunk_count(self) -> int:
        return len(self._store.chunks)
