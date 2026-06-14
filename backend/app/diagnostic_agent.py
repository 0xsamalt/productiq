"""The diagnostic agent — the differentiator.

Not just RAG. The system prompt instructs Gemma to act like a technician:
- Decide each turn whether to ASK a follow-up (to narrow the cause)
  or DIAGNOSE (when there's enough evidence).
- Cite Moss-retrieved chunks by their source + page.
- Never invent steps that aren't in the retrieved docs.
"""
from __future__ import annotations
from . import moss_service, llm_service


SYSTEM_PROMPT = """You are a senior technician for a specific product. The user has reported a problem. \
Your job is to diagnose it like a real human service engineer — by ELIMINATION, not by dumping search results.

You will be given:
- A short product description.
- The user's reported issue and the conversation so far.
- Relevant excerpts from the product's official manuals and support docs (with source filename and page).

Each turn, decide ONE of:

(A) ASK ONE follow-up question that would *eliminate* the most causes from the retrieved evidence. \
Prefer questions about observable symptoms (e.g. "does the headlight work?"), \
recent events ("any electrical work done recently?"), or simple inspections the user can perform safely.

(B) DIAGNOSE — only when the conversation gives you enough signal to commit to a likely root cause. \
Cite the manual reference inline, e.g. "Check Fuse F3 (Figure 4.2 of the service manual)". \
End with the most-likely cause and the next concrete action the user should take.

SAFETY (overrides everything else):
- If the reported symptom suggests fire, burning smell, smoke, sparks, scorching, electrical shock, \
fuel/gas leak, or any unstable mechanical failure: do NOT propose an inspection step. Output \
[DIAGNOSE] immediately and instruct the user to stop using the product, power it off / unplug it / \
move to a safe location, and contact a qualified technician or the manufacturer.
- Never instruct the user to bypass a safety interlock, defeat a guard, open a sealed battery / fuel \
tank, or work on a live mains circuit.
- Inspection steps you propose must be performable with the product powered off and unplugged.

Hard rules:
- ONE question per turn when asking. No bullet lists of 5 questions.
- Never invent part numbers, figure numbers, or fuse ratings that aren't in the retrieved excerpts.
- If the retrieved excerpts are empty OR clearly unrelated to the user's issue, output [DIAGNOSE] with \
exactly: "I don't have manual coverage for this issue. Please contact the manufacturer or check \
their support channel." Do not guess.
- Tone: calm, direct, technician-like. No filler ("Great question!").
- Keep replies under 120 words unless you're explaining a multi-step procedure from the docs.

Reply with plain text. Start with [ASK] or [DIAGNOSE] as the first token so the UI knows the mode."""


def _format_evidence(chunks: list[dict]) -> str:
    if not chunks:
        return "(no relevant excerpts found in the product docs for this query)"
    lines = []
    for i, c in enumerate(chunks, 1):
        md = c.get("metadata") or {}
        src = md.get("source", "unknown")
        page = md.get("page", "?")
        lines.append(f"[{i}] source={src} page={page}\n{c['text'].strip()}\n")
    return "\n".join(lines)


async def diagnose(
    product_id: str,
    product_name: str,
    product_description: str,
    history: list[dict],
    user_message: str,
    top_k: int = 6,
) -> dict:
    """One diagnostic step.

    Returns:
        {
          "reply": str,
          "mode": "ASK" | "DIAGNOSE" | "UNKNOWN",
          "citations": [ {source, page, score, text} ],
        }
    """
    retrieval_query = "\n".join(
        [m["content"] for m in history if m.get("role") == "user"][-3:] + [user_message]
    )
    chunks = await moss_service.query(product_id, retrieval_query, top_k=top_k)
    evidence = _format_evidence(chunks)

    product_block = f"Product: {product_name}\nDescription: {product_description.strip() or '(none)'}"

    # Turn budget: count how many follow-up questions we've already asked.
    # We don't track the assistant's prior [ASK]/[DIAGNOSE] mode in history
    # (it's stripped before being shown back), so use user-message count as a
    # proxy. The current message itself counts.
    user_turn_count = sum(1 for m in history if m.get("role") == "user") + 1

    MAX_ASK_TURNS = 3
    if user_turn_count <= 1:
        turn_directive = "First turn — start the diagnostic protocol."
    elif user_turn_count < MAX_ASK_TURNS:
        turn_directive = (
            f"Turn {user_turn_count}. You may still [ASK] one more follow-up "
            f"if it would meaningfully narrow the cause. Otherwise, commit to a [DIAGNOSE]."
        )
    else:
        turn_directive = (
            f"Turn {user_turn_count}. You have already asked enough questions. "
            f"You MUST output [DIAGNOSE] now. Commit to the most-likely cause given "
            f"everything the user has said so far, even if your confidence is moderate. "
            f"State your confidence (high / medium / low) at the end, and what one piece "
            f"of additional info would have raised it to high — but do not ask another question."
        )

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({
        "role": "user",
        "content": (
            f"{product_block}\n\n"
            f"TURN BUDGET: {turn_directive}\n\n"
            f"RETRIEVED DOC EXCERPTS:\n{evidence}\n\n"
            f"USER MESSAGE: {user_message}"
        ),
    })

    reply = llm_service.chat(messages, temperature=0.2, max_tokens=600).strip()

    mode = "UNKNOWN"
    if reply.upper().startswith("[ASK]"):
        mode = "ASK"
        reply = reply[len("[ASK]"):].lstrip(" :-")
    elif reply.upper().startswith("[DIAGNOSE]"):
        mode = "DIAGNOSE"
        reply = reply[len("[DIAGNOSE]"):].lstrip(" :-")

    citations = [
        {
            "source": (c.get("metadata") or {}).get("source", "unknown"),
            "page": (c.get("metadata") or {}).get("page"),
            "score": c["score"],
            "text": c["text"][:300],
        }
        for c in chunks
    ]

    return {"reply": reply, "mode": mode, "citations": citations}
