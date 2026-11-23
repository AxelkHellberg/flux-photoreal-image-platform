from __future__ import annotations

import threading

from image_platform_shared.config import get_settings
from image_platform_shared.database import session_scope
from image_platform_shared.enums import GenerationMode, GeneratorBackendType
from image_platform_shared.generators import FluxImageGeneratorAdapter, StubImageGeneratorAdapter
from image_platform_shared.generators.base import GenerationRequest
from image_platform_shared.jobs import (
    ClaimedJob,
    claim_job,
    mark_failure,
    mark_success,
    update_heartbeat,
    update_progress,
    update_prompt_final,
)
from image_platform_shared.logging import configure_logging, get_logger
from image_platform_shared.prompt_enhancers import create_prompt_enhancer
from image_platform_shared.queue import ImageJobQueue
from image_platform_shared.storage import create_storage_backend

logger = get_logger(__name__)


class LeaseLostError(RuntimeError):
    pass


class HeartbeatThread(threading.Thread):
    def __init__(self, *, job_id: str, lease_token: str, interval_seconds: int):
        super().__init__(daemon=True)
        self.job_id = job_id
        self.lease_token = lease_token
        self.interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self.lost_lease = False

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            with session_scope() as session:
                updated = update_heartbeat(session, self.job_id, self.lease_token)
            if not updated:
                self.lost_lease = True
                return


def build_generator(settings):
    backend = GeneratorBackendType(settings.image_generator_backend)
    if backend == GeneratorBackendType.FLUX:
        adapter = FluxImageGeneratorAdapter(settings)
    else:
        adapter = StubImageGeneratorAdapter()
    adapter.prepare()
    return adapter


def process_job(claimed: ClaimedJob, generator, storage, enhancer) -> None:
    settings = get_settings()
    heartbeat = HeartbeatThread(
        job_id=claimed.job.id,
        lease_token=claimed.lease_token,
        interval_seconds=settings.heartbeat_interval_seconds,
    )
    heartbeat.start()
    prompt_final = claimed.job.prompt_final

    def on_progress(percent: int, stage: str) -> None:
        with session_scope() as session:
            updated = update_progress(session, claimed.job.id, claimed.lease_token, percent, stage)
        if not updated:
            raise LeaseLostError(f"Lease was lost while updating progress for job {claimed.job.id}")

    try:
        if claimed.job.auto_enhance_prompt and settings.enable_prompt_enhancer:
            prompt_final = enhancer.enhance(claimed.job.prompt_original, claimed.job.negative_prompt)
            with session_scope() as session:
                updated = update_prompt_final(session, claimed.job.id, claimed.lease_token, prompt_final)
            if not updated:
                raise LeaseLostError(f"Lease was lost while updating prompt for job {claimed.job.id}")

        input_image_key = claimed.job.generation_params.get("input_image_key")
        input_image_bytes = None
        input_image_mime_type = None
        input_image_strength = None
        if input_image_key:
            input_image_bytes = storage.get_bytes(input_image_key)
            input_image_mime_type = claimed.job.generation_params.get("input_image_mime_type", "image/png")
            raw_strength = claimed.job.generation_params.get("input_image_strength")
            if raw_strength is not None:
                input_image_strength = float(raw_strength)

        request = GenerationRequest(
            job_id=claimed.job.id,
            prompt=prompt_final,
            negative_prompt=claimed.job.negative_prompt,
            width=claimed.job.width,
            height=claimed.job.height,
            seed=claimed.job.seed,
            mode=GenerationMode(claimed.job.mode),
            generation_params=claimed.job.generation_params,
            input_image_bytes=input_image_bytes,
            input_image_mime_type=input_image_mime_type,
            input_image_strength=input_image_strength,
        )
        result = generator.generate(request, on_progress=on_progress)
        storage_key = f"images/{claimed.job.id}/attempts/{claimed.lease_token}/result.png"
        storage.put_bytes(storage_key, result.image_bytes, result.mime_type)
        with session_scope() as session:
            updated = mark_success(
                session,
                claimed.job.id,
                claimed.lease_token,
                storage_bucket=storage.bucket_name,
                storage_key=storage_key,
                mime_type=result.mime_type,
                generation_params={**claimed.job.generation_params, **result.metadata},
            )
        if not updated:
            raise LeaseLostError(f"Lease was lost before marking success for job {claimed.job.id}")
        logger.info(
            "worker.job_succeeded",
            job_id=claimed.job.id,
            worker_id=settings.worker_id,
            lease_token=claimed.lease_token,
        )
    except LeaseLostError as exc:
        logger.warning("worker.lease_lost", job_id=claimed.job.id, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("worker.job_failed", job_id=claimed.job.id, error=str(exc))
        with session_scope() as session:
            mark_failure(
                session,
                claimed.job.id,
                claimed.lease_token,
                error_code="generation_failed",
                error_message=str(exc),
            )
    finally:
        heartbeat.stop()
        heartbeat.join(timeout=1)


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    queue = ImageJobQueue(settings.redis_url, settings.redis_queue_name)
    storage = create_storage_backend(settings)
    storage.ensure_ready()
    enhancer = create_prompt_enhancer(settings)
    generator = build_generator(settings)

    logger.info(
        "worker.starting",
        worker_id=settings.worker_id,
        generator_backend=settings.image_generator_backend,
        queue_name=settings.redis_queue_name,
    )

    try:
        while True:
            job_id = queue.blocking_pop(settings.worker_poll_timeout_seconds)
            if job_id is None:
                continue
            with session_scope() as session:
                claimed = claim_job(session, job_id, settings.worker_id)
            if claimed is None:
                logger.info("worker.job_skipped", job_id=job_id, reason="not_claimable")
                continue
            process_job(claimed, generator=generator, storage=storage, enhancer=enhancer)
    except KeyboardInterrupt:
        logger.info("worker.stopping", worker_id=settings.worker_id)
    finally:
        queue.close()


if __name__ == "__main__":
    main()
