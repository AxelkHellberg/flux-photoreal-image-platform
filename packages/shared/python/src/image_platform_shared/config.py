from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    max_attempts: int = 3
    heartbeat_interval_seconds: int = 10
    heartbeat_timeout_seconds: int = 60
    progress_timeout_seconds: int = 300
    reaper_interval_seconds: int = 15

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    public_api_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:3000"

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/image_platform"
    redis_url: str = "redis://localhost:6379/0"
    redis_queue_name: str = "image_jobs:v1"

    storage_backend: Literal["s3", "local"] = "s3"
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_region: str = "auto"
    s3_bucket: str = "image-platform-images"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    s3_use_ssl: bool = False
    s3_public_base_url: str | None = None
    local_storage_root: str = "./storage"

    image_generator_backend: Literal["stub", "flux"] = "stub"
    enable_prompt_enhancer: bool = False
    hf_token: str | None = None
    flux_model_id: str = "black-forest-labs/FLUX.1-Krea-dev"
    model_cache_dir: str = "./models/flux1-krea-dev"
    flux_dtype: Literal["bfloat16", "float16", "float32"] = "bfloat16"
    flux_device: str = "cuda"
    flux_enable_model_cpu_offload: bool = True
    flux_num_inference_steps: int = 30
    flux_guidance_scale: float = 4.5
    flux_input_image_strength: float = 0.6

    worker_id: str = "worker-local"
    worker_poll_timeout_seconds: int = 5

    next_public_api_base_url: str = Field(default="http://localhost:8000", alias="NEXT_PUBLIC_API_BASE_URL")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
