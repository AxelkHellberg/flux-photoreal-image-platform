from __future__ import annotations

from datetime import timedelta

import pytest
from image_platform_shared.config import Settings
from image_platform_shared.enums import JobStatus
from image_platform_shared.jobs import claim_job, create_job, requeue_stale_jobs, utc_now
from image_platform_shared.schemas import CreateImageRequest
from pydantic import ValidationError


@pytest.mark.parametrize("value", [0, -1])
def test_settings_reject_nonpositive_attempt_limits(value):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, max_attempts=value)

    assert error.value.errors()[0]["loc"] == ("max_attempts",)
    assert error.value.errors()[0]["type"] == "greater_than_equal"


@pytest.mark.parametrize("value", ["0", "-1"])
def test_settings_reject_nonpositive_attempt_limits_from_environment(monkeypatch, value):
    monkeypatch.setenv("MAX_ATTEMPTS", value)

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)

    assert error.value.errors()[0]["loc"] == ("max_attempts",)


def test_settings_keep_default_attempt_limit(monkeypatch):
    monkeypatch.delenv("MAX_ATTEMPTS", raising=False)

    assert Settings(_env_file=None).max_attempts == 3


@pytest.mark.parametrize("value", [1, 3])
def test_settings_accept_positive_attempt_limits(monkeypatch, value):
    monkeypatch.setenv("MAX_ATTEMPTS", str(value))

    assert Settings(_env_file=None).max_attempts == value
    assert Settings(_env_file=None, max_attempts=value).max_attempts == value


def test_one_attempt_job_can_run_and_fail_without_requeue(session_factory):
    settings = Settings(_env_file=None, max_attempts=1)
    with session_factory() as session:
        job = create_job(
            session,
            CreateImageRequest(prompt="Offline test image", aspect_ratio="1:1", mode="photoreal"),
            settings,
        )
        session.commit()

        claimed = claim_job(session, job.id, "test-worker")
        session.commit()
        assert claimed is not None
        assert claimed.job.max_attempts == 1
        assert claimed.job.attempt_count == 1

        claimed.job.heartbeat_at = utc_now() - timedelta(seconds=settings.heartbeat_timeout_seconds + 1)
        session.commit()
        outcome = requeue_stale_jobs(session, settings)
        session.commit()
        session.refresh(job)

        assert outcome.failed_job_ids == [job.id]
        assert outcome.requeued_job_ids == []
        assert job.status == JobStatus.FAILED
        assert job.error_code == "heartbeat_timeout"
