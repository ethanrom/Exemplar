"""Shared runtime settings. Reads `.env` once; every stream uses this instead of its own loader.

Resolution order for the dotenv file: $EXEMPLAR_DOTENV, then the first `.env` found walking up from
the current directory, then the repo root. Worktrees set EXEMPLAR_DOTENV / EXEMPLAR_DATA_DIR to the
main checkout so secrets and large data are never copied.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]


def _dotenv_path() -> Path | None:
    if os.environ.get("EXEMPLAR_DOTENV"):
        return Path(os.environ["EXEMPLAR_DOTENV"])
    for d in [Path.cwd(), *Path.cwd().parents]:
        if (d / ".env").is_file():
            return d / ".env"
    return REPO_ROOT / ".env" if (REPO_ROOT / ".env").is_file() else None


@dataclass(frozen=True)
class Settings:
    aws_access_key: str | None
    aws_secret_key: str | None
    aws_region: str | None
    strong_model: str | None        # CLAUDE_AWS_MODEL — never log or hard-code
    fast_model: str | None          # CLAUDE_AWS_FAST_MODEL
    model_alias: str | None         # CLAUDE_AWS_MODEL_ALIAS — the only model name safe to display/store
    ring_token: str | None          # Playground token: $RING_PLAYGROUND_TOKEN, else the `token` file
    ring_client_id: str | None
    ring_client_secret: str | None
    ring_webhook_signing_key: str | None
    data_dir: Path                  # $EXEMPLAR_DATA_DIR, default <repo>/data
    db_path: Path
    engine_host: str
    engine_port: int

    def boto3_session(self):
        import boto3
        return boto3.Session(aws_access_key_id=self.aws_access_key, aws_secret_access_key=self.aws_secret_key,
                             region_name=self.aws_region)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    path = _dotenv_path()
    if path:
        load_dotenv(path, override=False)
    env = os.environ.get
    data_dir = Path(env("EXEMPLAR_DATA_DIR") or REPO_ROOT / "data")
    token = env("RING_PLAYGROUND_TOKEN")
    token_file = Path(env("RING_TOKEN_FILE") or (path.parent if path else REPO_ROOT) / "token")
    if not token and token_file.is_file():
        token = token_file.read_text(encoding="utf-8").strip() or None
    return Settings(
        aws_access_key=env("CLAUDE_AWS_ACCESS_KEY"), aws_secret_key=env("CLAUDE_AWS_SECRET_KEY"),
        aws_region=env("CLAUDE_AWS_REGION"), strong_model=env("CLAUDE_AWS_MODEL"),
        fast_model=env("CLAUDE_AWS_FAST_MODEL"), model_alias=env("CLAUDE_AWS_MODEL_ALIAS"),
        ring_token=token, ring_client_id=env("RING_CLIENT_ID"), ring_client_secret=env("RING_CLIENT_SECRET"),
        ring_webhook_signing_key=env("RING_WEBHOOK_SIGNING_KEY"),
        data_dir=data_dir, db_path=Path(env("EXEMPLAR_DB") or data_dir / "exemplar.sqlite3"),
        engine_host=env("EXEMPLAR_HOST") or "127.0.0.1", engine_port=int(env("EXEMPLAR_PORT") or 8787),
    )
