from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    history: List[Dict[str, Any]] = Field(default_factory=list)
    user_id: Optional[str] = None


class IndexPathsRequest(BaseModel):
    paths: List[str] = Field(default_factory=list)
    urls: List[str] = Field(default_factory=list)


class LearningCorrectionRequest(BaseModel):
    event_id: str = Field(..., min_length=4, max_length=64)
    corrected_answer: str = Field(..., min_length=1, max_length=2400)
    corrected_url: str = Field(default="", max_length=500)
    tags: List[str] = Field(default_factory=list)
