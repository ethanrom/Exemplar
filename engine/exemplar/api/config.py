"""Tunables of the API service (everything that is not a secret and not in `exemplar.settings`)."""
from __future__ import annotations

import os
from dataclasses import dataclass, fields


def configure_logging(level: str = "INFO") -> None:
    """basicConfig for the CLIs, with the HTTP client loggers capped at WARNING.

    httpx logs every request URL at INFO, and Ring's pre-signed media URLs carry a `security_token` query value
    (a credential for 15 minutes): they must never reach a log file.
    """
    import logging
    import re
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore", "urllib3", "botocore", "boto3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    secret_q = re.compile(r"(?i)\b(code|state|access_token|security_token|code_verifier)=[^&\s\"]+")

    class RedactQuery(logging.Filter):
        """uvicorn's access log prints the full request line: the OAuth callback's `?code=` is a credential."""
        def filter(self, record: logging.LogRecord) -> bool:
            if isinstance(record.args, tuple):
                record.args = tuple(secret_q.sub(r"\1=***", a) if isinstance(a, str) else a for a in record.args)
            return True

    logging.getLogger("uvicorn.access").addFilter(RedactQuery())


@dataclass
class ApiConfig:
    # --- Ring ingest
    poll_interval_s: float = 15.0            # history poll while a valid token exists
    poll_enabled: bool = True
    clip_grace_s: float = 5.0                # download after clip end + 5 s
    webhook_assumed_clip_s: float = 10.0     # webhook events carry no end time: assume a 10 s clip
    initial_sync_limit: int = 50             # newest events imported on the very first sync
    device_cache_s: float = 300.0
    dedupe_window_ms: int = 5_000            # a poll hit within this of a webhook event is the same physical event
    # --- perception
    perception_concurrency: int = 2          # max 2 concurrent Bedrock calls
    fast_frames: int = 16
    strong_frames: int = 32
    # --- teach
    cegis_k: int = 6
    cegis_rounds: int = 4
    committee_samples: int = 200
    # --- live / uploads
    max_frame_bytes: int = 8 * 1024 * 1024
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024
    max_windows: int = 200
    # --- misc
    auth_expiring_s: float = 300.0           # `auth_expiring` MonitorEvent 5 min before a Playground token expires
    auth_check_interval_s: float = 15.0
    sse_ping_s: float = 15.0
    ui_url: str = "http://localhost:3000/"   # where the OAuth callback sends the browser back to
    default_timezone: str = "America/Los_Angeles"
    # --- rule actions (used by the monitor's ActionRunner); URLs / secrets are credentials: env only, never logged
    chime_enabled: bool = False              # early-access Ring chime playback; the Playground answers 400
    chime_audio_ref: str = "default"
    slack_webhook_url: str | None = None     # EXEMPLAR_SLACK_WEBHOOK_URL
    webhook_out_url: str | None = None       # EXEMPLAR_WEBHOOK_OUT_URL
    webhook_out_secret: str | None = None    # EXEMPLAR_WEBHOOK_OUT_SECRET (HMAC key for X-Signature)

    @classmethod
    def from_env(cls) -> "ApiConfig":
        """`EXEMPLAR_<FIELD>` overrides, e.g. EXEMPLAR_POLL_INTERVAL_S=5, EXEMPLAR_POLL_ENABLED=0."""
        cfg = cls()
        for f in fields(cls):
            raw = os.environ.get(f"EXEMPLAR_{f.name.upper()}")
            if raw is None or raw == "":
                continue
            cur = getattr(cfg, f.name)
            if f.name.endswith(("_url", "_secret")):
                setattr(cfg, f.name, raw)
                continue
            if isinstance(cur, bool):
                val: object = raw.strip().lower() in ("1", "true", "yes", "on")
            elif isinstance(cur, int):
                val = int(raw)
            elif isinstance(cur, float):
                val = float(raw)
            else:
                val = raw
            setattr(cfg, f.name, val)
        return cfg
