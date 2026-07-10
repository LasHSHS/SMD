"""Support / donation links - single place to configure how users can help."""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Literal

AUTHOR_URL = "https://github.com/LasHSHS"

# Optional tip links (platforms with free tiers for creators). Leave blank to hide.
PAYPAL_DONATE_URL = "https://www.paypal.com/donate?hosted_button_id=MFB8WWPUL8JPN"
KOFI_URL = "https://ko-fi.com/lashs"
LIBERAPAY_URL = "https://en.liberapay.com/Las_HS/"
GITHUB_SPONSORS_URL = ""  # e.g. https://github.com/sponsors/LasHSHS - no platform fee


@dataclass(frozen=True)
class SupportOption:
    label: str
    description: str
    url: str
    category: Literal["donate", "free"] = "donate"


def support_options() -> list[SupportOption]:
    """Return configured support options (empty URLs are omitted)."""
    options: list[SupportOption] = []

    if PAYPAL_DONATE_URL:
        options.append(
            SupportOption(
                "PayPal",
                "One-time tip - only if you already use PayPal",
                PAYPAL_DONATE_URL,
                "donate",
            )
        )
    if KOFI_URL:
        options.append(
            SupportOption(
                "Ko-fi",
                "One-time tip - card or PayPal via Ko-fi",
                KOFI_URL,
                "donate",
            )
        )
    if LIBERAPAY_URL:
        options.append(
            SupportOption(
                "Liberapay",
                "Recurring or one-time tip - no platform fee",
                LIBERAPAY_URL,
                "donate",
            )
        )
    if GITHUB_SPONSORS_URL:
        options.append(
            SupportOption(
                "GitHub Sponsors",
                "Monthly or one-time support for open-source work",
                GITHUB_SPONSORS_URL,
                "donate",
            )
        )

    options.append(
        SupportOption(
            "Star on GitHub",
            "Free - helps others find SMD and shows what to improve",
            AUTHOR_URL,
            "free",
        )
    )
    return options


def support_options_html() -> str:
    """About-tab HTML for support choices."""
    donate = [o for o in support_options() if o.category == "donate"]
    free = [o for o in support_options() if o.category == "free"]

    parts = [
        "<p>SMD is free to use. <b>No payment is required.</b> If it saved you time, pick "
        "whatever fits you - many people prefer free options like starring the project on GitHub.</p>",
    ]
    if donate:
        parts.append("<p><b>Optional tips</b> - only through a service you already use:</p><ul>")
        for opt in donate:
            parts.append(
                f"<li><a href='{html.escape(opt.url)}'><b>{html.escape(opt.label)}</b></a> - "
                f"{html.escape(opt.description)}</li>"
            )
        parts.append("</ul>")
    if free:
        parts.append("<p><b>Free ways to help</b> - no account charges, no pressure:</p><ul>")
        for opt in free:
            parts.append(
                f"<li><a href='{html.escape(opt.url)}'><b>{html.escape(opt.label)}</b></a> - "
                f"{html.escape(opt.description)}</li>"
            )
        parts.append("</ul>")
    parts.append(
        f"<p>Use the <b>Support me</b> menu in the top-right corner for the same links.</p>"
    )
    return "".join(parts)
