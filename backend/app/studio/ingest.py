"""Upload handling + text extraction (plan §2).

Markdown/plain-text is decoded directly; PDF goes through `pypdf` (the one genuinely new
capability — the SOP corpus is markdown). `doc_id` is the filename stem, matching the ids
used across `docs/sops/README.md` and the seed graph's provenance.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

_TEXT_SUFFIXES = {".md", ".markdown", ".txt", ""}


class UnsupportedDocumentError(ValueError):
    """The uploaded file type cannot be turned into text."""


class IngestedDoc(BaseModel):
    doc_id: str  # filename stem, e.g. "06-picking-packing-dg-coldchain"
    text: str


def ingest(filename: str, raw: bytes) -> IngestedDoc:
    """Extract text from one uploaded document."""
    suffix = Path(filename).suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        text = raw.decode("utf-8", errors="replace")
    elif suffix == ".pdf":
        text = _extract_pdf(raw)
    else:
        raise UnsupportedDocumentError(f"unsupported document type: {suffix or '(none)'}")
    return IngestedDoc(doc_id=Path(filename).stem, text=text)


def ingest_corpus(sops_dir: str | Path) -> list[IngestedDoc]:
    """Ingest the committed SOP markdown corpus (used by the live extraction run)."""
    directory = Path(sops_dir)
    return [
        ingest(path.name, path.read_bytes())
        for path in sorted(directory.glob("*.md"))
        if path.name.lower() != "readme.md"
    ]


def _extract_pdf(raw: bytes) -> str:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)
