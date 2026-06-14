"""Voice input — speech-to-text fallback via HF Whisper.

The browser uses the Web Speech API when available; when it isn't (Firefox,
Safari, etc.) it records audio with MediaRecorder and posts it here so the
server can transcribe it with Whisper. Product-agnostic, English only.
"""
from fastapi import APIRouter, UploadFile, File, HTTPException
from starlette.concurrency import run_in_threadpool
from ..llm_service import transcribe as run_transcribe

router = APIRouter()


@router.post("/transcribe")
async def transcribe_endpoint(file: UploadFile = File(...)):
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(400, "Empty audio upload")
    try:
        text = await run_in_threadpool(run_transcribe, audio_bytes)
    except Exception as e:
        raise HTTPException(502, f"Transcription failed: {e}")
    return {"text": text}
