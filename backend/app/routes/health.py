"""Product Health Score endpoints (company-facing analytics)."""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlmodel import Session

from ..db import get_session
from ..models import Product, ProductInsight
from .. import health_service

router = APIRouter()


def _serialize(insight: ProductInsight) -> dict:
    return {
        "product_id": insight.product_id,
        "health_score": insight.health_score,
        "grade": insight.grade,
        "breakdown": json.loads(insight.breakdown_json or "{}"),
        "summary": insight.summary,
        "top_issues": json.loads(insight.top_issues_json or "[]"),
        "coverage_gaps": json.loads(insight.coverage_gaps_json or "[]"),
        "trend": insight.trend,
        "sample_size": insight.sample_size,
        "computed_at": insight.computed_at.isoformat() if insight.computed_at else None,
    }


@router.post("/products/{product_id}/insights/refresh")
def refresh_insights(product_id: str, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    insight = health_service.compute_insight(session, product_id)
    return JSONResponse(_serialize(insight))


@router.get("/products/{product_id}/insights")
def get_insights(product_id: str, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    insight = health_service.load_insight(session, product_id)
    if insight is None:
        return JSONResponse({"product_id": product_id, "health_score": None, "computed_at": None})
    return JSONResponse(_serialize(insight))
