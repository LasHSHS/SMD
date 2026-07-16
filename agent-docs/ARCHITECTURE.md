# SMD Architecture Map (for AI agents)

**Read this first when picking up work on SMD. This is a navigation aid and a
record of non-obvious behavior, not a full spec.** Code changes constantly;
this file can go stale. Always verify exact current behavior by reading the
referenced file/function before making changes or answering a user's
question about behavior - especially anything load-bearing (data safety,
file deletion, matching logic).

**Update the relevant section of this file (and `DECISIONS.md` if it's a
"why" decision) whenever you make a structural or behavioral change.** See
`.cursor/rules/agent-docs.mdc` for the enforcement rule.

## What SMD is

A Windows desktop app (PyQt5, packaged with PyInstaller as `SMD.exe`) that
processes a Snapchat "Memories" data export ZIP entirely offline: extracts
bundled media, merges Snapchat overlay filters (stickers/text/drawings) onto
photos and videos, embeds capture date + GPS metadata, and verifies the
result. No network calls in the core pipeline. Not affiliated with Snap Inc.

## Top-level layout

- `desktop_gui_pyqt.py` - the entire GUI: main window, all 5 tabs, dialogs,
  background `QThread` workers. One large file (~5800 lines); see "GUI"
  below for the class map.
- `smd/` - all backend logic, importable independently of the GUI (and unit
  tested that way - see `tests/`).
- `tests/` - pytest suite, no GUI/Qt dependency, runs in a few seconds.
- `agent-docs/` - this file, `DECISIONS.md`, and packaging/publishing docs.
  Kept separate from user-facing `README.md`.
- `build_smd.ps1`, `smd.spec` - PyInstaller build. `tools/ffmpeg/` holds the
  bundled ffmpeg/ffprobe binaries (not built by us; downloaded, see
  `agent-docs/ALL_IN_ONE_PACKAGING.md`).

## Account folder layout (`smd/account_layout.py`)

Per account name, two roots:

- **User-facing**: `Desktop/<account>/merged/` (with overlays - what most
  users care about) and `Desktop/<account>/raw/` (without overlays, only
  created if "Also save without filters" is checked).
- **Technical** (`%LOCALAPPDATA%/SnapchatMemoriesDownloader/accounts/<account>/technical/`):
  `staging/` (extracted ZIP contents, main+overlay pairs), `json/`
  (`memories_history.json`), `reports/` (session summary, staging
  readiness, duplicate reports), `checkpoint/` (resume state), `quarantine/`
  (files that failed integrity checks), `logs/`, `debug/`.

`AccountPaths` (dataclass) is the single source of truth for all these paths;
always resolve via `resolve_account_paths()`, never hardcode a folder name.

## Processing pipeline (`smd/local_pipeline.py`)

Entry point: `process_bundled_export(...)`. Rough flow:

1. **Detect export format** (`smd/export_detect.py`) - bundled media in the
   ZIP vs "link-only" (JSON with download URLs, no media) which SMD
   deliberately does not support (offline-only by design).
2. **Extract ZIP(s) to `staging/`** - main/overlay files are paired by
   filename pattern `<date>_<uid>-main.<ext>` / `<date>_<uid>-overlay.<ext>`.
3. **Match staging items to JSON rows** - `build_match_map()` matches by
   Snapchat media UID first (`mid=` in `Download Link`/`Media Download Url`
   - **always empty, and thus always a no-op, for fully-bundled exports**),
   falling back to `build_deterministic_match_map()`'s date/type positional
   matching, which is what actually runs for most accounts. Within a
   same-day, same-type bucket: videos sort by each file's own embedded
   `creation_time` (read via ffprobe off the staged file before SMD touches
   it - the phone's own capture timestamp, reliably in the same order as
   the JSON `Date` field); photos have no such signal (Snapchat strips EXIF
   from exported photos) and stay on UID-stem order, which can still
   mismatch on multi-photo days. Iterates `items.items()` in
   **sorted-by-stem order**, not raw filesystem/dict order - this was a real
   determinism bug (two runs could match differently) fixed 2026-07-11. See
   agent-docs/DECISIONS.md 2026-07-14 entries for why the video ordering
   fix exists and what it does/doesn't cover.
