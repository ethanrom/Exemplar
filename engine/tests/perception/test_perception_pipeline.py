"""perceive() against a scripted fake bedrock-runtime client (offline)."""
from __future__ import annotations

import copy
import json

import pytest

from exemplar.contracts.trace import Trace, TraceContext, trace_errors
from exemplar.perception import PROMPT_VERSION, perceive, perceive_detailed
from exemplar.perception.sampling import sample_times_ms
from perception_helpers import FakeBedrock, auto_response, text_response, theft_payload, tool_response

N = 8                                    # frames sampled from the 10 s test clip with n_frames=8


def run(video, client, **kw):
    kw.setdefault("clip_id", "evt1")
    kw.setdefault("source", "upload")
    kw.setdefault("n_frames", N)
    return perceive_detailed(video, client=client, **kw)


# ------------------------------------------------------------------ request shape
def test_fast_request_parameters(video):
    fake = FakeBedrock(tool_response(theft_payload(N)))
    run(video, fake)
    (call,) = fake.calls
    assert call["modelId"] == "fake-fast-model"
    assert call["toolConfig"]["toolChoice"] == {"tool": {"name": "emit_trace"}}
    assert call["additionalModelRequestFields"] == {"thinking": {"type": "disabled"}}
    assert "temperature" not in json.dumps({k: v for k, v in call.items() if k != "messages"}, default=str)
    assert "temperature" not in call.get("inferenceConfig", {})
    assert "emit_trace" == call["toolConfig"]["tools"][0]["toolSpec"]["name"]
    assert "IGNORE the Ring watermark" in call["system"][0]["text"]
    content = call["messages"][0]["content"]
    caps = [b["text"] for b in content if "text" in b and b["text"].startswith("Frame ")]
    assert caps == [f"Frame {i} (t={t / 1000:.1f}s)" for i, t in enumerate(sample_times_ms(10000, N))]
    assert sum("image" in b for b in content) == N


def test_strong_request_parameters(video):
    fake = FakeBedrock(tool_response(theft_payload(N)))
    tr = run(video, fake, mode="strong").trace
    (call,) = fake.calls
    assert call["modelId"] == "fake-strong-model"
    assert call["toolConfig"]["toolChoice"] == {"auto": {}}
    assert call["additionalModelRequestFields"] == {"thinking": {"type": "between_tools"}}
    assert "MUST respond by calling the emit_trace tool" in call["messages"][0]["content"][-1]["text"]
    assert tr.perception.mode == "strong" and tr.perception.model_alias == "test-alias"


def test_model_ids_never_end_up_in_the_trace(video):
    tr = run(video, FakeBedrock(tool_response(theft_payload(N)))).trace
    dumped = tr.model_dump_json()
    assert "fake-fast-model" not in dumped and "fake-strong-model" not in dumped
    assert tr.perception.model_alias == "fast"


# ------------------------------------------------------------------ conversion
def test_happy_path_builds_a_valid_trace(video):
    ctx = TraceContext(sub_type="human", event_kind="upload", local_hour=14)
    res = run(video, FakeBedrock(tool_response(theft_payload(N), tokens=(6400, 1500))), context=ctx, source="meva")
    tr = res.trace
    assert isinstance(tr, Trace) and tr.status == "ok" and trace_errors(tr) == []
    assert tr.clip_id == "evt1" and tr.source == "meva" and tr.context == ctx
    assert tr.duration_ms == 10000
    assert [f.t_ms for f in tr.frames] == sample_times_ms(10000, N) and all(isinstance(f.t_ms, int) for f in tr.frames)
    assert {e.id for e in tr.entities} == {"p1", "k1"}
    assert tr.summary.startswith("A person takes a box")
    m = tr.perception
    assert (m.mode, m.n_frames, m.samples, m.tokens_in, m.tokens_out) == ("fast", N, 1, 6400, 1500)
    assert m.latency_ms >= 0 and m.cache_key and len(m.cache_key) == 64
    assert res.report.attempts == 1 and not res.cached
    assert tr.signal("picks_up", ("p1", "k1")).max() == 0.95


