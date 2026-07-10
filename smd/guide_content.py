"""Guide tab HTML for Qt QTextBrowser."""
from __future__ import annotations

import html
from pathlib import Path

GUIDE_IMAGE_WIDTH = 280

_STYLES = f"""
body {{ margin: 0; line-height: 1.55; }}
.guide-root {{ line-height: 1.55; }}
.guide-h2 {{ margin: 0 0 10px; font-size: 22px; font-weight: 700; }}
.guide-h3 {{ margin: 0 0 10px; font-size: 18px; font-weight: 700; }}
.guide-section {{
    margin: 32px 0 36px; padding: 0 0 28px;
    border-bottom: 1px solid rgba(128, 128, 128, 0.35);
}}
.guide-body {{ line-height: 1.65; font-size: 16px; }}
.guide-body p {{ margin: 0 0 12px; }}
.guide-body ul {{ margin: 8px 0 12px 22px; padding: 0; }}
.guide-body li {{ margin-bottom: 6px; }}
.guide-body code {{
    font-family: Consolas, monospace; font-size: 13px;
    background: rgba(128, 128, 128, 0.15); padding: 1px 5px; border-radius: 4px;
}}
.guide-intro {{ margin: 0 0 28px; line-height: 1.65; font-size: 16px; }}
.guide-img-wrap {{ text-align: center; margin: 20px 0 8px; }}
.guide-img {{
    max-width: 100%; height: auto;
    border: 1px solid #555; border-radius: 12px;
}}
.guide-missing {{
    color: #c45c0a; font-size: 13px; margin: 12px 0; font-style: italic;
}}
"""


def guide_assets_dir() -> Path:
    from smd.runtime import app_root, internal_root

    root = Path(__file__).resolve().parent.parent
    for base in (app_root(), internal_root(), root):
        candidate = base / 'assets' / 'guide'
        if candidate.is_dir():
            return candidate
    return root / 'assets' / 'guide'


def _scaled_image_size(path: Path, target_width: int) -> tuple[int, int]:
    """Width/height (px) for an image scaled to target_width, preserving aspect.

    Qt's rich-text layout reserves an image's *native* height even when CSS
    scales its width, which leaves large vertical gaps. Emitting explicit
    width+height attributes makes the layout reserve the correct scaled height.
    """
    try:
        from PIL import Image

        with Image.open(path) as img:
            w, h = img.size
        if w > 0:
            return target_width, max(1, round(target_width * h / w))
    except Exception:
        pass
    return target_width, target_width


def _guide_steps(save_tab_name: str) -> list[dict]:
    return [
        {
            'title': 'Before you request data: My Eyes Only',
            'body': (
                '<p><b>Do this first.</b> Anything still in <b>My Eyes Only</b> is <b>not</b> included in a normal '
                'Memories export. Open My Eyes Only, unlock it, and <b>move those snaps into Memories</b> '
                '(or save them to your phone) <b>before</b> you submit the data request below. '
                'If you skip this, those locked items will be missing from your export forever unless you export again later.</p>'
            ),
        },
        {
            'title': 'Step 1: Open your profile',
            'body': '<p>On the camera screen, tap your <b>profile icon</b> in the top-left corner.</p>',
            'image': 1,
            'alt': 'Tap profile icon top left',
        },
        {
            'title': 'Step 2: Open Settings',
            'body': '<p>Tap the <b>settings gear</b> in the top-right corner.</p>',
            'image': 2,
            'alt': 'Tap settings gear',
        },
        {
            'title': 'Step 3: Go to My Data',
            'body': '<p>Under <b>Privacy controls</b>, tap <b>My Data</b>.</p>',
            'image': 3,
            'alt': 'Privacy controls - My Data',
        },
        {
            'title': 'Step 4: Select Memories and JSON',
            'body': (
                '<p><b>Turn ON:</b></p><ul>'
                '<li><b>Export your Memories</b> (photos and videos inside the ZIP)</li>'
                '<li><b>Export JSON files</b> (includes <code>memories_history.json</code> with dates and GPS)</li>'
                '</ul><p>Turn <b>OFF</b> other categories if you only want memories. Then tap <b>Next</b>.</p>'
            ),
            'image': 4,
            'alt': 'Export Memories and JSON then Next',
        },
        {
            'title': 'Step 5: Choose date range and submit',
            'body': (
                '<p>Select <b>All Time</b> (or your preferred range), confirm your email, then tap <b>Submit</b>.</p>'
                '<p>Snapchat emails you when the export is ready. Large libraries may arrive as multiple ZIP parts:</p>'
                '<p><code>mydata~1234567890.zip</code>, <code>mydata~1234567890-2.zip</code>, and so on.</p>'
                '<p>Download <b>all parts</b> into one folder before processing. '
                'Snapchat\u2019s download link in the email expires after a few days \u2014 see the <b>Help</b> tab for details.</p>'
            ),
            'image': 5,
            'alt': 'All Time and Submit',
        },
        {
            'title': 'Step 6: Save your memories in SMD',
            'body': (
                f'<p>Open the <b>{html.escape(save_tab_name)}</b> tab, select any one ZIP or the folder with all parts, '
                'then click <b>Start full processing</b>.</p>'
            ),
        },
        {
            'title': 'After your export (optional)',
            'body': (
                '<p>Planning to keep using Snapchat? See the <b>Help</b> tab for privacy settings, '
                'My Eyes Only reminders, and what to do after your export is saved.</p>'
            ),
        },
    ]


def build_guide_html(save_tab_name: str) -> str:
    guide_dir = guide_assets_dir()
    parts = [
        '<html><head><meta charset="utf-8"><style>',
        _STYLES,
        '</style></head><body><div class="guide-root">',
        '<h2 class="guide-h2">How to request your Snapchat data</h2>',
        f'<p class="guide-intro">Follow these steps in the Snapchat app, then use the '
        f'<b>{html.escape(save_tab_name)}</b> tab in SMD.</p>',
    ]

    for step in _guide_steps(save_tab_name):
        parts.append('<section class="guide-section">')
        parts.append(f'<h3 class="guide-h3">{html.escape(step["title"])}</h3>')
        parts.append(f'<div class="guide-body">{step["body"]}</div>')
        image = step.get('image')
        if image is not None:
            path = guide_dir / f'{image}.png'
            if path.is_file():
                alt = html.escape(step.get('alt', ''))
                w, h = _scaled_image_size(path, GUIDE_IMAGE_WIDTH)
                parts.append(
                    f'<div class="guide-img-wrap">'
                    f'<img class="guide-img" src="{image}.png" alt="{alt}" '
                    f'width="{w}" height="{h}" />'
                    f'</div>'
                )
            else:
                parts.append(
                    f'<p class="guide-missing">Screenshot unavailable ({html.escape(str(image))}.png).</p>'
                )
        parts.append('</section>')

    parts.append('</div></body></html>')
    return ''.join(parts)
