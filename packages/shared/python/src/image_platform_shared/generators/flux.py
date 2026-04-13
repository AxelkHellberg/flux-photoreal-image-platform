from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from image_platform_shared.config import Settings
from image_platform_shared.generators.base import (
    GenerationRequest,
    GenerationResult,
    ImageGeneratorAdapter,
    ProgressCallback,
)


class FluxImageGeneratorAdapter(ImageGeneratorAdapter):
    def __init__(self, settings: Settings):
        self.settings = settings
        self._pipeline = None
        self._torch = None
        self._pipeline_kind: str | None = None

    def prepare(self) -> None:
        self._validate_runtime_config()

    def _validate_runtime_config(self) -> None:
        if not self.settings.hf_token:
            raise RuntimeError(
                "HF_TOKEN is required for the gated model black-forest-labs/FLUX.1-Krea-dev. "
                "Accept the model terms on Hugging Face and configure HF_TOKEN before starting the worker."
            )

    def _resolve_dtype(self, torch):
        if self.settings.flux_dtype == "float32":
            return torch.float32
        if self.settings.flux_dtype == "float16":
            return torch.float16
        if (
            self.settings.flux_device.startswith("cuda")
            and torch.cuda.is_available()
            and torch.cuda.is_bf16_supported()
        ):
            return torch.bfloat16
        return torch.float16

    def _teardown_pipeline(self) -> None:
        if self._pipeline is None:
            return
        pipeline = self._pipeline
        self._pipeline = None
        self._pipeline_kind = None
        del pipeline
        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()

    def _ensure_pipeline(self, kind: str):
        if self._pipeline is not None and self._pipeline_kind == kind:
            return self._pipeline

        self._validate_runtime_config()

        import torch
        from diffusers import FluxImg2ImgPipeline, FluxPipeline
        from huggingface_hub import snapshot_download

        self._torch = torch
        if self._pipeline is not None and self._pipeline_kind != kind:
            self._teardown_pipeline()
        model_root = Path(self.settings.model_cache_dir).expanduser().resolve()
        model_root.mkdir(parents=True, exist_ok=True)

        snapshot_download(
            repo_id=self.settings.flux_model_id,
            local_dir=str(model_root),
            token=self.settings.hf_token,
            resume_download=True,
        )

        os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

        pipeline_cls = FluxImg2ImgPipeline if kind == "img2img" else FluxPipeline
        pipeline = pipeline_cls.from_pretrained(
            str(model_root),
            torch_dtype=self._resolve_dtype(torch),
            token=self.settings.hf_token,
        )

        if self.settings.flux_enable_model_cpu_offload and self.settings.flux_device.startswith("cuda"):
            try:
                pipeline.enable_model_cpu_offload()
            except Exception as exc:
                if not torch.cuda.is_available():
                    raise RuntimeError(
                        "CUDA is unavailable in the worker runtime. "
                        "The installed torch build is incompatible with the node driver, "
                        "or the GPU is not accessible."
                    ) from exc
                pipeline = pipeline.to(self.settings.flux_device)
        else:
            pipeline = pipeline.to(self.settings.flux_device)

        self._pipeline = pipeline
        self._pipeline_kind = kind
        return pipeline

    def generate(self, request: GenerationRequest, on_progress: ProgressCallback | None = None) -> GenerationResult:
        pipeline_kind = "img2img" if request.input_image_bytes else "text2img"
        pipeline = self._ensure_pipeline(pipeline_kind)
        torch = self._torch
        steps = int(request.generation_params["num_inference_steps"])

        def handle_step_end(pipe, step_index, timestep, callback_kwargs):
            if on_progress:
                percent = 5 + int(((step_index + 1) / max(steps, 1)) * 90)
                on_progress(min(percent, 95), "generating")
            return callback_kwargs

        if on_progress:
            on_progress(3, "loading_pipeline")

        call_kwargs = {
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt or None,
            "width": request.width,
            "height": request.height,
            "guidance_scale": float(request.generation_params["guidance_scale"]),
            "num_inference_steps": steps,
            "generator": torch.Generator(device="cpu").manual_seed(request.seed),
            "callback_on_step_end": handle_step_end,
            "callback_on_step_end_tensor_inputs": [],
        }
        if request.input_image_bytes:
            source_image = Image.open(BytesIO(request.input_image_bytes))
            source_image = ImageOps.exif_transpose(source_image).convert("RGB")
            source_image = ImageOps.fit(
                source_image,
                (request.width, request.height),
                method=Image.Resampling.LANCZOS,
            )
            call_kwargs["image"] = source_image
            call_kwargs["strength"] = float(
                request.input_image_strength
                if request.input_image_strength is not None
                else self.settings.flux_input_image_strength
            )

        result = pipeline(**call_kwargs)

        if on_progress:
            on_progress(97, "encoding_image")

        image = result.images[0]
        buffer = BytesIO()
        image.save(buffer, format="PNG")

        if on_progress:
            on_progress(100, "completed")

        return GenerationResult(
            image_bytes=buffer.getvalue(),
            mime_type="image/png",
            metadata={
                "backend": "flux",
                "model_id": request.generation_params["model_id"],
                "num_inference_steps": request.generation_params["num_inference_steps"],
                "guidance_scale": request.generation_params["guidance_scale"],
                "torch_dtype": request.generation_params["torch_dtype"],
                "cpu_offload_enabled": request.generation_params["cpu_offload_enabled"],
                "negative_prompt_strategy": request.generation_params["negative_prompt_strategy"],
                "input_image_enabled": bool(request.input_image_bytes),
                "input_image_strength": request.input_image_strength,
            },
        )
