"""Re-index every product's documents into the current Moss project.

Use when:
- Moss credentials changed → all old chunks are gone, DB still says indexed=1.
- A product's first indexing was rejected by quota / network / transcript failure
  and the Document row got left with chunk_count=0.

Strategy per product:
1. Query Moss; if it already returns chunks for that product_id, treat as up-to-date
   and only re-process the individual docs marked indexed=0.
2. If Moss returns 0 chunks for the product, re-process EVERY doc the product owns.

Per-document re-processing:
  pdf   → pypdf parse + section-aware chunker
  text  → re-read file, run chunker
  image → Gemma 3 vision OCR, then chunker
  link  → httpx + BeautifulSoup, then chunker
  video → youtube-transcript-api, timestamped windows
"""
import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, ".")
from dotenv import load_dotenv

load_dotenv(".env", override=True)

from app import moss_service, youtube_ingest, web_ingest  # noqa: E402
from app.llm_service import extract_text_from_image  # noqa: E402
from app.pdf_parser import parse_pdf, parse_text  # noqa: E402


def _mime_for_ext(ext: str) -> str:
    return {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(
        ext.lstrip(".").lower(), "image/png"
    )


async def process_doc(doc: sqlite3.Row, product_id: str) -> int:
    """Return number of chunks added to Moss for this doc (0 on failure)."""
    kind = doc["kind"]
    doc_id = doc["id"]
    filename = doc["filename"] or "untitled"
    storage_path = doc["storage_path"]
    url = doc["url"]

    chunks: list[dict] = []
    try:
        if kind == "pdf" and storage_path and Path(storage_path).exists():
            chunks = parse_pdf(Path(storage_path), doc_id, filename)
        elif kind == "text" and storage_path and Path(storage_path).exists():
            text = Path(storage_path).read_text(encoding="utf-8", errors="ignore")
            chunks = parse_text(text, doc_id, filename)
        elif kind == "image" and storage_path and Path(storage_path).exists():
            ext = Path(storage_path).suffix
            ocr = extract_text_from_image(Path(storage_path).read_bytes(), image_mime=_mime_for_ext(ext))
            if ocr and ocr.upper() != "NO_TEXT_VISIBLE":
                chunks = parse_text(ocr, doc_id, filename)
        elif kind == "video" and url:
            chunks = youtube_ingest.fetch_chunks(url, doc_id, filename if filename != url else "YouTube video")
        elif kind == "link" and url:
            # If the URL is actually YouTube (legacy rows pre-dating the "video" kind), treat as video.
            if youtube_ingest.is_youtube_url(url):
                chunks = youtube_ingest.fetch_chunks(url, doc_id, filename if filename != url else "YouTube video")
            else:
                fetched, page_title = web_ingest.fetch_chunks(url, doc_id, filename if filename != url else "")
                chunks = fetched
        else:
            return 0
    except Exception as e:
        print(f"    [skip] {filename}: {e}")
        return 0

    if not chunks:
        return 0
    n = await moss_service.add_chunks(product_id, chunks)
    return n


async def main():
    con = sqlite3.connect("productiq.db")
    con.row_factory = sqlite3.Row

    await moss_service.ensure_shared_index()

    products = con.execute("SELECT id, name FROM product").fetchall()
    total_added = 0
    for p in products:
        pid = p["id"]
        pname = p["name"]
        existing = await moss_service.query(pid, "probe-existence-check", top_k=1)
        product_has_chunks = len(existing) > 0
        docs = con.execute(
            "SELECT id, filename, kind, url, storage_path, chunk_count, indexed FROM document "
            "WHERE product_id=? ORDER BY created_at ASC",
            (pid,),
        ).fetchall()

        print(f"\n=== {pname}  ({pid})  ===")
        print(f"    Moss currently has chunks for this product: {product_has_chunks}")
        print(f"    DB has {len(docs)} document rows")

        for d in docs:
            needs = (not product_has_chunks) or (not d["indexed"]) or (d["chunk_count"] == 0)
            if not needs:
                print(f"    [skip OK]  {d['filename'][:60]}  kind={d['kind']}  ({d['chunk_count']} chunks)")
                continue
            n = await process_doc(d, pid)
            con.execute(
                "UPDATE document SET chunk_count=?, indexed=? WHERE id=?",
                (n, 1 if n > 0 else 0, d["id"]),
            )
            con.commit()
            status = "OK" if n > 0 else "FAIL"
            print(f"    [{status}]      {d['filename'][:60]}  kind={d['kind']}  → {n} chunks")
            total_added += n

    print(f"\n=== Done. Added {total_added} chunks across all products. ===")


if __name__ == "__main__":
    asyncio.run(main())
