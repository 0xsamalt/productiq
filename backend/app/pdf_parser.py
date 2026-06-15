"""PDF / text → Moss-ready chunks.

Strategy (in order of preference):
  1. Detect section headings (e.g. `Section 4.2`, `7.1 ...`, all-caps headers,
     Markdown `#` heads) and group text under each one.
  2. Within a section, recursively split on paragraph (\\n\\n) → line (\\n)
     → sentence (. ) → word → char, so chunks end at semantic boundaries
     rather than mid-word.
  3. Each emitted chunk is prefixed with its section heading, so the
     embedding (and the LLM later) sees the context, not just the body.
  4. Page numbers + section text live in metadata so citations remain precise.

Tunables: `CHUNK_CHARS`, `OVERLAP_CHARS`. Both in characters (NOT tokens) —
moss-minilm is byte-pair tokenized so chars are a stable, conservative proxy.
"""
from __future__ import annotations
import re
from pathlib import Path
from pypdf import PdfReader

CHUNK_CHARS = 1200       # ~300 tokens for moss-minilm
OVERLAP_CHARS = 120      # ~10% — enough to bridge a sentence split, not redundant
MIN_CHUNK_CHARS = 80     # discard tiny scraps (e.g. orphaned page headers)

# Heading detectors — checked in order. Each must reject very long lines so
# stray sentences aren't promoted to headings.
_HEADING_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\s*(?:Section|Chapter|Appendix|Part|Step|Note|Warning|Caution)\s+[\dA-Z][\w.\-]*\b.*$", re.I),
    re.compile(r"^\s*\d+(?:\.\d+){0,3}\s+\S.{0,80}$"),       # "4.2 Electrical fuses"
    re.compile(r"^\s*#{1,6}\s+\S.{0,80}$"),                   # markdown headings
    re.compile(r"^\s*[A-Z][A-Z0-9 \-/&]{4,80}\s*$"),          # ALL-CAPS LINES (short)
]


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 100:
        return False
    return any(p.match(s) for p in _HEADING_PATTERNS)


def _norm_ws(text: str) -> str:
    """Collapse runs of whitespace but keep paragraph breaks."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_recursive(text: str, max_chars: int, separators: list[str]) -> list[str]:
    """Greedy split by the first separator that appears; recurse on too-long pieces."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # Pick the highest-level separator that exists in the text.
    sep_used = ""
    for s in separators:
        if s and s in text:
            sep_used = s
            break

    if not sep_used:
        # Last resort — hard char window with no overlap (overlap is added at merge step).
        return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]

    parts = text.split(sep_used)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) > max_chars:
            out.extend(_split_recursive(p, max_chars, separators[separators.index(sep_used) + 1:]))
        else:
            out.append(p)
    return out


def _merge_with_overlap(pieces: list[str], max_chars: int, overlap: int) -> list[str]:
    """Greedily pack pieces into <= max_chars chunks; add char-level tail overlap between adjacent chunks."""
    chunks: list[str] = []
    buf = ""
    for piece in pieces:
        candidate = (buf + ("\n\n" if buf else "") + piece).strip()
        if len(candidate) <= max_chars:
            buf = candidate
            continue
        # Flush buf, start new one with overlap from old buf's tail
        if buf:
            chunks.append(buf)
            tail = buf[-overlap:] if overlap and len(buf) > overlap else ""
            buf = (tail + "\n" + piece).strip() if tail else piece
        else:
            buf = piece
    if buf:
        chunks.append(buf)
    # Discard scraps that are too small to carry useful signal
    return [c for c in chunks if len(c) >= MIN_CHUNK_CHARS or len(chunks) == 1]


