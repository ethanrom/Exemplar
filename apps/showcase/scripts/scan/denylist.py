"""The exact-value deny set (Scan V) and the shape patterns (Scan S), shared by the export and the scanners.

The original values are collected **in memory only**, from the three read-only snapshots, and are never written to
disk. Only allow-listed *id and path* columns are read for this purpose: events.id / device_id, clips.id / path /
snapshot_path / sha256, traces.cache_key, and the ids of concepts, runs, rules and firings. ``events.raw_json``,
``ring_auth`` and ``webhook_deliveries`` are never selected: token values are therefore covered by shape (below),
not by value.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from inputs import load_inputs

_INPUTS = load_inputs()
SNAPSHOT_DIR = Path(_INPUTS["snapshots"])
SNAPSHOT_KEYS = ("recording", "heldout", "stills")


def path_roots() -> list[str]:
    """The machine's input folders and their top-level folders, lower-case (matched case-insensitively, with either
    slash direction)."""
    roots: set[str] = set()
    for k in ("snapshots", "main_checkout", "scratch"):
        posix = Path(_INPUTS[k]).as_posix().lower()
        roots.add(posix)
        parts = posix.split("/")
        if len(parts) >= 2:
            roots.add("/".join(parts[:2]))           # the drive plus its first folder
    out: set[str] = set()
    for r in roots:
        out.add(r)
        out.add(r.replace("/", "\\"))
    return sorted(out)


def _load(key: str) -> sqlite3.Connection:
    p = SNAPSHOT_DIR / f"{key}.sqlite3"
    src = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    db = sqlite3.connect(":memory:")
    src.backup(db)
    src.close()
    return db


# ---------------------------------------------------------------------------------------------- shapes (Scan S)
SHAPES: dict[str, re.Pattern] = {k: re.compile(v, re.IGNORECASE) for k, v in {
    "ring-id-prefix": r"ava1\.",
    "ring-api-name": r"ring\.(device|history|account)",
    "access-token": r"access_token",
    "refresh-token": r"refresh_token",
    "bearer": r"\bBearer\s",
    "aws-signature": r"X-Amz-",
    "signature-param": r"Signature=",
    "arn": r"arn:aws",
    "aws-env": r"CLAUDE_AWS",
    "model-id": r"anthropic\.|claude-[0-9]|-v\d:\d",
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "windows-path": r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]",
    "author-path": r"kaskara|Sandaruwan|/Users/",
    "local-host": r"localhost|127\.0\.0\.1|:8787",
    "engine-id": r"\b(cn|ru|run)_[0-9a-f]{10}\b",
    "upload-id": r"\bup_[0-9a-f]{10}",
    "jwt": r"\beyJ[A-Za-z0-9_-]{8,}\.",
}.items()}
# Long opaque strings (tokens, hashes, signed-URL payloads). Case-sensitive on purpose.
OPAQUE = re.compile(r"(?<![A-Za-z0-9+/_=.-])[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9+/_=-])")

HEXDIGEST = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
URL = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)
ALLOWED_URL_PREFIXES = (
    "https://www.youtube.com/watch?v=TfTFu8lGrwk", "https://www.youtube.com/watch?v=MJP2iL7xLro",
    "https://youtube.com/", "https://www.youtube.com/", "https://youtu.be/",
    "https://github.com/ethanrom/Exemplar", "https://github.com/AmazonAppDev/ring-api-helloworld",
    "https://creativecommons.org/", "https://registry.opendata.aws/mevadata",
    "http://mevadata.org/", "https://mevadata.org/", "https://developer.amazon.com/", "https://www.w3.org/",
    "https://w3.org/", "https://vercel.com/docs", "https://ring.com/", "https://developer.ring.com/",
    # Public documentation and namespace URLs that React, Next and Tailwind carry in the built site (error messages,
    # SVG/MathML namespaces, licence banners). They are strings of the libraries, not site content.
    "http://www.w3.org/", "https://react.dev/errors/", "https://reactjs.org/docs/error-decoder.html",
    "https://nextjs.org/docs/", "https://github.com/zloirock/core-js", "https://tailwindcss.com",
)


def _looks_opaque(s: str) -> bool:
    """Token-like runs: mixed-case letters with digits, a hex run that is not a git/SHA-256 digest, or a long base32 run.
    Lower-case words joined by dashes (file and alias names) are not tokens."""
    if HEXDIGEST.fullmatch(s):
        return False
    if re.fullmatch(r"[0-9a-fA-F]{32,}", s) or re.fullmatch(r"[A-Z2-7]{40,}", s):
        return True
    return bool(re.search(r"[A-Z]", s) and re.search(r"[a-z]", s) and re.search(r"[0-9]", s) and len(set(s)) >= 12)


def url_findings(text: str) -> list[str]:
    out = []
    for m in URL.finditer(text):
        u = m.group(0).rstrip(".,;")
        if not u.startswith(ALLOWED_URL_PREFIXES):
            out.append("url-not-allowlisted")
    return out


def shape_findings(text: str) -> list[str]:
    """Names (never values) of the shapes found in ``text``."""
    out = [name for name, rx in SHAPES.items() if rx.search(text)]
    # 40- and 64-hex strings are git and SHA-256 digests (the manifest); real cache keys and file hashes are caught by value.
    if any(_looks_opaque(m.group(0)) for m in OPAQUE.finditer(text)):
        out.append("opaque-token-shape")
    out.extend(url_findings(text))
    return out


# ---------------------------------------------------------------------------------------------- exact values (Scan V)
@dataclass
class Denylist:
    exact: dict[str, str] = field(default_factory=dict)         # value -> kind (case-sensitive substrings)
    windows6: dict[str, str] = field(default_factory=dict)      # 6-char windows of device-id tails -> kind
    paths_ci: dict[str, str] = field(default_factory=dict)      # lower-case value -> kind (case-insensitive)

    def add(self, value: str | None, kind: str, *, min_len: int = 6) -> None:
        if not value or len(value) < min_len:
            return
        self.exact.setdefault(value, kind)

    def finalize(self) -> "Denylist":
        # shortest values first is irrelevant for `in`; keep deterministic order
        return self

    def n_values(self) -> int:
        return len(self.exact) + len(self.windows6) + len(self.paths_ci)

    def find_text(self, text: str) -> list[str]:
        """Kinds of original values present in ``text`` (never the values themselves)."""
        hits: list[str] = []
        if len(text) >= 6:
            for v, kind in self.exact.items():
                if len(v) <= len(text) and v in text:
                    hits.append(kind)
            for w, kind in self.windows6.items():
                if w in text:
                    hits.append(kind)
            low = text.lower()
            for v, kind in self.paths_ci.items():
                if v in low:
                    hits.append(kind)
        return sorted(set(hits))

    def find_bytes(self, blob: bytes) -> list[str]:
        """Same as ``find_text`` for binary files, minus the 6-char windows (too short to be meaningful in bytes)."""
        hits: set[str] = set()
        for v, kind in self.exact.items():
            if len(v) >= 12 and v.encode("utf-8") in blob:
                hits.add(kind)
        low = blob.lower()
        for v, kind in self.paths_ci.items():
            if v.encode("utf-8") in low:
                hits.add(kind)
        return sorted(hits)


def build_denylist(keys: Iterable[str] = SNAPSHOT_KEYS) -> Denylist:
    d = Denylist()
    for key in keys:
        db = _load(key)
        for (eid,) in db.execute("select id from events"):
            _add_event_id(d, eid)
        for (dev,) in db.execute("select distinct device_id from events where device_id is not null"):
            d.add(dev, "device-id")
            tail = dev.rsplit(".", 1)[-1]
            for i in range(0, max(0, len(tail) - 5)):
                d.windows6.setdefault(tail[i:i + 6], "device-id-fragment")
            d.add(tail, "device-id-tail")
        for cid, path, snap, sha in db.execute("select id, path, snapshot_path, sha256 from clips"):
            _add_event_id(d, cid)
            for p in (path, snap):
                if p:
                    d.add(p, "local-path")
                    d.add(p.replace("\\", "/"), "local-path")
                    d.add(Path(p).name, "local-file-name", min_len=10)
            d.add(sha, "file-hash", min_len=16)
        for (ck,) in db.execute("select cache_key from traces where cache_key is not null"):
            d.add(ck, "cache-key", min_len=16)
        for table, kind in (("concepts", "concept-id"), ("runs", "run-id"), ("rules", "rule-id"), ("firings", "firing-id")):
            for (i,) in db.execute(f"select id from {table}"):
                d.add(i, kind, min_len=8)
        db.close()
    for root in path_roots():
        d.paths_ci[root] = "path-root"
    return d.finalize()


def _add_event_id(d: Denylist, eid: str) -> None:
    d.add(eid, "event-id", min_len=8)
    if eid.startswith("up_"):
        parts = eid.split("_")
        if len(parts) >= 2:
            d.add(parts[1], "upload-hash", min_len=10)
        return
    if len(eid) >= 40:
        d.add(eid[:27], "event-id-prefix")
        d.add(eid[-16:], "event-id-tail")
