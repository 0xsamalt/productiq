from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from .config import settings
from .db import init_db
from .routes import products, upload, diagnose, image as image_route, pages, audio


BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="productiq — assistant for your products", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Make templates importable from routes
app.state.templates = templates

app.include_router(pages.router)
app.include_router(products.router, prefix="/api")
app.include_router(upload.router, prefix="/api")
app.include_router(diagnose.router, prefix="/api")
app.include_router(image_route.router, prefix="/api")
app.include_router(audio.router, prefix="/api")


@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "moss_configured": bool(settings.MOSS_PROJECT_ID and settings.MOSS_PROJECT_KEY),
        "hf_configured": bool(settings.HF_TOKEN),
        "model": settings.HF_LLM_MODEL,
    }
