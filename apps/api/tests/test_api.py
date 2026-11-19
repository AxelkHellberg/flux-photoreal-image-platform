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


@pytest.mark.parametrize("image_format,mime_type", [("PNG", "image/png"), ("JPEG", "image/jpeg")])
@pytest.mark.parametrize("explicit_mime_type", [None, "image/explicit-override"])
def test_create_image_accepts_data_url_with_optional_mime_type(
    client, storage_backend, settings, image_format, mime_type, explicit_mime_type
):
    test_client, queue = client
    source = Image.new("RGB", (12, 8), (10, 20, 30))
    buf = BytesIO()
    source.save(buf, format=image_format)
    payload = {
        "prompt": "Use the reference image composition",
        "aspect_ratio": "1:1",
        "mode": "photoreal",
        "input_image_base64": f"data:{mime_type};base64,{base64.b64encode(buf.getvalue()).decode('ascii')}",
    }
    if explicit_mime_type is not None:
        payload["input_image_mime_type"] = explicit_mime_type

    response = test_client.post("/v1/images", json=payload)

    assert response.status_code == 202
    body = response.json()
    assert queue.items == [body["id"]]
    params = body["generation_params"]
    assert params["input_image_enabled"] is True
    assert params["input_image_mime_type"] == "image/png"
    assert params["input_image_strength"] == settings.flux_input_image_strength
    stored = storage_backend.get_bytes(params["input_image_key"])
    with Image.open(BytesIO(stored)) as normalized:
        assert normalized.format == "PNG"
        assert normalized.mode == "RGB"
        assert normalized.size == (12, 8)


@pytest.mark.parametrize(
    "image_payload,detail",
    [
        (
            {"input_image_base64": "aW1hZ2U="},
            "input_image_mime_type is required when input_image_base64 is provided",
        ),
        (
            {"input_image_base64": "data:;base64,aW1hZ2U="},
            "input_image_mime_type is required when input_image_base64 is provided",
        ),
        (
            {"input_image_base64": "data:image/png;base64", "input_image_mime_type": "image/png"},
            "Malformed input image data URL",
        ),
        (
            {"input_image_base64": "data:image/png;base64,%%%"},
            "input_image_base64 is not valid base64",
        ),
    ],
)
def test_create_image_rejects_incomplete_or_invalid_data_url(client, image_payload, detail):
    test_client, queue = client

    response = test_client.post(
        "/v1/images",
        json={"prompt": "Use the reference image", "aspect_ratio": "1:1", "mode": "photoreal", **image_payload},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert queue.items == []
