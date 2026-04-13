from __future__ import annotations

from abc import ABC, abstractmethod

from image_platform_shared.config import Settings


class PromptEnhancer(ABC):
    @abstractmethod
    def enhance(self, prompt: str, negative_prompt: str = "") -> str:
        raise NotImplementedError


class NoOpPromptEnhancer(PromptEnhancer):
    def enhance(self, prompt: str, negative_prompt: str = "") -> str:
        return prompt


class PromptEnhancer32BStub(PromptEnhancer):
    def enhance(self, prompt: str, negative_prompt: str = "") -> str:
        return prompt


def create_prompt_enhancer(settings: Settings) -> PromptEnhancer:
    if settings.enable_prompt_enhancer:
        return PromptEnhancer32BStub()
    return NoOpPromptEnhancer()