4. **Process each item** - `_process_single_item()`, dispatched one call per
   memory via a `ThreadPoolExecutor(max_workers=...)`. **Per item**, not
   globally: writes the raw output first (if "Also save without filters" is
   on), then the merged output second, in that order, inside the same call.
   Different items run concurrently across the worker pool; there is no
   separate global "all raw files, then all merged files" pass.
   - **No overlay + raw enabled** → fast path: process once into `raw_out`,
     then `link_or_copy()` (`smd/fsutil.py`) hardlinks `merged_out` to it
     instead of a second copy/remux - raw/ and merged/ are byte-identical in
     this case, so this is the same file on disk with zero extra I/O or
     space. Falls back to a real copy on non-hardlink-capable filesystems.
     See DECISIONS.md, "raw/merged hardlinked when identical" (2026-07-15).
   - **No overlay + raw disabled** → merged file is copied (or WebP→JPEG
     converted for images) straight to the output; no raw file at all.
   - **Overlay present** → `merge_image_overlay` (Pillow, images) or
     `merge_video_overlay` (ffmpeg, videos) in `smd/overlays.py` for
     `merged_out`; `raw_out` (if enabled) still gets the unfiltered original
     via its own copy/remux - these two are genuinely different bytes, so
     never hardlinked.
   - Metadata (`smd/metadata.py`) embeds capture date + GPS. For videos this
     is folded into whichever ffmpeg pass already touches the file (overlay
     merge, or `copy_video_with_metadata` for the no-overlay case) rather
     than a second separate remux - see DECISIONS.md, fixed 2026-07-12.
   - `validate_media_file()` (`smd/media_integrity.py`) does a cheap
     magic-byte check on every output in real time (not a full ffprobe -
     that only happens post-run, see Staging verification below).
   - Any "repair a bad output" retry on a hardlinked pair always uses an
     atomic (`os.replace`-based) write, never an in-place truncate+write -
     the latter would silently mutate both hardlinked names at once instead
     of just the broken one.
5. **Checkpoint** (`checkpoint/local_checkpoint.json`) saved every ~25 items
   so an interrupted run can resume without reprocessing everything.
6. **Post-run**: session report + staging verification (see below).

### Concurrency model (`smd/system_profile.py`)

- Performance modes: `maximum` (0.8 × logical CPUs), `balanced` (0.6×,
  default and persisted across launches), `conservative` (0.4×, used
  automatically on low battery).
- `max_ffmpeg` (concurrent ffmpeg subprocesses) is capped separately from
  worker count, tiered by RAM (1 if <8GB; up to 6 if ≥32GB) - GPU hardware
  encoders (AMF/NVENC/QSV) don't reliably support unlimited concurrent
  sessions, so this is a deliberate ceiling, not just a CPU/RAM guess.
- GPU encoder selection (`smd/gpu_encode.py`, `detect_video_encode_profiles()`):
  a one-time, cached, real test-encode probe (`_working_gpu_encoder()`)
  determines which single GPU encoder (NVENC, AMF, or QSV) actually works on
  *this* hardware - checking ffmpeg's `-encoders` list alone is not enough,
  since full ffmpeg builds compile in all three vendor wrappers regardless
  of what GPU is installed. Only that one GPU profile (if any) plus CPU
  x264 are returned; `merge_video_overlay` still tries them in order and
  falls back to CPU if the "working" one somehow fails on a specific file.

### Overlay/GPU encoding quality (`smd/gpu_encode.py`, `smd/overlays.py`)

