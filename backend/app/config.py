import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    MOSS_PROJECT_ID: str = os.getenv("MOSS_PROJECT_ID", "")
    MOSS_PROJECT_KEY: str = os.getenv("MOSS_PROJECT_KEY", "")

    HF_TOKEN: str = os.getenv("HF_TOKEN", "")
    HF_LLM_MODEL: str = os.getenv("HF_LLM_MODEL", "google/gemma-3-12b-it")
    HF_INFERENCE_PROVIDER: str = os.getenv("HF_INFERENCE_PROVIDER", "auto")

    APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT: int = int(os.getenv("APP_PORT", "8000"))
    DB_URL: str = os.getenv("DB_URL", "sqlite:///./productiq.db")
    STORAGE_DIR: Path = BASE_DIR / os.getenv("STORAGE_DIR", "./storage").lstrip("./")


settings = Settings()
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
