"""Retrieval-grounded remediation source: chunk, index, and score the SOP corpus
(PRD §6.1, §7; plan §4 Phase 3).

Pure-Python BM25 over `(doc_id, heading, text)` chunks — no embedding provider, no
vector DB, appropriate for 8 short documents (plan §1: "the threshold-based abstain
is what's being tested, not recall@k"). Below `threshold`, `retrieve()` returns
`Abstain` rather than guessing; `app/agent/nodes/remediate.py` is the only caller
allowed to turn a `Grounded` result into a reply, and it always carries the
`Citation` this module attaches.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from app.studio.ingest import IngestedDoc, ingest_corpus

DEFAULT_THRESHOLD = 6.0

_TOKEN_RE = re.compile(r"[a-záéíóúñü0-9]+")
_HEADING_RE = re.compile(r"^##\s+(.*)$", re.MULTILINE)
_BM25_K1 = 1.5
_BM25_B = 0.75

# Function words dropped before scoring: with only 8 short documents, common words
# like "what"/"is"/"the" appear in nearly every chunk and would otherwise dilute the
# score gap between on- and off-corpus queries that the abstain threshold depends on.
_STOPWORDS = frozenset(
    """
    a an the this that these those is are was were be been being do does did
    what which who whom whose when where why how i you he she it we they
    my your his her its our their me him them us to of in on at for with
    without and or but if then than as by from about into over under again
    further so not no nor can could should would may might must shall will
    just there here have has had having
    """.split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


class Chunk(BaseModel):
    doc_id: str
    heading: str
    text: str


class Citation(BaseModel):
    doc_id: str
    heading: str


class Grounded(BaseModel):
    citation: Citation
    excerpt: str
    score: float


class Abstain(BaseModel):
    reason: str
    top_score: float | None = None


def chunk_document(doc: IngestedDoc) -> list[Chunk]:
    """Split on level-2 (`## `) headings. Any preamble before the first heading
    (title, metadata block) becomes its own chunk under the document title."""
    matches = list(_HEADING_RE.finditer(doc.text))
    chunks: list[Chunk] = []

    preamble_end = matches[0].start() if matches else len(doc.text)
    preamble = doc.text[:preamble_end].strip()
    if preamble:
        title_match = re.search(r"^#\s+(.*)$", preamble, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else doc.doc_id
        chunks.append(Chunk(doc_id=doc.doc_id, heading=title, text=preamble))

    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(doc.text)
        body = doc.text[start:end].strip()
        chunks.append(Chunk(doc_id=doc.doc_id, heading=heading, text=body))

    return chunks


@dataclass
class Index:
    """BM25 index over a fixed set of chunks. Build once at startup (`build_index`)."""

    chunks: list[Chunk]
    _doc_tokens: list[list[str]] = field(default_factory=list)
    _doc_freq: Counter = field(default_factory=Counter)
    _avg_len: float = 0.0

    def __post_init__(self) -> None:
        self._doc_tokens = [tokenize(f"{c.heading} {c.text}") for c in self.chunks]
        self._doc_freq = Counter()
        for tokens in self._doc_tokens:
            for term in set(tokens):
                self._doc_freq[term] += 1
        lengths = [len(t) for t in self._doc_tokens] or [0]
        self._avg_len = sum(lengths) / len(lengths)

    def search(self, query: str, top_k: int = 5) -> list[tuple[Chunk, float]]:
        query_terms = tokenize(query)
        n_docs = len(self.chunks)
        scores = [0.0] * n_docs

        for term in query_terms:
            df = self._doc_freq.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            for i, tokens in enumerate(self._doc_tokens):
                tf = tokens.count(term)
                if tf == 0:
                    continue
                doc_len = len(tokens)
                denom = tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * doc_len / (self._avg_len or 1))
                scores[i] += idf * (tf * (_BM25_K1 + 1)) / denom

        ranked = sorted(
            zip(self.chunks, scores, strict=True), key=lambda pair: pair[1], reverse=True
        )
        return ranked[:top_k]


def build_index(docs: list[IngestedDoc]) -> Index:
    chunks = [chunk for doc in docs for chunk in chunk_document(doc)]
    return Index(chunks=chunks)


def build_index_from_sops(sops_dir: str | Path) -> Index:
    """Build the runtime index from the committed `docs/sops/` corpus at startup."""
    return build_index(ingest_corpus(sops_dir))


def retrieve(index: Index, query: str, threshold: float = DEFAULT_THRESHOLD) -> Grounded | Abstain:
    ranked = index.search(query, top_k=1)
    if not ranked or ranked[0][1] < threshold:
        top_score = ranked[0][1] if ranked else None
        return Abstain(reason=f"no chunk scored above threshold {threshold}", top_score=top_score)

    chunk, score = ranked[0]
    return Grounded(
        citation=Citation(doc_id=chunk.doc_id, heading=chunk.heading),
        excerpt=chunk.text,
        score=score,
    )
