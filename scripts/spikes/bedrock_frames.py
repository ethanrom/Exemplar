"""Exploratory probe used while integrating with Amazon Bedrock: sample frames from a clip, send them to
Claude in one Converse request with a forced tool schema, validate the result against the ontology, and
report latency + tokens.

Not used at runtime: the production pipeline is `engine/exemplar/perception/`.

    uv run --project engine python scripts/spikes/bedrock_frames.py CLIP.mp4 [--n 16] [--strong] [--start S --len L]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import boto3
import imageio_ffmpeg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "spike" / "bedrock"

ENTITY_TYPES = ["person", "vehicle", "package", "animal", "object"]
ZONES = ["door", "porch", "steps", "yard", "driveway", "sidewalk", "street", "dock"]
# pred -> argument kinds; "E" any entity, "P" person, "K" package|object, "Z" zone, "L" label
PREDS = {
    "present": "E", "in_zone": "EZ", "near": "EE", "carrying": "PK", "picks_up": "PK", "puts_down": "PK",
    "rings_bell": "P", "enters": "EZ", "leaves": "EZ", "facing_camera": "P", "attr": "EL",
}

SCHEMA = {
    "type": "object",
    "required": ["entities", "frames", "summary"],
    "properties": {
        "entities": {"type": "array", "items": {
            "type": "object", "required": ["id", "type", "attrs"],
            "properties": {"id": {"type": "string"}, "type": {"type": "string", "enum": ENTITY_TYPES},
                           "attrs": {"type": "array", "items": {"type": "string"}}}}},
        "frames": {"type": "array", "items": {
            "type": "object", "required": ["i", "facts"],
            "properties": {"i": {"type": "integer"}, "facts": {"type": "array", "items": {
                "type": "object", "required": ["pred", "args", "conf"],
                "properties": {"pred": {"type": "string", "enum": list(PREDS)},
                               "args": {"type": "array", "items": {"type": "string"}},
                               "conf": {"type": "string", "enum": ["low", "med", "high"]}}}}}}},
        "summary": {"type": "string"},
    },
}

SYSTEM = f"""You convert doorbell/security-camera frames into symbolic facts.
Entities: give each distinct entity a stable id used across all frames (p1, p2 for people; v1 vehicles;
k1 packages; a1 animals; o1 other objects). type is one of {ENTITY_TYPES}. attrs are short open-vocabulary
labels (e.g. delivery_uniform, hi_vis, hoodie, backpack, sedan, box).
Facts per frame: only assert what is visible in THAT frame. Predicates and argument types:
present(E) in_zone(E,Zone) near(E,E) carrying(Person,Package|Object) picks_up(Person,Package|Object)
puts_down(Person,Package|Object) rings_bell(Person) enters(E,Zone) leaves(E,Zone) facing_camera(Person) attr(E,Label).
Zone is one of {ZONES}. conf is low|med|high. Every frame index must appear in frames, even with no facts.
Ignore the Ring watermark overlay (logo top-left, device id / timestamp top-right). Do not identify anyone."""


def sample_frames(clip: Path, n: int, start: float, length: float | None, tmp: Path) -> list[tuple[float, Path]]:
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    _, secs = imageio_ffmpeg.count_frames_and_secs(str(clip))
    end = secs if length is None else min(secs, start + length)
    span = end - start
    n = max(1, min(n, int(span / 0.5)))          # ≥ 0.5 s apart
    out = []
    for i in range(n):
        t = start + span * (i + 0.5) / n
        p = tmp / f"f{i:02d}.jpg"
        subprocess.run([ff, "-v", "error", "-ss", f"{t:.3f}", "-i", str(clip), "-frames:v", "1",
                        "-vf", "scale=640:-2", "-q:v", "3", "-y", str(p)], check=True)
        out.append((round(t - start, 3), p))
    return out


def validate(obj: dict, n: int) -> list[str]:
    errs = []
    ents = {e["id"]: e["type"] for e in obj.get("entities", [])}
    if sorted(f["i"] for f in obj.get("frames", [])) != list(range(n)):
        errs.append(f"frames must contain each index 0..{n - 1} exactly once")
    for f in obj.get("frames", []):
        for fact in f["facts"]:
            kinds, args = PREDS.get(fact["pred"]), fact["args"]
            if kinds is None or len(args) != len(kinds):
                errs.append(f"frame {f['i']}: {fact['pred']}{tuple(args)} has wrong arity"); continue
            for k, a in zip(kinds, args):
                ok = {"E": a in ents, "P": ents.get(a) == "person", "K": ents.get(a) in ("package", "object"),
                      "Z": a in ZONES, "L": bool(a)}[k]
                if not ok:
                    errs.append(f"frame {f['i']}: {fact['pred']}{tuple(args)} argument {a!r} is not a valid {k}")
    return errs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", type=Path)
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--strong", action="store_true")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--len", type=float, default=None)
    a = ap.parse_args()
    load_dotenv(ROOT / ".env")
    model_id = os.environ["CLAUDE_AWS_MODEL" if a.strong else "CLAUDE_AWS_FAST_MODEL"]
    brt = boto3.client("bedrock-runtime", region_name=os.environ["CLAUDE_AWS_REGION"],
                       aws_access_key_id=os.environ["CLAUDE_AWS_ACCESS_KEY"],
                       aws_secret_access_key=os.environ["CLAUDE_AWS_SECRET_KEY"])
    with tempfile.TemporaryDirectory() as td:
        frames = sample_frames(a.clip, a.n, a.start, a.len, Path(td))
        content = []
        for i, (t, p) in enumerate(frames):
            content.append({"text": f"Frame {i} (t={t:.1f}s)"})
            content.append({"image": {"format": "jpeg", "source": {"bytes": p.read_bytes()}}})
        content.append({"text": "Call emit_trace with the entities, per-frame facts and a one-sentence summary."})
        messages = [{"role": "user", "content": content}]
        tool_cfg = {"tools": [{"toolSpec": {"name": "emit_trace", "description": "Emit the symbolic trace.",
                                            "inputSchema": {"json": SCHEMA}}}],
                    # the strong model rejects forced tool choice ("tool"/"any"); use auto + instruction
                    "toolChoice": {"auto": {}} if a.strong else {"tool": {"name": "emit_trace"}}}
        usage, t0, obj, errs = {"inputTokens": 0, "outputTokens": 0}, time.perf_counter(), None, []
        for attempt in range(2):                       # retry once, feeding the validation error back
            r = brt.converse(modelId=model_id, system=[{"text": SYSTEM}], messages=messages, toolConfig=tool_cfg,
                             inferenceConfig={"maxTokens": 8000},
                             # forced toolChoice is incompatible with extended thinking; the Haiku-class
                             # fast model may default to adaptive thinking, so switch it off explicitly
                             # strong model: "disabled" is rejected; it asks for "between_tools" instead
                             additionalModelRequestFields={"thinking": {"type": "between_tools" if a.strong else "disabled"}})
            for k in usage:
                usage[k] += r["usage"][k]
            block = next((c["toolUse"] for c in r["output"]["message"]["content"] if "toolUse" in c), None)
            if block is None:
                raise SystemExit(f"no tool call; stopReason={r['stopReason']}: {r['output']['message']['content']}"[:800])
            obj = block["input"]
            errs = validate(obj, len(frames))
            if not errs:
                break
            messages += [r["output"]["message"], {"role": "user", "content": [
                {"toolResult": {"toolUseId": block["toolUseId"], "status": "error",
                                "content": [{"text": "Validation failed:\n" + "\n".join(errs[:20])}]}}]}]
        dt = time.perf_counter() - t0
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"{a.clip.parent.name}_{a.clip.stem}_{'strong' if a.strong else 'fast'}_{int(a.start)}.json"
    dest.write_text(json.dumps({"times": [t for t, _ in frames], "trace": obj, "errors": errs,
                                "usage": usage, "latency_s": round(dt, 2), "attempts": attempt + 1}, indent=2))
    n_facts = sum(len(f["facts"]) for f in obj["frames"])
    print(f"model={'strong' if a.strong else 'fast'} frames={len(frames)} attempts={attempt + 1} "
          f"latency={dt:.1f}s tokens in={usage['inputTokens']} out={usage['outputTokens']} "
          f"entities={len(obj['entities'])} facts={n_facts} valid={not errs}")
    print("summary:", obj["summary"])
    print("saved", dest.relative_to(ROOT))


if __name__ == "__main__":
    main()
