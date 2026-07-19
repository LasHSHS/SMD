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

- `desktop_gui_pyqt.py` - thin entry script (~550 lines): early
  `pythonw` stdout redirect, `DownloaderGUI` (`__init__` + slim `init_ui`
  shell that wires tab mixins), and `main()`. PyInstaller/`Run-SMD.bat`
  still point here; they follow the `gui/` imports automatically.
- `gui/` - split-out desktop GUI package (mixin pattern, zero behavior
  change from the old god file). See "GUI" below for the class map.
- `smd/` - all backend logic, importable independently of the GUI (and unit
  tested that way - see `tests/`).
- `tests/` - pytest suite, no GUI/Qt dependency, runs in ~1s. Most files
  each unit-test one helper in isolation (matching, naming, hardlinking,
  staging checks). `test_full_pipeline_integration.py` is the exception -
  it drives the real top-level entry point (`local_pipeline.
  process_bundled_export`) against a synthetic-but-real ZIP (real JPEGs,
  a real tiny MP4 via the bundled ffmpeg) end to end: extract -> JSON
  match -> merge/hardlink -> checkpoint -> simulated-crash resume ->
  `check_staging_readiness`. This is the net that would actually catch a
  bug that loses/corrupts memories; the narrower unit tests can't, since
  each one mocks or bypasses the surrounding orchestration. Skips itself
  if ffmpeg isn't resolvable in the environment.
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

**Technical view + custom base dir** (`gui/tabs/save_memories_tab.py`,
`_account_paths()`): when the user picks their own base folder (instead of
the default `Desktop/SMD Media`), account folders sit flat under it -
`<base_dir>/<account>/` - matching the simple-mode pattern above, with no
extra `accounts/` wrapper (removed 2026-07-19; see `DECISIONS.md`). Any
pre-existing `<base_dir>/accounts/<name>/` folders are auto-flattened by
`migrate_flat_accounts_root()` the first time paths are resolved with
`create=True`. This is unrelated to the always-hidden, always-nested
`%LOCALAPPDATA%/.../accounts/<account>/` internal root above, which is
untouched.

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
   `gui/tabs/completion.py`) - if it comes back 100% clean, `technical/staging/`
   is deleted **silently**, no confirmation dialog. This is intentional: the
   average user never sees or understands "staging" and shouldn't have to.
2. **Manually via "Verify staging"** button (Technical view only) - same
   check, but asks "delete now?" before doing anything.

The "Keep staging media files" checkbox (Technical view only, default off)
skips step 1 entirely (no ffprobe check, no delete) - added 2026-07-11 for
users who want manual control over when staging disappears.

`SessionReport.summary_html()` (`smd/session_report.py`) leads with a
completeness banner (green/red/neutral) answering "did I lose any files?"
before anything else - built from `readiness.staging_main_count` (ground
truth: how many memories were actually found to process) vs
`outputs_verified`/`missing_merged`/`missing_raw`. When staging verification
was skipped ("Keep staging media files"), the banner falls back to the
cheap always-available folder counts and says so explicitly rather than
claiming a full check happened (added 2026-07-17).

## GUI (`gui/` package + thin `desktop_gui_pyqt.py`)

Main window: `DownloaderGUI(QMainWindow, WindowChromeMixin, GuideTabMixin,
SaveMemoriesTabMixin, FileCheckerTabMixin, CompletionMixin,
HelpAboutTabMixin)`. Mixins share `self` with the main window - method
bodies moved, call sites unchanged. One-way import rule: `gui/tabs/*` and
`gui/window_chrome.py` may import from `gui/common.py` /
`gui/widgets.py` / `gui/workers.py` / `gui/dialogs.py`, never from each
other or back into `desktop_gui_pyqt.py`.

Layout of `gui/`:

- `common.py` - `ROOT`, `TAB_SAVE_MEMORIES`, WebEngine availability,
  panel builders, `play_happy_tone`, `startup_log`, etc.
- `widgets.py` - reusable widgets (`DocBrowser`, `WidthAwareColumn`,
  `LiveRunDashboard`, `ProcessingShieldOverlay`, `_MainTabBar`, …).
- `workers.py` - all ten `QThread` workers + map/thumbnail helpers.
- `dialogs.py` - `DuplicateCompareDialog`, `SessionSummaryDialog`,
  `DuplicateReviewDialog`.
- `single_instance.py` - single-instance lock.
- `window_chrome.py` - `WindowChromeMixin` (theme, nav/section helpers,
  technical-view toggle, close/cleanup).
