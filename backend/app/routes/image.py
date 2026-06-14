"""Image-based troubleshooting — Gemma 3 multimodal."""
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlmodel import Session
from ..db import get_session
from ..models import Product
from ..llm_service import chat_with_image
from ..diagnostic_agent import SYSTEM_PROMPT
from ..moss_service import query as moss_query

router = APIRouter()


@router.post("/products/{product_id}/diagnose-image")
async def diagnose_image(
    product_id: str,
    note: str = Form(""),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    image_bytes = await file.read()
    mime = file.content_type or "image/png"

    # Step 1 — describe with PRODUCT CONTEXT so the model interprets the
    # image as a part of THIS product, not a generic visual lookalike.
    # (e.g. a mixer-grinder motor compartment can look exactly like a light
    # fixture from inside; without product context Gemma picks the wrong one.)
    description_prompt = (
        f"You are looking at a photo a user uploaded showing an issue with their "
        f"{product.name} ({product.category}). Product description: "
        f"{product.description or '(none provided)'}.\n\n"
        f"Assume the photo shows some part of THIS product (not a different device). "
        f"In 2-3 sentences, describe concretely what is visible: error codes / warning "
        f"lights / labels / damaged components / corrosion / disconnected wires / "
        f"foreign material. If the image clearly does not show the product or any "
        f"of its parts, say so explicitly."
    )
    visible = chat_with_image(
        user_text=description_prompt + (f"\n\nUser also wrote: {note}" if note else ""),
        image_bytes=image_bytes,
        image_mime=mime,
        max_tokens=250,
    ).strip()

    # Step 2 — retrieve from Moss using both the vision description and the user note.
    retrieval_q = (visible + " " + note).strip() or "device error"
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
        "Now apply the diagnostic protocol. Start with [ASK] or [DIAGNOSE]."
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

    return {
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
