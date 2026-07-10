# SMD Phase A Test Plan (Simple + Specific)

Run this exactly in order.  
Goal: prove the app is stable before Phase B.

---

## 0) What You Need Before Testing

- Windows laptop (10 or 11, 64-bit)
- Internet connection
- One real Snapchat export ZIP (must include `memories_history.json`)
- Project folder: `C:\Users\lasis\Documents\SMD`

Optional but useful:

- A second ZIP with many files (for cancel/resume test)

---

## 1) Start the App (Dev Run)

Open PowerShell in `C:\Users\lasis\Documents\SMD`, then run:

```powershell
.\.venv\Scripts\Activate.ps1
python .\desktop_gui_pyqt.py
```

### Pass if:

- App opens
- It does not crash on startup
- You see a startup status message (self-check)

---

## 2) Quick Import Validation (2 minutes)

### A. Valid ZIP

1. Click **Browse ZIP** (or import button)
2. Select your real Snapchat export ZIP
3. Enter account name: `test-account`

Pass if:

- ZIP is accepted
- No crash/error loop

### B. Invalid ZIP

1. Try a random non-Snapchat ZIP (or wrong file)

Pass if:

- You get a clear error message
- App stays usable

---

## 3) Main End-to-End Download Test (Most Important)

1. Use account name: `test-account`
2. Speed mode: **Normal**
3. Click **Start Download**
4. Let it complete (do not close app)

### Pass if ALL are true:

- Progress/status updates are visible during run
- App completes without crashing
- Files exist in:
  - `accounts\test-account\downloads`
- Some files have expected date-time names
- If broken tiny files are encountered, they appear in:
  - `accounts\test-account\downloads\quarantine`

---

## 4) Cancel + Resume Test (Critical Reliability)

Use a large export (or restart same test and cancel after 1-2 minutes).

1. Start download
2. Click **Cancel** mid-download
3. Close app
4. Reopen app
5. Select same ZIP + same account name `test-account`
6. Start download again

### Pass if ALL are true:

- App does not crash during cancel
- Resume run starts normally
- Already downloaded files are skipped
- Remaining files continue downloading

---

## 5) GPS Verification Test (GUI)

1. Go to analysis/scan tab
2. Select folder:
  - `accounts\test-account\downloads`
3. Run GPS check / map scan

### Pass if:

- No crash
- Some files are reported as GPS found/no GPS
- Results are shown clearly (not empty error spam)

---

## 6) “My Eyes Only” Notice Check

In the app download guidance/troubleshoot text, verify the message exists.

### Pass if:

- It clearly says `My Eyes Only` content is not included in this flow
- It tells user to move those items to Memories and re-export

---

## 7) CLI Smoke Test (Optional but recommended)

From PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python .\main.py "C:\FULL\PATH\TO\memories_history.json" -o ".\downloads-test" --limit 5
```

### Pass if:

- Command starts
- Downloads begin
- Final summary prints downloaded/skipped/failed

---

## 8) Final Result: Phase A PASS / FAIL

Mark **PASS** only if:

- Startup test passed
- Import validation passed
- End-to-end download passed
- Cancel + resume passed
- GPS verification passed
- My Eyes Only notice exists

If any one fails: mark **FAIL** and note exact step + error text.

---

## 9) Save Your Test Evidence (Very Useful)

After testing, save:

- 3 screenshots:
  - startup
  - in-progress download
  - completed summary
- One screenshot of GPS verification result
- Any error popup text (copy exact message)

This makes fixing remaining issues much faster.

# SMD Phase A Test Plan (Windows 10/11)

Use this checklist before Phase B. Goal: verify reliability and resume safety.

## Test Environment

- OS: Windows 10 x64 (required), Windows 11 x64 (recommended sanity check)
- Python: same version used for build
- Network: stable home internet
- Input: real Snapchat export ZIP containing `memories_history.json`

## Preflight

- App launches without crash
- Startup self-check message appears
- Import ZIP dialog opens and accepts a valid ZIP
- Invalid ZIP shows clear error

## Scenario 1: End-to-End Download (Primary)

1. Open app
2. Select export ZIP
3. Set account name (`test-account`)
4. Use Normal speed
5. Start download and let it finish

Expected:

- Status updates are visible and understandable
- Files are created under `accounts/test-account/downloads`
- No duplicate overwrite corruption
- Tiny/broken files are moved to `quarantine` when applicable
- Final completion message appears

## Scenario 2: Resume After Cancel (Critical)

1. Start a download with many items
2. Cancel mid-run
3. Close app
4. Reopen app, same account name, same ZIP
5. Start download again

Expected:

- App does not redownload already completed files (unless forced)
- Resume continues from remaining items
- No crash during cancel/restart

## Scenario 3: Re-embed Existing Files (Scan Tab Path)

1. Open scan/analysis tab
2. Select folder with downloaded media
3. Provide `memories_history.json` when prompted for mapping
4. Run GPS-related verification flow

Expected:

- No crash in re-embed/verification path
- Files with GPS are detected correctly
- Files without GPS are reported clearly

## Scenario 4: File Extension Integrity

1. Run folder scan on downloaded media
2. Let extension fix/check complete

Expected:

- Mislabeled media types are corrected where detectable
- Summary includes scanned count and fixed count
- Non-media files are skipped safely

## Scenario 5: My Eyes Only Communication

- Download guidance includes My Eyes Only notice
- Troubleshooting includes explanation for missing My Eyes Only files

## CLI Smoke Test

Run:

```powershell
python main.py "C:\path\to\memories_history.json" -o ".\downloads-test" --limit 5
```

Expected:

- CLI starts and parses JSON
- Downloads begin
- Summary prints downloaded/skipped/failed counts

## Pass Criteria

Phase A is accepted when:

- Scenario 1 passes
- Scenario 2 passes
- No blocker crash across all scenarios
- GPS and extension checks are functionally correct on real data samples

## Known Non-Goals for Phase A

- Full UI redesign
- Installer polishing and advanced onboarding
- Telemetry/analytics additions

