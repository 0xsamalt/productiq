"""Image-based troubleshooting — Gemma 3 multimodal."""
from uuid import uuid4

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session
from ..db import get_session
from ..models import Product, ChatMessage
from ..llm_service import chat_with_image, rewrite_for_retrieval
from ..diagnostic_agent import SYSTEM_PROMPT
from ..moss_service import query as moss_query

router = APIRouter()


@router.post("/products/{product_id}/diagnose-image")
async def diagnose_image(
    product_id: str,
    note: str = Form(""),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    request: Request = None,
):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    image_bytes = await file.read()
    mime = file.content_type or "image/png"

    # Step 1 — let Gemma describe what it sees so we can retrieve relevant docs.
    # Important: the description is shown BACK to the user (chat.js prepends
    # "What I see in the image:") so it must be in the user's language.
    description_prompt = (
        f"You are looking at a photo a user uploaded showing an issue with their "
        f"{product.name} ({product.category}). Product description: "
        f"{product.description or '(none provided)'}.\n\n"
        f"Assume the photo shows some part of THIS product (not a different device). "
        f"In 2-3 sentences, describe concretely what is visible: error codes / warning "
        f"lights / labels / damaged components / corrosion / disconnected wires / "
        f"foreign material.\n\n"
        f"OUTPUT RULES — read carefully:\n"
        f"1. If a 'User's note' is provided below, detect the language of that note. "
        f"Write your entire description in THAT SAME language, with no English preamble or explanation.\n"
        f"2. If there is no user note, write in English.\n"
        f"3. Keep part numbers, error codes, and printed labels (text shown in the image) in their original form.\n"
        f"4. Do NOT include any phrase like 'in English' or 'in Hindi' in your output. Just write the description directly."
    )
    user_text = description_prompt + (f"\n\nUser's note: {note}" if note else "\n\n(no user note)")
    visible = chat_with_image(
        user_text=user_text,
        image_bytes=image_bytes,
        image_mime=mime,
        max_tokens=250,
    ).strip()

    # Step 2 — retrieve from Moss. The vision description is already English; the
    # user's note might be in any language, so route it through the rewriter so
    # the search phrase Moss sees is consistently English.
    retrieval_q = rewrite_for_retrieval([visible, note], product.name) or (visible + " " + note).strip() or "device error"
    chunks = await moss_query(product.id, retrieval_q, top_k=6)

    evidence = "\n\n".join(
        f"[source={(c.get('metadata') or {}).get('source','?')} "
        f"page={(c.get('metadata') or {}).get('page','?')}]\n{c['text'].strip()}"
        for c in chunks
    ) or "(no relevant doc excerpts found)"

    # Step 3 — diagnostic turn with the image AND retrieved evidence in context.
    user_block = (
        f"Product: {product.name}\n"
        f"Description: {product.description or '(none)'}\n\n"
        f"WHAT THE IMAGE SHOWS (your own description):\n{visible}\n\n"
        f"USER'S NOTE: {note or '(none)'}\n\n"
        f"RETRIEVED DOC EXCERPTS:\n{evidence}\n\n"
        "Now apply the diagnostic protocol. Start with [ASK] or [DIAGNOSE].\n"
        "LANGUAGE: Respond in the SAME LANGUAGE as the USER'S NOTE above. "
        "If the note is empty, default to English. Keep manual part numbers, "
        "error codes, and section labels in their original form. The [ASK]/[DIAGNOSE] "
        "prefix itself must stay in English (the UI parses it)."
    )
    reply = chat_with_image(
        user_text=user_block,
        image_bytes=image_bytes,
        image_mime=mime,
        system=SYSTEM_PROMPT,
        max_tokens=600,
    ).strip()

    mode = "UNKNOWN"
    if reply.upper().startswith("[ASK]"):
        mode, reply = "ASK", reply[5:].lstrip(" :-")
    elif reply.upper().startswith("[DIAGNOSE]"):
        mode, reply = "DIAGNOSE", reply[10:].lstrip(" :-")
    # Persist session-scoped chat messages (ensure session_id cookie)
    session_id = None
    if request is not None:
        session_id = request.cookies.get("session_id")
    new_cookie = False
    if not session_id:
        session_id = str(uuid4())
        new_cookie = True

    # Save the user upload/note as a user message
    user_msg = ChatMessage(session_id=session_id, role="user", content=f"[uploaded an image] {note}")
    session.add(user_msg)
    session.commit()

    # Save assistant reply
    assistant_msg = ChatMessage(session_id=session_id, role="assistant", content=reply)
    session.add(assistant_msg)
    session.commit()

    payload = {
        "visible": visible,
        "reply": reply,
        "mode": mode,
        "citations": [
            {
                "source": (c.get("metadata") or {}).get("source", "unknown"),
                "page": (c.get("metadata") or {}).get("page"),
                "score": c["score"],
                "text": c["text"][:300],
            }
            for c in chunks
        ],
    }
    resp = JSONResponse(payload)
    if new_cookie:
        resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
    return resp
