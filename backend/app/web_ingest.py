"""HTML link → cleaned text → Moss-ready chunks.

For external documentation pages (FAQ, support portals, vendor pages) the
manufacturer attaches via the company dashboard. Fetched once at ingest
time; the URL is stored so citations can deep-link back.
"""
from __future__ import annotations
import re
import httpx
from bs4 import BeautifulSoup
from .pdf_parser import parse_text

USER_AGENT = "Mozilla/5.0 (compatible; productiq-bot/1.0; +https://productiq.local)"
FETCH_TIMEOUT = 30.0
MAX_BYTES = 2_000_000      # don't ingest pages > 2MB
STRIP_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "aside",
              "form", "iframe", "svg")


def _clean_html_to_text(html: str) -> tuple[str, str | None]:
    """Return (clean_text, page_title). Strips chrome/nav, keeps the main copy."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(list(STRIP_TAGS)):
        tag.decompose()

    title = (soup.title.string.strip() if soup.title and soup.title.string else None)

    # Prefer <main> or <article> when present (cleaner extraction).
    container = soup.find("main") or soup.find("article") or soup.body or soup
    text = container.get_text(separator="\n", strip=True)

    # Collapse very long runs of blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, title


def fetch_chunks(url: str, document_id: str, source_name: str) -> tuple[list[dict], str | None]:
    """Fetch the URL, extract text, return (chunks, resolved_title).

    Raises Exception on network / HTTP errors so caller can surface in `ingest_error`.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=True, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()

    ctype = resp.headers.get("content-type", "")
    if "html" not in ctype.lower() and "text" not in ctype.lower():
        raise ValueError(f"URL did not return HTML/text (content-type={ctype!r})")
    if len(resp.content) > MAX_BYTES:
        raise ValueError(f"Page too large ({len(resp.content)} bytes > {MAX_BYTES})")

    text, page_title = _clean_html_to_text(resp.text)
    if not text.strip():
        return [], page_title

    final_source = source_name or page_title or url
    chunks = parse_text(text, document_id, final_source)
    # Stamp the URL onto every chunk so citations can deep-link.
    for c in chunks:
        c.setdefault("metadata", {})["url"] = url
        c["metadata"]["kind"] = "web"
    return chunks, page_title
