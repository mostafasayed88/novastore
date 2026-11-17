"""Chunker: turns markdown knowledge docs into retrievable chunks.

We split on "## " headings because each section of our store documents is
a self-contained rule (one shipping zone, one warranty clause, ...). Each
chunk keeps its source doc and heading so answers can cite where a claim
came from - "answers cite store knowledge, not the model's memory".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Chunk:
    """One retrievable piece of a knowledge document."""

    doc: str          # file name, e.g. "shipping.md"
    title: str        # "##" heading text, or the "# " doc title
    text: str
    chunk_id: str = ""  # "shipping.md#2" style identifier
    tokens: list[str] = field(default_factory=list)


def tokenize(text: str) -> list[str]:
    """Very small, transparent tokenizer: lowercase words and numbers.

    English stopwords removed; numbers kept (order amounts, "14 days",
    "50 EGP" are meaningful in a store knowledge base). Arabic words are
    kept as-is so Arabic questions still find chunks.
    """
    import re

    stopwords = {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
        "is", "are", "be", "we", "our", "you", "your", "it", "at", "by", "as",
        "can", "will", "not", "if", "from", "that", "this", "do", "does",
    }
    raw = re.findall(r"[a-z0-9\u0600-\u06FF]+", text.lower())
    return [t for t in raw if t not in stopwords]


def chunk_markdown(text: str, doc: str) -> list[Chunk]:
    """Split one markdown document into sections.

    Strategy: the "# " title is the doc title; every "## " heading starts a
    new chunk whose text runs until the next heading. Section bodies are
    kept whole - they are 200-800 characters, ideal for retrieval.
    """
    lines = text.splitlines()
    doc_title = ""
    chunks: list[Chunk] = []
    current_title = ""
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        body = "\n".join(buffer).strip()
        if body:
            heading = current_title or doc_title or doc
            full_text = f"{heading}\n{body}" if heading else body
            chunks.append(
                Chunk(
                    doc=doc,
                    title=heading,
                    text=full_text,
                    chunk_id=f"{doc}#{len(chunks)}",
                    tokens=tokenize(full_text),
                )
            )
        buffer = []

    for line in lines:
        if line.startswith("# ") and not doc_title:
            doc_title = line[2:].strip()
            continue
        if line.startswith("## "):
            flush()
            current_title = line[3:].strip()
            continue
        buffer.append(line)

    flush()
    return chunks


def load_and_chunk_dir(knowledge_dir: Path) -> list[Chunk]:
    """Load every ``.md`` file in the knowledge directory and chunk it."""
    chunks: list[Chunk] = []
    for path in sorted(knowledge_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        chunks.extend(chunk_markdown(text, doc=path.name))
    return chunks