Calibrated via VMAF to "visually lossless" (not literal lossless, which
produced huge files for zero perceptible gain): x264 CRF 16, NVENC CQ 18, AMF
QP 22, QSV global_quality 18.

## Duplicate detection (`smd/duplicates.py`)

Byte-for-byte SHA-256 content hashing of `merged/` (not filename/date/size
heuristics). Runs in a background `QThread`
(`DuplicateScanWorker`) so the GUI doesn't freeze. Results cache to
`reports/duplicates_report.json`; the GUI checks this cache before
re-scanning. Deletion (`DuplicateReviewDialog` → "Delete unselected
duplicates") is **permanent**, removes the non-kept file from both
`merged/` and `raw/`, and is recorded in
`reports/duplicates_deleted_report_*.json` - this audit trail is what lets
staging verification (below) know those files were deleted on purpose.

## Staging verification (`smd/staging_check.py`)

`check_staging_readiness()` ffprobes **every** video (not a sample) plus
checks every staging item has a matching file in `merged/`/`raw/`, using the
*same* `build_match_map()` the real pipeline uses (a past bug used a
different/older matching function here, causing false "missing" reports -
fixed 2026-07-11). Excludes files intentionally removed via duplicate review
(reads the audit report above) from the "missing" count.

This check is expensive (minutes on a large library) and runs in
`StagingVerifyWorker` (background thread), not on the GUI thread. Two ways
it gets used:

1. **Automatically after every run** (`_finish_completion_summary` in
   `desktop_gui_pyqt.py`) - if it comes back 100% clean, `technical/staging/`
   is deleted **silently**, no confirmation dialog. This is intentional: the
   average user never sees or understands "staging" and shouldn't have to.
2. **Manually via "Verify staging"** button (Technical view only) - same
   check, but asks "delete now?" before doing anything.

The "Keep staging media files" checkbox (Technical view only, default off)
skips step 1 entirely (no ffprobe check, no delete) - added 2026-07-11 for
users who want manual control over when staging disappears.

## GUI (`desktop_gui_pyqt.py`)

Main window: `DownloaderGUI(QMainWindow)`. Five tabs (`self.tabs`, a
`QTabWidget`): **Guide**, **Save memories** (the main workflow - Setup,
Performance, Run, After-processing sections, stacked in a single column via
`_rebuild_process_controls_grid`), **File Checker** (folder scan + GPS map),
**Help**, **About**. The tab bar does **not** use `setExpanding(True)` -
each tab sizes to its own text via Qt's normal sizeHint, so the longest
label ("Save memories") can never get squeezed/clipped by shorter tabs
being forced to equal width (fixed 2026-07-12).

Key background workers (`QThread` subclasses) - all processing/scanning that
could take more than a fraction of a second runs off the GUI thread:

- `LocalExportWorker` - runs `process_bundled_export`, emits progress.
- `StagingVerifyWorker` / `StagingCheckWorker` - staging readiness check.
- `DuplicateScanWorker` - content-hash duplicate scan.
- `MapRenderWorker`, `MapWorker`, `ScanWorker` - File Checker tab (thumbnails,
  GPS map, folder scan).

`self.map_view` (the GPS map widget) is **not** created in `init_ui()` -
it's `None` behind a cheap placeholder label until `_ensure_map_view()`
runs, which happens the first time the user opens File Checker
(`_on_main_tab_changed`). This is deliberate: constructing a
`QWebEngineView` spins up Qt's embedded-Chromium subsystem (separate
`QtWebEngineProcess.exe` helper processes), the single most expensive thing
this app can do, and doing it eagerly for every launch made startup slow
for the ~4/5 of tabs that never touch it (fixed 2026-07-12). Any new code
that touches `self.map_view` must call `self._ensure_map_view()` first.

