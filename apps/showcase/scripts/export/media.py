"""Posters and frame sheets (SPEC 9.1): stills only, scaled and never cropped, no metadata.

Frames are taken from the clip file at the trace's own t_ms values (the frames Claude perceived), with the engine's
ffmpeg and the same seek method as perception. The Ring watermark is part of the pixels and is never touched: no crop,
no overlay, no dimming. Extracted JPEGs are cached in the scratch folder (outside the repo) so a rerun is cheap.
"""
from __future__ import annotations

import io
import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from common import ExportError, SCRATCH
from exemplar.perception.sampling import _extract_jpeg

POSTER_W = 640
POSTER_MAX = 60 * 1024
CELL_W, CELL_H = 320, 180
SHEET_MAX = 180 * 1024
CACHE = SCRATCH / "frames-cache"
FORBIDDEN_CHUNKS = (b"EXIF", b"XMP ", b"ICCP")


def _frame(path: Path, alias: str, t_ms: int) -> Image.Image:
    cache = CACHE / alias / f"{t_ms}.jpg"
    if cache.is_file():
        data = cache.read_bytes()
    else:
        data = _extract_jpeg(str(path), t_ms, None, POSTER_W)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
    img = Image.open(io.BytesIO(data))
    img.load()
    return img.convert("RGB")


def _save_under(img: Image.Image, dest: Path, limit: int) -> int:
    """WebP, highest quality that fits the byte budget. Pillow writes no EXIF/XMP/ICC unless asked."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    for q in (80, 72, 64, 56, 48, 40, 32):
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=q, method=6)
        if buf.tell() <= limit:
            dest.write_bytes(buf.getvalue())
            return q
    raise ExportError(f"{dest.name}: cannot fit the {limit} byte budget")


def _cell(img: Image.Image) -> Image.Image:
    """Scale to fit 320x180 (never crop); pad with black only if the aspect differs."""
    w, h = img.size
    scale = min(CELL_W / w, CELL_H / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    small = img.resize((nw, nh), Image.LANCZOS)
    if (nw, nh) == (CELL_W, CELL_H):
        return small
    cell = Image.new("RGB", (CELL_W, CELL_H), (0, 0, 0))
    cell.paste(small, ((CELL_W - nw) // 2, (CELL_H - nh) // 2))
    return cell


def make_media(alias: str, path: Path, times_ms: list[int], out_dir: Path) -> dict:
    """Write posters/<alias>.webp and sheets/<alias>.webp; returns their sizes."""
    if len(times_ms) != 16:
        raise ExportError(f"{alias}: expected 16 frame times")
    with ThreadPoolExecutor(max_workers=4) as pool:
        frames = list(pool.map(lambda t: _frame(path, alias, t), times_ms))
    poster = frames[len(frames) // 2]
    if poster.width > POSTER_W:
        poster = poster.resize((POSTER_W, round(poster.height * POSTER_W / poster.width)), Image.LANCZOS)
    pq = _save_under(poster, out_dir / "posters" / f"{alias}.webp", POSTER_MAX)
    sheet = Image.new("RGB", (CELL_W * 4, CELL_H * 4), (0, 0, 0))
    for i, f in enumerate(frames):
        sheet.paste(_cell(f), ((i % 4) * CELL_W, (i // 4) * CELL_H))
    sq = _save_under(sheet, out_dir / "sheets" / f"{alias}.webp", SHEET_MAX)
    return {"poster_q": pq, "sheet_q": sq}


def webp_chunks(path: Path) -> list[bytes]:
    """RIFF chunk fourccs of a WebP file (used to prove there is no EXIF/XMP/ICC chunk)."""
    b = path.read_bytes()
    if b[:4] != b"RIFF" or b[8:12] != b"WEBP":
        raise ExportError(f"{path.name}: not a WebP file")
    out, i = [], 12
    while i + 8 <= len(b):
        out.append(b[i:i + 4])
        (n,) = struct.unpack("<I", b[i + 4:i + 8])
        i += 8 + n + (n & 1)
    return out


def check_media_dir(media_dir: Path) -> dict:
    """Metadata and size checks on every image under the media dir."""
    n, total = 0, 0
    for p in sorted(media_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix != ".webp":
            raise ExportError(f"unexpected file type in media: {p.name}")
        bad = [c for c in webp_chunks(p) if c in FORBIDDEN_CHUNKS]
        if bad:
            raise ExportError(f"{p.name}: metadata chunk present")
        with Image.open(p) as im:
            if im.info.get("exif") or im.info.get("xmp") or im.info.get("icc_profile"):
                raise ExportError(f"{p.name}: metadata present")
        size = p.stat().st_size
        limit = POSTER_MAX if p.parent.name == "posters" else SHEET_MAX
        if size > limit:
            raise ExportError(f"{p.name}: {size} bytes exceeds {limit}")
        n += 1
        total += size
    return {"files": n, "bytes": total}
