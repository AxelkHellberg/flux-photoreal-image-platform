from __future__ import annotations

import sys
from types import SimpleNamespace

from image_platform_shared.config import Settings
from image_platform_shared.enums import GenerationMode
from image_platform_shared.generators.base import GenerationRequest
from image_platform_shared.generators.flux import FluxImageGeneratorAdapter
from PIL import Image


def test_prepare_requires_hf_token(tmp_path):
    settings = Settings(model_cache_dir=str(tmp_path), hf_token=None)
    adapter = FluxImageGeneratorAdapter(settings)

    try:
        adapter.prepare()
    except RuntimeError as exc:
        assert "HF_TOKEN is required" in str(exc)
    else:
        raise AssertionError("Expected prepare() to fail without HF_TOKEN")


def test_flux_adapter_loads_lazily_and_reuses_pipeline(monkeypatch, tmp_path):
    events: dict[str, list] = {"snapshots": [], "from_pretrained": []}

    class FakeGenerator:
        def __init__(self, device):
            self.device = device
            self.seed = None

        def manual_seed(self, seed):
            self.seed = seed
            return self

    class FakeCuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def is_bf16_supported():
            return True

    fake_torch = SimpleNamespace(
        float32="float32",
        float16="float16",
        bfloat16="bfloat16",
        cuda=FakeCuda(),
        Generator=FakeGenerator,
    )

    def fake_snapshot_download(*, repo_id, local_dir, token, resume_download):
        events["snapshots"].append(
            {
                "repo_id": repo_id,
                "local_dir": local_dir,
                "token": token,
                "resume_download": resume_download,
            }
        )
        return local_dir

    class FakePipeline:
        def __init__(self, kind="text2img"):
            self.cpu_offload_enabled = False
            self.kind = kind

        @classmethod
        def from_pretrained(cls, path, torch_dtype, token):
            events["from_pretrained"].append(
                {"path": path, "torch_dtype": torch_dtype, "token": token, "kind": cls.__name__}
            )
            return cls(kind=cls.__name__)

        def enable_model_cpu_offload(self):
            self.cpu_offload_enabled = True

        def __call__(
            self,
            *,
            prompt,
            negative_prompt,
            width,
            height,
            guidance_scale,
            num_inference_steps,
            generator,
            callback_on_step_end,
            callback_on_step_end_tensor_inputs,
            **kwargs,
        ):
            assert prompt == "Photoreal studio portrait"
            assert negative_prompt == "cgi, plastic skin"
            assert width == 1024
            assert height == 1024
            assert guidance_scale == 4.5
            assert num_inference_steps == 3
            assert generator.seed == 42
            assert callback_on_step_end_tensor_inputs == []
            assert kwargs == {}
            for index in range(num_inference_steps):
                callback_on_step_end(self, index, None, {})
            return SimpleNamespace(images=[Image.new("RGB", (width, height), (120, 100, 90))])

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=fake_snapshot_download))
    monkeypatch.setitem(
        sys.modules,
        "diffusers",
        SimpleNamespace(FluxPipeline=FakePipeline, FluxImg2ImgPipeline=FakePipeline),
    )

    settings = Settings(
        hf_token="hf_test",
        model_cache_dir=str(tmp_path / "cache"),
        flux_num_inference_steps=30,
        flux_guidance_scale=4.5,
        flux_enable_model_cpu_offload=True,
        flux_dtype="bfloat16",
    )
    adapter = FluxImageGeneratorAdapter(settings)

    request = GenerationRequest(
        job_id="job-1",
        prompt="Photoreal studio portrait",
        negative_prompt="cgi, plastic skin",
        width=1024,
        height=1024,
        seed=42,
        mode=GenerationMode.PHOTOREAL,
        generation_params={
            "model_id": settings.flux_model_id,
            "num_inference_steps": 3,
            "guidance_scale": 4.5,
            "torch_dtype": "bfloat16",
            "cpu_offload_enabled": True,
            "negative_prompt_strategy": "native_negative_prompt",
        },
    )

    progress_markers: list[tuple[int, str]] = []
    first = adapter.generate(request, on_progress=lambda percent, stage: progress_markers.append((percent, stage)))
    second = adapter.generate(request)

    assert first.mime_type == "image/png"
    assert first.image_bytes.startswith(b"\x89PNG")
    assert first.metadata["backend"] == "flux"
    assert first.metadata["model_id"] == settings.flux_model_id
    assert first.metadata["negative_prompt_strategy"] == "native_negative_prompt"
    assert second.image_bytes.startswith(b"\x89PNG")

    assert events["snapshots"] == [
        {
            "repo_id": settings.flux_model_id,
            "local_dir": str((tmp_path / "cache").resolve()),
            "token": "hf_test",
            "resume_download": True,
        }
    ]
    assert events["from_pretrained"] == [
        {
            "path": str((tmp_path / "cache").resolve()),
            "torch_dtype": "bfloat16",
            "token": "hf_test",
            "kind": "FakePipeline",
        }
    ]
    assert progress_markers[0] == (3, "loading_pipeline")
    assert progress_markers[-1] == (100, "completed")


