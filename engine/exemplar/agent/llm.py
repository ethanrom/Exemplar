"""The LLM side of the CEGIS loop: a Strands agent on Bedrock that proposes sketches through tool calls.

Bedrock quirks (verified against the live service, see docs/FRICTION_LOG.md): never send ``temperature``; the strong model rejects forced tool choice,
so the agent submits sketches through an ordinary tool call (``submit_sketches``) and `structured_output` is not used;
the region goes into the `boto3.Session`, not into `BedrockModel(region_name=...)`.  The model id comes from the
environment (`exemplar.settings`), never from code, and is never logged.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import TYPE_CHECKING

from .prompts import system_prompt, task_message
from .tools import build_tools

if TYPE_CHECKING:  # pragma: no cover
    from .cegis import RoundContext

log = logging.getLogger(__name__)


class ProposerUnavailable(RuntimeError):
    """The LLM backend cannot be used (missing credentials / model id, or the call failed)."""


def build_bedrock_model(max_tokens: int = 4096):
    from botocore.config import Config
    from strands.models import BedrockModel

    from ..settings import get_settings

    s = get_settings()
    if not (s.strong_model and s.aws_access_key and s.aws_secret_key and s.aws_region):
        raise ProposerUnavailable("Bedrock settings are missing (CLAUDE_AWS_MODEL / keys / region); using the offline "
                                  "template proposer")
    cfg = Config(read_timeout=180, connect_timeout=15, retries={"max_attempts": 3, "mode": "adaptive"})
    return BedrockModel(model_id=s.strong_model, boto_session=s.boto3_session(), boto_client_config=cfg,
                        max_tokens=max_tokens)


def _scrub(msg: str) -> str:
    """botocore embeds the model id (an ARN) in endpoint URLs; keep it out of events and logs."""
    return re.sub(r"https?://\S+", "<endpoint>", re.sub(r"arn:aws:[A-Za-z0-9:/_.\-]+", "<arn>", msg))


class StrandsProposer:
    """One Strands `Agent` for the whole run (it keeps the conversation, so later rounds see earlier counterexamples).

    ``usage`` accumulates Bedrock token counts (``inputTokens`` / ``outputTokens``) over the run, for cost reporting.
    """

    name = "strands"

    def __init__(self, model=None, *, max_tokens: int = 4096) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._agent = None
        self.usage = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0, "calls": 0}

    def _ensure(self, ctx: "RoundContext") -> None:
        if self._agent is not None:
            return
        from strands import Agent
        from strands.tools.executors import SequentialToolExecutor

        model = self._model if self._model is not None else build_bedrock_model(self._max_tokens)
        self._agent = Agent(model=model, tools=build_tools(ctx.state), system_prompt=system_prompt(ctx.k),
                            callback_handler=None, tool_executor=SequentialToolExecutor())
        ctx.state.cancel_hooks.append(self._agent.cancel)

    def propose(self, ctx: "RoundContext") -> list[str]:
        self._ensure(ctx)
        prompt = task_message(ctx.examples, ctx.nl_hint, ctx.k) if ctx.round == 1 else ctx.feedback()
        done = threading.Event()
        cancel = ctx.state.cancel
        if cancel is not None:                              # stop the agent at its next safe point when the user cancels
            def watch() -> None:
                while not done.wait(0.1):
                    if cancel.is_set():
                        self._agent.cancel()
                        return
            threading.Thread(target=watch, daemon=True, name="cegis-cancel-watch").start()
        try:
            res = self._agent(prompt)
        except ProposerUnavailable:
            raise
        except Exception as e:                              # botocore / strands errors: scrub, then let the loop fall back
            raise ProposerUnavailable(_scrub(f"{type(e).__name__}: {e}")) from None
        finally:
            done.set()
        ctx.state.check_cancel()
        try:
            u = res.metrics.accumulated_usage
            self.usage = {"inputTokens": int(u.get("inputTokens", 0)), "outputTokens": int(u.get("outputTokens", 0)),
                          "totalTokens": int(u.get("totalTokens", 0)), "calls": self.usage["calls"] + 1}
        except Exception:                                   # metrics are best-effort
            pass
        if ctx.state.accepted_this_round:
            return []                                       # everything went through submit_sketches
        # The model answered in prose instead of calling the tool: salvage any rule-looking lines.
        text = str(res)
        return [m.group(0).strip().strip("`") for m in re.finditer(r"exists [^\n]+", text)][: ctx.k]
