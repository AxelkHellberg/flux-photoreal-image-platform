from __future__ import annotations

import base64
from io import BytesIO

import pytest
from image_platform_shared.enums import JobStatus
from image_platform_shared.jobs import mark_success
from image_platform_shared.models import ImageJob
from PIL import Image
from sqlalchemy.orm import Session


@pytest.mark.parametrize("seed", [-(2**63) - 1, 2**63])
def test_create_image_rejects_seed_outside_storage_range(client, session_factory, seed):
    test_client, queue = client
    response = test_client.post(
        "/v1/images",
        json={"prompt": "Seed boundary fixture", "aspect_ratio": "1:1", "mode": "photoreal", "seed": seed},
    )

    assert response.status_code == 422
    assert any(error["loc"] == ["body", "seed"] for error in response.json()["detail"])
    assert queue.items == []
    with session_factory() as session:
        assert session.query(ImageJob).count() == 0


@pytest.mark.parametrize("seed", [-(2**63), -1, 0, 1, 2**63 - 1])
def test_create_image_preserves_supported_seed(client, session_factory, seed):
    test_client, queue = client
    response = test_client.post(
        "/v1/images",
        json={"prompt": "Seed boundary fixture", "aspect_ratio": "1:1", "mode": "photoreal", "seed": seed},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["seed"] == seed
    assert queue.items == [body["id"]]
    with session_factory() as session:
        assert session.get(ImageJob, body["id"]).seed == seed


@pytest.mark.parametrize("seed_payload", [{}, {"seed": None}])
def test_create_image_generates_seed_when_unspecified(client, seed_payload):
    test_client, queue = client
    response = test_client.post(
        "/v1/images",
        json={"prompt": "Random seed fixture", "aspect_ratio": "1:1", "mode": "photoreal", **seed_payload},
    )

    assert response.status_code == 202
    body = response.json()
    assert 1 <= body["seed"] <= 2_147_483_647
    assert queue.items == [body["id"]]


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
