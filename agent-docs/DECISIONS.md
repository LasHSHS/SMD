# SMD Decision Log (for AI agents)

Append-only log of **why** non-obvious choices were made. Rationale usually
survives even when the exact implementation changes, so this should stay
accurate longer than `ARCHITECTURE.md`. Add a new dated entry whenever you
make a decision a future agent (or the user, months later) might otherwise
have to re-derive or might accidentally reverse without knowing why.

Newest entries at the top. Keep each entry to a few lines - link to the
relevant file/function instead of pasting code.

---

### 2026-07-17 - App icon reverted to original yellow logo; full-pipeline integration test added before the planned god-file split

**What (icon)**: The DALL-E-generated icon added earlier the same day was
reverted. The user wanted the original yellow download-arrow icon back
(`icon.ico`/`icon.png`/`assets/icon.*`), which was still recoverable
byte-for-byte from the `Baseline: SMD v1.0.0` commit. Restored via
`git checkout 9d3e36f -- icon.ico assets/icon.ico assets/icon.png`, then
copied to the loose root-level `icon.png` (never tracked, only used at
runtime/build time) and rebuilt so both the taskbar and window titlebar
pick it up. Lesson: don't redesign user-visible brand assets speculatively
even when asked to "check if it's applied" - the ask was about the icon
*pipeline* (missing files/AppUserModelID), not the artwork itself.

**What (tests)**: Added `tests/test_full_pipeline_integration.py`, which
drives `local_pipeline.process_bundled_export()` end to end (synthetic ZIP
with real JPEGs + a real ffmpeg-generated MP4) instead of unit-testing
helpers in isolation. Covers: extract -> JSON match -> merge/hardlink ->
checkpoint -> simulated-crash resume (delete a merged/ output, rerun,
confirm exactly the one broken item is repaired via
`reconcile_checkpoint_with_disk`, not a full redo) -> `check_staging_readiness`.

**Why**: User flagged (and I agreed) that the existing 47 unit tests run in
under a second, which for an app whose core job is "don't lose someone's
memories" is a signal they're each testing small helpers, not the actual
risk surface. This integration test is the net that would catch a real
data-loss bug. It was deliberately built *before* the `desktop_gui_pyqt.py`
god-file split (also requested) so that large refactor has a regression
safety net on the pipeline it doesn't even touch directly - the split is
GUI-only, but confidence that "the pipeline still behaves" needed to exist
independent of GUI changes. Uses `pytest.mark.skipif(not ffmpeg_available())`
so CI/dev environments without ffmpeg degrade gracefully instead of failing.

### 2026-07-17 - File Checker made read-only; no camera make/model stat; App icon added

**What**: `run_full_analysis()` (`desktop_gui_pyqt.py`) now always runs
`ScanWorker` with `dry_run=True` - File Checker reports mismatched
extensions but never renames anything, on any folder. Extension fixing
stays exactly where it already was: automatic, inside `_fix_extension()`
(`smd/local_pipeline.py`), as part of every "Save memories" run.

**Why**: user wanted a clean mental model - "File checker should only check
files... the fixing stuff should be in save memories." Investigation showed
the fixing already only ever happened in the Save Memories pipeline for
SMD's own output; File Checker's rename-on-scan behavior was leftover
functionality for arbitrary external folders that blurred that line and
wasn't asked for.

**What (metadata stats)**: Tested real Make/Model EXIF and video container
tags on live Las-account output. Confirmed Snapchat strips all camera/device
identifying metadata from both photos and videos before export (only
`DateTime`/`GPSInfo`/`Orientation` survive on photos - and SMD wrote those -
plus generic `Core Media Video/Audio` handler names on videos). Added a
photo resolution breakdown to File Checker's media stats instead ("N unique
resolutions, most common WxH") as an honest proxy stat, and explicitly did
not add a fake "shot on which phone" feature since there is no real data
behind it.

