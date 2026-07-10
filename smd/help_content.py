"""Illustrative Help tab HTML (Qt QTextBrowser) - same visual language as the Guide."""
from __future__ import annotations

import html

_BODY = (
    "line-height: 1.65; font-size: 16px;"
    " p { margin: 0 0 12px; }"
    " ul { margin: 8px 0 12px 22px; padding: 0; }"
    " li { margin-bottom: 6px; }"
    " code { font-family: Consolas, monospace; font-size: 13px; "
    "background: rgba(128,128,128,0.15); padding: 1px 5px; border-radius: 4px; }"
)
_SECTION = (
    "margin: 32px 0 36px; padding: 0 0 28px; border-bottom: 1px solid rgba(128,128,128,0.35);"
)
_H2 = "margin: 0 0 12px; font-size: 22px;"
_H3 = "margin: 0 0 10px; font-size: 18px;"
_TOC = (
    "font-size: 15px; line-height: 2; margin: 16px 0 24px; padding: 14px 18px; "
    "background: rgba(128,128,128,0.1); border-radius: 10px;"
)


def _callout(kind: str, title: str, body: str) -> str:
    styles = {
        "warn": "background: rgba(196,92,10,0.16); border: 2px solid rgba(196,92,10,0.55);",
        "ok": "background: rgba(45,138,62,0.14); border: 2px solid rgba(45,138,62,0.45);",
        "info": "background: rgba(128,128,128,0.12); border: 2px solid rgba(128,128,128,0.4);",
        "tip": "background: rgba(245,196,0,0.14); border: 2px solid rgba(184,148,26,0.5);",
    }
    box = styles.get(kind, styles["info"])
    return (
        f'<div style="{box} border-radius: 10px; padding: 14px 16px; margin: 16px 0;">'
        f'<p style="margin:0 0 8px; font-size:17px; font-weight:700;">{html.escape(title)}</p>'
        f'<div style="{_BODY}">{body}</div></div>'
    )


def _flow_diagram(steps: list[tuple[str, str]]) -> str:
    cells = []
    for i, (label, caption) in enumerate(steps):
        cells.append(
            '<td style="text-align:center; vertical-align:top; padding:4px 6px;">'
            f'<div style="background:rgba(128,128,128,0.15); border:1px solid rgba(128,128,128,0.45); '
            f'border-radius:8px; padding:10px 12px; min-width:80px;">'
            f'<div style="font-weight:700; font-size:14px;">{html.escape(label)}</div>'
            f'<div style="font-size:12px; margin-top:4px; opacity:0.85;">{html.escape(caption)}</div>'
            "</div></td>"
        )
        if i < len(steps) - 1:
            cells.append(
                '<td style="text-align:center; vertical-align:middle; '
                'font-size:18px; padding:0 3px; color:rgba(128,128,128,0.9);">→</td>'
            )
    return (
        '<table style="width:100%; border-collapse:collapse; margin:16px 0 8px;">'
        f"<tr>{''.join(cells)}</tr></table>"
    )


def _pipeline_ladder(steps: list[tuple[str, str]]) -> str:
    rows = []
    for i, (title, detail) in enumerate(steps, start=1):
        rows.append(
            "<tr>"
            f'<td style="width:44px; vertical-align:top; padding:6px 10px 6px 0;">'
            f'<div style="width:32px; height:32px; line-height:32px; text-align:center; '
            f'border-radius:16px; font-weight:700; font-size:14px; '
            f'background:rgba(196,92,10,0.25); border:1px solid rgba(196,92,10,0.5);">{i}</div>'
            "</td>"
            f'<td style="vertical-align:top; padding:6px 0 14px;">'
            f'<div style="font-weight:700; font-size:15px; margin-bottom:4px;">{html.escape(title)}</div>'
            f'<div style="font-size:14px; line-height:1.5; opacity:0.9;">{detail}</div>'
            "</td></tr>"
        )
    return (
        '<table style="width:100%; border-collapse:collapse; margin:12px 0;">'
        f"{''.join(rows)}</table>"
    )


