"""Company + Product CRUD."""
import shutil
from pathlib import Path
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from sqlmodel import Session, select
from ..db import get_session
from ..models import Company, Product, Document
from ..config import settings
from ..moss_service import ensure_shared_index, delete_product_docs


async def _purge_product(product_id: str, session: Session) -> None:
    """Delete a product's docs from Moss, its Document rows, its storage files,
    and finally the Product row itself."""
    # 1. Moss vectors
    await delete_product_docs(product_id)
    # 2. Document rows
    docs = session.exec(select(Document).where(Document.product_id == product_id)).all()
    for d in docs:
        session.delete(d)
    # 3. Storage files
    storage = Path(settings.STORAGE_DIR) / product_id
    if storage.exists():
        shutil.rmtree(storage, ignore_errors=True)
    # 4. Product row
    product = session.get(Product, product_id)
    if product:
        session.delete(product)
    session.commit()

router = APIRouter()


@router.post("/companies")
async def create_company(
    name: str = Form(...),
    email: str = Form(...),
    session: Session = Depends(get_session),
):
    existing = session.exec(select(Company).where(Company.email == email)).first()
    if existing:
        return RedirectResponse(f"/company/{existing.id}", status_code=303)
    company = Company(name=name, email=email)
    session.add(company)
    session.commit()
    session.refresh(company)
    return RedirectResponse(f"/company/{company.id}", status_code=303)


@router.post("/products")
async def create_product(
    company_id: str = Form(...),
    name: str = Form(...),
    category: str = Form(...),
    description: str = Form(""),
    session: Session = Depends(get_session),
):
    if not session.get(Company, company_id):
        raise HTTPException(404, "Company not found")
    product = Product(
        company_id=company_id,
        name=name,
        category=category,
        description=description,
    )
    session.add(product)
    session.commit()
    session.refresh(product)

    await ensure_shared_index()
    return RedirectResponse(f"/p/{product.id}", status_code=303)


@router.delete("/products/{product_id}")
async def delete_product(product_id: str, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    await _purge_product(product_id, session)
    return JSONResponse({"ok": True})


@router.post("/products/{product_id}/delete")
async def delete_product_form(product_id: str, session: Session = Depends(get_session)):
    """HTML-form-friendly alias: <form method='post'> can't issue DELETE."""
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    company_id = product.company_id
    await _purge_product(product_id, session)
    return RedirectResponse(f"/company/{company_id}", status_code=303)
