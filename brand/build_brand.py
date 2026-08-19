"""Generate the NeredeParaVar brand assets for every platform.

Run:  python brand/build_brand.py

Everything is drawn as SVG and rasterised through the Chromium that Playwright
already installs for the KAP scraper, so there is no extra image toolchain.

The mark is a question mark whose dot is the lira sign -- the channel's name is
a question, and no other Turkish finance account uses one. The hook is drawn as
a path rather than set as type, because a typeface's "?" arrives with its own
dot and the lira sign has to occupy that position, not sit under it.

Every platform crops avatars to a circle, so the mark stays inside a safe
centre. Cover images keep their content away from the regions each platform
overlays or crops:

* X header 1500x500 -- the profile picture sits over the lower left.
* YouTube banner 2560x1440 -- only the central 1546x423 is guaranteed visible on
  every device ("safe area"); the rest is cropped on phones and tablets.
"""

from __future__ import annotations

import pathlib

from playwright.sync_api import sync_playwright

# --- brand ------------------------------------------------------------------

FOREST = "#16342A"   # background
CHALK = "#E8E4D9"    # mark and headline
AMBER = "#E0A33C"    # the lira dot and accents

SANS = "Helvetica Neue,Helvetica,Arial,sans-serif"

# Question-mark hook, drawn in a 1024x1024 field. The dot is deliberately absent.
HOOK = "M 322 352 C 322 168, 706 168, 706 358 C 706 496, 512 492, 512 606"

OUT = pathlib.Path(__file__).resolve().parent


def mark(scale: float = 1.0, dx: float = 0.0, dy: float = 0.0) -> str:
    """The logo mark, optionally scaled and moved within its parent SVG."""
    return (
        f'<g transform="translate({dx},{dy}) scale({scale})">'
        f'<g transform="translate(0,34)">'
        f'<path d="{HOOK}" fill="none" stroke="{CHALK}" stroke-width="94" '
        f'stroke-linecap="round"/>'
        f'<text x="512" y="838" font-family="{SANS}" font-weight="700" '
        f'font-size="228" fill="{AMBER}" text-anchor="middle">₺</text>'
        f"</g></g>"
    )


def avatar(size: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" '
        f'width="{size}" height="{size}">'
        f'<rect width="1024" height="1024" fill="{FOREST}"/>{mark()}</svg>'
    )


def wordmark(x: int, y: int, size: int = 86, sub: bool = True) -> str:
    """Name, then the sources line, then the promise."""
    out = (
        f'<text x="{x}" y="{y}" font-family="{SANS}" font-weight="700" '
        f'font-size="{size}" fill="{CHALK}" letter-spacing="-2">NeredeParaVar</text>'
    )
    if sub:
        out += (
            f'<text x="{x + 3}" y="{y + 68}" font-family="{SANS}" font-weight="600" '
            f'font-size="{size * 0.40:.0f}" fill="{AMBER}" letter-spacing="3">'
            f"TEFAS · BEFAS · KAP</text>"
            f'<text x="{x + 3}" y="{y + 124}" font-family="{SANS}" font-weight="400" '
            f'font-size="{size * 0.36:.0f}" fill="{CHALK}" opacity=".70">'
            f"Her gün · sade dille, veriyle</text>"
        )
    return out


def x_header() -> str:
    """1500x500. Content sits centre-right, clear of the avatar overlay."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1500 500" '
        f'width="1500" height="500">'
        f'<rect width="1500" height="500" fill="{FOREST}"/>'
        f"{mark(0.33, 250, 52)}"
        f"{wordmark(560, 228)}</svg>"
    )


def youtube_banner() -> str:
    """2560x1440, with everything inside the 1546x423 always-visible safe area.

    That box is centred, so it spans x 507..2053 and y 508..931. Anything outside
    is cropped on phones, which is where most viewers are.
    """
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2560 1440" '
        f'width="2560" height="1440">'
        f'<rect width="2560" height="1440" fill="{FOREST}"/>'
        f"{mark(0.42, 560, 505)}"
        f"{wordmark(1000, 672, 108)}</svg>"
    )


def telegram_cover() -> str:
    """Square card for pinning or sharing; not a platform requirement."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1080" '
        f'width="1080" height="1080">'
        f'<rect width="1080" height="1080" fill="{FOREST}"/>'
        f"{mark(0.62, 222, 130)}"
        f'<text x="540" y="880" font-family="{SANS}" font-weight="700" '
        f'font-size="96" fill="{CHALK}" text-anchor="middle" letter-spacing="-2">'
        f"NeredeParaVar</text>"
        f'<text x="540" y="946" font-family="{SANS}" font-weight="600" '
        f'font-size="40" fill="{AMBER}" text-anchor="middle" letter-spacing="4">'
        f"TEFAS · BEFAS · KAP</text></svg>"
    )


# name -> (svg, width, height). Sizes follow each platform's own guidance.
ASSETS = {
    # Avatars. All three platforms crop to a circle; YouTube asks for 800x800,
    # Telegram 512x512, X at least 400x400.
    "avatar/avatar_1024.png": (avatar(1024), 1024, 1024),
    "avatar/avatar_800_youtube.png": (avatar(800), 800, 800),
    "avatar/avatar_512_telegram.png": (avatar(512), 512, 512),
    "avatar/avatar_400_x.png": (avatar(400), 400, 400),
    # Covers.
    "cover/x_header_1500x500.png": (x_header(), 1500, 500),
    "cover/youtube_banner_2560x1440.png": (youtube_banner(), 2560, 1440),
    "cover/telegram_card_1080x1080.png": (telegram_cover(), 1080, 1080),
}

SOURCES = {
    "svg/avatar.svg": avatar(1024),
    "svg/x_header.svg": x_header(),
    "svg/youtube_banner.svg": youtube_banner(),
    "svg/telegram_card.svg": telegram_cover(),
}


def main() -> None:
    for name, svg in SOURCES.items():
        path = OUT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(svg, encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for name, (svg, width, height) in ASSETS.items():
            path = OUT / name
            path.parent.mkdir(parents=True, exist_ok=True)
            page = browser.new_page(viewport={"width": width, "height": height})
            page.set_content(f'<body style="margin:0">{svg}</body>')
            page.wait_for_timeout(300)
            page.screenshot(path=str(path))
            page.close()
            print("wrote", name)
        browser.close()


if __name__ == "__main__":
    main()