def _checklist(items: list[tuple[str, str]]) -> str:
    rows = []
    for title, detail in items:
        rows.append(
            "<tr>"
            '<td style="width:28px; vertical-align:top; padding:4px 10px 10px 0;">'
            '<div style="width:22px; height:22px; border:2px solid rgba(196,92,10,0.6); '
            'border-radius:4px; text-align:center; line-height:20px; font-size:14px;">☐</div>'
            "</td>"
            f'<td style="vertical-align:top; padding:4px 0 10px;">'
            f'<div style="font-weight:700; font-size:15px;">{html.escape(title)}</div>'
            f'<div style="font-size:14px; line-height:1.5; opacity:0.9; margin-top:3px;">{detail}</div>'
            "</td></tr>"
        )
    return (
        '<table style="width:100%; border-collapse:collapse; margin:14px 0;">'
        f"{''.join(rows)}</table>"
    )


def _tree_block(text: str) -> str:
    return (
        f'<pre style="font-family:Consolas,monospace; font-size:13px; line-height:1.45; '
        f"background:rgba(128,128,128,0.1); border-left:4px solid rgba(196,92,10,0.7); "
        f'border-radius:0 8px 8px 0; padding:14px 16px; margin:12px 0; white-space:pre-wrap;">'
        f"{html.escape(text)}</pre>"
    )


def _compare_two(left_title: str, left_body: str, right_title: str, right_body: str) -> str:
    return (
        '<table style="width:100%; border-collapse:collapse; margin:14px 0;">'
        "<tr>"
        '<td style="width:50%; vertical-align:top; padding:6px;">'
        '<div style="border:2px solid rgba(196,92,10,0.45); border-radius:10px; padding:14px;">'
        f'<div style="font-weight:700; font-size:16px; margin-bottom:8px;">{html.escape(left_title)}</div>'
        f'<div style="{_BODY}">{left_body}</div></div></td>'
        '<td style="width:50%; vertical-align:top; padding:6px;">'
        '<div style="border:2px solid rgba(128,128,128,0.45); border-radius:10px; padding:14px;">'
        f'<div style="font-weight:700; font-size:16px; margin-bottom:8px;">{html.escape(right_title)}</div>'
        f'<div style="{_BODY}">{right_body}</div></div></td>'
        "</tr></table>"
    )


