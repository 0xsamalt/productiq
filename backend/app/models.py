from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field
import uuid


def _uuid() -> str:
    return str(uuid.uuid4())


class Company(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str
    email: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Product(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    company_id: str = Field(foreign_key="company.id", index=True)
    name: str
    category: str
    description: str
    image_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Document(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    product_id: str = Field(foreign_key="product.id", index=True)
    filename: str
    kind: str  # "pdf" | "text" | "image" | "link"
    url: Optional[str] = None
    storage_path: Optional[str] = None
    chunk_count: int = 0
    indexed: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChatMessage(SQLModel, table=True):
    """Persistent chat messages tied to a browser session_id."""
    id: str = Field(default_factory=_uuid, primary_key=True)
    session_id: str = Field(index=True)
    role: str  # "user" | "assistant"
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DiagnosticEvent(SQLModel, table=True):
    """One user-reported issue turn, captured for product-health analytics.

    Written on every /diagnose turn. This is the raw signal the Product Health
    Score is computed from — what users report, whether the manuals covered it,
    and whether the agent reached a diagnosis.
    """
    id: str = Field(default_factory=_uuid, primary_key=True)
    product_id: str = Field(foreign_key="product.id", index=True)
    session_id: str = Field(index=True)
    user_message: str                       # the user's reported symptom/issue
    mode: str = "UNKNOWN"                    # "ASK" | "DIAGNOSE" | "UNKNOWN"
    had_coverage: bool = True               # did the manuals cover this issue?
    top_score: float = 0.0                  # best retrieval score this turn
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProductInsight(SQLModel, table=True):
    """Cached Product Health Score + insights for one product.

    Recomputed on demand (company clicks "Refresh insights"); read cheaply on
    every dashboard render. One row per product.
    """
    id: str = Field(default_factory=_uuid, primary_key=True)
    product_id: str = Field(foreign_key="product.id", unique=True, index=True)
    health_score: Optional[int] = None      # 0-100, None when too little data
    grade: str = "—"                        # Excellent / Good / Fair / At risk / —
    breakdown_json: str = "{}"              # per-component sub-scores (JSON)
    summary: str = ""                       # one-paragraph narrative
    top_issues_json: str = "[]"            # [{title, count, severity, ...}] (JSON)
    coverage_gaps_json: str = "[]"         # issue themes with no manual coverage
    trend: str = "flat"                    # "up" | "down" | "flat"
    sample_size: int = 0                    # number of diagnostic events analyzed
    computed_at: datetime = Field(default_factory=datetime.utcnow)
