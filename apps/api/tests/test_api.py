from __future__ import annotations

import base64
from io import BytesIO

import pytest
from image_platform_shared.enums import JobStatus
from image_platform_shared.jobs import mark_success
from image_platform_shared.models import ImageJob
from PIL import Image
from sqlalchemy.orm import Session


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


@pytest.mark.parametrize("object_exists", [True, False])
def test_result_download_handles_stored_and_missing_objects(client, session_factory, storage_backend, object_exists):
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
    if object_exists:
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
    if object_exists:
        assert result.status_code == 200
        assert result.headers["content-type"] == "image/png"
        assert result.content == b"png-bytes"
    else:
        assert result.status_code == 404
        assert result.json() == {"detail": "Result file not found"}


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