def test_flux_adapter_switches_to_img2img_pipeline_for_input_image(monkeypatch, tmp_path):
    events: dict[str, list] = {"from_pretrained": []}

    class FakeGenerator:
        def __init__(self, device):
            self.device = device

        def manual_seed(self, seed):
            self.seed = seed
            return self

    class FakeCuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def is_bf16_supported():
            return True

        @staticmethod
        def empty_cache():
            return None

    fake_torch = SimpleNamespace(
        float32="float32",
        float16="float16",
        bfloat16="bfloat16",
        cuda=FakeCuda(),
        Generator=FakeGenerator,
    )

    def fake_snapshot_download(**kwargs):
        return kwargs["local_dir"]

    class FakeTextPipeline:
        @classmethod
        def from_pretrained(cls, path, torch_dtype, token):
            events["from_pretrained"].append(cls.__name__)
            return cls()

        def enable_model_cpu_offload(self):
            return None

    class FakeImg2ImgPipeline(FakeTextPipeline):
        def __call__(self, *, image, strength, prompt, negative_prompt, **kwargs):
            assert image.size == (1024, 1024)
            assert strength == 0.55
            assert prompt == "Prompt"
            assert negative_prompt == "bad"
            return SimpleNamespace(images=[Image.new("RGB", (1024, 1024), (10, 20, 30))])

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=fake_snapshot_download))
    monkeypatch.setitem(
        sys.modules,
        "diffusers",
        SimpleNamespace(FluxPipeline=FakeTextPipeline, FluxImg2ImgPipeline=FakeImg2ImgPipeline),
    )

    source = Image.new("RGB", (300, 500), (200, 50, 60))
    buf = __import__("io").BytesIO()
    source.save(buf, format="PNG")

    settings = Settings(
        hf_token="hf_test",
        model_cache_dir=str(tmp_path / "cache"),
        flux_enable_model_cpu_offload=True,
        flux_input_image_strength=0.6,
    )
    adapter = FluxImageGeneratorAdapter(settings)
    request = GenerationRequest(
        job_id="job-2",
        prompt="Prompt",
        negative_prompt="bad",
        width=1024,
        height=1024,
        seed=7,
        mode=GenerationMode.PHOTOREAL,
        generation_params={
            "model_id": settings.flux_model_id,
            "num_inference_steps": 3,
            "guidance_scale": 4.5,
            "torch_dtype": "bfloat16",
            "cpu_offload_enabled": True,
            "negative_prompt_strategy": "native_negative_prompt",
        },
        input_image_bytes=buf.getvalue(),
        input_image_mime_type="image/png",
        input_image_strength=0.55,
    )

    result = adapter.generate(request)
    assert result.image_bytes.startswith(b"\x89PNG")
    assert events["from_pretrained"] == ["FakeImg2ImgPipeline"]
    assert result.metadata["input_image_enabled"] is True
    assert result.metadata["input_image_strength"] == 0.55
