"""One perception sample: frames -> Bedrock Converse (`emit_trace` tool) -> validated `Trace`.

Model-quality problems never raise: after one retry (the validation errors go back to the model as a
`toolResult` with status "error", or as plain text when it never called the tool) the result is
`Trace(status="perception_failed", error=...)`.  Infrastructure errors (credentials, throttling that outlasts
botocore's retries, network) raise `PerceptionBackendError`.

`client` is anything with a boto3-style `converse(**kwargs) -> dict` (a `bedrock-runtime` client, or a fake).
"""
from __future__ import annotations

import json
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, NoRegionError, PartialCredentialsError

from exemplar.contracts.trace import PerceptionMeta, Trace, TraceContext

from . import prompt
from .normalize import build_trace, failed_trace, normalize
from .sampling import SampledFrame

log = logging.getLogger("exemplar.perception")

MAX_ATTEMPTS = 2           # first try + ONE retry


class PerceptionBackendError(RuntimeError):
    """The Bedrock call itself failed (credentials, throttling that outlasted botocore's retries, connection
    drops, rejected parameters) — not a model-quality problem.  The model id is scrubbed from the message
    (botocore puts it in the endpoint URL).  `code` is the AWS error code when there is one."""

    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.code = code


class PerceptionNotConfigured(PerceptionBackendError):
    """Bedrock is not set up: no model id, credentials or region (``CLAUDE_AWS_*`` in `.env`). Nothing was sent;
    callers can show a "configure Bedrock" message and try again once the setup is fixed."""

    def __init__(self, message: str):
        super().__init__(message, "NotConfigured")


@dataclass
class SampleResult:
    trace: Optional[Trace] = None
    attempts: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    dropped: Counter = field(default_factory=Counter)
    retry_errors: list[str] = field(default_factory=list)     # errors that triggered the retry (first attempt)


def make_client(read_timeout: int = 300):
    """bedrock-runtime client from the shared settings (credentials/region from `.env`)."""
    from botocore.config import Config

    from exemplar.settings import get_settings
    cfg = Config(read_timeout=read_timeout, connect_timeout=15, retries={"max_attempts": 4, "mode": "adaptive"})
    try:
        return get_settings().boto3_session().client("bedrock-runtime", config=cfg)
    except NoRegionError as e:
        raise PerceptionNotConfigured(f"{type(e).__name__}: {e}") from None


def _feedback_message(assistant_msg: dict[str, Any], errors: Sequence[str]) -> dict[str, Any]:
    """User turn that follows a failed attempt: toolResult(error) for every toolUse, else plain text."""
    text = prompt.retry_text(errors)
    uses = [c["toolUse"] for c in assistant_msg.get("content", []) if "toolUse" in c]
    if not uses:
        return {"role": "user", "content": [{"text": text}]}
    results = [{"toolResult": {"toolUseId": u["toolUseId"], "status": "error",
                               "content": [{"text": text if i == 0 else "Ignored: call the tool once."}]}}
               for i, u in enumerate(uses)]
    return {"role": "user", "content": results}


def run_sample(client: Any, *, model_id: str, strong: bool, model_alias: Optional[str], frames: Sequence[SampledFrame],
               window_ms: int, clip_id: str, source: str, context: TraceContext) -> SampleResult:
    """One extraction (<= 2 Converse calls).  `meta.latency_ms` covers the Converse calls of this sample."""
    times = [f.t_ms for f in frames]
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt.user_content(frames, window_ms, strong)}]
    system = [{"text": prompt.build_system_prompt()}]
    tool_cfg = prompt.tool_config(strong)
    extra = prompt.model_fields(strong)
    max_tokens = 12000 if strong else 8000

    res = SampleResult()
    t0 = time.perf_counter()
    errors: list[str] = []
    trace: Optional[Trace] = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = client.converse(modelId=model_id, system=system, messages=messages, toolConfig=tool_cfg,
                                   inferenceConfig={"maxTokens": max_tokens}, additionalModelRequestFields=extra)
        except (NoCredentialsError, PartialCredentialsError, NoRegionError) as e:
            raise PerceptionNotConfigured(f"{type(e).__name__}: {e}") from None
        except (BotoCoreError, ClientError) as e:
            code = e.response.get("Error", {}).get("Code") if isinstance(e, ClientError) else type(e).__name__
            raise PerceptionBackendError(f"{code}: {str(e).replace(model_id, '<model>')}"[:500], code) from None
        res.attempts = attempt
        usage = resp.get("usage") or {}
        res.tokens_in += int(usage.get("inputTokens", 0))
        res.tokens_out += int(usage.get("outputTokens", 0))
        msg = resp.get("output", {}).get("message", {"role": "assistant", "content": []})
        stop = resp.get("stopReason")
        use = next((c["toolUse"] for c in msg.get("content", [])
                    if "toolUse" in c and c["toolUse"].get("name") == prompt.TOOL_NAME), None)

        if use is None:
            errors = [f"you did not call the {prompt.TOOL_NAME} tool (stopReason={stop}); call it with the full trace"]
        else:
            payload = use.get("input")
            if isinstance(payload, str):                   # some failure modes hand back the raw JSON text
                try:
                    payload = json.loads(payload)
                except ValueError:
                    payload = None
            norm = normalize(payload, times)
            res.dropped = norm.dropped                   # repairs of the *last* parsed attempt only
            meta = PerceptionMeta(mode="strong" if strong else "fast", model_alias=model_alias, n_frames=len(frames),
                                  tokens_in=res.tokens_in, tokens_out=res.tokens_out,
                                  latency_ms=int((time.perf_counter() - t0) * 1000))
            trace, errors = build_trace(norm, clip_id=clip_id, source=source, duration_ms=window_ms,
                                        context=context, meta=meta)
            if stop == "max_tokens":                       # the tool input may be incomplete even if it validates
                errors.insert(0, "your output was cut off (max tokens): be more compact, omit empty detail")
        if not errors:
            break
        log.info("perception attempt %d for %s failed validation: %s", attempt, clip_id, errors[:3])
        if attempt == 1:
            res.retry_errors = list(errors)
        if attempt < MAX_ATTEMPTS:
            messages += [msg, _feedback_message(msg, errors)]

    latency_ms = int((time.perf_counter() - t0) * 1000)
    meta = PerceptionMeta(mode="strong" if strong else "fast", model_alias=model_alias, n_frames=len(frames),
                          tokens_in=res.tokens_in, tokens_out=res.tokens_out, latency_ms=latency_ms)
    if errors or trace is None:
        res.trace = failed_trace(clip_id=clip_id, source=source, duration_ms=window_ms, context=context, meta=meta,
                                 error="validation failed after retry: " + "; ".join(errors[:5]))
    else:
        res.trace = trace.model_copy(update={"perception": meta})
    return res
