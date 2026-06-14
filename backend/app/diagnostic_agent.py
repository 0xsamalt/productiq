"""The diagnostic agent — the differentiator.

Not just RAG. The system prompt instructs Gemma to act like a technician:
- Decide each turn whether to ASK a follow-up (to narrow the cause)
  or DIAGNOSE (when there's enough evidence).
- Cite Moss-retrieved chunks by their source + page.
- Never invent steps that aren't in the retrieved docs.
"""
from __future__ import annotations
from . import moss_service, llm_service


SYSTEM_PROMPT = """You are a senior technician for a specific product. The user is asking about that product. \
Your job is to either troubleshoot like a real human service engineer (by ELIMINATION), or answer a \
direct usage question — depending on what kind of input you get.

You will be given:
- A short product description.
- The user's message and the conversation so far.
- Relevant excerpts from the product's official manuals and support docs (with source filename and page).

First, classify the user's message:

  FAULT — something is broken / not working / behaving wrong / safety concern.
          Examples: "the horn doesn't work", "fries come out soggy", "I smell burning".

  USAGE — pure how-to / when-to / can-I question about NORMAL operation, with no reported defect.
          Examples: "do I need to shake the fries?", "how often should I oil it?", "can I use it outdoors?"

Then act:

(A) If FAULT and you still need more info → output [ASK] with ONE follow-up question that would \
*eliminate* the most causes from the retrieved evidence. Prefer questions about observable symptoms, \
recent events, or simple inspections the user can perform safely. ONE question per turn.

(B) If FAULT and you have enough signal to commit, OR if it's a USAGE question \
→ output [DIAGNOSE]. Answer directly from the retrieved excerpts. Cite the source inline, e.g. \
"shake the fries halfway through (Philips airfryer video, 1:01)". End with the next concrete action.

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
- NEVER fabricate concrete numbers (times, temperatures, voltages, torque values, part numbers, \
figure numbers, fuse ratings, page numbers) that don't appear verbatim in the retrieved excerpts. \
If the user asks for a specific number and it's not in the excerpts, say so explicitly: \
"the retrieved docs don't specify the exact [X]" — do NOT fall back to general world knowledge.
- If the retrieved excerpts are empty OR clearly unrelated to the user's question, output [DIAGNOSE] \
with exactly: "I don't have manual coverage for this issue. Please contact the manufacturer or check \
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
    # Multilingual: ask Gemma to rewrite the user's recent turns into an English
    # search phrase before hitting Moss (moss-minilm is English-leaning).
    recent_user_msgs = [m["content"] for m in history if m.get("role") == "user"][-3:] + [user_message]
    retrieval_query = llm_service.rewrite_for_retrieval(recent_user_msgs, product_name)
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
            f"Do NOT ask another question. "
            f"Only mention confidence if it is NOT high — i.e., if you genuinely can't be sure, "
            f"add ONE short final sentence like 'Note: this is a best-guess from limited info.' "
            f"For a confident answer with clear citation, do not mention confidence at all — "
            f"and do not narrate what extra info 'would have' helped. The user doesn't care."
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
            f"USER MESSAGE: {user_message}\n\n"
            "LANGUAGE: Respond in the SAME LANGUAGE the user wrote in. "
            "If the user wrote in Hindi, reply in Hindi. Spanish → Spanish. "
            "Keep manual part numbers, error codes, and section labels in their original form. "
            "The [ASK]/[DIAGNOSE] prefix itself must stay in English (the UI parses it)."
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
