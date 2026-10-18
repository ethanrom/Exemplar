"""claims.json: the few headline numbers the pages need, copied exactly as published in docs/DEVPOST.md.

Each claim names a phrase that must appear verbatim on exactly one line of the file. The line number and the line are
recorded as the source, so a reader can see where the number comes from. If the published text changes, rerunning
the export either follows it or stops here.
"""
from __future__ import annotations

from common import ExportError, REPO

SOURCE = "docs/DEVPOST.md"
# (id, needle that locates the line, display text copied from that line)
CLAIMS = (
    ("teach.duration_published", "This took under 30 seconds", "under 30 seconds"),
    ("cost.per_event_live", "$0.0014–$0.0015 per watched event", "$0.0014–$0.0015 per watched event in our live runs"),
    ("cost.per_event_mean", "$0.0018 on average over 1,005 clips", "$0.0018 on average over 1,005 clips"),
    ("cost.rule_eval", "about a tenth of a millisecond", "about a tenth of a millisecond"),
    ("perception.frames", "reads 16 frames per clip", "16 frames per clip"),
    ("calibration.alpha_default", "(10% by default)", "10% by default"),
    ("verify.encoding_cases", "3,850 randomized cases", "3,850 randomized cases"),
    ("verify.planted_bugs", "7 of 7 deliberately planted solver bugs caught", "7 of 7 deliberately planted solver bugs caught"),
    ("verify.conformal_draws", "A 100,000-draw simulation", "A 100,000-draw simulation of the false-alarm bound"),
    ("tests.counts", "860+ engine tests", "860+ engine tests, 205 evaluation tests and 22 webhook tests"),
    ("contract.api_ops", "33 of 33 operations", "33 of 33 operations"),
    ("friction.entries", "51 friction-log entries", "51 friction-log entries"),
)


def build_claims() -> dict:
    lines = (REPO / SOURCE).read_text(encoding="utf-8").splitlines()
    out = []
    for cid, needle, display in CLAIMS:
        hits = [i for i, ln in enumerate(lines, start=1) if needle in ln]
        if len(hits) != 1:
            raise ExportError(f"claims: {cid}: phrase found on {len(hits)} lines of {SOURCE} (expected exactly 1)")
        i = hits[0]
        if display not in lines[i - 1]:
            raise ExportError(f"claims: {cid}: display text is not on the source line")
        out.append({"id": cid, "display": display, "source": {"path": SOURCE, "line": i, "quote": lines[i - 1].strip()}})
    return {"source": SOURCE, "note": "Copied as published; the numbers ledger of the submission stream, when it lands, supersedes these.",
            "claims": out}
