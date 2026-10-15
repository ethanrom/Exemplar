"""Actions run when a rule fires: ui, webhook_out, slack, chime.

Every action yields ``{"action", "status": ok|skipped|failed, "detail"}`` and an ``action_result``
MonitorEvent; none of them ever raises into the monitor.

* ``ui``: emits the ``rule_fired`` MonitorEvent (the Live screen lights up). The monitor always runs it first,
  so a slow webhook never delays the notification.
* ``webhook_out``: POSTs the firing as JSON (witness included) to a configured URL. Body is compact JSON with
  sorted keys; with a secret the request carries ``X-Signature: sha256=<hex HMAC-SHA256 of the raw body>``
  (the same scheme Ring uses for its own webhooks) and ``X-Exemplar-Delivery: <firing id>`` for receiver-side
  dedupe across retries. Transport errors, 408/425/429 and 5xx are retried with exponential backoff (Retry-After
  honoured for 429, capped); other 4xx fail at once.
* ``slack``: an incoming-webhook URL; a short message with the rule's English text and the top witness span
  (the first temporal span, else the first span). Text from the rule is escaped for Slack (& < >).
* ``chime``: Ring ``chime_play`` behind a flag (early-access API; the Playground answers 400). Needs a sync
  callable ``(device_id, audio_ref)``: `chime_via_ring_client` adapts `exemplar.ring.RingClient`. Any exception
  becomes ``failed`` with the error text.

URLs and secrets are never written into ``detail`` (only the host name), since a Slack webhook URL is a credential.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Callable, Optional, Sequence
from urllib.parse import urlparse

import httpx

from exemplar.contracts.trace import Trace

if TYPE_CHECKING:
    from .types import DeployedRule, EventInput, FiringRecord

log = logging.getLogger("exemplar.monitor.actions")

ACTIONS = ("ui", "webhook_out", "slack", "chime")
RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
TEMPORAL_OPS = frozenset({"then", "eventually", "always", "holds_for"})
SLACK_MAX = 600


def result(action: str, status: str, detail: Optional[str] = None) -> dict:
    return {"action": action, "status": status, "detail": detail}


@dataclass(frozen=True)
class ActionContext:
    rule: "DeployedRule"
    record: "FiringRecord"           # the firing as decided (its `actions` are filled in by the runner)
    event: "EventInput"
    trace: Trace
    emit: Callable[[dict], None]     # MonitorEvent sink (the monitor stamps `at_ms`)


def chime_via_ring_client(client: Any, *, loop: Optional[asyncio.AbstractEventLoop] = None,
                          timeout_s: float = 60.0) -> Callable[[str, str], Any]:
    """Adapt the async `RingClient.chime_play` to the sync ``(device_id, audio_ref)`` callable `ActionRunner` wants.

    Pass the application's running event loop as ``loop`` when the client was created on it (its httpx client is
    bound to that loop). Without ``loop`` each call runs in a fresh loop via `asyncio.run`, which is fine for a
    client that is created per call or mocked, not for a long-lived pooled one.
    """
    def call(device_id: str, audio_ref: str) -> Any:
        coro = client.chime_play(device_id, audio_ref)
        if loop is not None:
            return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=timeout_s)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        with ThreadPoolExecutor(max_workers=1) as pool:          # called from inside a loop: use a helper thread
            return pool.submit(asyncio.run, coro).result(timeout=timeout_s)
    return call


def top_span(witness: Optional[dict]) -> Optional[dict]:
    spans = (witness or {}).get("spans") or []
    return next((s for s in spans if s.get("op") in TEMPORAL_OPS), spans[0] if spans else None)


def _slack_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def slack_text(rule: "DeployedRule", record: "FiringRecord") -> str:
    parts = [f"Exemplar: {_slack_escape(rule.english)}"]
    score = "" if record.score is None else f"score {record.score:+.2f}"
    if record.tau is not None and score:
        score += f" (tau {record.tau:.2f})"
    parts.append(" | ".join(x for x in (f"event {record.event_id}", score) if x))
    span = top_span(record.witness)
    if span:
        parts.append(f"evidence: {_slack_escape(str(span.get('text', span.get('op'))))} "
                     f"at {span['t_start_ms'] / 1000:.1f}-{span['t_end_ms'] / 1000:.1f} s")
    text = "\n".join(parts)
    return text if len(text) <= SLACK_MAX else text[:SLACK_MAX - 1] + "…"


def _host(url: str) -> str:
    return urlparse(url).netloc or "?"


class ActionRunner:
    def __init__(self, *, webhook_url: Optional[str] = None, webhook_secret: Optional[str] = None,
                 slack_url: Optional[str] = None, chime: Optional[Callable[[str, str], Any]] = None,
                 chime_audio_ref: str = "default", chime_enabled: bool = False,
                 http: Optional[httpx.Client] = None, retries: int = 3, backoff_s: float = 0.5,
                 max_backoff_s: float = 8.0, timeout_s: float = 5.0,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.webhook_url, self.webhook_secret, self.slack_url = webhook_url, webhook_secret, slack_url
        self.chime, self.chime_audio_ref, self.chime_enabled = chime, chime_audio_ref, chime_enabled
        self.retries, self.backoff_s, self.max_backoff_s, self.timeout_s = retries, backoff_s, max_backoff_s, timeout_s
        self._sleep = sleep
        self._http = http
        self._own_http = http is None

    def close(self) -> None:
        if self._own_http and self._http is not None:
            self._http.close()
            self._http = None

    # ------------------------------------------------------------------ driver
    def run(self, names: Sequence[str], ctx: ActionContext) -> list[dict]:
        """Run the named actions in order; returns their results (and emits one ``action_result`` each)."""
        done: list[dict] = []
        for name in names:
            handler = {"ui": self._ui, "webhook_out": self._webhook, "slack": self._slack, "chime": self._chime}.get(name)
            try:
                res = handler(ctx) if handler else result(name, "skipped", f"unknown action '{name}'")
            except Exception as e:                                   # an action must never take the monitor down
                log.exception("action %s raised", name)
                res = result(name, "failed", f"{type(e).__name__}: {e}"[:300])
            done.append(res)
            self._emit_result(ctx, done, res)
        return done

    def _emit_result(self, ctx: ActionContext, done: list[dict], res: dict) -> None:
        detail = f": {res['detail']}" if res.get("detail") else ""
        firing = replace(ctx.record, actions=tuple(done)).to_api()
        try:
            ctx.emit({"type": "action_result", "event_id": ctx.record.event_id, "rule_id": ctx.record.rule_id,
                      "firing": firing, "message": f"{res['action']} {res['status']}{detail}"})
        except Exception:
            log.exception("emit failed for action_result")

    # ------------------------------------------------------------------ actions
    def _ui(self, ctx: ActionContext) -> dict:
        ctx.emit({"type": "rule_fired", "event_id": ctx.record.event_id, "rule_id": ctx.record.rule_id,
                  "firing": ctx.record.to_api(), "message": ctx.rule.english})
        return result("ui", "ok")

    def _webhook(self, ctx: ActionContext) -> dict:
        if not self.webhook_url:
            return result("webhook_out", "skipped", "webhook URL not configured")
        rec, rule = ctx.record, ctx.rule
        payload = {"type": "rule_fired", "rule_id": rec.rule_id, "concept_id": rule.concept_id, "event_id": rec.event_id,
                   "clip_id": ctx.event.clip_id, "english": rule.english, "stage": rec.stage, "score": rec.score,
                   "tau": rec.tau, "fired_at_ms": rec.created_at_ms, "witness": rec.witness}
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "exemplar-monitor/1",
                   "X-Exemplar-Delivery": rec.id}
        if self.webhook_secret:
            headers["X-Signature"] = "sha256=" + hmac.new(self.webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return self._post("webhook_out", self.webhook_url, body, headers)

    def _slack(self, ctx: ActionContext) -> dict:
        if not self.slack_url:
            return result("slack", "skipped", "Slack webhook URL not configured")
        body = json.dumps({"text": slack_text(ctx.rule, ctx.record)}, ensure_ascii=False).encode("utf-8")
        return self._post("slack", self.slack_url, body, {"Content-Type": "application/json"})

    def _chime(self, ctx: ActionContext) -> dict:
        if not self.chime_enabled:
            return result("chime", "skipped", "chime flag is off")
        if self.chime is None:
            return result("chime", "skipped", "no chime backend configured")
        device = ctx.event.device_id or ctx.trace.context.device_id
        if not device:
            return result("chime", "failed", "event has no device id")
        try:
            self.chime(device, self.chime_audio_ref)
        except Exception as e:
            return result("chime", "failed", f"{type(e).__name__}: {e}"[:300])
        return result("chime", "ok")

    # ------------------------------------------------------------------ HTTP with retries
    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=self.timeout_s, follow_redirects=False)
        return self._http

    def _delay(self, attempt: int, resp: Optional[httpx.Response]) -> float:
        if resp is not None and resp.status_code == 429:
            try:
                return min(float(resp.headers.get("retry-after", "")), self.max_backoff_s)
            except ValueError:
                pass
        return min(self.backoff_s * (2 ** attempt), self.max_backoff_s)

    def _post(self, action: str, url: str, body: bytes, headers: dict) -> dict:
        client, host = self._client(), _host(url)
        last = ""
        for attempt in range(self.retries + 1):
            resp: Optional[httpx.Response] = None
            try:
                resp = client.post(url, content=body, headers=headers)
            except httpx.HTTPError as e:                              # transport errors, timeouts
                last = type(e).__name__
            else:
                if 200 <= resp.status_code < 300:
                    tries = f" after {attempt + 1} attempts" if attempt else ""
                    return result(action, "ok", f"HTTP {resp.status_code} from {host}{tries}")
                last = f"HTTP {resp.status_code}"
                if resp.status_code not in RETRY_STATUS:
                    return result(action, "failed", f"{last} from {host} (not retried)")
            if attempt < self.retries:
                self._sleep(self._delay(attempt, resp))
        return result(action, "failed", f"{last} from {host} after {self.retries + 1} attempts")
