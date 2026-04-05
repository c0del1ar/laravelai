from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    history: List[Dict[str, Any]] = Field(default_factory=list)
    user_id: Optional[str] = None
