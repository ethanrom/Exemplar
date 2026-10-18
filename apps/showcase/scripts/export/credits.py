"""credits.json: licence and permission evidence for every media source (SPEC 9.2).

Evidence quotes public metadata fields (video URL + quoted field), never a local path. The ids are the keys that
library.json's `credit` field points to. Text is plain; the site renders the polished credit lines elsewhere.
"""
from __future__ import annotations

import importlib.metadata as md

from aliases import Registry
from common import ExportError

CHECKED_ON = "2026-10-18"
FROLLARD_URL = "https://www.youtube.com/watch?v=TfTFu8lGrwk"
FOX_URL = "https://www.youtube.com/watch?v=MJP2iL7xLro"
CC4 = "https://creativecommons.org/licenses/by/4.0/"
YT_LICENCE = "Creative Commons Attribution license (reuse allowed)"


def _aliases(reg: Registry, key: str) -> list[str]:
    return sorted(a for a, r in reg.by_alias.items() if r.credit == key)


def _attributions(reg: Registry, key: str) -> list[str]:
    seen: list[str] = []
    for a in _aliases(reg, key):
        s = reg.by_alias[a].clip.get("attribution")
        if s and s not in seen:
            seen.append(s)
    return seen


def build_credits(reg: Registry) -> list[dict]:
    z3 = md.metadata("z3-solver")
    if (z3.get("License") or "").strip().lower() != "mit license":
        raise ExportError("z3-solver metadata no longer reports the MIT licence; check before crediting it")
    gen_attr = _attributions(reg, "generated")
    entries = [
        {
            "id": "frollard", "group": "cc_by", "title": "Thief stealing our package", "author": "frollard",
            "url": FROLLARD_URL, "licence": "CC BY 4.0", "licence_url": CC4,
            "permission": {
                "basis": "cc_by", "status": "cleared", "checked_on": CHECKED_ON,
                "evidence": (f"YouTube metadata of {FROLLARD_URL}: license \"{YT_LICENCE}\"; uploader \"frollard\"; "
                             "uploaded 2018-12-06. The metadata does not state a licence version; the project's "
                             "materials cite CC BY 4.0, the deed YouTube links.")},
            "modification": "Cut into 20 s windows at a 5 s stride (17 windows); 16 frames per window extracted and "
                            "scaled for display. The video itself is not hosted.",
            "note": "Attribution recorded with each window: " + " | ".join(_attributions(reg, "frollard")),
            "aliases": _aliases(reg, "frollard"),
        },
        {
            "id": "playground-frollard", "group": "playground_frollard_derived",
            "title": "Ring Developer Playground simulated-event recordings, package scene",
            "author": "Ring Developer Playground (sandbox output); underlying footage by frollard", "url": FROLLARD_URL,
            "licence": "CC BY 4.0 (underlying footage)", "licence_url": CC4,
            "permission": {
                "basis": "cc_by", "status": "cleared", "checked_on": CHECKED_ON,
                "evidence": (f"The Playground's package clip is derived from the CC BY video \"Thief stealing our package\" "
                             f"by frollard ({FROLLARD_URL}); YouTube metadata: license \"{YT_LICENCE}\", uploader "
                             "\"frollard\". The recording is Ring sandbox output and carries Ring's watermark.")},
            "modification": "Frames extracted and scaled for display. Ring's burned-in watermark is left unaltered.",
            "note": "Twenty recordings of the Playground's package scene, made by simulating events in the Ring Developer Playground.",
            "aliases": _aliases(reg, "playground-frollard"),
        },
        {
            "id": "playground-sandbox", "group": "playground_other",
            "title": "Ring Developer Playground simulated-event recordings, vehicle and bird scenes",
            "author": "Ring Developer Playground (sandbox output)",
            "licence": "Ring Developer Playground sandbox output; no separate licence",
            "permission": {
                "basis": "ring_sandbox", "status": "cleared", "checked_on": CHECKED_ON,
                "evidence": ("Ring Developer Playground simulated-event recording, made by the project author with their own "
                             "Playground access. No licence beyond Playground access applies. The project author has decided "
                             "that these frames are shown, as in the public demo video.")},
            "modification": "Frames extracted and scaled for display. Ring's burned-in watermark is left unaltered.",
            "note": "Six vehicle recordings and seven bird recordings.",
            "aliases": _aliases(reg, "playground-sandbox"),
        },
        {
            "id": "ringtv-fox", "group": "cc_by",
            "title": "Ring Video Doorbell Pro Finds Out Who's Been Taking The Morning Paper | RingTV", "author": "Ring",
            "url": FOX_URL, "licence": "CC BY (YouTube Creative Commons Attribution license)", "licence_url": CC4,
            "permission": {
                "basis": "cc_by", "status": "cleared", "checked_on": CHECKED_ON,
                "evidence": (f"YouTube metadata of {FOX_URL}: license \"{YT_LICENCE}\"; channel \"Ring\" (verified); "
                             "uploaded 2020-11-25. Published by Ring's own channel.")},
            "modification": "Cut into three 20 s windows; 16 frames per window extracted and scaled for display.",
            "note": "Attribution recorded with each window: " + " | ".join(_attributions(reg, "ringtv-fox")),
            "aliases": _aliases(reg, "ringtv-fox"),
        },
        {
            "id": "meva", "group": "meva",
            "title": "MEVA: Multiview Extended Video with Activities",
            "author": "Kitware, Inc. and IARPA", "url": "https://registry.opendata.aws/mevadata",
            "licence": "CC BY 4.0", "licence_url": CC4,
            "permission": {
                "basis": "cc_by", "status": "cleared", "checked_on": CHECKED_ON,
                "evidence": ("AWS Open Data registry entry https://registry.opendata.aws/mevadata; its licence file "
                             "(http://mevadata.org/resources/MEVA-data-license.txt) reads \"Creative Commons Attribution "
                             "4.0 International License\".")},
            "modification": "Cut to 20 s windows, cropped to a fixed 16:9 region of interest and scaled to 1280 px wide "
                            "when the clips were prepared; 16 frames per window extracted and scaled for display.",
            "note": ("Accessed 2026-10-15 from https://registry.opendata.aws/mevadata. Corona et al., \"MEVA: A Large-Scale "
                     "Multiview, Multimodal Video Dataset for Activity Detection\", WACV 2021. Attribution recorded with "
                     "each window: " + " | ".join(_attributions(reg, "meva"))),
            "aliases": _aliases(reg, "meva"),
        },
        {
            "id": "generated", "group": "generated",
            "title": "AI-generated example images, animated", "author": "Exemplar contributors (image generation tool: Gemini)",
            "licence": "Own work, generated for this project",
            "permission": {
                "basis": "own_work", "status": "cleared", "checked_on": CHECKED_ON,
                "evidence": ("AI-generated by the project author for this project (three scenes, each with and without a "
                             "package). Attribution recorded with the clips: " + " | ".join(gen_attr))},
            "modification": "Each still was animated into a 20 s or 32 s clip; 16 frames per clip extracted and scaled for display.",
            "note": "AI-generated imagery, not a real camera recording.",
            "aliases": _aliases(reg, "generated"),
        },
        {
            "id": "exemplar-repo", "group": "software", "title": "Exemplar (this project)", "author": "Exemplar contributors",
            "url": "https://github.com/ethanrom/Exemplar", "licence": "MIT",
            "permission": {"basis": "own_work", "status": "cleared", "checked_on": CHECKED_ON,
                           "evidence": "LICENSE at the repository root: \"MIT License\", \"Copyright (c) 2026 Exemplar contributors\"."},
            "aliases": [],
        },
        {
            "id": "geist", "group": "software", "title": "Geist font (npm package geist 1.7.2)", "author": "Vercel",
            "licence": "SIL Open Font License 1.1",
            "permission": {"basis": "open_source", "status": "cleared", "checked_on": CHECKED_ON,
                           "evidence": "package.json of geist 1.7.2, field license: \"SIL OPEN FONT LICENSE\"."},
            "aliases": [],
        },
        {
            "id": "z3", "group": "software", "title": f"Z3 theorem prover (z3-solver {md.version('z3-solver')})",
            "author": "Microsoft Research", "licence": "MIT",
            "permission": {"basis": "open_source", "status": "cleared", "checked_on": CHECKED_ON,
                           "evidence": "z3-solver package metadata, field License: \"MIT License\". Used by the Python engine."},
            "aliases": [],
        },
    ]
    for e in entries:
        if not e["permission"]["evidence"].strip():
            raise ExportError(f"credits entry {e['id']} has no permission evidence")
        if e["group"] != "software" and not e["aliases"]:
            raise ExportError(f"credits entry {e['id']} credits no clip")
    return entries
