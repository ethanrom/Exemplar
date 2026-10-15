# Friction notes: stream G (eval-data)

Per-stream notes; combined into `docs/FRICTION_LOG.md` in Phase 3. Format per entry: task, steps, expected vs actual, severity, workaround, suggestion.

## G-1 MEVA download throughput from a residential connection is about 1 MB/s
- **Task:** fetch 22 MEVA clips (3.5 GB; two were already on disk) from `s3://mevadata-public-01/drops-123-r13/`.
- **Steps:** anonymous boto3 ranged GETs (1 MiB chunks, 3 parallel files), and an 8-thread parallel-range test on one file.
- **Expected:** tens of MB/s from a US-East-1 public bucket.
- **Actual:** about 1.0 MB/s in total; extra threads did not help (8 threads competing with the running download gave 0.7 MB/s). 3.3 GB (20 new clips) took 48 minutes (2870 s, about 1.15 MB/s).
- **Severity:** medium (blocks the dataset prep for most of an hour; nothing to do with the code).
- **Workaround:** start the download first, build the rest of the pipeline while it runs; the downloader is resumable (`.part` + Range requests) so a dropped connection does not restart a 250 MB file.
- **Suggestion:** document the expected size per clip (140-340 MB here) and publish a small "starter subset" manifest (per-clip size + a few lower-resolution proxies) so a hackathon participant does not need to pull full 1080p AVIs to try the dataset.

## G-2 Git for Windows rewrites the leading slash of sparse-checkout patterns
- **Task:** extend the blob-less sparse clone of `meva-data-repo` with more annotation files.
- **Steps:** `git sparse-checkout add "/annotation/DIVA-phase-2/MEVA/kitware/<date>/<hour>/*.yml"` from Git Bash.
- **Expected:** the pattern is stored as written.
- **Actual:** MSYS path conversion turned it into `C:/Program Files/Git/annotation/...`, so nothing matched and no files appeared; `git sparse-checkout list` showed the mangled paths (and the earlier `/documents/...` patterns had the same problem).
- **Severity:** low-medium (silent no-op; costs a debugging round).
- **Workaround:** `MSYS_NO_PATHCONV=1` for shell use; from Python (`subprocess`) the arguments are passed unchanged, so `eval/data/rois.py::ensure_geometry` does not need it.
- **Suggestion:** the MEVA README could show cone-mode commands (`git sparse-checkout set --cone annotation/DIVA-phase-2/MEVA/kitware/2018-03-07`), which have no leading slash.

## G-3 Public annotations contain no theft-like activity, and activity names changed in 2020
- **Task:** choose benchmark concepts from the annotated activities.
- **Steps:** counted activity names over all 456 annotated exterior-EO clips in `kitware/` (2018-03-05 to 2018-03-15).
- **Expected:** at least one theft / abandonment style activity for the Ring "package" story.
- **Actual:** 34 activity names, none of them `person_steals_object` or `person_abandons_package`; `person_picks_up_object` (296) and `person_puts_down_object` (249) are the closest. Old and new names co-exist in the docs (`person_enters_through_structure` vs `person_enters_scene_through_structure`).
- **Severity:** medium for our use (forced the theft story onto CC BY footage from outside MEVA).
- **Workaround:** coarse concepts (vehicle stops, person exits vehicle, door crossing, loading/unloading); the theft demo uses the frollard clip with hand-made annotations (`eval/data/frollard.yaml`).
- **Suggestion:** state in the dataset README which activity names are actually present in the open `kitware/` annotations.

## G-4 Annotation frame numbers can exceed the video length
- **Observation:** a few activities end at frame 9059 in 300 s (9000-frame) videos, and several videos are slightly longer than 300 s. Frame indexing is 0-based (299 of the 769 annotated clips have an activity starting at frame 0; a 1-based scheme would never produce 0).
- **Severity:** low. **Workaround:** instances that end after the video's measured duration are skipped (`beyond_video_end` in `STATS.md`).
- **Suggestion:** document the indexing base and that annotations can run past the clip end.

## G-5 Wide-angle surveillance scenes: a "union of activity boxes" ROI is the whole frame
- **Task:** choose one close-up crop per camera.
- **Actual:** actions are spread over parking lots (G424: door on the right, vehicles in the middle and far left), so the union of the actor boxes of all concept activities covers essentially the full 1920x1080 frame. People stay 10-40 px tall.
- **Workaround:** densest fixed 960x540 window chosen from train videos only (README.md); instances outside the crop are not used as positives.
- **Suggestion (for anyone benchmarking doorbell-style perception on MEVA):** the dataset's strength is overview coverage; a real doorbell view needs a different source, so treat this benchmark as a stress test of coarse concepts, not of fine hand-object detail.

## G-6 Repository `.gitignore` pattern `data/` also ignores `eval/data/`
- **Task:** commit the stream's code under `eval/data/` and `eval/tests/data/`.
- **Actual:** the root `.gitignore` entry `data/` (meant for the top-level scratch dir) matches any directory called `data`, so `git add eval/data/...` silently does nothing.
- **Workaround:** `git add -f` for the new files (already tracked files are picked up normally afterwards).
- **Suggestion (integrator):** anchor the pattern as `/data/`.
