"""Product Health Score — turns diagnostic conversations into company insights.

There is no reviews/tickets table in ProductIQ; the only signal about what's
wrong with a product is what users report in the diagnostic chat. This module
mines those DiagnosticEvent rows into:

  - a 0-100 Health Score (coverage + resolution + severity + trend),
  - the top recurring issue themes (LLM-clustered),
  - documentation gaps (themes the manuals didn't cover),
  - a short narrative summary.

Computed on demand and cached in ProductInsight (one row per product).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlmodel import Session, select

from . import llm_service
from .models import DiagnosticEvent, ProductInsight

# Below this many events the score is statistically meaningless — we still show
# the raw signals but withhold a single number.
MIN_EVENTS = 5
MAX_MESSAGES_TO_CLUSTER = 150

# Health Score weights (must sum to 1.0).
W_COVERAGE = 0.30
W_RESOLUTION = 0.30
W_SEVERITY = 0.25
W_TREND = 0.15

_SEVERITY_WEIGHT = {"high": 1.0, "medium": 0.5, "low": 0.15}


def _grade(score: int) -> str:
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 50:
        return "Fair"
    return "At risk"


def _cluster_issues(events: list[DiagnosticEvent]) -> dict:
    """Ask the LLM to group reported issues into themes.

    Returns {"summary": str, "clusters": [{title, severity, member_indices, example}]}.
    Indices refer to the position of each event in `events`. Counts and doc-gap
    rates are derived from those indices here (not trusted to the model).
    """
    sample = events[-MAX_MESSAGES_TO_CLUSTER:]
    numbered = "\n".join(
        f"[{i}] {e.user_message.strip()[:300]}" for i, e in enumerate(sample)
    )
    prompt = (
        "You are a product-quality analyst. Below are problems users reported "
        "about a single product, each on its own line prefixed with an index.\n\n"
        "Group them into a small set of distinct issue themes (merge duplicates "
        "and paraphrases). For each theme give:\n"
        '  - "title": a short human label (e.g. "Battery not charging")\n'
        '  - "severity": one of "high" (safety risk or total failure), '
        '"medium" (degraded function), "low" (minor / usage question)\n'
        '  - "member_indices": the list of indices belonging to this theme\n'
        '  - "example": the clearest verbatim example line\n\n'
        "Also write a 2-3 sentence \"summary\" of the overall product health "
        "picture for the manufacturer.\n\n"
        "Return ONLY valid JSON: "
        '{"summary": "...", "clusters": [{"title": "...", "severity": "...", '
        '"member_indices": [...], "example": "..."}]}\n\n'
        f"REPORTED ISSUES:\n{numbered}"
    )
    raw = llm_service.chat(
        [{"role": "user", "content": prompt}], temperature=0.1, max_tokens=1200
    ).strip()
    # Tolerate ```json fences / stray prose around the object.
    if "```" in raw:
        raw = raw.split("```")[1] if raw.count("```") >= 2 else raw
        raw = raw.replace("json", "", 1).strip() if raw.lstrip().lower().startswith("json") else raw
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start : end + 1]
    data = json.loads(raw)
    if not isinstance(data, dict) or "clusters" not in data:
        raise ValueError("unexpected cluster shape")
    return data


def compute_insight(session: Session, product_id: str) -> ProductInsight:
    """Recompute and persist the Product Health Score for one product."""
    events = session.exec(
        select(DiagnosticEvent)
        .where(DiagnosticEvent.product_id == product_id)
        .order_by(DiagnosticEvent.created_at.asc())
    ).all()

    insight = session.exec(
        select(ProductInsight).where(ProductInsight.product_id == product_id)
    ).first()
    if insight is None:
        insight = ProductInsight(product_id=product_id)
        session.add(insight)

    total = len(events)
    insight.sample_size = total
    insight.computed_at = datetime.utcnow()

    if total == 0:
        insight.health_score = None
        insight.grade = "—"
        insight.summary = "No diagnostic conversations yet. Insights appear once users start reporting issues."
        insight.breakdown_json = "{}"
        insight.top_issues_json = "[]"
        insight.coverage_gaps_json = "[]"
        insight.trend = "flat"
        session.commit()
        session.refresh(insight)
        return insight

    # --- Numeric signals (always available, no LLM) ---
    coverage_rate = sum(1 for e in events if e.had_coverage) / total

    sessions: dict[str, bool] = {}
    for e in events:
        sessions[e.session_id] = sessions.get(e.session_id, False) or (e.mode == "DIAGNOSE")
    resolution_rate = (sum(1 for v in sessions.values() if v) / len(sessions)) if sessions else 0.0

    now = datetime.utcnow()
    recent = sum(1 for e in events if e.created_at >= now - timedelta(days=30))
    prior = sum(1 for e in events if now - timedelta(days=60) <= e.created_at < now - timedelta(days=30))
    if prior == 0:
        trend, trend_score = "flat", 0.7
    else:
        ratio = recent / prior
        if ratio > 1.2:
            trend = "up"
        elif ratio < 0.8:
            trend = "down"
        else:
            trend = "flat"
        trend_score = max(0.0, min(1.0, 1.0 - max(0.0, ratio - 1.0) * 0.5))

    # --- LLM clustering (best-effort) ---
    sample = events[-MAX_MESSAGES_TO_CLUSTER:]
    top_issues: list[dict] = []
    coverage_gaps: list[dict] = []
    summary = ""
    severity_score = 0.7  # neutral default if clustering fails
    try:
        clustered = _cluster_issues(events)
        summary = (clustered.get("summary") or "").strip()
        weighted_sev = 0.0
        weighted_n = 0
        for c in clustered.get("clusters", []):
            idxs = [i for i in (c.get("member_indices") or []) if isinstance(i, int) and 0 <= i < len(sample)]
            if not idxs:
                continue
            members = [sample[i] for i in idxs]
            count = len(members)
            sev = str(c.get("severity", "low")).lower()
            if sev not in _SEVERITY_WEIGHT:
                sev = "low"
            gap_count = sum(1 for m in members if not m.had_coverage)
            issue = {
                "title": (c.get("title") or "Untitled issue").strip(),
                "count": count,
                "severity": sev,
                "example": (c.get("example") or members[0].user_message).strip()[:200],
                "doc_gap_rate": round(gap_count / count, 2),
            }
            top_issues.append(issue)
            if gap_count / count >= 0.5:
                coverage_gaps.append(issue)
            weighted_sev += _SEVERITY_WEIGHT[sev] * count
            weighted_n += count
        if weighted_n:
            # Higher weighted severity → lower severity_score.
            severity_score = max(0.0, 1.0 - weighted_sev / weighted_n)
        top_issues.sort(key=lambda x: (x["count"], _SEVERITY_WEIGHT[x["severity"]]), reverse=True)
        coverage_gaps.sort(key=lambda x: x["count"], reverse=True)
    except Exception as exc:  # noqa: BLE001 — LLM/JSON failures shouldn't 500 the dashboard
        summary = summary or f"Issue clustering unavailable ({type(exc).__name__}); score reflects coverage, resolution and trend only."

    breakdown = {
        "coverage": round(coverage_rate, 3),
        "resolution": round(resolution_rate, 3),
        "severity": round(severity_score, 3),
        "trend": round(trend_score, 3),
    }

    if total < MIN_EVENTS:
        insight.health_score = None
        insight.grade = "—"
        if not summary:
            summary = "Too few conversations for a reliable score yet."
        summary = f"Only {total} conversation(s) so far — score withheld until {MIN_EVENTS}. " + summary
    else:
        score = (
            W_COVERAGE * coverage_rate
            + W_RESOLUTION * resolution_rate
            + W_SEVERITY * severity_score
            + W_TREND * trend_score
        ) * 100
        insight.health_score = round(score)
        insight.grade = _grade(insight.health_score)

    insight.summary = summary
    insight.breakdown_json = json.dumps(breakdown)
    insight.top_issues_json = json.dumps(top_issues[:8])
    insight.coverage_gaps_json = json.dumps(coverage_gaps[:5])
    insight.trend = trend

    session.commit()
    session.refresh(insight)
    return insight


def load_insight(session: Session, product_id: str) -> ProductInsight | None:
    """Cheap read of the cached insight for dashboard rendering."""
    return session.exec(
        select(ProductInsight).where(ProductInsight.product_id == product_id)
    ).first()
