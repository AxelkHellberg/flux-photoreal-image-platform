from collections.abc import Iterator

from fastapi import Request
from image_platform_shared.config import Settings, get_settings
from image_platform_shared.database import get_session_factory
from image_platform_shared.queue import ImageJobQueue
from image_platform_shared.storage import StorageBackend, create_storage_backend
from sqlalchemy.orm import Session


def get_app_settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", get_settings())


def get_queue(request: Request) -> ImageJobQueue:
    queue = getattr(request.app.state, "queue", None)
    if queue is None:
        settings = get_app_settings(request)
        queue = ImageJobQueue(settings.redis_url, settings.redis_queue_name)
        request.app.state.queue = queue
    return queue


def get_storage(request: Request) -> StorageBackend:
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        storage = create_storage_backend(get_app_settings(request))
        storage.ensure_ready()
        request.app.state.storage = storage
    return storage


def get_db(request: Request) -> Iterator[Session]:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
