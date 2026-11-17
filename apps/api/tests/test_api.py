from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from image_platform_shared.enums import JobStatus
from image_platform_shared.jobs import mark_success
from image_platform_shared.models import ImageJob
from PIL import Image
from sqlalchemy.orm import Session


def _history_cursor(payload: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "not-a-cursor",
        "é",
        "!!!!",
        base64.urlsafe_b64encode(b"\xff").decode("ascii"),
        base64.urlsafe_b64encode(b"not-json").decode("ascii"),
        _history_cursor({}),
        _history_cursor([]),
        _history_cursor(None),
        _history_cursor({"created_at": "yesterday", "id": "job-id"}),
        _history_cursor({"created_at": None, "id": "job-id"}),
        _history_cursor({"created_at": 123, "id": "job-id"}),
        _history_cursor({"created_at": "2026-01-01T00:00:00", "id": None}),
        _history_cursor({"created_at": "2026-01-01T00:00:00", "id": 123}),
        _history_cursor({"created_at": "2026-01-01T00:00:00", "id": ""}),
        _history_cursor({"created_at": "2026-01-01T00:00:00", "id": "job-id"}) + "!",
    ],
)
def test_image_history_rejects_invalid_cursors(client, cursor):
    test_client, queue = client

    response = test_client.get("/v1/images", params={"cursor": cursor})

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid history cursor"}
    assert queue.items == []


@pytest.mark.parametrize("created_at", ["2026-01-01T00:00:00", "2026-01-01T00:00:00+00:00"])
def test_image_history_accepts_supported_cursor_timestamps(client, created_at):
    test_client, _ = client

    response = test_client.get(
        "/v1/images", params={"cursor": _history_cursor({"created_at": created_at, "id": "job-id"})}
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_image_history_paginates_equal_timestamps_without_duplicates(client, session_factory):
    test_client, _ = client
    job_ids = []
    for index in range(5):
        response = test_client.post(
            "/v1/images",
            json={"prompt": f"Studio still life {index}", "aspect_ratio": "1:1", "mode": "photoreal"},
        )
        assert response.status_code == 202
        job_ids.append(response.json()["id"])

    with session_factory() as session:
        for index, job_id in enumerate(job_ids):
            job = session.get(ImageJob, job_id)
            job.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc) - timedelta(days=index // 3)
        session.commit()

    expected_ids = sorted(job_ids[:3], reverse=True) + sorted(job_ids[3:], reverse=True)
    received_ids = []
    cursor = None
    for page in range(3):
        params = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        response = test_client.get("/v1/images", params=params)
        assert response.status_code == 200
        body = response.json()
        received_ids.extend(job["id"] for job in body["items"])
        cursor = body["next_cursor"]
        if page < 2:
            assert cursor is not None
    assert cursor is None
    assert received_ids == expected_ids


def test_create_image_queues_job(client):
    test_client, queue = client

    response = test_client.post(
        "/v1/images",
        json={
            "prompt": "Studio portrait of a chrome teapot in sunlight",
            "negative_prompt": "blurry",
            "aspect_ratio": "1:1",
            "mode": "photoreal",
            "seed": 123,
            "auto_enhance_prompt": False,
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert queue.items == [body["id"]]


def test_result_download_returns_binary(client, session_factory, storage_backend):
    test_client, _ = client
    create_response = test_client.post(
        "/v1/images",
        json={
            "prompt": "Architectural photo of a brutalist library",
            "negative_prompt": "low quality",
            "aspect_ratio": "1:1",
            "mode": "photoreal",
            "seed": 777,
            "auto_enhance_prompt": False,
        },
    )
    job_id = create_response.json()["id"]

    session: Session = session_factory()
    job = session.get(ImageJob, job_id)
    job.status = JobStatus.RUNNING
    job.lease_token = "lease-1"
    session.commit()

    storage_path = "images/test/result.png"
    storage_backend.put_bytes(storage_path, b"png-bytes", "image/png")
    mark_success(
        session,
        job_id,
        "lease-1",
        storage_bucket=None,
        storage_key=storage_path,
        mime_type="image/png",
        generation_params={"model_name": "stub"},
    )
    session.commit()
    session.close()

    result = test_client.get(f"/v1/images/{job_id}/result")
    assert result.status_code == 200
    assert result.headers["content-type"] == "image/png"
    assert result.content == b"png-bytes"


def test_create_image_persists_input_image_metadata(client, session_factory, storage_backend):
    test_client, queue = client
    source = Image.new("RGB", (128, 96), (10, 20, 30))
    buf = BytesIO()
    source.save(buf, format="PNG")

    response = test_client.post(
        "/v1/images",
        json={
            "prompt": "Use this composition as a base",
            "negative_prompt": "blurry",
            "aspect_ratio": "4:5",
            "mode": "photoreal",
            "seed": 123,
            "auto_enhance_prompt": False,
            "input_image_base64": base64.b64encode(buf.getvalue()).decode("utf-8"),
            "input_image_mime_type": "image/png",
            "input_image_strength": 0.55,
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert queue.items == [body["id"]]
    assert body["generation_params"]["input_image_enabled"] is True
    assert body["generation_params"]["input_image_strength"] == 0.55
    assert body["generation_params"]["input_image_key"] == f"images/{body['id']}/input.png"

    stored = storage_backend.get_bytes(f"images/{body['id']}/input.png")
    assert stored.startswith(b"\x89PNG")
