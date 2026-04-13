from __future__ import annotations

from io import BytesIO
from random import Random

from PIL import Image, ImageDraw

from image_platform_shared.generators.base import (
    GenerationRequest,
    GenerationResult,
    ImageGeneratorAdapter,
    ProgressCallback,
)


class StubImageGeneratorAdapter(ImageGeneratorAdapter):
    def generate(self, request: GenerationRequest, on_progress: ProgressCallback | None = None) -> GenerationResult:
        if on_progress:
            on_progress(10, "rendering_prompt")

        randomizer = Random(request.seed)
        background = (
            randomizer.randint(10, 80),
            randomizer.randint(60, 160),
            randomizer.randint(110, 220),
        )
        accent = (
            min(background[0] + 80, 255),
            min(background[1] + 40, 255),
            min(background[2] + 20, 255),
        )

        image = Image.new("RGB", (request.width, request.height), background)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((80, 80, request.width - 80, request.height - 80), radius=40, outline=accent, width=12)
        draw.text((120, 120), f"FLUX Stub\nMode: {request.mode}\nSeed: {request.seed}", fill=(255, 255, 255))
        draw.text((120, 320), request.prompt[:200], fill=(240, 240, 240))
        if request.negative_prompt:
            draw.text((120, 520), f"Negative: {request.negative_prompt[:180]}", fill=(220, 220, 220))

        if on_progress:
            on_progress(80, "encoding_image")

        buffer = BytesIO()
        image.save(buffer, format="PNG")

        if on_progress:
            on_progress(100, "completed")

        return GenerationResult(
            image_bytes=buffer.getvalue(),
            mime_type="image/png",
            metadata={"backend": "stub", "background": background, "accent": accent},
        )
