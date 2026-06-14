"""Diagnostic chat endpoint."""
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import Session
from ..db import get_session
from ..models import Product, ChatMessage, DiagnosticEvent
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
    request: Request = None,
):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    # Identify (or create) a session_id for this browser session
    session_id = None
    if request is not None:
        session_id = request.cookies.get("session_id")
    new_cookie = False
    if not session_id:
        session_id = str(uuid4())
        new_cookie = True

    # Persist the user's message
    user_msg = ChatMessage(session_id=session_id, role="user", content=body.message)
    session.add(user_msg)
    session.commit()

    result = await run_diagnose(
        product_id=product.id,
        product_name=product.name,
        product_description=product.description or "",
        history=[t.model_dump() for t in body.history],
        user_message=body.message,
    )

    # Persist the assistant's reply
    assistant_msg = ChatMessage(session_id=session_id, role="assistant", content=result.get("reply", ""))
    session.add(assistant_msg)

    # Capture an analytics event for the Product Health Score. The agent emits a
    # fixed "I don't have manual coverage" line when retrieval was empty/unrelated;
    # treat that (or a missing/weak citation set) as a documentation gap.
    citations = result.get("citations") or []
    top_score = max((c.get("score") or 0.0 for c in citations), default=0.0)
    reply_text = (result.get("reply") or "").lower()
    had_coverage = bool(citations) and "don't have manual coverage" not in reply_text
    session.add(DiagnosticEvent(
        product_id=product.id,
        session_id=session_id,
        user_message=body.message,
        mode=result.get("mode", "UNKNOWN"),
        had_coverage=had_coverage,
        top_score=float(top_score),
    ))
    session.commit()

    resp = JSONResponse(result)
    if new_cookie:
        resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
    return resp
