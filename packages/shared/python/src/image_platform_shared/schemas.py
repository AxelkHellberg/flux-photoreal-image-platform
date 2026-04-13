from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from image_platform_shared.enums import AspectRatioPreset, GenerationMode, JobStatus, SeedStrategy


class CreateImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    negative_prompt: str = Field(default="", max_length=4000)
    aspect_ratio: AspectRatioPreset
    mode: GenerationMode
    seed: int | None = None
    auto_enhance_prompt: bool = False
    input_image_base64: str | None = None
    input_image_mime_type: str | None = None
    input_image_strength: float | None = Field(default=None, ge=0.0, le=1.0)


class RetryImageRequest(BaseModel):
    seed_strategy: SeedStrategy = SeedStrategy.SAME


class ImageJobResponse(BaseModel):
    id: str
    status: JobStatus
    prompt_original: str
    prompt_final: str
    negative_prompt: str
    aspect_ratio: AspectRatioPreset
    width: int
    height: int
    mode: GenerationMode
    seed: int
    auto_enhance_prompt: bool
    progress_percent: int
    progress_stage: str
    generation_params: dict[str, Any]
    result_url: str | None
    storage_bucket: str | None
    storage_key: str | None
    mime_type: str | None
    heartbeat_at: datetime | None
    attempt_count: int
    max_attempts: int
    worker_id: str | None
    error_code: str | None
    error_message: str | None
    retried_from_job_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class ImageJobListResponse(BaseModel):
    items: list[ImageJobResponse]
    next_cursor: str | None = None


class HealthResponse(BaseModel):
    status: str
    queue_name: str
    storage_backend: str
    generator_backend: str