def test_harmless_issues_are_normalised_and_counted(video):
    payload = theft_payload(N)
    payload["frames"][0]["facts"] += [{"pred": "present", "args": ["ghost"], "conf": "high"},
                                      {"pred": "in_zone", "args": ["k1", "STEPS"], "conf": "high"}]
    res = run(video, FakeBedrock(tool_response(payload)))
    assert res.trace.status == "ok" and res.report.attempts == 1
    assert res.report.dropped.get("fact_unknown_entity") == 1


def test_n_frames_is_clamped_per_mode(video):
    # min_gap_s=0.1 lets the 10 s clip supply 100 frames, so only the per-mode caps (24 fast / 32 strong) bind
    fast = perceive(video, clip_id="x", source="upload", n_frames=99, min_gap_s=0.1, client=FakeBedrock(auto_response))
    strong = perceive(video, clip_id="x", source="upload", n_frames=99, min_gap_s=0.1, mode="strong",
                      client=FakeBedrock(auto_response))
    assert fast.status == strong.status == "ok"
    assert fast.perception.n_frames == 24 and len(fast.frames) == 24
    assert strong.perception.n_frames == 32 and len(strong.frames) == 32


def test_min_gap_reduces_frames(video):
    tr = perceive(video, clip_id="x", source="upload", n_frames=99, client=FakeBedrock(auto_response))
    assert tr.perception.n_frames == 20                              # 10 s / 0.5 s


def test_tool_input_delivered_as_json_text_is_parsed(video):
    resp = tool_response(json.dumps(theft_payload(N)))
    assert run(video, FakeBedrock(resp)).trace.status == "ok"


# ------------------------------------------------------------------ validation / retry
def bad_payload():
    p = theft_payload(N)
    p["frames"][1]["facts"].append({"pred": "rings_doorbell", "args": ["p1"], "conf": "high"})
    return p


def test_retry_once_with_errors_as_tool_result(video):
    fake = FakeBedrock(tool_response(bad_payload(), tokens=(1000, 300), tool_id="tu_A"),
                       tool_response(theft_payload(N), tokens=(1500, 250), tool_id="tu_B"))
    res = run(video, fake)
    assert res.trace.status == "ok" and res.report.attempts == 2
    assert res.trace.perception.tokens_in == 2500 and res.trace.perception.tokens_out == 550
    assert any("unknown predicate" in e for e in res.report.retry_errors)
    second = fake.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    tr_block = second[2]["content"][0]["toolResult"]
    assert tr_block["toolUseId"] == "tu_A" and tr_block["status"] == "error"
    assert "rings_doorbell" in tr_block["content"][0]["text"]
    assert second[0] == fake.calls[0]["messages"][0]            # frames are resent unchanged


def test_second_failure_gives_perception_failed_not_an_exception(video):
    fake = FakeBedrock(tool_response(bad_payload()), tool_response(bad_payload()))
    res = run(video, fake)
    tr = res.trace
    assert tr.status == "perception_failed" and "unknown predicate" in tr.error
    assert tr.frames == () and tr.entities == () and tr.duration_ms == 10000
    assert tr.perception.tokens_in == 2000 and len(fake.calls) == 2
    # failures are not cached: a re-run calls the model again
    fake2 = FakeBedrock(tool_response(theft_payload(N)))
    assert run(video, fake2).trace.status == "ok" and len(fake2.calls) == 1


def test_strong_no_tool_call_is_a_validation_failure_with_text_retry(video):
    fake = FakeBedrock(text_response("Here is my analysis..."), tool_response(theft_payload(N)))
    res = run(video, fake, mode="strong")
    assert res.trace.status == "ok" and res.report.attempts == 2
    msgs = fake.calls[1]["messages"]
    assert msgs[1]["role"] == "assistant" and msgs[2]["role"] == "user"
    assert "did not call the emit_trace tool" in msgs[2]["content"][0]["text"]


