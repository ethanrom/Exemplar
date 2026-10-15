"""Anonymous access to the MEVA bucket (AWS Open Data, us-east-1) with boto3: listing + resumable download."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from . import paths

_KEY_RE = re.compile(r"^drops-123-r13/(?P<date>[\d-]+)/(?P<hour>\d{2})/(?P<stem>.+)\.r13\.avi$")


@dataclass(frozen=True)
class S3Video:
    stem: str
    key: str
    size: int
    date: str
    hour: str  # S3 folder hour; can differ from the clip's start hour


def client():
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    return boto3.client("s3", region_name="us-east-1", config=Config(signature_version=UNSIGNED, retries={"max_attempts": 8, "mode": "standard"}))


def list_videos(refresh: bool = False, cache: Path | None = None) -> dict[str, S3Video]:
    """All `*.r13.avi` objects under drops-123-r13/ keyed by clip stem (cached as JSON under the data dir)."""
    cache = cache or paths.meva_dir() / "s3_listing.json"
    if cache.is_file() and not refresh:
        rows = json.loads(cache.read_text(encoding="utf-8"))
    else:
        rows = []
        pager = client().get_paginator("list_objects_v2")
        for page in pager.paginate(Bucket=paths.S3_BUCKET, Prefix=paths.S3_PREFIX):
            for o in page.get("Contents", []):
                if o["Key"].endswith(".r13.avi"):
                    rows.append({"key": o["Key"], "size": o["Size"]})
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rows), encoding="utf-8")
    out: dict[str, S3Video] = {}
    for r in rows:
        m = _KEY_RE.match(r["key"])
        if m:
            out[m["stem"]] = S3Video(m["stem"], r["key"], r["size"], m["date"], m["hour"])
    return out


def download(key: str, dest: Path, size: int, chunk: int = 1 << 20, retries: int = 6) -> str:
    """Resumable download to `dest` via `dest.part` + ranged GETs. Returns 'skipped' | 'downloaded' | 'resumed'."""
    if dest.is_file() and dest.stat().st_size == size:
        return "skipped"
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    s3 = client()
    resumed = part.is_file() and part.stat().st_size > 0
    for attempt in range(retries):
        have = part.stat().st_size if part.is_file() else 0
        if have > size:  # corrupt partial
            part.unlink()
            have = 0
        if have == size:
            break
        try:
            resp = s3.get_object(Bucket=paths.S3_BUCKET, Key=key, Range=f"bytes={have}-")
            with part.open("ab") as fh:
                for buf in resp["Body"].iter_chunks(chunk):
                    fh.write(buf)
        except Exception:  # network hiccup: back off and resume from what we have
            time.sleep(min(2**attempt, 30))
            continue
        break
    if not part.is_file() or part.stat().st_size != size:
        raise IOError(f"incomplete download for {key}: {part.stat().st_size if part.is_file() else 0}/{size} bytes")
    part.replace(dest)
    return "resumed" if resumed else "downloaded"
