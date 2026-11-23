from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import Mock

import pytest
from image_platform_shared.config import Settings
from image_platform_shared.database import Base
from image_platform_shared.enums import AspectRatioPreset, GenerationMode, JobStatus
from image_platform_shared.generators.base import GenerationResult
from image_platform_shared.generators.flux import FluxImageGeneratorAdapter
from image_platform_shared.generators.stub import StubImageGeneratorAdapter
from image_platform_shared.jobs import claim_job, create_job, mark_success, update_progress
from image_platform_shared.schemas import CreateImageRequest
from image_platform_shared.storage import LocalFilesystemStorageBackend
from image_platform_worker import main as worker_main
from image_platform_worker.main import build_generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def build_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()


def test_stub_generator_returns_png_bytes():
    generator = StubImageGeneratorAdapter()
    result = generator.generate(
        request=type(
            "Req",
            (),
            {
                "job_id": "job-1",
                "prompt": "Art deco lobby in amber light",
                "negative_prompt": "",
                "width": 512,
                "height": 512,
                "seed": 5,
                "mode": GenerationMode.PHOTOREAL,
                "generation_params": {},
            },
        )(),
    )
    assert result.mime_type == "image/png"
    assert result.image_bytes.startswith(b"\x89PNG")


def test_stale_lease_cannot_mark_success():
    session = build_session()
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    job = create_job(
        session,
        CreateImageRequest(
            prompt="A modular chair in a gallery",
            negative_prompt="",
            aspect_ratio=AspectRatioPreset.SQUARE,
            mode=GenerationMode.PHOTOREAL,
            seed=12,
            auto_enhance_prompt=False,
        ),
        settings,
    )
    session.commit()

    claimed = claim_job(session, job.id, "worker-a")
    session.commit()
    assert claimed is not None

    session.query(type(job)).filter_by(id=job.id).update({"lease_token": None, "status": JobStatus.QUEUED})
    session.commit()

    updated = mark_success(
        session,
        job.id,
        claimed.lease_token,
        storage_bucket="bucket",
        storage_key="images/job.png",
        mime_type="image/png",
        generation_params={"model_name": "stub"},
    )
    assert updated is False


def test_progress_update_requires_matching_lease():
    session = build_session()
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    job = create_job(
        session,
        CreateImageRequest(
            prompt="A steel bridge under pink dusk",
            negative_prompt="",
            aspect_ratio=AspectRatioPreset.LANDSCAPE,
            mode=GenerationMode.PHOTOREAL,
            seed=44,
            auto_enhance_prompt=False,
        ),
        settings,
    )
    session.commit()

    claimed = claim_job(session, job.id, "worker-a")
    session.commit()

    assert update_progress(session, job.id, claimed.lease_token, 50, "generating") is True
    assert update_progress(session, job.id, "wrong-lease", 80, "generating") is False


@pytest.mark.parametrize("stale_finishes_last", [True, False])
def test_stale_attempt_cannot_replace_successful_result(tmp_path, monkeypatch, stale_finishes_last):
    session = build_session()
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    job = create_job(
        session,
        CreateImageRequest(
            prompt="A ceramic bowl in soft daylight",
            aspect_ratio=AspectRatioPreset.SQUARE,
            mode=GenerationMode.PHOTOREAL,
            seed=52,
        ),
        settings,
    )
    session.commit()
    stale_claim = claim_job(session, job.id, "worker-old")
    session.commit()
    assert stale_claim is not None

    session.query(type(job)).filter_by(id=job.id).update({"lease_token": None, "status": JobStatus.QUEUED})
    current_claim = claim_job(session, job.id, "worker-current")
    session.commit()
    assert current_claim is not None

    storage = LocalFilesystemStorageBackend(str(tmp_path / "storage"))
    storage.ensure_ready()
    monkeypatch.setattr(worker_main, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_main, "session_scope", lambda: nullcontext(session))
    monkeypatch.setattr(worker_main, "HeartbeatThread", Mock())

    attempts = [(current_claim, b"winning-result"), (stale_claim, b"stale-result")]
    if not stale_finishes_last:
        attempts.reverse()
    for claim, image_bytes in attempts:
        generator = Mock()
        generator.generate.return_value = GenerationResult(
            image_bytes=image_bytes, mime_type="image/png", metadata={}
        )
        worker_main.process_job(claim, generator=generator, storage=storage, enhancer=None)
        session.commit()

    session.refresh(job)
    assert job.status == JobStatus.SUCCEEDED
    assert job.lease_token == current_claim.lease_token
    assert storage.get_bytes(job.storage_key) == b"winning-result"


def test_progress_update_refreshes_last_progress_only_when_marker_changes():
    session = build_session()
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    job = create_job(
        session,
        CreateImageRequest(
            prompt="A quiet library with oak shelves",
            negative_prompt="",
            aspect_ratio=AspectRatioPreset.SQUARE,
            mode=GenerationMode.PHOTOREAL,
            seed=77,
            auto_enhance_prompt=False,
        ),
        settings,
    )
    session.commit()

    claimed = claim_job(session, job.id, "worker-a")
    session.commit()
    first_progress_at = session.get(type(job), job.id).last_progress_at

    assert update_progress(session, job.id, claimed.lease_token, 50, "generating") is True
    session.commit()
    second_progress_at = session.get(type(job), job.id).last_progress_at
    assert second_progress_at is not None
    assert second_progress_at >= first_progress_at

    assert update_progress(session, job.id, claimed.lease_token, 50, "generating") is True
    session.commit()
    third_progress_at = session.get(type(job), job.id).last_progress_at
    assert third_progress_at == second_progress_at


def test_build_generator_selects_flux_backend(monkeypatch):
    monkeypatch.setattr(FluxImageGeneratorAdapter, "prepare", lambda self: None)
    settings = Settings(image_generator_backend="flux", hf_token="hf_test")

    generator = build_generator(settings)

    assert isinstance(generator, FluxImageGeneratorAdapter)


def test_build_generator_selects_stub_backend():
    settings = Settings(image_generator_backend="stub")

    generator = build_generator(settings)

    assert isinstance(generator, StubImageGeneratorAdapter)