def test_never_calling_the_tool_fails_cleanly(video):
    res = run(video, FakeBedrock(text_response()), mode="strong")
    assert res.trace.status == "perception_failed" and "did not call" in res.trace.error


def test_truncated_output_is_reported_to_the_model(video):
    cut = tool_response({"entities": [], "frames": []}, stop="max_tokens")
    fake = FakeBedrock(cut, tool_response(theft_payload(N)))
    res = run(video, fake)
    assert res.trace.status == "ok"
    assert "cut off" in fake.calls[1]["messages"][2]["content"][0]["toolResult"]["content"][0]["text"]


def test_infrastructure_errors_propagate(video):
    with pytest.raises(RuntimeError, match="throttled"):
        run(video, FakeBedrock(RuntimeError("throttled")))


def test_aws_errors_become_backend_errors_without_the_model_id(video):
    from botocore.exceptions import ClientError, ConnectionClosedError

    from exemplar.perception import PerceptionBackendError
    err = ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down fake-fast-model"}}, "Converse")
    with pytest.raises(PerceptionBackendError) as ei:
        run(video, FakeBedrock(err))
    assert ei.value.code == "ThrottlingException" and "fake-fast-model" not in str(ei.value)
    conn = ConnectionClosedError(endpoint_url="https://bedrock-runtime.x.amazonaws.com/model/fake-fast-model/converse")
    with pytest.raises(PerceptionBackendError) as ei:
        run(video, FakeBedrock(conn))
    assert "fake-fast-model" not in str(ei.value) and "<model>" in str(ei.value)


