"""API Key generation and verification."""
from __future__ import annotations

import hashlib
import secrets


def generate_api_key() -> str:
    return f"ot_{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(api_key: str, stored_hash: str) -> bool:
    return hash_api_key(api_key) == stored_hash