- `tabs/guide_tab.py`, `tabs/save_memories_tab.py`, `tabs/completion.py`,
  `tabs/file_checker_tab.py`, `tabs/help_about_tabs.py` - tab mixins.

Shell chrome in `DownloaderGUI.init_ui`: `#appHeader` (logo/title, a bold
clickable `self.free_palestine_label` - flag emoji + "Free Palestine"
linking to matwproject.org - just left of the Support button, then theme
toggle), then `#tabsShell` with the five tabs.

Five tabs (`self.tabs`): **Guide**, **Save memories** (Setup / Performance /
Run / After-processing via `_rebuild_process_controls_grid`), **File
Checker**, **Help**, **About**. The tab bar does **not** use
`setExpanding(True)` - each tab sizes to its own text via Qt's normal
sizeHint so "Save memories" cannot get clipped (fixed 2026-07-12).

Key background workers (`gui/workers.py`) - anything that could take more
than a fraction of a second runs off the GUI thread:

- `LocalExportWorker` - runs `process_bundled_export`, emits progress.
- `StagingVerifyWorker` / `StagingCheckWorker` - staging readiness check.
- `DuplicateScanWorker` - content-hash duplicate scan.
- `MapRenderWorker`, `MapWorker`, `ScanWorker` - File Checker tab.

`self.map_view` is **not** created in `init_ui()` - it's `None` behind a
placeholder until `_ensure_map_view()` (`FileCheckerTabMixin`) runs on
first File Checker open (`WindowChromeMixin._on_main_tab_changed`).
Constructing a `QWebEngineView` spins up Qt WebEngine (separate helper
processes); doing it eagerly made every launch pay that cost (fixed
2026-07-12). Any new code that touches `self.map_view` must call
`self._ensure_map_view()` first.

## File Checker tab (report-only, `gui/tabs/file_checker_tab.py`)

`run_full_analysis()` always runs `ScanWorker(..., dry_run=True)` - it never
renames anything. Extension fixing is not a separate step users need to run:
it already happens automatically inside `_fix_extension()`
(`smd/local_pipeline.py`) as part of every "Save memories" run, before a
file is written to `merged/`/`raw/`. File Checker exists to (a) report
extension mismatches on *any* folder, including ones SMD never touched, and
(b) show media stats + the GPS map - not to fix SMD's own output (fixed
2026-07-17; previously it silently renamed files, which conflicted with the
"check only" mental model this tab should have).

Media stats (`MapWorker._append_media_stats`) also reports a resolution
breakdown for photos (`_image_dimensions()` - cheap, `Image.open()` only
reads the header) as a "how many different screens/devices, roughly" signal.
Deliberately does **not** claim to show camera make/model or "which phone" -
verified empirically that Snapchat strips all of that from both photos and
videos before export (no `Make`/`Model` EXIF tag, no device info in video
container tags either). Also deliberately skips video dimensions (would
need a dedicated `ffprobe` call per video - real cost at 10k+ videos - for a
"fun stats" feature that isn't worth the slowdown).

Map tiles already flip to CartoDB dark_matter automatically in dark mode -
`_map_base_tile(dark=...)` picks the tile set at render time
(`_create_themed_map`), used for the default Copenhagen map
(`init_default_map`) and every "Load GPS map" / "Check folder" render
(`MapRenderWorker`). Toggling the app theme on an *already-open* map does
not live-swap its tiles (see "Known sharp edges" below) - use the map's own
layer-control (top right of the map) to switch basemaps without losing
zoom/pan, or just reopen/rescan to get the theme-matched default.

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
- App icon: `icon.ico`/`icon.png` live at repo root (used by `smd.spec` for
  the compiled EXE's icon, and `apply_window_icon()`'s ROOT-based fallback)
  *and* under `assets/` (used by the window/header/splash icon code paths,
  and bundled into the frozen build via `smd.spec`'s `datas`). Both copies
  must exist and stay in sync - several independent lookups check different
  paths for historical reasons; there is no single source of truth here.
  Missing either copy silently falls back to no icon (fixed 2026-07-17 - the
  files didn't exist at all before, so every lookup was silently failing;
  see DECISIONS.md).
- Map theme sync is one-way: a map picks up the current theme *when it is
  rendered*, but toggling the app theme does not retroactively re-tile an
  already-open map (`toggle_dark_mode()` deliberately skips this - see
  DECISIONS.md, "Map Theme Toggle Fix"). Don't re-add an automatic
  re-render on theme toggle without solving the pan/zoom-reset regression it
  caused before.
