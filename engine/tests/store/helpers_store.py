"""Tiny helper shared by the store tests."""
from __future__ import annotations

import base64
import json
import time


def fresh_jwt(minutes: float = 30.0) -> str:
    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    now = int(time.time())
    return f"{b64({'alg': 'none'})}.{b64({'iat': now - 60, 'exp': now + int(minutes * 60)})}.c2ln"
