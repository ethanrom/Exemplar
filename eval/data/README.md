# eval/data: the Exemplar evaluation dataset

Stream G (eval-data). Turns the public MEVA surveillance corpus into a small benchmark of **labelled 10-20 s clips**
for four coarse concepts, plus 18 windows of a CC BY "package theft" video for the demo's teach story.
Everything below is deterministic (seed 0) and reproducible from the committed configs; only the large files
(videos, clips) live outside git, under `$EXEMPLAR_DATA_DIR` (gitignored `data/`).

| committed file | what |
|---|---|
| `concepts.yaml` | the 4 concepts, their MEVA activities, the NL description (zero-shot prompt) and teach hint, confuser activities |
| `videos.yaml` | the 22 selected MEVA videos (5 cameras, 5 days) with S3 keys, sizes and annotated instance counts |
| `video_info.yaml` | width / height / fps / duration of every selected video (`ffmpeg -i`) |
| `splits.yaml` | video -> `train` / `calib` / `test` (by **video**, stratified by camera) |
| `rois.yaml` | one fixed 16:9 crop per camera (native pixels) + how much of the annotated action it covers |
| `manifest.jsonl` | **the benchmark**: one window per line (fields below) |
| `STATS.md` | counts per concept / split / camera, dropped instances, ROI coverage |
| `frollard.yaml` | hand annotation of the CC BY theft video and its 18 labelled windows |

## Reproduce

```bash
export PYTHONUTF8=1
export EXEMPLAR_DATA_DIR="D:/kaskara/amazon dev hackathon/data"     # large data; any writable dir works
# once: blob-less sparse clone of gitlab.kitware.com/meva/meva-data-repo at $EXEMPLAR_DATA_DIR/meva/meva-data-repo,
#       with /annotation/DIVA-phase-2/MEVA/kitware/*/*/*.activities.yml checked out (geometry is fetched on demand)
uv run --project engine python -m eval.data.select        # videos.yaml  (S3 listing is cached; --refresh-s3 to re-list)
uv run --project engine python -m eval.data.download      # ~3.3 GB, resumable, size-checked (slow link: ~45 min)
uv run --project engine python -m eval.data.probe         # video_info.yaml
uv run --project engine python -m eval.data.splits        # splits.yaml
uv run --project engine python -m eval.data.rois          # rois.yaml + previews in $EXEMPLAR_DATA_DIR/meva/roi_previews/
uv run --project engine python -m eval.data.windows       # manifest.jsonl + STATS.md   (~2 min, parses 6 MB geometry files)
uv run --project engine python -m eval.data.cut           # ~1000 clips -> $EXEMPLAR_DATA_DIR/meva/clips/<concept>/<id>.mp4 (idempotent)
uv run --project engine python -m eval.data.frollard      # frollard.yaml windows + clips -> $EXEMPLAR_DATA_DIR/external/windows/
uv run --project engine pytest eval/tests
```

Selection, splits, ROIs and windows are committed, so a fresh checkout only needs `download` + `cut` (+ `frollard`)
to get the clips; rerunning the earlier steps must reproduce the committed files byte for byte.

## Concepts (`concepts.yaml`)

| id | MEVA activities | description (zero-shot prompt) |
|---|---|---|
| `vehicle_stop` | `vehicle_stops` | A vehicle that was driving comes to a stop and stays parked in view of the camera. |
| `person_exits_vehicle` | `person_exits_vehicle` | A person gets out of a parked vehicle: a door opens and the person steps out onto the ground. |
| `door_crossing` | `person_enters_scene_through_structure`, `person_exits_scene_through_structure` | A person walks through a building doorway, either coming out of a door into the camera view or going into a door and leaving the view. |
| `vehicle_loading` | `person_loads_vehicle`, `person_unloads_vehicle` | A person loads items into, or unloads items from, a vehicle, for example at an open trunk or rear door. |

MEVA's public annotations contain no theft or abandonment activity, so these are the coarse, countable concepts
(PLAN.md section 3). `confusers` (related activities such as `vehicle_starts`, `person_opens_trunk`) define *hard* negatives.

## Windows (`windows.py`)

* **Positive**: an annotated instance of one of the concept's activities that is *in view* (below), padded with seeded
  random padding to a **10-20 s** window inside the video that contains the whole instance (>= 0.5 s of context on both
  sides when possible). Instances already inside an earlier positive window of the same video do not produce a second,
  near-duplicate window; a window can therefore contain several instances (`events`).
* **Negative**: a seeded random 10-20 s window that stays >= 1 s away from every instance of the concept's activities that is in
  view or ambiguous. About half are **hard**: built around an in-view confuser activity (field `hard`). `other_activities`
  lists every other annotated activity overlapping the window. Target ~3.5 negatives per positive; busy concepts
  (`door_crossing`) get fewer because little valid space remains (see `STATS.md`).
