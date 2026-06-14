"""PDF → text chunks for Moss ingestion.

Strategy: extract per-page, then sliding-window chunk on character count
with overlap. Cheap and predictable for hackathon demo.
"""
from __future__ import annotations
from pathlib import Path
from pypdf import PdfReader


CHUNK_CHARS = 1200
OVERLAP_CHARS = 200


def _window(text: str, size: int, overlap: int) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return []
    out: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        out.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return out


def parse_pdf(path: Path, document_id: str, source_name: str) -> list[dict]:
    """Return Moss-ready chunks: {id, text, metadata}."""
    reader = PdfReader(str(path))
    chunks: list[dict] = []
    for page_num, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if not page_text.strip():
            continue
        for i, piece in enumerate(_window(page_text, CHUNK_CHARS, OVERLAP_CHARS)):
            chunks.append({
                "id": f"{document_id}:p{page_num}:c{i}",
                "text": piece,
                "metadata": {
                    "document_id": document_id,
                    "source": source_name,
                    "page": page_num,
                    "chunk": i,
                },
            })
    return chunks


def parse_text(text: str, document_id: str, source_name: str) -> list[dict]:
    chunks = []
    for i, piece in enumerate(_window(text, CHUNK_CHARS, OVERLAP_CHARS)):
        chunks.append({
            "id": f"{document_id}:t:c{i}",
            "text": piece,
            "metadata": {
                "document_id": document_id,
                "source": source_name,
                "page": None,
                "chunk": i,
            },
        })
    return chunks
