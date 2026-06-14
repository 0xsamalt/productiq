from sqlmodel import SQLModel, Session, create_engine
from .config import settings
from . import models  # noqa: F401 — ensures tables are registered

engine = create_engine(
    settings.DB_URL,
    connect_args={"check_same_thread": False} if settings.DB_URL.startswith("sqlite") else {},
)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
