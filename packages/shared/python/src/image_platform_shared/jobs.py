from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from random import SystemRandom
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, desc, or_, select, update
from sqlalchemy.orm import Session

from image_platform_shared.config import Settings
from image_platform_shared.enums import AspectRatioPreset, GenerationMode, JobStatus, SeedStrategy
from image_platform_shared.models import ImageJob
from image_platform_shared.schemas import CreateImageRequest, ImageJobResponse

ASPECT_RATIO_DIMENSIONS: dict[AspectRatioPreset, tuple[int, int]] = {
    AspectRatioPreset.SQUARE: (1024, 1024),
    AspectRatioPreset.LANDSCAPE: (1152, 648),
    AspectRatioPreset.PORTRAIT: (648, 1152),
    AspectRatioPreset.PORTRAIT_CLASSIC: (1024, 1280),
    AspectRatioPreset.PHOTO: (1152, 768),
}


@dataclass(slots=True)
class ClaimedJob:
    job: ImageJob
    lease_token: str


@dataclass(slots=True)
class ReaperOutcome:
    requeued_job_ids: list[str]
    failed_job_ids: list[str]


_RANDOM = SystemRandom()


class InvalidHistoryCursorError(ValueError):
    """A history cursor cannot be decoded into a timestamp and job ID."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_seed() -> int:
    return _RANDOM.randint(1, 2_147_483_647)


def build_dimensions(aspect_ratio: AspectRatioPreset) -> tuple[int, int]:
    return ASPECT_RATIO_DIMENSIONS[aspect_ratio]


def build_generation_params(
    mode: GenerationMode,
    aspect_ratio: AspectRatioPreset,
    settings: Settings,
) -> dict[str, Any]:
    width, height = build_dimensions(aspect_ratio)
    normalized_mode = GenerationMode.PHOTOREAL
    return {
        "mode": normalized_mode.value,
        "model_id": settings.flux_model_id,
        "num_inference_steps": settings.flux_num_inference_steps,
        "guidance_scale": settings.flux_guidance_scale,
        "torch_dtype": settings.flux_dtype,
        "cpu_offload_enabled": settings.flux_enable_model_cpu_offload,
        "negative_prompt_strategy": "native_negative_prompt",
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio.value,
        "input_image_enabled": False,
        "input_image_key": None,
        "input_image_mime_type": None,
        "input_image_strength": None,
    }


def with_input_image(
    generation_params: dict[str, Any],
    *,
    input_image_key: str | None,
    input_image_mime_type: str | None,
    input_image_strength: float | None,
) -> dict[str, Any]:
    next_params = dict(generation_params)
    next_params.update(
        {
            "input_image_enabled": bool(input_image_key),
            "input_image_key": input_image_key,
            "input_image_mime_type": input_image_mime_type,
            "input_image_strength": input_image_strength,
        }
    )
    return next_params


def _encode_cursor(job: ImageJob) -> str:
    payload = {"created_at": job.created_at.isoformat(), "id": job.id}
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        decoded = base64.b64decode(cursor.encode("ascii"), altchars=b"-_", validate=True)
        payload = json.loads(decoded.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Expected an object")
        created_at, job_id = payload.get("created_at"), payload.get("id")
        if not isinstance(created_at, str) or not isinstance(job_id, str) or not job_id:
            raise ValueError("Expected a timestamp and job ID")
        return datetime.fromisoformat(created_at), job_id
    except ValueError as exc:
        raise InvalidHistoryCursorError("Invalid history cursor") from exc


def serialize_job(job: ImageJob, settings: Settings) -> ImageJobResponse:
    result_url = None
    if job.storage_key and job.status == JobStatus.SUCCEEDED:
        result_url = f"{settings.public_api_base_url}/v1/images/{job.id}/result"
    return ImageJobResponse(
        id=job.id,
        status=JobStatus(job.status),
        prompt_original=job.prompt_original,
        prompt_final=job.prompt_final,
        negative_prompt=job.negative_prompt,
        aspect_ratio=AspectRatioPreset(job.aspect_ratio),
        width=job.width,
        height=job.height,
        mode=GenerationMode(job.mode),
        seed=job.seed,
        auto_enhance_prompt=job.auto_enhance_prompt,
        progress_percent=job.progress_percent,
        progress_stage=job.progress_stage,
        generation_params=job.generation_params,
        result_url=result_url,
        storage_bucket=job.storage_bucket,
        storage_key=job.storage_key,
        mime_type=job.mime_type,
        heartbeat_at=job.heartbeat_at,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        worker_id=job.worker_id,
        error_code=job.error_code,
        error_message=job.error_message,
        retried_from_job_id=job.retried_from_job_id,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        updated_at=job.updated_at,
    )


def create_job(
    session: Session,
    request: CreateImageRequest,
    settings: Settings,
    *,
    retried_from_job_id: str | None = None,
    seed: int | None = None,
) -> ImageJob:
    width, height = build_dimensions(request.aspect_ratio)
    final_seed = seed if seed is not None else request.seed if request.seed is not None else generate_seed()
    normalized_mode = GenerationMode.PHOTOREAL
    job = ImageJob(
        id=str(uuid4()),
        status=JobStatus.QUEUED,
        prompt_original=request.prompt,
        prompt_final=request.prompt,
        negative_prompt=request.negative_prompt,
        aspect_ratio=request.aspect_ratio.value,
        width=width,
        height=height,
        mode=normalized_mode.value,
        seed=final_seed,
        auto_enhance_prompt=request.auto_enhance_prompt,
        progress_percent=0,
        progress_stage=JobStatus.QUEUED,
        generation_params=build_generation_params(normalized_mode, request.aspect_ratio, settings),
        max_attempts=settings.max_attempts,
        retried_from_job_id=retried_from_job_id,
    )
    session.add(job)
    session.flush()
    session.refresh(job)
    return job


def get_job(session: Session, job_id: str) -> ImageJob | None:
    return session.get(ImageJob, job_id)


def list_jobs(
    session: Session, settings: Settings, limit: int = 20, cursor: str | None = None
) -> tuple[list[ImageJobResponse], str | None]:
    stmt = select(ImageJob).order_by(desc(ImageJob.created_at), desc(ImageJob.id)).limit(limit + 1)
    if cursor is not None:
        created_at, job_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                ImageJob.created_at < created_at,
                and_(ImageJob.created_at == created_at, ImageJob.id < job_id),
            )
        )
    jobs = list(session.execute(stmt).scalars())
    next_cursor = None
    if len(jobs) > limit:
        next_cursor = _encode_cursor(jobs[limit - 1])
        jobs = jobs[:limit]
    return [serialize_job(job, settings) for job in jobs], next_cursor


def retry_job(session: Session, source_job: ImageJob, seed_strategy: SeedStrategy, settings: Settings) -> ImageJob:
    seed = source_job.seed if seed_strategy == SeedStrategy.SAME else generate_seed()
    request = CreateImageRequest(
        prompt=source_job.prompt_original,
        negative_prompt=source_job.negative_prompt,
        aspect_ratio=AspectRatioPreset(source_job.aspect_ratio),
        mode=GenerationMode.PHOTOREAL,
        seed=seed,
        auto_enhance_prompt=source_job.auto_enhance_prompt,
    )
    retried = create_job(session, request, settings, retried_from_job_id=source_job.id, seed=seed)
    retried.generation_params = with_input_image(
        retried.generation_params,
        input_image_key=source_job.generation_params.get("input_image_key"),
        input_image_mime_type=source_job.generation_params.get("input_image_mime_type"),
        input_image_strength=source_job.generation_params.get("input_image_strength"),
    )
    session.flush()
    session.refresh(retried)
    return retried


def claim_job(session: Session, job_id: str, worker_id: str) -> ClaimedJob | None:
    lease_token = uuid4().hex
    now = utc_now()
    stmt = (
        update(ImageJob)
        .where(
            ImageJob.id == job_id,
            ImageJob.status == JobStatus.QUEUED,
            ImageJob.attempt_count < ImageJob.max_attempts,
        )
        .values(
            status=JobStatus.RUNNING,
            attempt_count=ImageJob.attempt_count + 1,
            lease_token=lease_token,
            worker_id=worker_id,
            heartbeat_at=now,
            last_progress_at=now,
            started_at=now,
            finished_at=None,
            error_code=None,
            error_message=None,
            progress_percent=1,
            progress_stage="starting",
        )
    )
    result = session.execute(stmt)
    if result.rowcount == 0:
        return None
    session.flush()
    job = get_job(session, job_id)
    if job is None:
        return None
    return ClaimedJob(job=job, lease_token=lease_token)


def update_prompt_final(session: Session, job_id: str, lease_token: str, prompt_final: str) -> bool:
    result = session.execute(
        update(ImageJob)
        .where(ImageJob.id == job_id, ImageJob.lease_token == lease_token, ImageJob.status == JobStatus.RUNNING)
        .values(prompt_final=prompt_final, heartbeat_at=utc_now())
    )
    return result.rowcount > 0


def update_heartbeat(session: Session, job_id: str, lease_token: str) -> bool:
    result = session.execute(
        update(ImageJob)
        .where(ImageJob.id == job_id, ImageJob.lease_token == lease_token, ImageJob.status == JobStatus.RUNNING)
        .values(heartbeat_at=utc_now())
    )
    return result.rowcount > 0


def update_progress(session: Session, job_id: str, lease_token: str, percent: int, stage: str) -> bool:
    job = get_job(session, job_id)
    if job is None or job.lease_token != lease_token or job.status != JobStatus.RUNNING:
        return False

    values: dict[str, Any] = {
        "progress_percent": percent,
        "progress_stage": stage,
        "heartbeat_at": utc_now(),
    }
    if job.progress_percent != percent or job.progress_stage != stage:
        values["last_progress_at"] = utc_now()

    result = session.execute(
        update(ImageJob)
        .where(ImageJob.id == job_id, ImageJob.lease_token == lease_token, ImageJob.status == JobStatus.RUNNING)
        .values(**values)
    )
    return result.rowcount > 0


def mark_success(
    session: Session,
    job_id: str,
    lease_token: str,
    *,
    storage_bucket: str | None,
    storage_key: str,
    mime_type: str,
    generation_params: dict[str, Any],
) -> bool:
    result = session.execute(
        update(ImageJob)
        .where(ImageJob.id == job_id, ImageJob.lease_token == lease_token, ImageJob.status == JobStatus.RUNNING)
        .values(
            status=JobStatus.SUCCEEDED,
            storage_bucket=storage_bucket,
            storage_key=storage_key,
            mime_type=mime_type,
            generation_params=generation_params,
            progress_percent=100,
            progress_stage="completed",
            heartbeat_at=utc_now(),
            last_progress_at=utc_now(),
            finished_at=utc_now(),
        )
    )
    return result.rowcount > 0


def mark_failure(session: Session, job_id: str, lease_token: str, *, error_code: str, error_message: str) -> bool:
    result = session.execute(
        update(ImageJob)
        .where(ImageJob.id == job_id, ImageJob.lease_token == lease_token, ImageJob.status == JobStatus.RUNNING)
        .values(
            status=JobStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
            progress_stage="failed",
            heartbeat_at=utc_now(),
            last_progress_at=utc_now(),
            finished_at=utc_now(),
        )
    )
    return result.rowcount > 0


def requeue_stale_jobs(session: Session, settings: Settings) -> ReaperOutcome:
    now = utc_now()
    heartbeat_cutoff = datetime.fromtimestamp(now.timestamp() - settings.heartbeat_timeout_seconds, tz=timezone.utc)
    progress_cutoff = datetime.fromtimestamp(now.timestamp() - settings.progress_timeout_seconds, tz=timezone.utc)
    running_jobs = list(session.execute(select(ImageJob).where(ImageJob.status == JobStatus.RUNNING)).scalars())
    requeued: list[str] = []
    failed: list[str] = []
    for job in running_jobs:
        stale_reason: str | None = None
        stale_message: str | None = None
        if job.heartbeat_at is None or job.heartbeat_at < heartbeat_cutoff:
            stale_reason = "heartbeat_timeout"
            stale_message = "Job exceeded the heartbeat timeout."
        elif job.last_progress_at is None or job.last_progress_at < progress_cutoff:
            stale_reason = "progress_timeout"
            stale_message = "Job stopped making progress before completion."

        if stale_reason is None or stale_message is None:
            continue

        if job.attempt_count < job.max_attempts:
            session.execute(
                update(ImageJob)
                .where(ImageJob.id == job.id, ImageJob.lease_token == job.lease_token)
                .values(
                    status=JobStatus.QUEUED,
                    lease_token=None,
                    worker_id=None,
                    heartbeat_at=None,
                    last_progress_at=None,
                    progress_percent=0,
                    progress_stage="queued",
                    error_code=None,
                    error_message=None,
                    started_at=None,
                )
            )
            requeued.append(job.id)
        else:
            session.execute(
                update(ImageJob)
                .where(ImageJob.id == job.id, ImageJob.lease_token == job.lease_token)
                .values(
                    status=JobStatus.FAILED,
                    error_code=stale_reason,
                    error_message=f"{stale_message} The job exhausted all attempts.",
                    progress_stage="failed",
                    finished_at=now,
                )
            )
            failed.append(job.id)
    return ReaperOutcome(requeued_job_ids=requeued, failed_job_ids=failed)
