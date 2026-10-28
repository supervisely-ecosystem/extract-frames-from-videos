# extract-frames-from-videos: fixes 2026-10 (branch `ecosystem-fixes-2026-10`)

Base: `origin/master` @ 501b266 (v1.1.4, `supervisely/data-operations:6.74.34`). Lifecycle `legacy`, headless,
~110 lines on module globals. Targeted fixes + image move, not a rewrite (the code is small enough that a
`sly-app-modernize` rewrite would be the next step). `config.json` `name`, `context_menu` and modal state keys are
unchanged.

## Behaviour contract

- **Started from** `videos_project` or `videos_dataset` (`context.projectId`, `context.datasetId`).
- **Options** (`modal.state.*`)
  - `framesStep` (default 10): extract frames 0, N, 2N, … < `frames_count`;
  - `datasetsStructure`: `keep original` (same dataset tree) | `create dataset for every video`
    (flat, `<video id>_<video name>`);
  - `projectName` (default `extracted-frames`, renamed on conflict).
- **Output**: a new images project in the task's workspace with the source project's description; images
  `<video id>_frame_<index:06d>.jpg`, RGB as decoded by OpenCV, no annotations (by design; see
  turn-video-project-into-images for frames with labels); image meta `original_project_id/_name`,
  `original_dataset_id/_name`, `original_video_id/_name`, `frame`. Task output project + workflow input
  (project or dataset) and output (project). Source data is never modified.

## Fixed (one commit each; tests offline, `python -m pytest tests`)

Old code = `origin/master` with `APP_SRC=<old src>`; both Python 3.8 and 3.14 with SDK 6.74.34 give the same results.

| # | Commit | Problem | Tests old → new |
|---|---|---|---|
| 0 | d951c7a | No tests. Harness: fake `sly.Api`, real mp4 files whose frames encode their index | 4/4 regression tests pass on old |
| 1 | a2d9cdc | **Wrong success**: only top-level datasets were read; a dataset launch ignored its children. Nested videos silently missing | 0/3 → 3/3 |
| 2 | df76c8c | **Wrong success**: no videos → empty project + success; a video OpenCV cannot read → no frames, success; step 0 → ZeroDivisionError after an empty project was created; progress total off by one | 0/3 → 3/3 |
| 3 | 072ccfc | Local download path built from the video name (user data) → a name with `../` writes outside the data dir | 0/1 → 1/1 |
| 4 | e3347d7 | Image move (below) | 11/11 in the image |

Whole suite: old code 4/11, new code **11/11** (Python 3.8, Python 3.14, and inside `base-py-sdk-hardened:6.74.34`).

## Intentional behaviour changes

- Nested datasets are processed. `keep original` recreates the tree (`parent_id`); a dataset launch takes the
  selected dataset and everything under it, the selected dataset becoming top-level in the result. Result datasets are
  created with `change_name_if_conflict`.
- When nothing is extracted, the task fails and the empty result project it created is removed.
- Videos that yield no frame although `frames_count > 0` make the task fail **after** the output project and workflow
  output are set (frames of the other videos stay); videos that stop early only log a warning.
- `framesStep < 1` fails before anything is created.
- Downloaded videos are stored locally as `<video id><ext>` (invisible to users).

## Image

`supervisely/data-operations:6.74.34` (sdk_legacy) → **`supervisely/base-py-sdk-hardened:6.74.34`** (Python 3.14.7).
`dev_requirements.txt` unchanged (`supervisely==6.74.34`): the app uses only the SDK (OpenCV, python-dotenv).
`supervisely_lib` alias import → `supervisely`. SDK stays 6.74.34 (`instance_version` 6.17.22 → [6.74.29, 6.74.35)).
No build job needed; release workflows unchanged. Checked: the hardened image's OpenCV reads the same frame counts as
data-operations for mp4v, H.264 with B-frames (mp4, mkv), HEVC and VP9; seeking with `CAP_PROP_POS_FRAMES` returns
the exact frame on all of them.

## Found, not fixed

- Annotations are not carried over to frames (documented "without labels"; turn-video-project-into-images does it).
- `frames_count` is trusted; a video whose metadata has `frames_count = None` would crash the task (not seen on dev).
- Each frame is fetched with a seek (`CAP_PROP_POS_FRAMES`), slow for step 1 on long videos; correct on the codecs
  above.
- A failed download or upload of one video still stops the whole task (unchanged, but no longer reported as success).
- `debug.env` points to another team's project; left as is (no secrets in it).

## Dev-check plan (do not run in this phase)

Projects in workspace 733 (read on dev 2026-10-28). Each case: branch run, then the same command without
`--version ... --branch` (published v1.1.4) for comparison. Prefix: `uv run ecosystem-fleet/fleet.py run extract-frames-from-videos --workspace 733`.

| Case | Command (prefix +) | Expected (branch) | Published v1.1.4 |
|---|---|---|---|
| nested project | `--project 9409 --state framesStep=50 --state datasetsStructure="keep original" --version ecosystem-fixes-2026-10 --branch` | success; datasets `ds0` (frames 7 + 5 = 12) and `ds0/nested` (5); 17 images; meta `frame` = index in the name | `ds0` only, 12 images |
| dataset launch with child | `--project 9409 --dataset 48141 --state framesStep=50 ...` | same 17 images, tree `ds0/nested` | 12 images (child ignored) |
| flat, per-video datasets | `--project 9491 --state framesStep=3 --state datasetsStructure="create dataset for every video" ...` | success; 3 datasets `7599626_fv-0.mp4`, …; 3 images each (0, 3, 6) | same |
| flat, keep original | `--project 9491 --state framesStep=3 ...` | dsA 3, dsB 6 images | same |
| empty dataset | `--project 9742 --dataset 49540 ...` | task error "No frames were extracted (no videos …)", no project created | success, empty project "extracted-frames" |
| invalid step | `--project 9491 --state framesStep=0 ...` | task error "Frames step must be 1 or more", no project | ZeroDivisionError, empty project left |

Check after each run: task status/output, result project tree (`api.dataset.get_list(recursive=True)`), image counts per
dataset and the meta of one image. Remove nothing; note created project ids for the coordinator.
