import hashlib
import hmac
import json
import os
from typing import Dict, Any


def generate_challenge(length: int = 32) -> str:
    return os.urandom(length).hex()

def derive_key(secret: str, salt: bytes = b"") -> bytes:
    return hashlib.pbkdf2_hmac('sha256', secret.encode(), salt, 100000, dklen=32)

def compute_signature(key: bytes, msg_dict: Dict[str, Any]) -> str:
    immutable_keys = ["sender_id", "channel", "event", "data", "timestamp", "request_id", "target_id", "is_stream", "is_final", "origin_server_id", "challenge"]
    parts = []
    
    for k in sorted(immutable_keys):
        if k in msg_dict:
            val = msg_dict[k]
            serialized_val = json.dumps(val, sort_keys=True, separators=(",", ":"))
            parts.append(f"{k}:{serialized_val}")
    
    payload = "|".join(parts).encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

def verify_signature(key: bytes, msg_dict: Dict[str, Any], signature: str) -> bool:
    if not signature:
        return False
    expected = compute_signature(key, msg_dict)
    return hmac.compare_digest(expected, signature)

def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()

def verify_hash(secret: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(secret), stored_hash)
