"""Phase 0 spike: probe the Ring Developer Playground (PLAN.md §5, questions 1, 2, 4).

Throwaway tooling — the real client is stream A's `engine/exemplar/ring/`.

    engine/.venv/Scripts/python scripts/spikes/ring_probe.py info
    engine/.venv/Scripts/python scripts/spikes/ring_probe.py watch --minutes 20
    engine/.venv/Scripts/python scripts/spikes/ring_probe.py chime

Token: $RING_PLAYGROUND_TOKEN, else the file given by --token-file (default: <repo>/token).
Everything (status codes, headers, bodies, media) is written under data/spike/ring/.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

import httpx

API = "https://api.amazonvision.com"
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "spike" / "ring"
FILTERS = ["", "motion", "motion.human", "motion.vehicle", "motion.other_motion", "ding", "on_demand"]


def load_token(path: Path) -> str:
    tok = os.environ.get("RING_PLAYGROUND_TOKEN") or path.read_text().strip()
    return tok


def claims(tok: str) -> dict:
    p = tok.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))


def log(rec: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.time(), **rec}
    with (OUT / "log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec)[:400])


class Ring:
    def __init__(self, tok: str):
        self.c = httpx.Client(base_url=API, headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        self.raw = httpx.Client(timeout=60)  # pre-signed URLs: no auth header

    def get(self, path: str, **params) -> httpx.Response:
        r = self.c.get(path, params=params or None)
        log({"op": "GET", "path": path, "params": params, "status": r.status_code, "body": r.text[:2000]})
        return r

    def media(self, kind: str, device: str, body: dict, dest: Path) -> tuple[int, dict]:
        """POST …/media/{kind}/download, then GET the 303 Location without auth."""
        r = self.c.post(f"/v1/devices/{device}/media/{kind}/download", json=body, follow_redirects=False)
        rec = {"op": f"{kind}_download", "body": body, "post_status": r.status_code}
        if r.status_code != 303:
            log({**rec, "resp": r.text[:500]})
            return r.status_code, {}
        loc = r.headers["location"]
        rec["location_host"] = httpx.URL(loc).host
        g = self.raw.get(loc)
        hdrs = {k: v for k, v in g.headers.items() if k.lower().startswith("x-media") or k.lower() == "content-type"}
        rec.update(get_status=g.status_code, headers=hdrs, bytes=len(g.content))
        if g.status_code in (200, 206):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(g.content)
            rec["saved"] = str(dest.relative_to(ROOT))
        else:
            rec["resp"] = g.text[:500]
        log(rec)
        return g.status_code, hdrs


def media_with_backoff(ring: Ring, kind: str, device: str, body: dict, dest: Path, budget_s: float = 150) -> int:
    """Retry 416/425/5xx with exponential backoff (PLAN.md §2.7: ~2 min)."""
    delay, t0 = 2.0, time.time()
    while True:
        status, _ = ring.media(kind, device, body, dest)
        if status in (200, 206) or status not in (416, 425, 500, 503) or time.time() - t0 > budget_s:
            return status
        time.sleep(delay)
        delay = min(delay * 2, 30)


def device_id(ring: Ring) -> str:
    r = ring.get("/v1/devices", include="status,capabilities,configurations")
    r.raise_for_status()
    return r.json()["data"][0]["id"]


def cmd_info(ring: Ring, tok: str) -> None:
    c = claims(tok)
    print(f"token iat={c.get('iat')} exp={c.get('exp')} expires_in={int(c['exp'] - time.time())}s")
    ring.get("/v1/users/me")
    dev = device_id(ring)
    for sub in ("status", "capabilities", "configurations", "location"):
        ring.get(f"/v1/devices/{dev}/{sub}")
    ring.get(f"/v1/history/devices/{dev}/events")


def cmd_watch(ring: Ring, tok: str, minutes: float, poll_s: float) -> None:
    dev = device_id(ring)
    exp = claims(tok)["exp"]
    seen: dict[str, dict] = {}
    end = min(time.time() + minutes * 60, exp - 30)
    print(f"watching history for {int(end - time.time())}s — trigger Playground events now")
    while time.time() < end:
        for flt in FILTERS:
            params = {"event_types": flt} if flt else {}
            try:
                r = ring.c.get(f"/v1/history/devices/{dev}/events", params=params or None)
            except httpx.TransportError as e:   # seen: RemoteProtocolError "Server disconnected"
                log({"op": "history", "filter": flt, "transport_error": repr(e)})
                continue
            if r.status_code != 200:
                log({"op": "history", "filter": flt, "status": r.status_code, "body": r.text[:500]})
                continue
            for ev in r.json().get("data", []):
                eid, a = ev["id"], ev["attributes"]
                if eid not in seen:
                    seen[eid] = {"attributes": a, "filters": set(), "first_seen": time.time()}
                    log({"op": "new_event", "id": eid, "attributes": a,
                         "seen_lag_s": round(time.time() - a["start"] / 1000, 1)})
                seen[eid]["filters"].add(flt or "*")
        for eid, s in seen.items():
            if s.get("fetched"):
                continue
            a = s["attributes"]
            end_ms = a.get("end") or a["start"] + 30_000
            if time.time() * 1000 < end_ms + 5_000:  # PLAN.md §2.7: wait clip end + 5 s
                continue
            s["fetched"] = True
            d = OUT / eid[-16:]
            (d).mkdir(parents=True, exist_ok=True)
            (d / "event.json").write_text(json.dumps({**a, "id": eid, "filters": sorted(s["filters"])}, indent=2))
            log({"op": "fetch_media", "id": eid, "filters": sorted(s["filters"])})
            media_with_backoff(ring, "image", dev, {"type": "at_timestamp", "timestamp": a["start"]}, d / "snapshot.jpg")
            media_with_backoff(ring, "video", dev, {"timestamp": a["start"], "duration": max(1000, end_ms - a["start"])},
                               d / "clip.mp4")
        time.sleep(poll_s)
    print(json.dumps({k[-16:]: {"filters": sorted(v["filters"]), **v["attributes"]} for k, v in seen.items()}, indent=2))


def cmd_chime(ring: Ring) -> None:
    dev = device_id(ring)
    conf = ring.get(f"/v1/devices/{dev}/configurations")
    slots = []
    try:
        slots = conf.json()["data"]["attributes"].get("audio", {}).get("customizable_slots", [])
    except Exception:  # noqa: BLE001 — spike: shape unknown, log and carry on
        pass
    ref = (slots[0].get("audio_ref") if slots else None) or "spike-probe"
    r = ring.c.post(f"/v1/devices/{dev}/media/audio/playback",
                    json={"data": {"type": "audio", "attributes": {"audio_ref": ref}}})
    log({"op": "chime", "audio_ref": ref, "status": r.status_code, "body": r.text[:1000]})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["info", "watch", "chime"])
    ap.add_argument("--token-file", type=Path, default=ROOT / "token")
    ap.add_argument("--minutes", type=float, default=20)
    ap.add_argument("--poll", type=float, default=5)
    a = ap.parse_args()
    tok = load_token(a.token_file)
    if claims(tok)["exp"] < time.time():
        sys.exit("token expired — paste a fresh Playground token")
    ring = Ring(tok)
    if a.cmd == "info":
        cmd_info(ring, tok)
    elif a.cmd == "watch":
        cmd_watch(ring, tok, a.minutes, a.poll)
    else:
        cmd_chime(ring)


if __name__ == "__main__":
    main()
