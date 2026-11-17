"""TF-IDF embeddings and cosine similarity - in ~100 readable lines.

Why not sentence-transformers? Two reasons:

1. Transparency: this project's rule is "nothing is a black box". Every
   learner can read exactly how a question becomes a vector here.
2. Footprint: our corpus is ~30 chunks; TF-IDF is excellent at this scale,
   installs nothing extra, and runs anywhere (no torch download).

The public API (``embed_corpus`` / ``embed_query``) matches what a neural
embedder would expose, so swapping one in later touches only this file.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from novastore.rag.chunker import Chunk, tokenize


@dataclass
class TfidfIndex:
    """A trained TF-IDF model bound to one corpus."""

    vocab: dict[str, int]                 # token -> column index
    idf: list[float]                      # inverse document frequency per column
    vectors: list[dict[str, float]]       # one sparse L2-normalized vector per chunk


def embed_corpus(chunks: list[Chunk]) -> TfidfIndex:
    """Learn vocabulary + IDF weights from the corpus and vectorize it.

    IDF formula (smooth): idf(t) = ln((1 + N) / (1 + df(t))) + 1, so a token
    appearing in EVERY chunk gets low weight and rare tokens ("warranty")
    get high weight.
    """
    n_docs = len(chunks)
    if n_docs == 0:
        return TfidfIndex(vocab={}, idf=[], vectors=[])

    doc_freq: Counter[str] = Counter()
    for chunk in chunks:
        doc_freq.update(set(chunk.tokens))

    vocab = {token: i for i, token in enumerate(sorted(doc_freq))}
    idf = [
        math.log((1 + n_docs) / (1 + doc_freq[token])) + 1.0
        for token in sorted(doc_freq)
    ]

    vectors: list[dict[str, float]] = []
    for chunk in chunks:
        vectors.append(_vectorize(chunk.tokens, vocab, idf))
    return TfidfIndex(vocab=vocab, idf=idf, vectors=vectors)


def embed_query(query: str, index: TfidfIndex) -> dict[str, float]:
    """Vectorize a query with the corpus-fitted model.

    Tokens the corpus has never seen are dropped - they contribute nothing
    to cosine similarity anyway.
    """
    return _vectorize(tokenize(query), index.vocab, index.idf)


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity of two sparse, already L2-normalized vectors is
    just the dot product."""
    if len(a) > len(b):
        a, b = b, a
    return sum(weight * b.get(token, 0.0) for token, weight in a.items())


def _vectorize(tokens: list[str], vocab: dict[str, int], idf: list[float]) -> dict[str, float]:
    """TF-IDF vector, L2-normalized. Term frequency is raw count."""
    if not tokens:
        return {}
    counts = Counter(tokens)
    vec: dict[str, float] = {}
    for token, count in counts.items():
        col = vocab.get(token)
        if col is None:
            continue  # out-of-vocabulary token
        vec[token] = count * idf[col]
    norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
    return {token: w / norm for token, w in vec.items()}