**What (app icon)**: Added `icon.ico`/`icon.png` at repo root and under
`assets/` - they did not exist anywhere in the repo before, despite four
separate code paths (`apply_window_icon()`, the `DownloaderGUI.__init__`
icon set, the header logo, the splash screen logo) all being wired up to
load one if present. This is also why the *compiled* `SMD.exe` had no icon
either, not just source/bat runs - `smd.spec`'s `icon_arg` silently
resolved to `None`. Also added `SetCurrentProcessExplicitAppUserModelID`
so Windows gives SMD its own taskbar identity instead of grouping it under
pythonw.exe's generic icon when run from source.

**Why not implement**: cloud upload, a media gallery grid, and macOS/Linux
builds were re-confirmed out of scope per prior decisions (see below) after
a competitor sweep (`canvases/smd-competitive-landscape.canvas.tsx`) turned
up nothing that changed that calculus.

---

### 2026-07-16 - Keep system/display awake for the duration of a run

**What**: `_set_keep_awake()` (`desktop_gui_pyqt.py`) calls Win32
`SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)`
when a run starts, and clears it (`ES_CONTINUOUS` alone) at every exit path:
setup failure, cancel/fail in `on_download_finished`, the early-return in
`_show_completion_summary`, both `_on_completion_finalize_*` callbacks, and
`closeEvent` as a last-resort safety net. Scope is "run start" through "post-run
verification/finalize done" - not just the extract/merge phase - since that
tail work (`StagingVerifyWorker`, `CompletionFinalizeWorker`) can also run
for minutes on a large library.

**Why**: user with an AMD RX 6900 XT reported SMD getting dramatically slower
partway through a multi-hour run, coinciding with the monitor going to sleep;
`Ctrl+Shift+Win+B` (restarts the GPU driver) was their existing workaround.
Checked the actual run log (`run_activity_20260716_204525.log`, Las account,
13,988 files): throughput was a steady ~60-90 files/min for the first ~2.5
hours, then dropped to ~10-45 files/min from roughly 23:25 to 00:20 - the
window spanning the monitor-sleep report (~23:01) and the driver restart
(~23:32) - before recovering. That's a real, measurable 2-4x slowdown, not
just a perception. Rather than try to detect/recover from the AMD post-wake
render slowdown (a driver-level issue outside SMD's control), it's simpler
and fully sufficient to just never let the display/system sleep while SMD
has active work in flight. Deliberately does NOT keep the machine awake
outside of a run - normal power saving is untouched the rest of the time.

### 2026-07-15 - raw/merged hardlinked when identical, instead of processed/copied twice

**What**: `_process_single_item()` (`smd/local_pipeline.py`) now has a fast
path: when "Also save without filters" (`keep_raw`) is on **and** the item
has no overlay to burn in, `raw_out` and `merged_out` would end up
byte-identical - so it processes once into `raw_out`, then calls the new
`link_or_copy()` (`smd/fsutil.py`) to hardlink `merged_out` to it instead of
a second full copy (photos) or ffmpeg remux (videos). `link_or_copy` falls
back to a real atomic copy if hardlinking isn't possible (different volume,
non-NTFS filesystem) - always correct, just not space/time-saving in that
case. Overlay items are completely untouched (they need genuinely different
bytes in each folder) and so is `keep_raw=False` (nothing to link from).

**Why**: this was previously ~2x the disk I/O, EXIF writes, and ffmpeg
remuxes for every no-overlay item when raw was enabled, for output that is
provably identical bytes in both folders. Flagged as the biggest throughput
win in a 2026-07-14 pipeline audit; hardlinking is the correct fix rather
than "just skip raw" because it doesn't change what the user gets - both
folders still contain a real file at the expected path, they just share the
same disk blocks.

**Non-obvious correctness constraint**: any code that "repairs" a bad
raw/merged output written after this fast path (see the two `not ok_raw` /
`not ok_merged` retry blocks in `_process_single_item`) must use an atomic,
`os.replace`-based write (`atomic_copy`, `_write_main_to_output`), never an
in-place truncate+write (`shutil.copy2` onto an existing path, `open(path,
"wb")`). Since the two paths can be the same inode, an in-place write on one
name would silently mutate the *other* hardlinked name's content too,
instead of just fixing the broken one. The pre-existing overlay-path repair
at line ~925 (`shutil.copy2(work_main, merged_out)`) is safe *only* because
that branch is never reachable when a hardlink exists - don't reuse it for
the fast path without re-checking this invariant.

