"""Server-rendered HTML pages (Jinja)."""
from typing import Optional
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select
from ..db import get_session
from ..models import Product, Company, Document

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: Optional[str] = None,
    session: Session = Depends(get_session),
):
    if q:
        products = session.exec(
            select(Product)
            .where(
                (Product.name.ilike(f"%{q}%"))
                | (Product.category.ilike(f"%{q}%"))
            )
            .order_by(Product.created_at.desc())
        ).all()
    else:
        products = session.exec(select(Product).order_by(Product.created_at.desc())).all()

    return _templates(request).TemplateResponse(
        request,
        "index.html",
        {"products": products, "q": q},
    )


@router.get("/p/{product_id}", response_class=HTMLResponse)
def product_page(product_id: str, request: Request, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    company = session.get(Company, product.company_id)
    docs = session.exec(
        select(Document).where(Document.product_id == product_id).order_by(Document.created_at.desc())
    ).all()
    return _templates(request).TemplateResponse(
        request,
        "product.html",
        {
            "product": product,
            "company": company,
            "docs": docs,
        },
    )


@router.get("/company", response_class=HTMLResponse)
def company_dashboard(request: Request, session: Session = Depends(get_session)):
    companies = session.exec(select(Company)).all()
    return _templates(request).TemplateResponse(
        request, "company.html", {"companies": companies},
    )


@router.get("/company/{company_id}", response_class=HTMLResponse)
def company_detail(company_id: str, request: Request, session: Session = Depends(get_session)):
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Company not found")
    products = session.exec(select(Product).where(Product.company_id == company_id)).all()
    docs_by_product: dict[str, list[Document]] = {}
    for p in products:
        docs_by_product[p.id] = session.exec(
            select(Document).where(Document.product_id == p.id).order_by(Document.created_at.desc())
        ).all()
    return _templates(request).TemplateResponse(
        request, "company_detail.html",
        {"company": company, "products": products, "docs_by_product": docs_by_product},
    )
