"""Deny-scans (SPEC 4.8): Scan V (exact original values, built in memory from the databases) and Scan S (shapes).

    uv run --project engine python apps/showcase/scripts/scan/denyscan.py [--out PATH] [--root PATH ...]

Default roots: apps/showcase/data, apps/showcase/public/media, apps/showcase/lib/data and the export/scan scripts.
`--out` adds a built `out/` folder. Text files (and gzip-compressed ones, decompressed) get both scans; images get
a filename check, a metadata check and a byte search for the long original values. Findings print the file, line and
the kind of match, never the value. Exit code 1 on any hit.

Exempt by path only: this file and denylist.py (they contain the patterns), and inputs.local.json (untracked, holds
this machine's folder names and is never published).
"""
from __future__ import annotations

import argparse
import gzip
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from denylist import Denylist, build_denylist, shape_findings   # noqa: E402

SHOWCASE = Path(__file__).resolve().parents[2]
EXEMPT_NAMES = {"denylist.py", "denyscan.py", "inputs.local.json"}
SKIP_DIRS = {"node_modules", ".next", ".cache", "__pycache__", ".git"}
TEXT_EXT = {".json", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".md", ".txt", ".css", ".html", ".svg", ".py", ".yml",
            ".yaml", ".map", ".xml", ".csv", ".jsonl", ".mdx"}
IMAGE_EXT = {".webp", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".avif"}
FORBIDDEN_CHUNKS = (b"EXIF", b"XMP ", b"ICCP")
# In a built out/ folder: Next's main and polyfill bundles carry a dummy base URL ("http://n") and the test vectors of the
# URL polyfill ("https://a@b", "localhost"), and the build id names a folder. Those are the framework's strings, not site
# content, so the host-and-URL shapes are waived for those bundles and the random build-id folder is not treated as a
# token. Scan V (the exact original values) and every other shape still apply to both.
FRAMEWORK_BUNDLE = re.compile(r"(^|/)_next/static/chunks/(main|main-app|polyfills)-[0-9a-f]+\.js$")
WAIVED_IN_FRAMEWORK = {"url-not-allowlisted", "local-host"}
# The opt-in Z3 (out/z3/<version>/): Emscripten's generated glue script (URLs in its comments and strings, long
# base64-like tables) and our esbuild bundle of lib/synth/z3/worker.ts (minified onto one line, so its identifiers read
# as token runs). Both are generated from sources the scan already covers unminified (node_modules is vendored code, lib/
# is scanned as written), so the same three shape checks are waived for them; Scan V (the exact original values) and
# every other shape still apply, and the .wasm is byte-searched like any binary.
Z3_ASSET = re.compile(r"(^|/)z3/\d+\.\d+\.\d+/(z3-built|z3-worker\.[0-9a-f]+)\.js$")
WAIVED_IN_Z3 = {"url-not-allowlisted", "local-host", "opaque-token-shape"}
BUILD_ID_DIR = re.compile(r"(^|/)(_next/static/)[A-Za-z0-9_-]{21}/")


def default_roots() -> list[Path]:
    return [SHOWCASE / "data", SHOWCASE / "public" / "media", SHOWCASE / "lib" / "data",
            SHOWCASE / "scripts" / "export", SHOWCASE / "scripts" / "scan"]


def iter_files(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("*")):
        if p.is_file() and not (set(p.relative_to(root).parts[:-1]) & SKIP_DIRS):
            yield p


def _text_hits(deny: Denylist, text: str) -> list[tuple[int, list[str]]]:
    """(line number, kinds) for every offending line; whole-text pre-check keeps clean files fast."""
    if not (deny.find_text(text) or shape_findings(text)):
        return []
    out = []
    for i, line in enumerate(text.splitlines(), start=1):
        kinds = deny.find_text(line) + shape_findings(line)
        if kinds:
            out.append((i, sorted(set(kinds))))
    return out or [(0, sorted(set(deny.find_text(text) + shape_findings(text))))]


def _webp_chunks(b: bytes) -> list[bytes]:
    out, i = [], 12
    while i + 8 <= len(b):
        out.append(b[i:i + 4])
        (n,) = struct.unpack("<I", b[i + 4:i + 8])
        i += 8 + n + (n & 1)
    return out


def scan_file(deny: Denylist, p: Path, rel: str) -> list[str]:
    findings: list[str] = []
    name = BUILD_ID_DIR.sub(lambda m: m.group(1) + m.group(2) + "BUILD/", rel)
    for kinds in (deny.find_text(rel), shape_findings(name)):
        if kinds:
            findings.append(f"{rel}: file name matches {sorted(set(kinds))}")
    ext = p.suffix.lower()
    if ext in IMAGE_EXT:
        b = p.read_bytes()
        if ext == ".webp":
            if b[:4] != b"RIFF" or b[8:12] != b"WEBP":
                findings.append(f"{rel}: not a WebP file")
            else:
                bad = [c.decode("ascii", "replace") for c in _webp_chunks(b) if c in FORBIDDEN_CHUNKS]
                if bad:
                    findings.append(f"{rel}: image metadata chunk(s) {bad}")
        elif ext in (".jpg", ".jpeg") and (b"Exif\x00" in b[:4096] or b"http://ns.adobe.com/xap" in b[:65536]):
            findings.append(f"{rel}: image metadata present")
        elif ext == ".png" and any(c in b for c in (b"tEXt", b"iTXt", b"zTXt", b"eXIf")):
            findings.append(f"{rel}: PNG text/EXIF chunk present")
        kinds = deny.find_bytes(b)
        if kinds:
            findings.append(f"{rel}: image bytes contain {kinds}")
        return findings
    if ext == ".gz":
        try:
            text = gzip.decompress(p.read_bytes()).decode("utf-8", "replace")
        except Exception:
            findings.append(f"{rel}: unreadable gzip")
            return findings
    elif ext in TEXT_EXT:
        text = p.read_text(encoding="utf-8", errors="replace")
    else:
        kinds = deny.find_bytes(p.read_bytes())
        if kinds:
            findings.append(f"{rel}: binary file contains {kinds}")
        return findings
    waived = WAIVED_IN_FRAMEWORK if FRAMEWORK_BUNDLE.search(rel) else WAIVED_IN_Z3 if Z3_ASSET.search(rel) else set()
    for line, kinds in _text_hits(deny, text):
        kinds = [k for k in kinds if k not in waived]
        if kinds:
            findings.append(f"{rel}:{line}: {kinds}")
    return findings


def scan(roots: list[Path], deny: Denylist | None = None) -> tuple[int, list[str]]:
    deny = deny or build_denylist()
    n, findings = 0, []
    for root in roots:
        if not root.exists():
            continue
        base = root if root.is_dir() else root.parent
        for p in iter_files(root):
            if p.name in EXEMPT_NAMES:
                continue
            n += 1
            rel = p.relative_to(SHOWCASE).as_posix() if SHOWCASE in p.parents else p.relative_to(base).as_posix()
            findings.extend(scan_file(deny, p, rel))
    return n, findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, help="a built out/ folder to scan as well")
    ap.add_argument("--root", type=Path, action="append", help="replace the default roots")
    a = ap.parse_args()
    roots = a.root or default_roots()
    if a.out:
        roots = roots + [a.out]
    deny = build_denylist()
    n, findings = scan(roots, deny)
    print(f"denyscan: {deny.n_values()} original values + shape patterns over {n} files "
          f"in {len([r for r in roots if r.exists()])} roots")
    for f in findings:
        print("  HIT", f)
    print("denyscan: " + ("FAIL" if findings else "clean"), f"({len(findings)} finding(s))")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
