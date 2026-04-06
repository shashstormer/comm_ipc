from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, Optional, List
import time


class CommData(BaseModel):
    sender_id: str = ""
    server_id: str = ""
    channel: str = ""
    event: str = ""
    data: Any = None
    timestamp: int = Field(default_factory=lambda: int(time.time()))
    metadata: Dict[str, Any] = Field(default_factory=dict)
    request_id: Optional[str] = None
    target_id: Optional[str] = None
    path: List[str] = Field(default_factory=list)
    is_stream: bool = False
    is_final: bool = True
    signature: Optional[str] = None
    origin_server_id: Optional[str] = None
    sub_name: Optional[str] = None

    @field_validator('sender_id', 'server_id', 'channel', 'event', mode='before')
    @classmethod
    def handle_none(cls, v):
        return v if v is not None else ""

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'CommData':
        return cls.model_validate(d)
