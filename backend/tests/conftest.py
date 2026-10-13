"""Shared pytest fixtures.

Integration tests run against a dedicated PostgreSQL database
(`<POSTGRES_DB>_test`, created automatically) so development data is never
touched. The schema is built by running the real Alembic migrations, which
also verifies that migrations apply cleanly.
"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from cryptography.fernet import Fernet

# Connector tests store encrypted credentials; use a throwaway key for the test run.
os.environ.setdefault("CONNECTOR_ENCRYPTION_KEY", Fernet.generate_key().decode())

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password, hash_token, new_session_token
from app.db.session import get_db
from app.main import create_app
from app.models import Base, User, UserSession

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
    # DELETE (children first) is much faster than TRUNCATE for the small amounts of
    # data tests create: TRUNCATE allocates new files and fsyncs every table.
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


TEST_PASSWORD = "correct-horse-battery-staple"
# Hashing is deliberately slow (scrypt); compute the test hash once.
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


def create_test_user(
    db: Session, role: str = "admin", email: str | None = None
) -> tuple[User, str]:
    """Insert a user with TEST_PASSWORD and an active session; return (user, token)."""
    user = User(
        email=email or f"{role}@example.com",
        name=f"Test {role.capitalize()}",
        password_hash=TEST_PASSWORD_HASH,
        role=role,
    )
    db.add(user)
    db.flush()
    token = new_session_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db.commit()
    return user, token


@pytest.fixture()
def app_factory(engine: Engine, db: Session):
    """Builds TestClients bound to the test database; optionally signed in."""
    app = create_app()
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _override() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override
    clients: list[TestClient] = []

    def make(role: str | None) -> TestClient:
        test_client = TestClient(app)
        if role is not None:
            _, token = create_test_user(db, role)
            test_client.headers["Authorization"] = f"Bearer {token}"
        clients.append(test_client)
        return test_client

    yield make
    for test_client in clients:
        test_client.close()


@pytest.fixture()
def client(app_factory) -> TestClient:
    """Signed in as an admin (full access)."""
    return app_factory("admin")


@pytest.fixture()
def anon_client(app_factory) -> TestClient:
    """Not signed in."""
    return app_factory(None)


@pytest.fixture()
def client_for(app_factory):
    """client_for("viewer") -> a client signed in with that role."""
    return app_factory