* Windows of one concept and video never overlap. Lengths are in integer ms (not frame aligned).
* **Manifest fields**: `id, concept, label (pos|neg), split, video, camera, date, start_ms, dur_ms, roi [x,y,w,h], other_activities,
  hard (neg only), own_out_of_view, events (pos only: concept instances inside the window, window-relative ms), source_ref, clip`.
  `clip` is relative to `$EXEMPLAR_DATA_DIR`. `id` is `<concept>-<camera>-<video start>-<start_ms>-<pos|neg>`.

## Splits (`splits.py`): leakage rules

Split by **video**, never by clip, stratified by camera (each camera has train, calib and test videos).

| split | use |
|---|---|
| `train` | pool for the k teaching examples and the active-learning questions (`example` / `active` provenance); also the only source for ROI choice |
| `calib` | `random`-provenance calibration labels: sample uniformly from these (positives and negatives) to set tau_alpha and the recall CI. Never used for fitting or for picking examples. |
| `test` | held-out evaluation: F1 at tau_alpha and the empirical false-alarm rate vs alpha |

`test_data_manifest.py` checks that no video is in two splits and that ROIs only use train videos.

## ROI (`rois.py`): the doorbell-style crop

MEVA people are 10-40 px tall in the 1920x1080 frame, so each camera gets **one fixed crop**, chosen once per camera from
**train-split videos only** (never per activity or per clip), cut at native resolution and scaled to 1280 px wide:

1. take every instance of every concept activity in the camera's train videos (boxes of the instance's actors, every 5th frame);
2. crop size is fixed at 960x540 (half the frame width, 16:9);
3. slide it over the frame (32x18 px grid) and keep the positions that maximise the concept-balanced weight of instances **in view**
   (>= 80 % of the instance's box centres inside the crop);
4. among those, centre the crop on the action (closest to the weighted mean position).

An instance is *out of view* when <= 10 % of its box centres are inside the crop and *partly in view* in between; only in-view
instances become positives, out-of-view instances are ignored for negatives (a doorbell never sees them) and counted per window in
`own_out_of_view`. The planned "union of all activity boxes" rule was dropped after trying it: on the wide parking-lot views
(e.g. G424) it covers essentially the whole frame, which defeats the purpose. `rois.yaml` reports train and held-out in-view
shares; previews (`<camera>.jpg` with the box and annotated positions, `<camera>_crop.jpg` the cut as the model sees it) are in
`$EXEMPLAR_DATA_DIR/meva/roi_previews/`.

**Expect weak perception on G336, G339 and G436**: those are far-field lot/lawn views where people stay ~15-30 px tall even in
the crop. G505 (bus stop under a canopy) is a genuine close-up, G424 is mixed.

## Frame indexing

KPF `tsr0 = [f0, f1]` and geometry `ts0` are frame numbers of the 30 fps AVI, **0-based, end inclusive**: 299 of the 769 annotated
clips have an activity starting at frame 0, which a 1-based scheme cannot produce. An activity covers
`[round(f0*1000/30), round((f1+1)*1000/30))` ms. Any residual off-by-one is 33 ms against 10-20 s windows. Some annotations run
past the video end (frame 9059 in 9000-frame clips); those instances are skipped.

## Demo windows (`frollard.py`)

"Thief stealing our package" by frollard, CC BY 4.0, https://www.youtube.com/watch?v=TfTFu8lGrwk (102 s, 1920x1080). Times were
read off 1 s and 0.5 s contact sheets (+/- 0.5 s): box on the steps from 0 s; a distant person at the top-right edge from ~8 s; walks up
from ~13 s and reaches the steps at ~19.5 s; **picks up 20.5-22.0 s; leaves with the box 22.0-24.0 s**; a different-looking passer-by
crosses the back of the yard 48.3-53.5 s and lingers at the right edge until ~59.5 s; empty afterwards. 15 s windows at a 5 s stride
(18): **positive iff the whole pickup-and-leave lies inside** (starts 10, 15, 20 s), negatives are the rest (person walking up but
no pickup, walk-by, empty scene). Cut with no crop, 1280 px wide.

## Attribution and modification

* **MEVA** (Multiview Extended Video with Activities): Kitware and IARPA, CC BY 4.0, accessed 2026-10-15 from
  https://registry.opendata.aws/mevadata (annotations: https://gitlab.kitware.com/meva/meva-data-repo). Corona et al., "MEVA: A Large-Scale
  Multiview, Multimodal Video Dataset for Activity Detection", WACV 2021.
* **"Thief stealing our package"** by frollard, CC BY 4.0, https://www.youtube.com/watch?v=TfTFu8lGrwk.
* All clips are **modified**: cut to 10-20 s windows, cropped to a per-camera region of interest, scaled to 1280 px wide, re-encoded to
  H.264 without audio. Annotations are used as published; the window labels are derived from them.
