"""Upload product support material → parse → push to Moss."""
import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from sqlmodel import Session
from ..db import get_session
from ..models import Document, Product
from ..config import settings
from ..moss_service import add_chunks, ensure_shared_index
from ..pdf_parser import parse_pdf, parse_text

router = APIRouter()


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


@router.post("/products/{product_id}/upload")
async def upload_document(
    product_id: str,
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    ext = Path(file.filename or "").suffix.lower()
    kind = {
        ".pdf": "pdf",
        ".txt": "text",
        ".md": "text",
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
    }.get(ext, "text")

    doc = Document(
        product_id=product_id,
        filename=file.filename or "untitled",
        kind=kind,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)

    storage = Path(settings.STORAGE_DIR) / product_id
    storage.mkdir(parents=True, exist_ok=True)
    stored_path = storage / f"{doc.id}{ext}"
    with stored_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    doc.storage_path = str(stored_path)

    chunks: list[dict] = []
    if kind == "pdf":
        chunks = parse_pdf(stored_path, doc.id, doc.filename)
    elif kind == "text":
        text = stored_path.read_text(encoding="utf-8", errors="ignore")
        chunks = parse_text(text, doc.id, doc.filename)
    # images get attached as raw assets; not chunked here.

    if chunks:
        await ensure_shared_index()
        added = await add_chunks(product_id, chunks)
        doc.chunk_count = added
        doc.indexed = True

    session.add(doc)
    session.commit()

    if _wants_html(request):
        return RedirectResponse(f"/company/{product.company_id}", status_code=303)
    return JSONResponse({
        "ok": True,
        "document_id": doc.id,
        "kind": kind,
        "chunk_count": doc.chunk_count,
    })


@router.post("/products/{product_id}/upload-link")
async def upload_link(
    product_id: str,
    request: Request,
    url: str = Form(...),
    title: str = Form(""),
    session: Session = Depends(get_session),
):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    doc = Document(
        product_id=product_id,
        filename=title or url,
        kind="link",
        url=url,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    if _wants_html(request):
        return RedirectResponse(f"/company/{product.company_id}", status_code=303)
    return JSONResponse({"ok": True, "document_id": doc.id})
