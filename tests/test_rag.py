"""RAG tests: chunking, retrieval relevance, honest empty results."""

from __future__ import annotations

from novastore.config import PROJECT_ROOT
from novastore.rag.chunker import chunk_markdown, load_and_chunk_dir
from novastore.rag.retriever import Retriever


def _retriever() -> Retriever:
    return Retriever(
        PROJECT_ROOT / "data" / "knowledge",
        top_k=4,
        min_score=0.05,
    )


def test_chunking_produces_sections():
    text = "# Doc\n\nintro\n\n## First rule\n\nrule one body\n\n## Second rule\n\nrule two body\n"
    chunks = chunk_markdown(text, doc="doc.md")
    # 1 intro chunk (doc title) + one chunk per "##" section
    assert len(chunks) == 3
    assert chunks[0].title == "Doc"  # the intro, kept retrievable
    assert chunks[1].title == "First rule"
    assert "rule one body" in chunks[1].text
    assert chunks[1].doc == "doc.md"
    assert chunks[1].tokens  # tokenized for the index


def test_all_docs_are_indexed():
    chunks = load_and_chunk_dir(PROJECT_ROOT / "data" / "knowledge")
    docs = {c.doc for c in chunks}
    assert {"shipping.md", "returns.md", "warranty.md", "faq.md", "b2b.md"} <= docs
    assert len(chunks) > 15  # a real corpus, not a stub


def test_retrieval_finds_shipping_answer():
    retriever = _retriever()
    results = retriever.retrieve("How long does shipping take to Cairo?")
    assert results, "expected at least one chunk"
    assert results[0].doc == "shipping.md"
    assert results[0].score > 0


def test_retrieval_finds_warranty():
    retriever = _retriever()
    results = retriever.retrieve("What does the ThinkPad warranty cover?")
    docs = [r.doc for r in results]
    assert "warranty.md" in docs


def test_retrieval_miss_is_honest():
    """Gibberish must return NOTHING - that is what triggers 'I don't know'."""
    retriever = _retriever()
    assert retriever.retrieve("zzz qqq xyzzy plugh") == []