**Known side effect**: `folder_size_bytes()` (used for the session summary
and Technical-view storage label) sums each file's logical size per folder,
so it double-counts hardlinked pairs - the merged/raw byte counts shown to
the user are each the full logical size, not deduplicated true disk usage.
Not fixed here (display-only, no data-safety impact); worth revisiting if
the discrepancy confuses users the way the original 125GB-vs-45GB question
did.

### 2026-07-15 - Post-run finalize + duplicate review: move remaining GUI-thread blocking work to QThreads

**What**: `CompletionFinalizeWorker` (staging delete + `build_session_report`),
`TechnicalStorageWorker` (debounced folder-size scan for Technical view),
`DuplicatePreviewWorker` (lazy duplicate-dialog thumbnails/captions), and
routing `_open_duplicate_review_if_needed`'s cache-miss fallback through the
existing `DuplicateScanWorker` instead of a synchronous hash on the GUI thread.

**Why**: two audits found the pipeline run itself was already off-thread, but
the minutes-long freeze users reported after a large run finished was still
real: Pillow re-validating every merged photo, `shutil.rmtree` on staging,
ffmpeg/ffprobe per duplicate card, and 7× recursive size scans on account-name
keystrokes were all still synchronous on the Qt main thread. This pass moves
those to background workers without changing verification thoroughness or
output correctness.

### 2026-07-15 - Safe throughput wins: ffmpeg semaphore gap, duplicate size pre-filter, x264 preset

**What**: `copy_video_with_metadata()` now runs under `ffmpeg_sem` like overlay
merges; duplicate scan buckets by file size before SHA-256; CPU x264 fallback
preset `slow` → `medium`; checkpoint flush every 25 items (was 10); duplicate
hash workers cap raised to 16; video-ordering ffprobe pool raised to
`min(16, max_workers)`.

**Why**: low-risk fixes from a throughput audit - the semaphore gap was causing
unbounded concurrent ffmpeg remuxes; size pre-filter skips hashing files that
cannot possibly be byte-identical; other tweaks reduce I/O/subprocess overhead
without touching the hardlink/GPU-hwaccel ideas deferred to a later pass.

### 2026-07-14 - Line across the top of the main tab strip: `QSS border-top: none` on `::tab` wasn't enough; needed `QTabBar.setDrawBase(False)`

**What**: `_MainTabBar.__init__()` (`desktop_gui_pyqt.py`) now calls
`self.setDrawBase(False)` on construction.

**Why**: the horizontal line the user kept seeing across the whole tab strip
was not the border on individual tabs (`QTabWidget#mainTabs > QTabBar::tab`
already had `border-top: none;` in `smd/theme.py` from an earlier, ineffective
fix attempt). It was Qt's `PE_FrameTabBarBase` primitive - a separate line the
Fusion style paints for the `QTabBar` widget itself, to visually connect the
bar to its pane. This primitive is independent of the `::tab` box model, so no
amount of QSS on `::tab` selectors touches it. `QTabBar::setDrawBase(bool)` is
the actual Qt API for suppressing it, hence the code-level fix instead of a
third QSS attempt. Verified fixed only after confirming the user was testing
a freshly rebuilt EXE, not a stale running instance - worth checking that
first next time a "the CSS fix didn't work" report comes in.

### 2026-07-14 - Fixed `NameError: name 'message' is not defined` crash on every run start

