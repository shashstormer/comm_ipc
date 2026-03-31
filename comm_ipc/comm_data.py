from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List
import time


@dataclass
class CommData:
    sender_id: str
    server_id: str
    channel: str
    event: str
    data: Any
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None
    target_id: Optional[str] = None
    path: List[str] = field(default_factory=list)
    is_stream: bool = False
    is_final: bool = True
    signature: Optional[str] = None
    origin_server_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sender_id": self.sender_id,
            "server_id": self.server_id,
            "channel": self.channel,
            "event": self.event,
            "data": self.data,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "request_id": self.request_id,
            "target_id": self.target_id,
            "path": self.path,
            "is_stream": self.is_stream,
            "is_final": self.is_final,
            "signature": self.signature,
            "origin_server_id": self.origin_server_id
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'CommData':
        return cls(
            sender_id=d.get("sender_id", ""),
            server_id=d.get("server_id", ""),
            channel=d.get("channel", ""),
            event=d.get("event", ""),
            data=d.get("data"),
            timestamp=d.get("timestamp", time.time()),
            metadata=d.get("metadata", {}),
            request_id=d.get("request_id"),
            target_id=d.get("target_id"),
            path=d.get("path", []),
            is_stream=bool(d.get("is_stream", False)),
            is_final=bool(d.get("is_final", True)),
            signature=d.get("signature"),
            origin_server_id=d.get("origin_server_id")
        )
