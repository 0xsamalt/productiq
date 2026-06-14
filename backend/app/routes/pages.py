"""Server-rendered HTML pages (Jinja)."""
from typing import Optional
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select
from ..db import get_session
from ..models import Product, Company, Document
from ..models import ChatMessage

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
    # Ensure the user has a session_id cookie for chat persistence.
    session_id = request.cookies.get("session_id")
    new_cookie = False
    if not session_id:
        session_id = str(uuid4())
        new_cookie = True

    # Load chat history for this session (ordered oldest->newest)
    chat_rows = session.exec(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
    ).all()
    chat_history = [
        {"role": c.role, "content": c.content, "created_at": c.created_at.isoformat()}
        for c in chat_rows
    ]

    resp = _templates(request).TemplateResponse(
        request,
        "product.html",
        {
            "product": product,
            "company": company,
            "docs": docs,
            "chat_history": chat_history,
        },
    )
    if new_cookie:
        resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
    return resp


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