def _group_by_heading(text: str) -> list[tuple[str | None, str]]:
    """Return [(heading, body), ...] for one page or one text doc."""
    sections: list[tuple[str | None, list[str]]] = []
    current_heading: str | None = None
    current_body: list[str] = []
    for line in text.splitlines():
        if _is_heading(line):
            if current_body:
                sections.append((current_heading, current_body))
            current_heading = line.strip()
            current_body = []
        else:
            current_body.append(line)
    if current_body:
        sections.append((current_heading, current_body))
    return [(h, "\n".join(b).strip()) for h, b in sections if "".join(b).strip()]


def _chunk_section(heading: str | None, body: str) -> list[str]:
    """Split one section into chunks and prepend the heading to each."""
    pieces = _split_recursive(body, CHUNK_CHARS, ["\n\n", "\n", ". ", " ", ""])
    chunks = _merge_with_overlap(pieces, CHUNK_CHARS, OVERLAP_CHARS)
    if heading:
        return [f"[{heading}]\n{c}".strip() for c in chunks]
    return chunks


def _render_page_to_png(path: Path, page_num_0indexed: int, dpi: int = 180) -> bytes:
    """Render one PDF page to PNG bytes via PyMuPDF (no system deps).
    Used only on scanned/image-only PDFs as an OCR fallback path."""
    import pymupdf  # local import — heavy dep, only loaded when we actually need OCR
    doc = pymupdf.open(str(path))
    try:
        page = doc.load_page(page_num_0indexed)
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def _ocr_pdf_pages(path: Path, page_count: int) -> dict[int, str]:
    """Run Gemma 3 vision OCR on every page that pypdf couldn't read.
    Returns {page_num_1indexed: extracted_text}."""
    # Avoid circular import: llm_service uses huggingface_hub which is fine to import lazily.
    from .llm_service import extract_text_from_image
    out: dict[int, str] = {}
    for p in range(page_count):
        try:
            png = _render_page_to_png(path, p)
        except Exception:
            continue
        try:
            text = extract_text_from_image(png, image_mime="image/png")
        except Exception:
            continue
        if text and text.upper() != "NO_TEXT_VISIBLE":
            out[p + 1] = text
    return out


def parse_pdf(path: Path, document_id: str, source_name: str) -> list[dict]:
    """Return Moss-ready chunks: {id, text, metadata{source,page,section,chunk}}.

    Tries pypdf text extraction first. If the PDF has NO text layer (scanned /
    image-only) AND has pages, falls back to per-page Gemma 3 vision OCR.
    """
    reader = PdfReader(str(path))
    page_texts: dict[int, str] = {}
    for page_num, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        text = _norm_ws(raw)
        if text:
            page_texts[page_num] = text

    # OCR fallback: text-less PDF, but it has pages → likely a scanned doc.
    if not page_texts and len(reader.pages) > 0:
        page_texts = _ocr_pdf_pages(path, len(reader.pages))

    out: list[dict] = []
    for page_num, text in sorted(page_texts.items()):
        for sec_idx, (heading, body) in enumerate(_group_by_heading(text)):
            if not body.strip():
                continue
            for c_idx, chunk in enumerate(_chunk_section(heading, body)):
                out.append({
                    "id": f"{document_id}:p{page_num}:s{sec_idx}:c{c_idx}",
                    "text": chunk,
                    "metadata": {
                        "document_id": document_id,
                        "source": source_name,
                        "page": page_num,
                        "section": heading or "",
                        "chunk": c_idx,
                    },
                })
    return out


def parse_text(text: str, document_id: str, source_name: str) -> list[dict]:
    """Same chunking strategy as PDFs, just without a page dimension."""
    text = _norm_ws(text)
    if not text:
        return []
    out: list[dict] = []
    for sec_idx, (heading, body) in enumerate(_group_by_heading(text)):
        if not body.strip():
            continue
        for c_idx, chunk in enumerate(_chunk_section(heading, body)):
            out.append({
                "id": f"{document_id}:t:s{sec_idx}:c{c_idx}",
                "text": chunk,
                "metadata": {
                    "document_id": document_id,
                    "source": source_name,
                    "page": None,
                    "section": heading or "",
                    "chunk": c_idx,
                },
            })
    return out
