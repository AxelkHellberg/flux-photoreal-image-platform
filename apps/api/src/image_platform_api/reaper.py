from __future__ import annotations

import time

from image_platform_shared.config import get_settings
from image_platform_shared.database import session_scope
from image_platform_shared.jobs import requeue_stale_jobs
from image_platform_shared.logging import configure_logging, get_logger
from image_platform_shared.queue import ImageJobQueue

logger = get_logger(__name__)


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    queue = ImageJobQueue(settings.redis_url, settings.redis_queue_name)
    logger.info("reaper.starting", interval_seconds=settings.reaper_interval_seconds)

    while True:
        with session_scope() as session:
            outcome = requeue_stale_jobs(session, settings)
        for job_id in outcome.requeued_job_ids:
            queue.enqueue(job_id)
        if outcome.requeued_job_ids or outcome.failed_job_ids:
            logger.info(
                "reaper.cycle",
                requeued_job_ids=outcome.requeued_job_ids,
                failed_job_ids=outcome.failed_job_ids,
            )
        time.sleep(settings.reaper_interval_seconds)


if __name__ == "__main__":
    main()
