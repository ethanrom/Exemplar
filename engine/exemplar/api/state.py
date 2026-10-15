"""`AppState`: everything the routes and background tasks share (one per FastAPI app)."""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from exemplar.contracts.dsl_ast import Rule
from exemplar.ring import AuthManager
from exemplar.settings import Settings, get_settings
from exemplar.store import RuleRow, Store

from . import cost as cost_mod
from .bus import MonitorBus, RunHub
from .config import ApiConfig
from .errors import NotAvailable
from .process import Processor
from .services import Services
from .tz import DEFAULT_TZ, tz_for_state

log = logging.getLogger("exemplar.api.state")

DATA_SUBDIRS = ("clips", "snapshots", "live", "uploads")


class AppState:
    def __init__(self, *, settings: Settings | None = None, config: ApiConfig | None = None,
                 store: Store | None = None, services: Services | None = None,
                 auth: AuthManager | None = None) -> None:
        self.settings = settings or get_settings()
        self.config = config or ApiConfig.from_env()
        self.data_dir = Path(self.settings.data_dir)
        for sub in DATA_SUBDIRS:
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)
        self.store = store or Store(self.settings.db_path)
        self.services = services or Services()
        self.auth = auth or AuthManager.from_settings(self.settings, store=self.store.auth)
        self.bus = MonitorBus()
        self.run_hub = RunHub()
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="exemplar")
        self.processor = Processor(self)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.started_at_ms = int(time.time() * 1000)
        self.cancel_events: dict[str, threading.Event] = {}
        self.teach_lock = threading.Lock()
        self.question_cache: dict[Any, Any] = {}
        self._monitor: Any = None
        self._monitor_lock = threading.RLock()
        self._device_tz: dict[str, str] = {}
        self._ring: Any = None
        self.oauth_pending: dict[str, tuple[str, str, float]] = {}   # state -> (code_verifier, redirect_uri, t)
        from .ingest import IngestPipeline          # late: ingest imports this module's types
        self.pipeline = IngestPipeline(self)

    # ------------------------------------------------------------------ paths
    def clip_path(self, clip_id: str, ext: str = ".mp4") -> Path:
        from .media import file_stem
        return self.data_dir / "clips" / f"{file_stem(clip_id)}{ext}"

    def snapshot_path(self, clip_id: str) -> Path:
        from .media import file_stem
        return self.data_dir / "snapshots" / f"{file_stem(clip_id)}.jpg"

    # ------------------------------------------------------------------ ring
    def ring(self) -> Any:
        """The shared Ring client (created lazily, inside the running event loop)."""
        if self._ring is None:
            self._ring = self.services.make_ring_client(self.auth, chime_enabled=self.config.chime_enabled)
        return self._ring

    async def close_ring(self) -> None:
        if self._ring is not None and hasattr(self._ring, "aclose"):
            await self._ring.aclose()
        self._ring = None

    def tz_for_device(self, device_id: str | None) -> str:
        return self._device_tz.get(device_id or "", self.config.default_timezone or DEFAULT_TZ)

    def note_device_location(self, device_id: str, attrs: dict[str, Any]) -> str:
        tz = tz_for_state(attrs.get("state"), attrs.get("country") or "US", self.config.default_timezone)
        self._device_tz[device_id] = tz
        return tz

    # ------------------------------------------------------------------ monitor
    def deployed_rule(self, row: RuleRow) -> Any:
        """E's `DeployedRule` for a stored rule."""
        return self.services.deployed_rule_cls(
            rule_id=row.id, concept_id=row.concept_id, rule=Rule.model_validate_json(row.ast_json),
            tau=float(row.tau if row.tau is not None else 0.0), delta=float(row.delta),
            actions=tuple(row.actions) or ("ui",), english=row.english)

    def get_monitor(self) -> Any:
        """The (lazily created) E `Monitor`, with every `deployed` rule registered. Raises NotAvailable."""
        with self._monitor_lock:
            if self._monitor is None:
                cls = self.services.monitor_cls
                kwargs: dict[str, Any] = dict(
                    perceive_fast=self.processor.perceive_fast, perceive_strong=self.processor.perceive_strong,
                    on_firing=self.processor.on_firing, on_event=self.processor.on_monitor_event)
                runner = self.services.make_action_runner(self)
                if runner is not None:
                    kwargs["actions"] = runner
                mon = cls(**kwargs)
                for row in self.store.rules.deployed():
                    mon.deploy(self.deployed_rule(row))
                self._monitor = mon
            return self._monitor

    def monitor_if_ready(self) -> Any | None:
        with self._monitor_lock:
            return self._monitor

    def deploy_rule(self, row: RuleRow) -> None:
        with self._monitor_lock:
            created_now = self._monitor is None
            mon = self.get_monitor()                  # a new monitor already registered every `deployed` rule in the DB
            if not created_now or row.status != "deployed":
                mon.deploy(self.deployed_rule(row))

    def undeploy_rule(self, rule_id: str) -> None:
        with self._monitor_lock:
            if self._monitor is not None:
                self._monitor.undeploy(rule_id)

    # ------------------------------------------------------------------ cost
    def cost_summary(self) -> dict[str, Any]:
        mon_cost = None
        mon = self.monitor_if_ready()
        if mon is not None:
            try:
                mon_cost = mon.cost()
            except Exception:  # noqa: BLE001
                log.exception("monitor.cost() failed")
        # The meter is the cost of watching: perception spend of monitored events / number of monitored events.
        # Before any rule has scored an event, fall back to perception spend per ingested clip.
        n_monitored = self.store.firings.distinct_events()
        if n_monitored:
            totals, denom = self.store.cost.perception_totals(monitored_only=True), n_monitored
        else:
            totals, denom = self.store.cost.perception_totals(monitored_only=False), self.store.cost.distinct_clips()
        return cost_mod.summarize(totals, self.store.firings.stage_counts(), denom, mon_cost, per_event_denominator=denom)

    # ------------------------------------------------------------------ lifecycle
    def shutdown(self) -> None:
        for ev in list(self.cancel_events.values()):
            ev.set()
        self.executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["AppState", "NotAvailable"]
