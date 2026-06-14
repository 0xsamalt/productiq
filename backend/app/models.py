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
