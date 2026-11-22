from __future__ import annotations

import base64
from io import BytesIO

import pytest
from image_platform_shared.database import Base
from image_platform_shared.enums import JobStatus
from image_platform_shared.models import ImageJob
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def session_factory(tmp_path):
    # Separate connections must observe only committed request transactions.
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'jobs.sqlite3'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    engine.dispose()


def image_payload(with_input: bool) -> dict:
    payload = {
        "prompt": "A ceramic bowl in natural light",
        "aspect_ratio": "1:1",
        "mode": "photoreal",
        "seed": 123,
    }
    if with_input:
        image = BytesIO()
        Image.new("RGB", (16, 16), (10, 20, 30)).save(image, format="PNG")
        payload.update(
            input_image_base64=base64.b64encode(image.getvalue()).decode("ascii"),
            input_image_mime_type="image/png",
            input_image_strength=0.55,
        )
    return payload


@pytest.mark.parametrize("retry", [False, True], ids=["create", "retry"])
@pytest.mark.parametrize("with_input", [False, True], ids=["text", "reference"])
def test_enqueued_job_is_committed_with_all_metadata(
    client, session_factory, storage_backend, monkeypatch, retry, with_input
):
    test_client, queue = client
    payload = image_payload(with_input)
    source = None
    if retry:
        response = test_client.post("/v1/images", json=payload)
        assert response.status_code == 202
        source = response.json()
        queue.items.clear()

    observed = []

    def inspect_delivery(job_id):
        with session_factory() as worker_session:
            job = worker_session.get(ImageJob, job_id)
            observed.append(
                None
                if job is None
                else {
                    "id": job.id,
                    "status": job.status,
                    "seed": job.seed,
                    "retried_from_job_id": job.retried_from_job_id,
                    "generation_params": job.generation_params,
                }
            )
        queue.items.append(job_id)

    monkeypatch.setattr(queue, "enqueue", inspect_delivery)
    if retry:
        response = test_client.post(f"/v1/images/{source['id']}/retry", json={"seed_strategy": "same"})
    else:
        response = test_client.post("/v1/images", json=payload)

    assert response.status_code == 202
    body = response.json()
    assert queue.items == [body["id"]]
    assert len(observed) == 1
    delivered = observed[0]
    assert delivered is not None
    assert delivered["id"] == body["id"]
    assert delivered["status"] == JobStatus.QUEUED
    assert delivered["seed"] == 123
    assert delivered["retried_from_job_id"] == (source["id"] if retry else None)
    assert delivered["generation_params"] == body["generation_params"]
    assert delivered["generation_params"]["input_image_enabled"] is with_input
    if with_input:
        input_id = source["id"] if retry else body["id"]
        assert delivered["generation_params"]["input_image_key"] == f"images/{input_id}/input.png"
        assert delivered["generation_params"]["input_image_mime_type"] == "image/png"
        assert delivered["generation_params"]["input_image_strength"] == 0.55
        assert storage_backend.get_bytes(f"images/{input_id}/input.png").startswith(b"\x89PNG")


@pytest.mark.parametrize("retry", [False, True], ids=["create", "retry"])
def test_failed_commit_does_not_deliver_job(client, session_factory, monkeypatch, retry):
    test_client, queue = client
    payload = image_payload(with_input=False)
    source = None
    if retry:
        response = test_client.post("/v1/images", json=payload)
        assert response.status_code == 202
        source = response.json()
        queue.items.clear()

    def fail_commit(session):
        raise RuntimeError("Simulated database commit failure")

    monkeypatch.setattr(session_factory.class_, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="Simulated database commit failure"):
        if retry:
            test_client.post(f"/v1/images/{source['id']}/retry", json={"seed_strategy": "same"})
        else:
            test_client.post("/v1/images", json=payload)

    assert queue.items == []
    with session_factory() as worker_session:
        assert worker_session.scalar(select(func.count()).select_from(ImageJob)) == (1 if retry else 0)
