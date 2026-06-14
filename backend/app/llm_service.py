"""HF Inference wrapper for Gemma 3 12B-IT (text + vision).

Uses huggingface_hub.InferenceClient which proxies to whichever provider
hosts the model (Together / Fireworks / Hyperbolic / etc.) via provider="auto".
"""
from __future__ import annotations
import base64
from typing import AsyncIterator, Iterable
from huggingface_hub import InferenceClient
from .config import settings


def _client() -> InferenceClient:
    if not settings.HF_TOKEN:
        raise RuntimeError("HF_TOKEN missing. Set it in .env")
    return InferenceClient(
        provider=settings.HF_INFERENCE_PROVIDER,
        api_key=settings.HF_TOKEN,
    )


def chat(messages: list[dict], temperature: float = 0.2, max_tokens: int = 800) -> str:
    """Single-shot chat completion. Returns the assistant text."""
    resp = _client().chat.completions.create(
        model=settings.HF_LLM_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


def chat_stream(messages: list[dict], temperature: float = 0.2, max_tokens: int = 800) -> Iterable[str]:
    """Stream token chunks. Synchronous generator; wrap with `iterate_in_threadpool` for FastAPI SSE."""
    stream = _client().chat.completions.create(
        model=settings.HF_LLM_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    for chunk in stream:
        try:
            delta = chunk.choices[0].delta.content
        except (AttributeError, IndexError):
            delta = None
        if delta:
            yield delta


def chat_with_image(
    user_text: str,
    image_bytes: bytes,
    image_mime: str = "image/png",
    system: str | None = None,
    history: list[dict] | None = None,
    max_tokens: int = 800,
) -> str:
    """Multimodal call: user message contains both text and an image (base64 data URL)."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{image_mime};base64,{b64}"

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    if history:
        messages.extend(history)
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    })
    return chat(messages, max_tokens=max_tokens)