def test_missing_setup_raises_not_configured(video, monkeypatch):
    """No model id, no credentials, no region: a PerceptionNotConfigured (a backend error), before anything is sent."""
    from botocore.exceptions import NoCredentialsError, NoRegionError

    from exemplar import settings
    from exemplar.perception import PerceptionBackendError, PerceptionNotConfigured
    monkeypatch.delenv("CLAUDE_AWS_FAST_MODEL")
    settings.get_settings.cache_clear()
    with pytest.raises(PerceptionNotConfigured, match="CLAUDE_AWS_FAST_MODEL is not configured"):
        run(video, None)
    monkeypatch.setenv("CLAUDE_AWS_FAST_MODEL", "fake-fast-model")
    settings.get_settings.cache_clear()
    for err in (NoCredentialsError(), NoRegionError()):
        fake = FakeBedrock(err)
        with pytest.raises(PerceptionNotConfigured) as ei:
            run(video, fake)
        assert isinstance(ei.value, PerceptionBackendError) and ei.value.code == "NotConfigured"
        assert "fake-fast-model" not in str(ei.value)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("CLAUDE_AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(video.parent / "no-aws-config"))
    settings.get_settings.cache_clear()
    from exemplar.perception.extract import make_client
    with pytest.raises(PerceptionNotConfigured, match="NoRegionError"):
        make_client()


# ------------------------------------------------------------------ self-consistency
def test_two_samples_are_merged(video):
    a = theft_payload(N)
    b = copy.deepcopy(a)
    b["frames"][4]["facts"].append({"pred": "near", "args": ["p1", "k1"], "conf": "high"})   # only in b
    b["frames"][3]["facts"][1]["conf"] = "low"                                                # lower in b
    fake = FakeBedrock(tool_response(a, tokens=(1000, 100)), tool_response(b, tokens=(1000, 100)))
    res = run(video, fake, mode="strong", samples=2)
    tr = res.trace
    assert tr.status == "ok" and tr.perception.samples == 2 and len(fake.calls) == 2
    assert tr.perception.tokens_in == 2000 and tr.perception.tokens_out == 200
    assert res.report.attempts == 2 and res.report.merge["facts_partial"] >= 2
    assert tr.signal("near", ("p1", "k1"))[4] == 0.6 and tr.signal("near", ("k1", "p1"))[4] == 0.6   # one-sided -> low
    assert tr.signal("in_zone", ("k1", "steps"))[3] == 0.6      # min(high, low)
    assert tr.signal("picks_up", ("p1", "k1"))[2] == 0.95       # both high


def test_one_failed_sample_falls_back_to_the_other(video):
    # two samples run concurrently: whichever call comes first succeeds, the other (and its retry) never calls the tool
    res = run(video, FakeBedrock(tool_response(theft_payload(N)), text_response(), text_response()), mode="strong", samples=2)
    assert res.trace.status == "ok" and res.trace.perception.samples == 1 and res.report.samples_failed == 1


def test_samples_bounds(video):
    for bad in (0, 4):
        with pytest.raises(ValueError):
            run(video, FakeBedrock(text_response()), samples=bad)
    with pytest.raises(ValueError):
        run(video, FakeBedrock(text_response()), mode="turbo")  # type: ignore[arg-type]


# ------------------------------------------------------------------ cache
def test_cache_hit_skips_the_model_and_force_bypasses(video, isolated_settings):
    fake = FakeBedrock(tool_response(theft_payload(N)))
    first = run(video, fake)
    assert not first.cached and len(fake.calls) == 1
    files = list((isolated_settings / "cache" / "traces").glob("*.json"))
    assert [f.stem for f in files] == [first.trace.perception.cache_key]

    ctx = TraceContext(sub_type="vehicle", event_kind="live")
    again = run(video, fake, context=ctx, source="ring")
    assert again.cached and len(fake.calls) == 1
    assert again.trace.context == ctx and again.trace.source == "ring"      # caller metadata, not perception
    assert again.trace.frames == first.trace.frames and again.trace.perception == first.trace.perception

    forced = run(video, fake, force=True)
    assert not forced.cached and len(fake.calls) == 2


def test_cache_key_ignores_clip_bytes_but_not_parameters(video, tmp_path):
    fake = FakeBedrock(auto_response)
    run(video, fake)
    other = tmp_path / "rerendered.mp4"
    other.write_bytes(video.read_bytes() + b"\x00watermark re-rendered")         # different bytes, same event
    assert run(other, fake).cached and len(fake.calls) == 1
    for changed in (dict(n_frames=4), dict(mode="strong"), dict(start_s=1, dur_s=4), dict(roi=(0, 0, 100, 100)),
                    dict(clip_id="evt2"), dict(width=320), dict(samples=2)):
        assert not run(video, fake, **changed).cached, changed


def test_prompt_version_and_model_are_part_of_the_key(monkeypatch):
    from exemplar.perception import cache
    base = dict(clip_id="c", n_frames=16, min_gap_s=0.5, width=640, roi=None, mode="fast", samples=1, model_alias="fast")
    k1 = cache.cache_key(**base)
    assert cache.cache_key(**{**base, "start_s": 0.0}) == k1 and cache.cache_key(**{**base, "start_s": 1}) != k1
    assert cache.cache_key(**{**base, "model_fp": "abcd1234"}) != k1
    assert cache.cache_key(**{**base, "model_alias": "other"}) != k1
    monkeypatch.setattr(cache, "PROMPT_VERSION", PROMPT_VERSION + "-next")
    assert cache.cache_key(**base) != k1


def test_corrupt_cache_entry_is_ignored(video, isolated_settings):
    fake = FakeBedrock(tool_response(theft_payload(N)))
    key = run(video, fake).trace.perception.cache_key
    (isolated_settings / "cache" / "traces" / f"{key}.json").write_text("{not json", encoding="utf-8")
    assert not run(video, fake).cached and len(fake.calls) == 2
