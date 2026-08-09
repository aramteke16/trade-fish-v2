"""Stream 3 extraction schema (plan §4). The LLM scores information, never price."""

from typing import Literal

from pydantic import BaseModel, Field

Catalyst = Literal["earnings", "guidance", "order_win", "mgmt_change",
                   "regulatory", "rating", "none"]


class Extraction(BaseModel):
    catalyst: Catalyst
    sentiment: float = Field(ge=-1, le=1)
    surprise: float = Field(ge=-1, le=1)
    guidance_delta: float = Field(ge=-1, le=1)
    magnitude: float = Field(ge=0, le=1)
    novelty: float = Field(ge=0, le=1)
    uncertainty: float = Field(ge=0, le=1)
    persistence: int = Field(ge=0, le=4)
    evidence: str = ""


NEUTRAL = Extraction(catalyst="none", sentiment=0, surprise=0, guidance_delta=0,
                     magnitude=0, novelty=0, uncertainty=0, persistence=0)


class ExtractionResult(BaseModel):
    extraction: Extraction
    extraction_failed: bool = False   # True -> treat features as missing, not zero
    provider: str
    model: str
    prompt_version: str
    tokens_used: int = 0
    latency_ms: int = 0
    cached: bool = False
