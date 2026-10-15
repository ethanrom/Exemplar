"""Phase 0 spike (PLAN.md §5 Q8): minimal Strands agent with one tool on BedrockModel,
using the application-inference-profile ARN from .env.

    uv run --project engine python scripts/spikes/strands_hello.py [--fast]
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import boto3
from dotenv import load_dotenv
from strands import Agent, tool
from strands.models import BedrockModel

ROOT = Path(__file__).resolve().parents[2]


@tool
def typecheck(sketch: str) -> str:
    """Typecheck an Exemplar DSL sketch. Returns 'ok' or an error message.

    Args:
        sketch: the rule text, e.g. "exists p:Person: eventually[0,?b] rings_bell(p)"
    """
    return "ok" if sketch.strip().startswith("exists") else "error: a rule must start with 'exists'"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="use CLAUDE_AWS_FAST_MODEL instead of CLAUDE_AWS_MODEL")
    a = ap.parse_args()
    load_dotenv(ROOT / ".env")
    session = boto3.Session(
        aws_access_key_id=os.environ["CLAUDE_AWS_ACCESS_KEY"],
        aws_secret_access_key=os.environ["CLAUDE_AWS_SECRET_KEY"],
        region_name=os.environ["CLAUDE_AWS_REGION"],
    )
    model = BedrockModel(boto_session=session,
                         model_id=os.environ["CLAUDE_AWS_FAST_MODEL" if a.fast else "CLAUDE_AWS_MODEL"],
                         max_tokens=512)
    agent = Agent(model=model, tools=[typecheck], callback_handler=None,
                  system_prompt="You write rules in the Exemplar DSL. Always call typecheck before answering.")
    t0 = time.perf_counter()
    res = agent("Propose one rule sketch for 'someone rang the doorbell', typecheck it, and reply with just the rule.")
    dt = time.perf_counter() - t0
    tool_calls = [c for m in agent.messages for c in m["content"] if "toolUse" in c]
    print("reply:", str(res).strip()[:300])
    print("tool calls:", [c["toolUse"]["name"] for c in tool_calls])
    print("usage:", res.metrics.accumulated_usage, f"latency={dt:.1f}s")


if __name__ == "__main__":
    main()
