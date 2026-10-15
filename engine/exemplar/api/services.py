"""`Services`: the injection point for everything owned by other streams.

D (`exemplar.synth`, `exemplar.agent`) and E (`exemplar.active`, `exemplar.calibrate`, `exemplar.monitor`) were
not merged when this was written, so nothing from them is imported at module load. Each capability is resolved
on first use (`importlib`), and a missing module surfaces as `NotAvailable` -> HTTP 503
`{"error": "... not available yet"}`. Tests (and the integrator) pass their own callables:

    Services(run_cegis=fake_cegis, example_cls=Example, calibrate=fake_calibrate, disable=("monitor_cls",))

Names follow docs/streams/phase2-interfaces.md exactly.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Callable

from .errors import NotAvailable

log = logging.getLogger("exemplar.api.services")

# key -> (module, attribute, human label for the 503 message)
_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "perceive": ("exemplar.perception", "perceive_detailed", "perception"),
    "run_cegis": ("exemplar.agent", "run_cegis", "synthesis agent (exemplar.agent)"),
    "example_cls": ("exemplar.synth", "Example", "synthesis (exemplar.synth)"),
    "candidate_cls": ("exemplar.synth", "Candidate", "synthesis (exemplar.synth)"),
    "build_committee": ("exemplar.active", "build_committee", "active learning (exemplar.active)"),
    "select_query": ("exemplar.active", "select_query", "active learning (exemplar.active)"),
    "calibrate": ("exemplar.calibrate", "calibrate", "calibration (exemplar.calibrate)"),
    "monitor_cls": ("exemplar.monitor", "Monitor", "monitor (exemplar.monitor)"),
    "deployed_rule_cls": ("exemplar.monitor", "DeployedRule", "monitor (exemplar.monitor)"),
    "event_input_cls": ("exemplar.monitor", "EventInput", "monitor (exemplar.monitor)"),
}
_OPTIONAL: dict[str, tuple[str, str]] = {
    "render_trace_text": ("exemplar.synth", "render_trace_text"),
    "action_runner_cls": ("exemplar.monitor", "ActionRunner"),
}


class Services:
    """Lazy capability container. Constructor kwargs override the defaults; `disable=` forces a 503."""

    def __init__(self, *, disable: tuple[str, ...] = (), ring_factory: Callable[[Any], Any] | None = None,
                 action_runner_factory: Callable[[Any], Any] | None = None, **overrides: Any) -> None:
        unknown = set(overrides) - set(_DEFAULTS) - set(_OPTIONAL)
        if unknown:
            raise TypeError(f"unknown service(s): {sorted(unknown)}")
        self._o = dict(overrides)
        self._disabled = set(disable)
        self._ring_factory = ring_factory
        self._action_runner_factory = action_runner_factory
        self._cache: dict[str, Any] = {}

    # ------------------------------------------------------------------ resolution
    def get(self, key: str) -> Any:
        """The capability, or raise `NotAvailable`."""
        if key in self._disabled:
            raise NotAvailable(_DEFAULTS.get(key, ("", "", key))[2])
        if key in self._o:
            return self._o[key]
        if key in self._cache:
            return self._cache[key]
        module, attr, label = _DEFAULTS[key]
        try:
            val = getattr(importlib.import_module(module), attr)
        except (ImportError, AttributeError) as e:
            log.info("service %s unavailable: %s", key, e)
            raise NotAvailable(label) from e
        self._cache[key] = val
        return val

    def maybe(self, key: str) -> Any | None:
        """Like `get` but returns None instead of raising (optional capabilities)."""
        if key in self._disabled:
            return None
        if key in self._o:
            return self._o[key]
        if key in self._cache:
            return self._cache[key]
        spec = _OPTIONAL.get(key) or _DEFAULTS[key][:2]
        try:
            val = getattr(importlib.import_module(spec[0]), spec[1])
        except (ImportError, AttributeError):
            return None
        self._cache[key] = val
        return val

    def available(self, key: str) -> bool:
        try:
            self.get(key)
            return True
        except NotAvailable:
            return False

    # ------------------------------------------------------------------ named accessors
    @property
    def perceive(self) -> Callable[..., Any]:
        return self.get("perceive")

    @property
    def run_cegis(self) -> Callable[..., Any]:
        return self.get("run_cegis")

    @property
    def example_cls(self) -> Callable[..., Any]:
        return self.get("example_cls")

    @property
    def candidate_cls(self) -> Callable[..., Any]:
        return self.get("candidate_cls")

    @property
    def build_committee(self) -> Callable[..., Any]:
        return self.get("build_committee")

    @property
    def select_query(self) -> Callable[..., Any]:
        return self.get("select_query")

    @property
    def calibrate(self) -> Callable[..., Any]:
        return self.get("calibrate")

    @property
    def monitor_cls(self) -> Callable[..., Any]:
        return self.get("monitor_cls")

    @property
    def deployed_rule_cls(self) -> Callable[..., Any]:
        return self.get("deployed_rule_cls")

    @property
    def event_input_cls(self) -> Callable[..., Any]:
        return self.get("event_input_cls")

    @property
    def render_trace_text(self) -> Callable[..., str] | None:
        return self.maybe("render_trace_text")

    # ------------------------------------------------------------------ factories
    def make_ring_client(self, auth: Any, *, chime_enabled: bool = False) -> Any:
        """A `RingClient` bound to the shared `AuthManager` (tests inject a fake)."""
        if self._ring_factory is not None:
            return self._ring_factory(auth)
        from exemplar.ring import RingClient
        return RingClient(auth, chime_enabled=chime_enabled)

    def make_action_runner(self, state: Any) -> Any | None:
        """The `ActionRunner` handed to the Monitor.

        An injected factory wins. Otherwise, when the real `exemplar.monitor` is in use (no `monitor_cls`
        override), build E's runner from the config: Slack / outbound webhook URLs and the chime flag, with chime
        playback going through the app's Ring client on the app's event loop (`chime_via_ring_client`).
        """
        if self._action_runner_factory is not None:
            return self._action_runner_factory(state)
        if "monitor_cls" in self._o:
            return None
        try:
            from exemplar.monitor import ActionRunner, chime_via_ring_client
        except ImportError:
            return None
        cfg = state.config
        chime = None
        if cfg.chime_enabled and state.loop is not None:
            chime = chime_via_ring_client(state.ring(), loop=state.loop)
        return ActionRunner(webhook_url=cfg.webhook_out_url, webhook_secret=cfg.webhook_out_secret,
                            slack_url=cfg.slack_webhook_url, chime=chime, chime_audio_ref=cfg.chime_audio_ref,
                            chime_enabled=cfg.chime_enabled)
