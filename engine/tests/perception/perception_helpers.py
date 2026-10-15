"""Test doubles and canned model outputs for the perception tests."""
from __future__ import annotations

import threading
from typing import Any


class FakeBedrock:
    """Scripted bedrock-runtime stand-in.  `script` items are response dicts, exceptions, or callables
    (kwargs -> response).  Every call's kwargs are recorded (deep enough for assertions).  Thread-safe."""

    def __init__(self, *script: Any):
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def converse(self, **kw: Any) -> dict[str, Any]:
        with self._lock:
            self.calls.append({**kw, "messages": list(kw["messages"])})
            item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item(kw) if callable(item) else item


def tool_response(payload: Any, *, tokens: tuple[int, int] = (1000, 200), stop: str = "tool_use",
                  tool_id: str = "tu_1", name: str = "emit_trace") -> dict[str, Any]:
    return {"output": {"message": {"role": "assistant", "content": [
        {"toolUse": {"toolUseId": tool_id, "name": name, "input": payload}}]}},
        "stopReason": stop, "usage": {"inputTokens": tokens[0], "outputTokens": tokens[1]}}


def text_response(text: str = "I cannot do that", *, tokens: tuple[int, int] = (1000, 20)) -> dict[str, Any]:
    return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}, "stopReason": "end_turn",
            "usage": {"inputTokens": tokens[0], "outputTokens": tokens[1]}}


def theft_payload(n_frames: int) -> dict[str, Any]:
    """A clean model output for n_frames frames: p1 arrives, picks up k1, leaves."""
    frames = []
    for i in range(n_frames):
        facts = [{"pred": "present", "args": ["k1"], "conf": "high"}, {"pred": "in_zone", "args": ["k1", "steps"], "conf": "high"}]
        if i >= 1:
            facts += [{"pred": "present", "args": ["p1"], "conf": "high"}, {"pred": "in_zone", "args": ["p1", "steps"], "conf": "med"}]
        if i == 2:
            facts += [{"pred": "picks_up", "args": ["p1", "k1"], "conf": "high"}]
        if i >= 2:
            facts += [{"pred": "carrying", "args": ["p1", "k1"], "conf": "high"}]
        frames.append({"i": i, "facts": facts})
    return {"entities": [{"id": "p1", "type": "person", "attrs": ["hoodie"]},
                         {"id": "k1", "type": "package", "attrs": ["cardboard_box"]}],
            "frames": frames, "summary": "A person takes a box from the steps and leaves."}


def auto_response(kw: dict[str, Any]) -> dict[str, Any]:
    """A valid answer sized to however many frames the request carries."""
    n = sum("image" in b for b in kw["messages"][0]["content"])
    return tool_response(theft_payload(n))
