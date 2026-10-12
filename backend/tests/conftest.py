"""Shared pytest fixtures.

Integration tests run against a dedicated PostgreSQL database
(`<POSTGRES_DB>_test`, created automatically) so development data is never
touched. The schema is built by running the real Alembic migrations, which
also verifies that migrations apply cleanly.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.session import get_db
from app.main import create_app
from app.models import Base

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _test_db_name() -> str:
    return os.environ.get("TEST_POSTGRES_DB", f"{get_settings().postgres_db}_test")


def _ensure_database(name: str) -> None:
    settings = get_settings()
    with psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        dbname="postgres",
        autocommit=True,
        connect_timeout=5,
    ) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    name = _test_db_name()
    _ensure_database(name)
    url = get_settings().database_url_for(name)

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")

    eng = create_engine(url)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine: Engine) -> Iterator[Session]:
    """A session on a freshly truncated schema."""
    tables = [t.name for t in Base.metadata.sorted_tables]
    if tables:
        with engine.begin() as conn:
            quoted = ", ".join(f'"{t}"' for t in tables)
            conn.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(engine: Engine, db: Session) -> Iterator[TestClient]:
    app = create_app()
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _override() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as test_client:
        yield test_client