**What**: A previous refactor that split per-run disk logging out of
`append_debug_message()` into its own `_write_run_log_line()` helper left a
few trailing lines (`short = message.strip()` +
`self._refresh_run_dashboard(...)`) behind in the *new* helper instead of
moving them there deliberately - `_write_run_log_line(self, line)` has no
`message` or `phase` in scope, so this raised `NameError` unconditionally,
every single time `append_debug_message()` ran. Since the very first call
happens immediately when a run starts (logging the chosen performance
mode), this crashed *every* "Start full processing" click, before the
worker thread even began, with a `QMessageBox` showing the raw
`NameError` text and no `processing_error.log` written (the crash was in
GUI setup code, not inside the worker's own try/except). Moved the
orphaned lines back into `append_debug_message()`, where `message`/`phase`
are actually defined.

**Why it wasn't caught sooner**: the accounts tested earlier in this
session (Las) had already finished processing before this dashboard-log
refactor landed, so nothing in this session actually clicked "Start" again
until testing a second account (Mary) afterward - the bug was latent in
the built EXE the whole time. Ran `pyflakes` across `desktop_gui_pyqt.py`
and every file in `smd/` afterward to confirm no other undefined-name
bugs are lurking; only pre-existing unused-import/variable warnings
remained.

### 2026-07-14 - Video-to-JSON-row matching uses each file's own embedded creation_time

**What**: `build_deterministic_match_map()` (`local_pipeline.py`) is the
fallback used whenever a file has no Snapchat media id to match on - which,
critically, is **always**, for any bundled export where `Download Link`/
`Media Download Url` are empty (a fully-offline/bundled export, seemingly
Snapchat's current default). It used to sort same-(day,type) files by
their UID string and JSON rows by `Date`, then pair index-by-index. UID
strings have zero relationship to actual capture order, so this could -
and did - silently swap which JSON row (date/GPS/time) got assigned to
which real file whenever 2+ items of the same type shared a UTC day.

Fixed by sorting video items (only) by each file's own embedded
`creation_time`, read directly off the staged file via ffprobe *before*
SMD writes anything to it (`metadata.read_video_capture_time`). This is
the phone's own encoder timestamp, and it reliably preserves the same
relative order as the JSON `Date` field (empirically: `Date` consistently
lags a video's own `creation_time` by ~15-40s, the "saved to memories"
delay) - so sorting by it instead of by UID string gives the correct
pairing. Photos are **not** fixed by this: Snapchat strips EXIF entirely
from exported photos (confirmed empty on every sample checked), so there
is no per-file signal to sort same-day multi-photo bursts by; they remain
on UID-stem order and can still mismatch. Only probes videos in buckets
with >1 item (a lone video has nothing to be mis-ordered against, so skip
the ffprobe call) and only trusts ffprobe when it actually returns a
value, falling back a video with no readable time to the end of the
group (sorted after all timed ones) so it can't bump a correctly-ordered
neighbor out of place.

**Why**: found via a user's report that a specific video's filename
(`17-31-37`) didn't match what Snapchat's own app showed for that exact
clip (`21:56` local). Traced the video's *own* embedded `creation_time`
(read straight from the original ZIP, confirmed by content: matched the
exact scene in the user's screenshot) to `19:57:12 UTC`, one JSON row
away from what SMD had actually assigned it (`14:31:37 UTC` - a
completely different, unrelated clip's row). Rebuilding the whole day's
video group by hand confirmed **4 of 6** videos that day were mismatched
under the old UID-string sort; all 6 came out correct once sorted by
their own `creation_time` instead, each landing within a consistent
15-40s "save lag" of its JSON row. Given how common multi-video days are,
and that UID-matching is completely inert for any account with an empty
`Download Link` (seemingly the norm now), this likely affected a
meaningful fraction of every such account's video output, not just this
one clip.

**Caveat**: this only fixes *future* runs. Files already extracted before
this fix keep whatever (possibly wrong) date/GPS/name they got; fixing
them requires reprocessing from the original export ZIP, since the
correct pairing can't be reconstructed from the already-mismatched output
alone.

### 2026-07-14 - Local time uses system timezone, not GPS-derived timezone

**What**: `smd/timeutil.py`'s `to_local_datetime()` used `timezonefinder` +
`pytz` to look up the timezone at the memory's GPS coordinates and convert
UTC to *that* zone. Changed to always use the PC's own system timezone
(`date.astimezone()` with no arg), dropping `timezonefinder`/`pytz` as
dependencies entirely (removed from `requirements.txt`, `pyproject.toml`,
`smd.spec`, `NOTICE`).

**Why**: a user found a video filed as `17-31-37` from a trip to Iraq that
Snapchat's own app displayed as `21:56`. Root cause: the phone's system
timezone stayed on the user's home zone (Denmark, UTC+2) the whole trip
(no auto-update while roaming), so Snapchat displays every timestamp in the
*device's configured timezone*, never the GPS-implied one. SMD's GPS-based
conversion was "geographically accurate" but disagreed with what the
Snapchat app - and the user's memory - actually showed. Confirmed by
recomputing the raw UTC timestamps against the user's home timezone: the
numbers lined up with what Snapchat displayed once GPS was taken out of the
equation. Using the local machine's system timezone matches Snapchat's own
behavior for the common case (processing your own export on your own PC in
your own home timezone) without needing to guess a traveling phone's
clock setting, which the export JSON doesn't record. This changes output
filenames/EXIF timestamps for any future exports containing memories
captured while traveling outside the PC's timezone; already-extracted
files from before this fix keep their old (GPS-derived) names unless
manually reprocessed.

### 2026-07-12 - Single-instance lock: atomic exclusive-create, not exists()-check-then-write()

**What**: `SingleInstance.is_already_running()` (`desktop_gui_pyqt.py`) used
to `Path.exists()` the lock file, and only if absent, `open(path, 'w')` to
claim it - two separate steps with a gap between them. Replaced with one
atomic `os.open(path, O_CREAT | O_EXCL | O_WRONLY)`: the OS itself
guarantees only one caller can ever succeed when two try at the same path
at the same time, closing the gap entirely.

**Why**: found two `pythonw.exe` processes running `desktop_gui_pyqt.py`
with the exact same process-creation timestamp (real evidence, not
theoretical) - a classic TOCTOU race, plausibly from a double-click
registering twice. Both had checked "does the lock file exist?" before
either had written it, so both proceeded to build a full window: double
the startup cost (explaining a "feels slow again" report) and two windows
independently touching the same account data with no awareness of each
other. Verified the fix with a 20-thread concurrent-claim stress test:
exactly 1 winner, 19 losers, every run.

### 2026-07-12 - Tab clipping fix, round 2: setElideMode(ElideNone) + scroll buttons, plus the real culprit (an unshortened checkbox label)

**What**: removing `setExpanding(True)` (previous entry, same day) turned
out not to be sufficient - "Save memories" was still rendering clipped
("iave memorie:") in a real screenshot. Root cause of the *remaining* clip:
Qt's `QTabBar` will still shrink/elide tabs below their natural sizeHint
whenever the bar doesn't have room for all tabs at full size and can't
scroll - true even without `setExpanding`. Fixed properly with
`tab_bar.setElideMode(Qt.ElideNone)` (Qt-guaranteed: text is never
shortened) + `setUsesScrollButtons(True)` as the fallback for genuinely
insufficient width (small arrows instead of silently truncated text).

Separately, while investigating a related "content box still needs a
horizontal scrollbar" report, found the actual likely cause: the
"Keep staging media files after processing" checkbox
(`self.keep_staging_chk`) kept its full long sentence as the *visible*
label (unlike its siblings "Also save without filters" / "Technical view",
which were shortened in the 2026-07-11 width fixes) - the full explanation
was already in its tooltip, so the long visible label was pure oversight.
Shortened to "Keep staging media files". Since this checkbox only shows
with Technical view on, this cost was invisible unless you had that
setting enabled - which the primary tester does, so it was the most likely
real cause of the residual overflow, not the outer content-box cap.

**Lesson**: when adding any new Technical-view-only control, check its
*visible* label length against its siblings, not just whether it has a
tooltip - `_technical_widgets()` keeping visibility/styling in sync doesn't
catch label-length regressions.

### 2026-07-12 - GPS map (QWebEngineView) built lazily, not eagerly at every startup

**What**: `self.map_view` used to be a real `QWebEngineView()` created
unconditionally in `init_ui()`, plus a default Copenhagen map built and
loaded into it 200ms after startup (`QTimer.singleShot(200,
self.init_default_map)`). Now `self.map_view` starts as `None` with a cheap
`QLabel` placeholder in its place; `_ensure_map_view()` swaps in the real
widget (and only then builds the default map) the first time the user
opens **File Checker** - via `_on_main_tab_changed`, plus a defensive call
in `on_map_render_finished`.

**Why**: user reported startup "took forever" with a loading screen every
launch. `QWebEngineView`/`QWebEngineProfile` spin up Qt's embedded-Chromium
subsystem (confirmed via Task Manager: two separate `QtWebEngineProcess.exe`
helper processes appear the moment it's constructed) - by a wide margin the
single most expensive thing the app does at startup, paid by **100% of
launches** even though only the File Checker tab (one of five) ever uses
it. Deferring it until that tab is actually opened means most sessions
(Guide/Save memories/Help/About only) never pay this cost at all, and even
File Checker users pay it once, when they navigate there, not blocking the
initial window.

**Caveat on this investigation**: attempts to get an exact before/after
timing number via automated headless relaunches in this session were
unreliable - an `offscreen` QPA platform env var leaked from earlier GPU
testing contaminated the first round, and even after clearing it,
detached/non-interactive process launches (no real window station) hung far
longer than a real interactive desktop session reasonably would, for
reasons unrelated to this fix (confirmed by reproducing a similar hang with
WebEngine untouched). Treat the *architectural* fix (don't eagerly build
the heaviest possible Qt subsystem for a tab most sessions never open) as
solid regardless; get real-world timing from an actual interactive launch,
not headless automation, if verifying further.

### 2026-07-12 - Main tab bar: size each tab to its own text, don't force equal widths

**What**: `tab_bar.setExpanding(True)` removed from the main `QTabWidget`
setup in `desktop_gui_pyqt.py`. `TAB_PADDING_H` (`smd/theme.py`) bumped
16 -> 20 for extra breathing room.

**Why**: `setExpanding(True)` forces every tab to the *same* width
(dividing the bar's width evenly, then only giving extra room to whichever
tab's natural size already exceeds that share). On the user's real Windows
render, "Save memories" - the longest label - was getting clipped/its
letters cut off. An offscreen PyQt sizeHint measurement couldn't reproduce
clipping using its font-substitution fallback, so this is suspected to be a
real-font-metric ("Segoe UI Variable Text") width the offscreen test
couldn't replicate - rather than debug that further, switching to Qt's
default (non-expanding) per-tab sizeHint sizing removes the whole class of
risk: each tab is guaranteed at least enough width for its own text, by
Qt's own contract, regardless of what any other tab needs. Trade-off: tabs
no longer stretch to fill the full bar width on wide windows (small gap
after the last tab) - a minor cosmetic cost for guaranteed-correct text.

### 2026-07-12 - Content column max-width trimmed another 20px (1370 -> 1350)

**What**: `CONTENT_MAX_FORM`/`CONTENT_MAX_DOCS`/`CONTENT_MAX_NARROW`
(`smd/theme.py`) reduced from 1370 to 1350.

**Why**: user asked to make "the internal box of each tab" (the
`WidthAwareColumn`-capped content area) 20px narrower, as a further tweak
on top of the 2026-07-11 width fixes.

**Update, same day**: reduced further to 1270 (another -80px) per explicit
follow-up request, targeting a horizontal scrollbar the user saw at ~half
their 1440p monitor's width (~1280px window). Note this cap is often *not*
the binding constraint at that window size in the first place - see the
"Tab clipping fix, round 2" entry below for the more likely actual cause
(an oversized checkbox label) found while investigating this.

### 2026-07-12 - GPU encoder detection: probe hardware for real, don't trust ffmpeg's compiled-in `-encoders` list

**What**: `gpu_encode.py` used to pick which GPU encoder to try first by
checking whether `h264_nvenc`/`h264_amf`/`h264_qsv` appeared in `ffmpeg
-encoders` output, in that fixed priority order. Replaced with
`_working_gpu_encoder()`: a real, tiny test encode (320x240 solid color, 1
frame) per candidate, run once and cached, that only returns an encoder id
if it *actually produces output* on this machine.

**Why**: "full" ffmpeg builds (including the one SMD bundles) compile in the
NVENC/AMF/QSV wrapper code unconditionally - `-encoders` lists all three
regardless of what GPU is actually installed. On a real AMD-only machine
(RX 6900 XT, no NVIDIA hardware at all) this meant `h264_nvenc` was always
tried first, always failed, and `merge_video_overlay`'s per-file try loop
silently fell through to AMF - correct output, but one wasted failing
ffmpeg subprocess call (full process spawn + init) on *every single*
overlay video merge, forever. Confirmed empirically: before the fix, each
merge cost 2 ffmpeg calls (failed NVENC + succeeded AMF); after, 1.
`preferred_video_encoder_label()` (used for the GUI/log status line) was
also wrong as a result, unconditionally claiming "NVIDIA GPU" on this
machine.

**Gotcha hit while building the probe**: the first probe attempt used a
64x64 test frame and wrongly reported *no* working GPU encoder at all - AMD
AMF's `encoder->Init()` fails below its minimum resolution, which looks
identical to "hardware not present" if you only check the return code.
Fixed by probing at 320x240. If you ever see a GPU encoder wrongly reported
as unavailable, check resolution/pixel-format minimums before assuming the
hardware genuinely can't do it.

**Not done**: probing QSV/NVENC on real hardware (none available). Probe
logic is generic (same real-encode-attempt approach for all three) so it
should generalize, but only AMD AMF has been hardware-verified end-to-end.

### 2026-07-12 - Metadata embedding folded into the existing ffmpeg pass, not a separate remux

**What**: `copy_video_with_metadata()` (metadata.py) and
`metadata_flags` param on `merge_video_overlay()` (overlays.py) let the
capture-date/GPS `-metadata` flags ride along on whichever ffmpeg pass
already touches the video, instead of a second dedicated remux pass
afterward.

**Why**: every video was being read and written to disk twice - once to
produce the output (copy or overlay-encode), once more just to remux in the
date. On a ~14,000-file library with mostly short clips, that per-file fixed
overhead (process spawn + full read/write) adds up more than raw
compute/GPU-encode time does. Verified via synthetic-video smoke tests
before rollout (creation_time/location land correctly in both paths); full
`pytest` suite green.

**Not done**: raising `max_ffmpeg` concurrency further. Measured on a real
run (Ryzen 7800X3D, 16 threads, 5 concurrent ffmpeg @ "maximum" mode): CPU
~37%, GPU video-codec engine only 5-9% used per job, but the GPU's *shared*
3D/shader engine (used for scaling/compositing before hardware encode) was
near-saturated in aggregate across the 5 jobs. More parallelism likely
wouldn't help and could destabilize AMF encoding, which doesn't reliably
support unlimited concurrent sessions. The concurrency cap is a hardware
constraint, not a software throttle worth loosening.

### 2026-07-11 - "Keep staging media files" checkbox, Technical-view-only, red text for all technical controls

**What**: new checkbox skips the automatic post-run staging ffprobe check
and silent auto-delete entirely. Only visible with Technical view on;
defaults to **off**. All Technical-view-only controls now render in red
(`smd.theme.technical_text_style`).

**Why**: the average SMD user will never open Technical view and has no
mental model of "staging" - for them, silent verify-then-delete-on-success
after a run is correct and expected, and must stay the default. The
checkbox exists purely as an opt-out for people who want to manually inspect
`technical/staging/` before it's gone. Red text makes "these are advanced,
not for you" visually obvious at a glance rather than requiring the user to
read every tooltip.

**Side effect used deliberately**: when the checkbox is on, the expensive
ffprobe-every-video check is skipped entirely (not just the delete) since
there's no point verifying what you're not going to delete - this also cuts
post-run wait time for people who choose it.

### 2026-07-11 - Verification uses the exact same matching function as processing

**What**: `staging_check.py` calls `build_match_map()` - the same function
`local_pipeline.py` uses to actually process files - instead of a separate,
older `build_deterministic_match_map`.

**Why**: a real "Las" account run was 100% successful but "Verify staging"
reported 41 files missing. Root-caused to two independent bugs: (1)
verification didn't know about files the user intentionally deleted via
duplicate review (fixed by reading the `duplicates_deleted_report_*.json`
audit trail), and (2) verification's matching logic could disagree with the
pipeline's own matching logic for items sharing a media UID, because one
iterated a dict in insertion order and the other didn't. Using one shared,
deterministically-ordered function for both eliminates the class of bug
entirely rather than just patching the symptom.

### 2026-07-11 - Processing UI lockout redesigned: dim sections, don't cover the dashboard

**What**: `ProcessingShieldOverlay` (full-window, blocks all input) is now
only used for the short, non-cancelable post-run staging verification.
During the actual run, `_set_run_lockout()` dims/disables Setup, Performance,
and After-processing sections individually and leaves Run (Start/Cancel) and
the Live Run Dashboard fully interactive.

**Why**: the old full-window overlay covered the dashboard too, so users
could not scroll their own live log while a multi-hour run was in progress -
exactly when they'd most want to review it. There was nothing about
"dashboard" that needed to be locked; only settings that could corrupt an
in-flight run needed disabling.

### 2026-07-11 - Video encode quality recalibrated (CRF 0 → 16, "lossless" GPU presets → quality-targeted)

**What**: `gpu_encode.py` overlay-merge encode settings changed from
CRF 0 / literal-lossless GPU presets to VMAF-calibrated "visually lossless":
x264 CRF 16, NVENC CQ 18, AMD AMF QP 22, Intel QSV global_quality 18.

**Why**: literal lossless re-encoding of already-lossy source video produced
enormous files (a `merged/` folder several times the size of `raw/`/staging)
for zero perceptible quality gain over the original. VMAF comparison showed
these settings are visually indistinguishable from lossless at a fraction of
the file size.

### 2026-07-11 - Duplicate detection: content hash, not a separate folder, log-only with permanent delete on request

**What**: `duplicates.py` hashes `merged/` content (SHA-256, byte-for-byte),
not filename/date heuristics. Detected duplicates stay in place - **no**
separate "Duplicates" folder is created. The review dialog lets the user
pick which copy(s) to keep; anything not kept is **permanently deleted**
from both `merged/` and `raw/`, recorded in a dated JSON audit report.

**Why**: an earlier idea (move duplicates into a dedicated folder for
later review) was explicitly rejected by the user in favor of keeping
everything in the normal output folders and only touching disk on an
explicit "delete" action. Scanning is expensive (hashes every file) so it's
cached to `reports/duplicates_report.json` and runs on a background thread
so it never freezes the GUI.

### 2026-07 - Offline-only by design; link-only exports rejected, not worked around

**What**: `export_detect.py` only supports exports where media is actually
bundled inside the ZIP. "Link-only" exports (JSON with download URLs,
requiring a live network fetch from Snapchat's CDN per item) are detected
and rejected with a clear message - not partially supported.

**Why**: product decision for reliability and user trust - no telemetry, no
upload, no dependency on Snapchat's servers staying available or the user's
network. Every known competitor (free or paid) has this exact same
limitation, so it isn't a competitive disadvantage worth extra engineering
or a "workaround" doc.

### 2026-07 - Windows-only; no macOS/Linux/mobile build planned by the maintainer

**What**: official target is Windows 10/11 (64-bit) only. The PyQt5 source is
cross-platform in principle but is not built, tested, or supported on any
other OS.

**Why**: maintainer has no non-Windows hardware to build or test on.
Contributions porting to other platforms are welcome (see `README.md`) but
won't be started proactively.