**"Technical view" checkbox** gates visibility of advanced controls (`Open
technical folder`, `Verify staging`, `Open debug folder`,
`technical_storage_label`, `Keep staging media files`) - see
`_technical_widgets()` / `_apply_technical_view_ui()`. These are also styled
in red (`smd.theme.technical_text_style()`) so they visually read as
"advanced, not for the average user." Add any new technical-only control to
`_technical_widgets()` so visibility + styling stay in sync automatically.

**Processing UI lockout**: while a run is active, `_set_run_lockout()` dims
and disables Setup/Performance/After-processing sections but leaves the Run
section (Start/Cancel) and the Live Run Dashboard fully interactive and
scrollable. The full-window `ProcessingShieldOverlay` is only used for the
brief, non-cancelable post-run staging verification step - it used to also
cover the live run, which is why scrolling the dashboard used to be
impossible during a run (fixed 2026-07-11).

**Single instance**: `SingleInstance` class + a signal file in the temp dir -
launching SMD while it's already running brings the existing window to
front instead of opening a second one.

**Keep-awake during a run**: `_set_keep_awake()` wraps Win32
`SetThreadExecutionState` to stop the system/display from sleeping between
run start and the end of post-run verification/finalize (all the
`_set_keep_awake(False)` call sites mark true "run is fully done" points,
not just when `_set_run_lockout(False)` fires - that happens earlier, before
verification). See DECISIONS.md, "Keep system/display awake for the
duration of a run" (2026-07-16).

## Module map (`smd/`)

| Module | Responsibility |
|---|---|
| `local_pipeline.py` | Core processing pipeline (see above) |
| `overlays.py` | Burn overlay onto image (Pillow) or video (ffmpeg) |
| `metadata.py` | Embed EXIF/GPS (images), container date/GPS + iTunes atoms (video); read GPS back out for the map |
| `gpu_encode.py` | Detect/rank GPU video encoders, quality profiles |
| `system_profile.py` | Hardware detection → worker/ffmpeg concurrency limits |
| `export_detect.py` | Bundled vs link-only export detection |
| `account_layout.py` | Folder layout for one account (user + technical) |
| `duplicates.py` | SHA-256 content-hash duplicate detection |
| `staging_check.py` | Post-run completeness/integrity verification |
| `media_integrity.py` | Cheap real-time output validation (magic bytes) |
| `video_repair.py` | Best-effort repair of corrupt/incomplete source video |
| `session_report.py` | Post-run summary shown to the user |
| `time_estimate.py` | Rough ETA before starting a run |
| `map_gps.py` | GPS lookups for the File Checker map |
| `fsutil.py` | Atomic file writes (crash/disk-full safe); `link_or_copy()` hardlinks byte-identical outputs with an atomic-copy fallback |
| `ffmpeg_bundle.py`, `procutil.py` | Resolve bundled ffmpeg/ffprobe, subprocess flags (hide console windows on Windows) |
| `theme.py` | Design system - colors, spacing, Qt stylesheets |
| `guide_content.py`, `help_content.py`, `about_content.py` | Static HTML content for those tabs |
| `models.py` | `Memory` dataclass (one JSON row) |
| `runtime.py` | Path resolution for frozen (PyInstaller) vs source runs |

## Known sharp edges

- `_process_single_item` writes raw before merged, per item - see pipeline
  step 4 above. Don't assume a two-phase global pass.
- Every video costs at least 1 ffmpeg subprocess call even with no overlay
  (metadata embedding needs a real remux; mutagen alone can't set the
  container-level `creation_time` that Explorer/Google Photos read).
- `build_match_map` must stay in sync between `local_pipeline.py` (actual
  processing) and `staging_check.py` (verification) - they must use the
  *same* function, or verification will falsely disagree with what actually
  got written.
- QSS/Qt stylesheet specificity: a widget's own `setStyleSheet()` beats an
  app-wide rule targeting it by object name or property selector. When
  styling a specific existing widget (e.g. red "technical" text), prefer
  setting it directly on the widget instance rather than fighting
  specificity in the global stylesheet.
