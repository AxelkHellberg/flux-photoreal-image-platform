from __future__ import annotations

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as DatabaseTimeoutError
from sqlalchemy.orm import Session


def test_health_reports_ready_dependencies(client):
    test_client, _ = client

    response = test_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "queue_name": "image_jobs:v1",
        "storage_backend": "local",
        "generator_backend": "stub",
    }


def test_health_rejects_unsuccessful_queue_ping(client, monkeypatch):
    test_client, queue = client
    monkeypatch.setattr(queue, "ping", lambda: False)

    response = test_client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "Queue is unavailable"}


@pytest.mark.parametrize("error_type", [RedisConnectionError, RedisTimeoutError])
def test_health_reports_queue_outages(client, monkeypatch, error_type):
    test_client, queue = client

    def unavailable():
        raise error_type("private connection details")

    monkeypatch.setattr(queue, "ping", unavailable)

    response = test_client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "Queue is unavailable"}


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT 1", {}, Exception("private connection details")),
        DatabaseTimeoutError("private connection details"),
    ],
)
def test_health_reports_database_outages(client, monkeypatch, error):
    test_client, queue = client

    def unavailable(*args, **kwargs):
        raise error

    def unexpected_queue_probe():
        pytest.fail("Queue must not be probed after a failed database check")

    monkeypatch.setattr(Session, "execute", unavailable)
    monkeypatch.setattr(queue, "ping", unexpected_queue_probe)

    response = test_client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}


def test_health_preserves_unexpected_programming_errors(client, monkeypatch):
    test_client, queue = client

    def broken_probe():
        raise RuntimeError("broken queue implementation")

    monkeypatch.setattr(queue, "ping", broken_probe)

    with pytest.raises(RuntimeError, match="broken queue implementation"):
        test_client.get("/health")
