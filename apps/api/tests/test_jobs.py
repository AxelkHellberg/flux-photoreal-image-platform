from __future__ import annotations

from datetime import timedelta

from image_platform_shared.config import Settings
from image_platform_shared.database import Base
from image_platform_shared.enums import AspectRatioPreset, GenerationMode, JobStatus, SeedStrategy
from image_platform_shared.jobs import (
    build_generation_params,
    claim_job,
    create_job,
    generate_seed,
    mark_success,
    requeue_stale_jobs,
    retry_job,
    serialize_job,
    utc_now,
    with_input_image,
)
from image_platform_shared.models import ImageJob
from image_platform_shared.schemas import CreateImageRequest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def build_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()


def build_settings() -> Settings:
    return Settings(database_url="sqlite+pysqlite:///:memory:", public_api_base_url="http://localhost:8000")


def test_retry_preserves_or_regenerates_seed():
    session = build_session()
    settings = build_settings()
    original = create_job(
        session,
        CreateImageRequest(
            prompt="A concrete staircase in fog",
            negative_prompt="blurry",
            aspect_ratio=AspectRatioPreset.SQUARE,
            mode=GenerationMode.PHOTOREAL,
            seed=1234,
            auto_enhance_prompt=False,
        ),
        settings,
    )
    session.commit()

    same_seed_job = retry_job(session, original, SeedStrategy.SAME, settings)
    new_seed_job = retry_job(session, original, SeedStrategy.NEW, settings)

    assert same_seed_job.seed == 1234
    assert new_seed_job.seed != 1234


def test_retry_preserves_input_image_metadata():
    session = build_session()
    settings = build_settings()
    original = create_job(
        session,
        CreateImageRequest(
            prompt="Reference-driven portrait",
            negative_prompt="artifact",
            aspect_ratio=AspectRatioPreset.PORTRAIT_CLASSIC,
            mode=GenerationMode.PHOTOREAL,
            seed=4321,
            auto_enhance_prompt=False,
        ),
        settings,
    )
    original.generation_params = with_input_image(
        original.generation_params,
        input_image_key=f"images/{original.id}/input.png",
        input_image_mime_type="image/png",
        input_image_strength=0.55,
    )
    session.commit()

    retried = retry_job(session, original, SeedStrategy.SAME, settings)

    assert retried.generation_params["input_image_enabled"] is True
    assert retried.generation_params["input_image_key"] == f"images/{original.id}/input.png"
    assert retried.generation_params["input_image_mime_type"] == "image/png"
    assert retried.generation_params["input_image_strength"] == 0.55


def test_claim_and_mark_success_are_lease_bound():
    session = build_session()
    settings = build_settings()
    job = create_job(
        session,
        CreateImageRequest(
            prompt="Editorial portrait with dramatic shadows",
            negative_prompt="artifact",
            aspect_ratio=AspectRatioPreset.LANDSCAPE,
            mode=GenerationMode.PHOTOREAL,
            seed=999,
            auto_enhance_prompt=False,
        ),
        settings,
    )
    session.commit()

    claimed = claim_job(session, job.id, "worker-a")
    session.commit()
    assert claimed is not None
    assert claimed.job.attempt_count == 1

    updated = mark_success(
        session,
        job.id,
        claimed.lease_token,
        storage_bucket="bucket",
        storage_key="images/job.png",
        mime_type="image/png",
        generation_params={"model_name": "stub"},
    )
    session.commit()

    assert updated is True
    refreshed = session.get(ImageJob, job.id)
    assert refreshed.status == JobStatus.SUCCEEDED
    assert serialize_job(refreshed, settings).result_url == f"{settings.public_api_base_url}/v1/images/{job.id}/result"


def test_reaper_requeues_and_fails_exhausted_jobs():
    session = build_session()
    settings = build_settings()

    requeue_job = create_job(
        session,
        CreateImageRequest(
            prompt="A copper lamp in a dark room",
            negative_prompt="noise",
            aspect_ratio=AspectRatioPreset.SQUARE,
            mode=GenerationMode.PHOTOREAL,
            seed=generate_seed(),
            auto_enhance_prompt=False,
        ),
        settings,
    )
    fail_job = create_job(
        session,
        CreateImageRequest(
            prompt="Minimal ceramic vase",
            negative_prompt="broken geometry",
            aspect_ratio=AspectRatioPreset.PORTRAIT,
            mode=GenerationMode.PHOTOREAL,
            seed=generate_seed(),
            auto_enhance_prompt=False,
        ),
        settings,
    )
    session.commit()

    claim_job(session, requeue_job.id, "worker-a")
    claim_job(session, fail_job.id, "worker-b")
    session.commit()

    session.get(ImageJob, requeue_job.id).heartbeat_at = utc_now() - timedelta(seconds=90)
    failing = session.get(ImageJob, fail_job.id)
    failing.heartbeat_at = utc_now() - timedelta(seconds=90)
    failing.attempt_count = failing.max_attempts
    session.commit()

    outcome = requeue_stale_jobs(session, settings)
    session.commit()

    assert requeue_job.id in outcome.requeued_job_ids
    assert fail_job.id in outcome.failed_job_ids
    assert session.get(ImageJob, requeue_job.id).status == JobStatus.QUEUED
    assert session.get(ImageJob, fail_job.id).status == JobStatus.FAILED


def test_reaper_requeues_jobs_with_stale_progress_even_if_heartbeat_is_fresh():
    session = build_session()
    settings = build_settings().model_copy(update={"progress_timeout_seconds": 30, "heartbeat_timeout_seconds": 300})
    job = create_job(
        session,
        CreateImageRequest(
            prompt="A fashion portrait under harsh sun",
            negative_prompt="artifact",
            aspect_ratio=AspectRatioPreset.SQUARE,
            mode=GenerationMode.PHOTOREAL,
            seed=generate_seed(),
            auto_enhance_prompt=False,
        ),
        settings,
    )
    session.commit()

    claimed = claim_job(session, job.id, "worker-a")
    session.commit()
    assert claimed is not None

    running = session.get(ImageJob, job.id)
    running.heartbeat_at = utc_now()
    running.last_progress_at = utc_now() - timedelta(seconds=90)
    session.commit()

    outcome = requeue_stale_jobs(session, settings)
    session.commit()

    assert outcome.requeued_job_ids == [job.id]
    refreshed = session.get(ImageJob, job.id)
    assert refreshed.status == JobStatus.QUEUED
    assert refreshed.last_progress_at is None


def test_generation_params_use_flux_defaults_for_all_public_ratios():
    settings = build_settings()

    square = build_generation_params(GenerationMode.PHOTOREAL, AspectRatioPreset.SQUARE, settings)
    portrait_classic = build_generation_params(GenerationMode.PHOTOREAL, AspectRatioPreset.PORTRAIT_CLASSIC, settings)
    photo = build_generation_params(GenerationMode.PHOTOREAL, AspectRatioPreset.PHOTO, settings)

    assert square["mode"] == "photoreal"
    assert square["model_id"] == settings.flux_model_id
    assert square["num_inference_steps"] == settings.flux_num_inference_steps
    assert square["guidance_scale"] == settings.flux_guidance_scale
    assert square["width"] == 1024
    assert square["height"] == 1024

    assert portrait_classic["width"] == 1024
    assert portrait_classic["height"] == 1280
    assert portrait_classic["aspect_ratio"] == "4:5"

    assert photo["width"] == 1152
    assert photo["height"] == 768
    assert photo["aspect_ratio"] == "3:2"
