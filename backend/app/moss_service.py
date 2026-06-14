"""Thin async wrapper around the Moss SDK.

Design: ONE shared index for the whole app, with product_id as a metadata field.
Every query filters by {field: "product_id", condition: {"$eq": <id>}} so docs
from product A never leak into a chat about product B. This keeps us under
Moss's 3-index free-tier cap regardless of how many products are added.
"""
from typing import Optional
from moss import (
    MossClient,
    DocumentInfo,
    QueryOptions,
    MutationOptions,
)
from .config import settings


_client: Optional[MossClient] = None

SHARED_INDEX = "productiq-knowledge"
EMBED_MODEL = "moss-minilm"


def client() -> MossClient:
    global _client
    if _client is None:
        if not settings.MOSS_PROJECT_ID or not settings.MOSS_PROJECT_KEY:
            raise RuntimeError("Moss credentials missing. Set MOSS_PROJECT_ID and MOSS_PROJECT_KEY in .env")
        _client = MossClient(settings.MOSS_PROJECT_ID, settings.MOSS_PROJECT_KEY)
    return _client


def _to_doc_infos(product_id: str, chunks: list[dict]) -> list[DocumentInfo]:
    out: list[DocumentInfo] = []
    for c in chunks:
        md = {k: str(v) for k, v in (c.get("metadata") or {}).items() if v is not None}
        md["product_id"] = product_id  # stamp ownership
        out.append(DocumentInfo(id=c["id"], text=c["text"], metadata=md))
    return out


async def ensure_shared_index() -> None:
    """Idempotent. Loads the shared index, creating it once on first run."""
    try:
        await client().load_index(SHARED_INDEX)
        return
    except Exception:
        pass
    seed = [DocumentInfo(
        id="__seed__",
        text="productiq shared knowledge base initialized",
        metadata={"product_id": "__seed__"},
    )]
    await client().create_index(SHARED_INDEX, seed, EMBED_MODEL)
    await client().load_index(SHARED_INDEX)


async def add_chunks(product_id: str, chunks: list[dict]) -> int:
    if not chunks:
        return 0
    await client().add_docs(SHARED_INDEX, _to_doc_infos(product_id, chunks), MutationOptions(upsert=True))
    return len(chunks)


async def query(product_id: str, q: str, top_k: int = 6) -> list[dict]:
    """Semantic search scoped to one product via metadata filter."""
    await client().load_index(SHARED_INDEX)
    flt = {"field": "product_id", "condition": {"$eq": product_id}}
    results = await client().query(SHARED_INDEX, q, QueryOptions(top_k=top_k, filter=flt))
    out: list[dict] = []
    for d in results.docs:
        if d.id == "__seed__":
            continue
        out.append({
            "id": d.id,
            "text": d.text,
            "score": float(d.score),
            "metadata": getattr(d, "metadata", None) or {},
        })
    return out


async def delete_product_docs(product_id: str) -> int:
    """Delete every chunk belonging to one product."""
    try:
        all_docs = await client().get_docs(SHARED_INDEX)
    except Exception:
        return 0
    to_delete = [d.id for d in all_docs
                 if (getattr(d, "metadata", None) or {}).get("product_id") == product_id]
    if not to_delete:
        return 0
    await client().delete_docs(SHARED_INDEX, to_delete)
    return len(to_delete)


async def list_indexes() -> list[str]:
    try:
        idxs = await client().list_indexes()
        return [getattr(i, "name", str(i)) for i in idxs]
    except Exception:
        return []


async def delete_index(name: str) -> None:
    try:
        await client().delete_index(name)
    except Exception:
        pass
