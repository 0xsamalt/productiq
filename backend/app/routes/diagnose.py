"""Diagnostic chat endpoint."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session
from ..db import get_session
from ..models import Product
from ..diagnostic_agent import diagnose as run_diagnose

router = APIRouter()


class Turn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class DiagnoseRequest(BaseModel):
    history: list[Turn] = []
    message: str


@router.post("/products/{product_id}/diagnose")
async def diagnose_endpoint(
    product_id: str,
    body: DiagnoseRequest,
    session: Session = Depends(get_session),
):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    result = await run_diagnose(
        product_id=product.id,
        product_name=product.name,
        product_description=product.description or "",
        history=[t.model_dump() for t in body.history],
        user_message=body.message,
    )
    return result
