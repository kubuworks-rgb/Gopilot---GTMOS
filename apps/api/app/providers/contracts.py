from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel


OutputT = TypeVar("OutputT", bound=BaseModel)


class StructuredLLMProvider(Protocol):
    async def generate(self, *, prompt_name: str, inputs: dict[str, object], output_schema: type[OutputT]) -> OutputT: ...


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class ResearchProvider(Protocol):
    async def research(self, *, workspace_id: str, plan: dict[str, object]) -> list[dict[str, object]]: ...


class DeterministicTestProvider:
    def __init__(self, fixtures: dict[str, dict[str, object]]) -> None:
        self.fixtures = fixtures

    async def generate(self, *, prompt_name: str, inputs: dict[str, object], output_schema: type[OutputT]) -> OutputT:
        del inputs
        if prompt_name not in self.fixtures:
            raise KeyError(f"No deterministic fixture for {prompt_name}")
        return output_schema.model_validate(self.fixtures[prompt_name])


class LiveProviderNotConfigured(RuntimeError):
    """Typed failure used instead of silently substituting fixture output."""
