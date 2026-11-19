import base64
from contextlib import asynccontextmanager
from io import BytesIO

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from image_platform_shared.config import Settings, get_settings
from image_platform_shared.enums import JobStatus
from image_platform_shared.jobs import create_job, get_job, list_jobs, retry_job, serialize_job, with_input_image
from image_platform_shared.logging import configure_logging, get_logger
from image_platform_shared.queue import ImageJobQueue
from image_platform_shared.schemas import (
    CreateImageRequest,
    HealthResponse,
    ImageJobListResponse,
    ImageJobResponse,
    RetryImageRequest,
)
from image_platform_shared.storage import StorageBackend, create_storage_backend
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import text
from sqlalchemy.orm import Session

from image_platform_api.dependencies import get_app_settings, get_db, get_queue, get_storage

logger = get_logger(__name__)
MAX_INPUT_IMAGE_BYTES = 20 * 1024 * 1024


def _decode_input_image(payload: CreateImageRequest, settings: Settings) -> tuple[bytes, str, float] | None:
    if not payload.input_image_base64:
        return None

    encoded = payload.input_image_base64.strip()
    if encoded.startswith("data:"):
        try:
            header, encoded = encoded.split(",", 1)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Malformed input image data URL") from exc
        if not payload.input_image_mime_type:
            payload.input_image_mime_type = header.removeprefix("data:").split(";", 1)[0]

    if not payload.input_image_mime_type:
        raise HTTPException(
            status_code=422,
            detail="input_image_mime_type is required when input_image_base64 is provided",
        )

    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="input_image_base64 is not valid base64") from exc

    if len(raw) > MAX_INPUT_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="input image is too large")

    try:
        image = Image.open(BytesIO(raw))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=422, detail="input image could not be decoded") from exc

    normalized = BytesIO()
    image.save(normalized, format="PNG")
    strength = payload.input_image_strength
    if strength is None:
        strength = settings.flux_input_image_strength
    return normalized.getvalue(), "image/png", float(strength)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = getattr(app.state, "settings", get_settings())
    app.state.settings = settings
    configure_logging(settings)

    storage = getattr(app.state, "storage", None)
    if storage is None:
        storage = create_storage_backend(settings)
        app.state.storage = storage
    storage.ensure_ready()

    logger.info("api.startup", environment=settings.app_env)
    yield


app = FastAPI(title="Image Platform API", version="0.1.0", lifespan=lifespan)
app.state.settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=app.state.settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health(
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    queue: ImageJobQueue = Depends(get_queue),
) -> HealthResponse:
    session.execute(text("SELECT 1"))
    queue.ping()
    return HealthResponse(
        status="ok",
        queue_name=settings.redis_queue_name,
        storage_backend=settings.storage_backend,
        generator_backend=settings.image_generator_backend,
    )


@app.post("/v1/images", response_model=ImageJobResponse, status_code=202)
def create_image(
    payload: CreateImageRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    queue: ImageJobQueue = Depends(get_queue),
    storage: StorageBackend = Depends(get_storage),
) -> ImageJobResponse:
    job = create_job(session, payload, settings)
    input_image = _decode_input_image(payload, settings)
    if input_image is not None:
        image_bytes, mime_type, strength = input_image
        input_image_key = f"images/{job.id}/input.png"
        storage.put_bytes(input_image_key, image_bytes, mime_type)
        job.generation_params = with_input_image(
            job.generation_params,
            input_image_key=input_image_key,
            input_image_mime_type=mime_type,
            input_image_strength=strength,
        )
        session.flush()
        session.refresh(job)
    queue.enqueue(job.id)
    logger.info("job.created", job_id=job.id, mode=job.mode, aspect_ratio=job.aspect_ratio)
    return serialize_job(job, settings)


@app.get("/v1/images", response_model=ImageJobListResponse)
def image_history(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> ImageJobListResponse:
    items, next_cursor = list_jobs(session, settings, limit=limit, cursor=cursor)
    return ImageJobListResponse(items=items, next_cursor=next_cursor)


@app.get("/v1/images/{job_id}", response_model=ImageJobResponse)
def image_detail(
    job_id: str,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> ImageJobResponse:
    job = get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return serialize_job(job, settings)


@app.get("/v1/images/{job_id}/result")
def image_result(
    job_id: str,
    session: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
) -> Response:
    job = get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.SUCCEEDED:
        raise HTTPException(status_code=409, detail="Job result is not available yet")
    if not job.storage_key or not job.mime_type:
        raise HTTPException(status_code=404, detail="Result file not found")
    payload = storage.get_bytes(job.storage_key)
    return Response(
        content=payload,
        media_type=job.mime_type,
        headers={"Content-Disposition": f'inline; filename="{job.id}.png"'},
    )


@app.post("/v1/images/{job_id}/retry", response_model=ImageJobResponse, status_code=202)
def retry_image(
    job_id: str,
    payload: RetryImageRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    queue: ImageJobQueue = Depends(get_queue),
) -> ImageJobResponse:
    job = get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    retried_job = retry_job(session, job, payload.seed_strategy, settings)
    queue.enqueue(retried_job.id)
    logger.info(
        "job.retried",
        source_job_id=job.id,
        job_id=retried_job.id,
        strategy=payload.seed_strategy,
    )
    return serialize_job(retried_job, settings)
