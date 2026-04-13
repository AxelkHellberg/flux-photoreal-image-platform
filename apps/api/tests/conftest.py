from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from image_platform_api.main import app
from image_platform_shared.config import Settings
from image_platform_shared.database import Base
from image_platform_shared.storage import LocalFilesystemStorageBackend
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class FakeQueue:
    def __init__(self):
        self.items: list[str] = []

    def enqueue(self, job_id: str) -> None:
        self.items.append(job_id)

    def ping(self) -> bool:
        return True


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="sqlite+pysqlite://",
        storage_backend="local",
        local_storage_root=str(tmp_path / "storage"),
        public_api_base_url="http://testserver",
        cors_origins="http://localhost:3000",
    )


@pytest.fixture
def session_factory(settings: Settings):
    engine = create_engine(
        settings.database_url,
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def storage_backend(tmp_path: Path) -> LocalFilesystemStorageBackend:
    storage = LocalFilesystemStorageBackend(str(tmp_path / "storage"))
    storage.ensure_ready()
    return storage


@pytest.fixture
def client(
    settings: Settings,
    session_factory,
    storage_backend: LocalFilesystemStorageBackend,
) -> Generator[tuple[TestClient, FakeQueue], None, None]:
    queue = FakeQueue()

    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.storage = storage_backend
    app.state.queue = queue

    with TestClient(app) as test_client:
        yield test_client, queue

    for attr in ("settings", "session_factory", "storage", "queue"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)
