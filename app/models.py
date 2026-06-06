from pydantic import BaseModel
from typing import Any


class HermesTaskRequest(BaseModel):
    """Normalized task request sent to the Hermes backend."""
    prompt: str
    max_tokens: int = 2048


class HermesTaskResult(BaseModel):
    """Normalized response from Hermes."""
    content: str
    model: str | None = None
    finish_reason: str | None = None
