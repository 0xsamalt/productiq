"""YouTube link → transcript → Moss-ready chunks (with timestamps).

Pulls auto-captions via youtube-transcript-api (no Whisper, no API key needed).
Each chunk represents ~60s of video and carries the start timestamp in its
metadata, so citations can deep-link to "https://youtu.be/<id>?t=187".
"""
from __future__ import annotations
import re
from youtube_transcript_api import YouTubeTranscriptApi

_YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/|youtube\.com/shorts/)"
    r"([0-9A-Za-z_-]{11})"
)

WINDOW_SECONDS = 60          # group caption segments into ~1-minute chunks
MAX_CHUNK_CHARS = 1200       # match pdf_parser size budget
PREFERRED_LANGS = ("en", "en-US", "en-GB", "hi", "hi-IN")


def is_youtube_url(url: str) -> bool:
    return bool(_YOUTUBE_RE.search(url or ""))


def extract_video_id(url: str) -> str | None:
    m = _YOUTUBE_RE.search(url or "")
    return m.group(1) if m else None


def _fmt_ts(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _ts_url(url: str, t: int) -> str:
    """Append a t=<seconds> param so the link jumps to that moment."""
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}t={t}"


def fetch_chunks(url: str, document_id: str, source_name: str) -> list[dict]:
    """Fetch the YouTube transcript and return Moss-ready chunks.

    Raises ValueError if the URL isn't YouTube or the video has no transcript.
    """
    vid = extract_video_id(url)
    if not vid:
        raise ValueError(f"Not a YouTube URL: {url}")

    try:
        # youtube-transcript-api ≥ 1.0 changed to an instance-based API; the
        # fetched object yields snippets with .text / .start / .duration attrs.
        fetched = YouTubeTranscriptApi().fetch(vid, languages=list(PREFERRED_LANGS))
        segments = [
            {"text": s.text, "start": s.start, "duration": s.duration}
            for s in fetched
        ]
    except Exception as e:
        raise ValueError(f"Could not fetch transcript: {e}")

    if not segments:
        return []

    chunks: list[dict] = []
    buf_text: list[str] = []
    buf_start: float | None = None
    buf_chars = 0

    def flush() -> None:
        if not buf_text or buf_start is None:
            return
        text = " ".join(s.strip() for s in buf_text if s.strip())
        if not text:
            return
        ts = int(buf_start)
        chunks.append({
            "id": f"{document_id}:yt:t{ts}",
            "text": f"[Video at {_fmt_ts(ts)}]\n{text}",
            "metadata": {
                "document_id": document_id,
                "source": source_name,
                "url": _ts_url(url, ts),
                "timestamp": ts,
                "timestamp_label": _fmt_ts(ts),
                "kind": "video",
            },
        })

    for seg in segments:
        seg_text = (seg.get("text") or "").replace("\n", " ").strip()
        seg_start = float(seg.get("start", 0.0))
        if buf_start is None:
            buf_start = seg_start
        elapsed = seg_start - buf_start
        new_chars = buf_chars + len(seg_text) + 1
        if elapsed > WINDOW_SECONDS or new_chars > MAX_CHUNK_CHARS:
            flush()
            buf_text = [seg_text]
            buf_start = seg_start
            buf_chars = len(seg_text)
        else:
            buf_text.append(seg_text)
            buf_chars = new_chars
    flush()
    return chunks