def build_help_html(process_tab_name: str = "Save memories") -> str:
    p = html.escape(process_tab_name)
    parts = [
        "<div style='line-height:1.55;'>",
        f"<h2 style='{_H2}'>Help</h2>",
        f"<p style='{_BODY} margin-bottom:12px;'>"
        "Turn your Snapchat export into dated photos and videos on your PC - filters, GPS, and all. "
        "Use the <b>Guide</b> tab for Snapchat steps; this page covers SMD itself.</p>",
        f'<nav style="{_TOC}">'
        "<b>On this page</b><br>"
        '<a href="#start">1. Start here</a><br>'
        '<a href="#before">2. Before export</a><br>'
        f'<a href="#run">3. Run processing</a><br>'
        '<a href="#folders">4. Where files go</a><br>'
        '<a href="#after">5. After processing</a><br>'
        '<a href="#fix">6. Troubleshooting</a>'
        "</nav>",
        f'<section id="start" style="{_SECTION}">',
        f"<h3 style='{_H3}'>1. Start here</h3>",
        _flow_diagram(
            [
                ("Guide tab", "Request export"),
                ("Email", "Download all ZIPs"),
                (process_tab_name, "Start full processing"),
                ("Desktop folder", "Your library"),
            ]
        ),
        _checklist(
            [
                (
                    "All ZIP parts in one folder",
                    "Names like <code>mydata~123.zip</code>, <code>mydata~123-2.zip</code>. "
                    f"Pick any one file or the whole folder on the <b>{p}</b> tab.",
                ),
                (
                    "Export summary looks right",
                    "Yellow banner should say <b>Bundled export</b> with ZIP part count and media file count.",
                ),
                (
                    "Project name set",
                    "Example <code>Mary</code> - folder is created when processing <b>starts</b>, not while typing.",
                ),
                (
                    "Enough disk space",
                    "Plan for roughly <b>2-3× the ZIP size</b> during the run; you can free staging later "
                    "(Technical view only).",
                ),
            ]
        ),
        _callout(
            "tip",
            "New to Snapchat export?",
            "Open the <b>Guide</b> tab first - it has screenshots for requesting your data.",
        ),
        "</section>",
        f'<section id="before" style="{_SECTION}">',
        f"<h3 style='{_H3}'>2. Before export</h3>",
        _callout(
            "warn",
            "My Eyes Only is never included",
            "<p>Unlock <b>My Eyes Only</b> and move snaps into <b>Memories</b> "
            "<b>before</b> you submit the data request. SMD cannot recover what Snapchat omitted.</p>"
            "<p>Snaps never saved to Memories (Camera Roll only, chats, expired stories) are excluded too.</p>",
        ),
        _compare_two(
            "Download link - expires",
            "<p>Snapchat’s email link for each ZIP part - often only a few days.</p>"
            "<p>Download <b>every part</b> before it expires.</p>",
            "ZIP on disk - permanent",
            "<p>Once saved, process offline anytime.</p>"
            "<p>Keep ZIPs as backup until your library looks complete.</p>",
        ),
        f"<p style='{_BODY}'>Inside each ZIP part:</p>",
        _tree_block(
            "memories_history.json     dates, GPS, titles\n"
            "memories/\n"
            "  abc-main.jpg + abc-overlay.png    filter layer\n"
            "  def-main.mp4 + def-overlay.png\n"
            "  …"
        ),
        _callout(
            "ok",
            "Bundled export (current Snapchat format)",
            "<p>Media is already inside the ZIP. JSON rows with <b>no URL</b> or <code>N/A</code> are "
            "<b>normal</b> - files live in <code>memories/</code>, not on the web.</p>"
            "<p>Older exports without bundled media are <b>not supported</b> - request a fresh export from Snapchat.</p>",
        ),
        "</section>",
        f'<section id="run" style="{_SECTION}">',
        f"<h3 style='{_H3}'>3. Run processing</h3>",
        f"<p style='{_BODY}'>On the <b>{p}</b> tab:</p>",
        _pipeline_ladder(
            [
                (
                    "Select ZIP files or folder",
                    "<b>Select ZIP folder</b> is easiest when all parts sit together.",
                ),
                (
                    "Choose performance + estimate",
                    "<b>Maximum</b> / <b>Balanced</b> / <b>Eco</b>. Use <b>Estimate time</b> and "
                    "<b>Recommended settings</b> before long runs.",
                ),
                (
                    "Run block options",
                    "Filters are always included. Optionally tick <b>Also save without filters</b> for plain copies. "
                    "Tick <b>Technical view</b> only if you need staging, verify, or folder trees (see section 4).",
                ),
                (
                    "Start full processing",
                    "Extract → match JSON → merge overlays → embed metadata → summary popup.",
                ),
            ]
        ),
        f"<p style='{_BODY}'>During the run:</p>",
        _pipeline_ladder(
            [
                (
                    "Checkpoint every 10 files",
                    "Progress saved under technical storage so you can cancel and resume later.",
                ),
                (
                    "Output filenames",
                    "From JSON date/time, e.g. <code>2019-07-04_18-32-01.jpg</code>. "
                    "Collisions get a suffix - see <code>technical/reports/filename_collisions.json</code> "
                    "(Technical view).",
                ),
                (
                    "Metadata",
                    "JPEG EXIF date + GPS when available. Same for MP4/MOV container tags.",
                ),
            ]
        ),
        _callout(
            "info",
            "Privacy",
            "Bundled processing stays on your PC. SMD is not affiliated with Snap Inc.",
        ),
        "</section>",
        f'<section id="folders" style="{_SECTION}">',
        f"<h3 style='{_H3}'>4. Where files go</h3>",
        f"<p style='{_BODY}'>Layout depends on <b>Technical view</b> on the Run card (off by default):</p>",
        _compare_two(
            "Simple (default)",
            "<p><b>Your photos/videos:</b> <code>Desktop/&lt;project&gt;/</code></p>"
            "<p>If <b>Also save without filters</b> is on:</p>"
            "<ul>"
            "<li><code>Desktop/&lt;project&gt;/merged/</code> - with filters</li>"
            "<li><code>Desktop/&lt;project&gt;/raw/</code> - plain copies</li>"
            "</ul>"
            "<p><b>Working data</b> (staging, JSON, checkpoints) lives in "
            "<code>%LOCALAPPDATA%\\SnapchatMemoriesDownloader\\accounts\\&lt;project&gt;\\technical\\</code> "
            "- hidden from normal browsing.</p>",
            "Technical view (advanced)",
            "<p>Everything under <code>Desktop/SMD Media/accounts/&lt;project&gt;/</code>:</p>"
            "<ul>"
            "<li><code>downloads/merged/</code> - finished library</li>"
            "<li><code>downloads/raw/</code> - optional plain copies</li>"
            "<li><code>technical/staging/</code> - huge temp extract</li>"
            "<li><code>technical/reports/</code>, <code>checkpoint/</code>, <code>logs/</code></li>"
            "</ul>"
            "<p>Enables <b>Verify staging</b>, <b>Open technical folder</b>, and storage size labels.</p>",
        ),
        _callout(
            "warn",
            "Disk space",
            "<p><code>staging/</code> can match the uncompressed ZIP size. "
            "Only delete it after <b>Verify staging</b> passes (Technical view).</p>"
            "<p>If space runs out mid-run: free space, same project name, run again - checkpoint resumes.</p>",
        ),
        "</section>",
        f'<section id="after" style="{_SECTION}">',
        f"<h3 style='{_H3}'>5. After processing</h3>",
        _pipeline_ladder(
            [
                ("Read the summary popup", "Check failed count and file totals."),
                (
                    "Open finished folder",
                    "Opens your library folder (Desktop project folder, or <code>downloads/merged/</code> in Technical view).",
                ),
                (
                    "Spot-check a few files",
                    "Filters, dates, and GPS look correct in Properties or File Checker.",
                ),
                (
                    "Review duplicates (optional)",
                    "Scans for byte-identical files. Pick keepers; non-keepers copy to "
                    "<code>duplicates_selected_&lt;timestamp&gt;/</code> beside your library - merged folder is untouched.",
                ),
                (
                    "Verify staging + delete (Technical view)",
                    "When verify passes, delete <code>technical/staging/</code> to reclaim space.",
                ),
            ]
        ),
        _callout(
            "ok",
            "Resume after cancel or crash",
            "<p>Same project name + same ZIPs → finished files are skipped automatically.</p>"
            "<p>Deleted <code>merged/</code> but kept ZIPs → re-run re-merges. "
            "Deleted staging → re-extracts from ZIPs (slower).</p>",
        ),
        _callout(
            "tip",
            "File Checker tab",
            "<b>Check folder</b> then <b>Load GPS map</b> to confirm location metadata. "
            "Empty map with GPS count &gt; 0 in the metadata panel usually means zoom or filter - "
            "no GPS on a file is normal for indoor snaps.",
        ),
        "</section>",
        f'<section id="fix" style="{_SECTION} border-bottom:none;">',
        f"<h3 style='{_H3}'>6. Troubleshooting</h3>",
        _callout(
            "info",
            "Incomplete library / low file count",
            "<p>Almost always <b>missing ZIP parts</b>. You need every <code>mydata~…-N.zip</code> in one folder.</p>",
        ),
        _callout(
            "info",
            "Banner says export not supported",
            "<p>Your ZIP has no bundled media. Request a new Snapchat export with "
            "<b>Export your Memories</b> and <b>Export JSON files</b> enabled (see Guide tab).</p>",
        ),
        _callout(
            "warn",
            "Specific snaps missing",
            "<p>(1) Was it in My Eyes Only? (2) All ZIP parts? (3) Saved to Memories before export? "
            "(4) Search <code>memories_history.json</code> for the date.</p>",
        ),
        _callout(
            "warn",
            "Video overlays missing or black",
            "<p>Video merge needs bundled <b>ffmpeg</b>. Check <code>technical/quarantine/</code> for failed items.</p>",
        ),
        _callout(
            "warn",
            "Out of disk space",
            "<p>Free space on the drive holding your project, resume with the same name. "
            "Then Verify staging → delete staging (Technical view).</p>",
        ),
        "</section>",
        "</div>",
    ]
    return "".join(parts)
