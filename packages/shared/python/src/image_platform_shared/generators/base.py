from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from image_platform_shared.enums import GenerationMode

ProgressCallback = Callable[[int, str], None]


@dataclass(slots=True)
class GenerationRequest:
    job_id: str
    prompt: str
    negative_prompt: str
    width: int
    height: int
    seed: int
    mode: GenerationMode
    generation_params: dict[str, Any]
    input_image_bytes: bytes | None = None
    input_image_mime_type: str | None = None
    input_image_strength: float | None = None


@dataclass(slots=True)
class GenerationResult:
    image_bytes: bytes
    mime_type: str
    metadata: dict[str, Any]


class ImageGeneratorAdapter(ABC):
    def prepare(self) -> None:
        return None

    @abstractmethod
    def generate(self, request: GenerationRequest, on_progress: ProgressCallback | None = None) -> GenerationResult:
        raise NotImplementedError
