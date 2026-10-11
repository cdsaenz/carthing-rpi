"""
Theme — adaptive palette from album art + base design tokens.
"""

import os
from PIL import Image
import colorsys


# ── Screen ────────────────────────────────────
WIDTH = 800
HEIGHT = 480

# ── Base palette (used when no album art) ─────
BG_DEFAULT = (18, 18, 24)
TEXT_PRIMARY = (255, 255, 255)
TEXT_SECONDARY = (180, 180, 200)
TEXT_DIM = (120, 120, 140)
ACCENT = (30, 215, 96)        # Spotify green
PROGRESS_BG = (70, 70, 80)
PROGRESS_FILL = (255, 255, 255)

# ── Font paths ────────────────────────────────
# Poppins — free OFL font, closest common match to Spotify's Circular
_FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
FONT_BOLD = os.path.join(_FONTS_DIR, "Poppins-Bold.ttf")
FONT_SEMIBOLD = os.path.join(_FONTS_DIR, "Poppins-SemiBold.ttf")
FONT_MEDIUM = os.path.join(_FONTS_DIR, "Poppins-Medium.ttf")
FONT_REGULAR = os.path.join(_FONTS_DIR, "Poppins-Regular.ttf")

# ── Font sizes ────────────────────────────────
# Sized for an 800x480 5" panel — noticeably bigger than SCT's own screen,
# so text needs to scale up to use the space instead of looking lost in it.
SIZE_TOPLABEL = 24   # album + year, above the track name
SIZE_TRACK = 52
SIZE_ARTIST = 30
SIZE_TIME = 16
SIZE_CLOCK = 132   # home screen's big local time
SIZE_DATE = 26
SIZE_TEMP = 62


def extract_palette(pil_image, sample_size=48, num_colors=8):
    """
    Extract a dominant, vibrant color from album art.

    A flat pixel average washes out fast — any cover with black/white
    background or several strong hues (a tri-color sleeve, a photo with sky
    in it) averages toward gray no matter how punchy the art actually looks.
    Instead: cluster into a small palette, then pick the cluster that's both
    prevalent *and* saturated (ignoring near-black/near-white clusters,
    which are usually just background/padding, not "the" color).

    Returns (bg, text, accent) tuple of RGB tuples.
    """
    if pil_image is None:
        return BG_DEFAULT, TEXT_PRIMARY, ACCENT

    try:
        small = pil_image.resize((sample_size, sample_size), Image.LANCZOS).convert("RGB")
        quantized = small.quantize(colors=num_colors)
        palette = quantized.getpalette()
        counts = quantized.getcolors()  # [(count, palette_index), ...]

        best_score = -1.0
        best_rgb = None
        fallback_rgb = None
        for count, idx in counts:
            pr, pg, pb = palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2]
            hh, ss, vv = colorsys.rgb_to_hsv(pr / 255, pg / 255, pb / 255)
            if fallback_rgb is None or count > fallback_rgb[0]:
                fallback_rgb = (count, (pr, pg, pb))
            if vv < 0.12 or vv > 0.95:
                continue  # near-black / near-white — background padding, not "the" color
            score = ss * count
            if score > best_score:
                best_score = score
                best_rgb = (pr, pg, pb)

        r, g, b = best_rgb if best_rgb is not None else fallback_rgb[1]

        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        bg_v = min(0.34, max(0.16, v * 0.55))
        bg_s = min(1.0, s * 1.4)
        br, bg_g, bb = colorsys.hsv_to_rgb(h, bg_s, bg_v)
        bg = (int(br * 255), int(bg_g * 255), int(bb * 255))

        # Accent: saturated, medium brightness version
        acc_v = max(0.6, min(0.85, v))
        acc_s = max(0.5, min(1.0, s * 1.4))
        ar, ag, ab = colorsys.hsv_to_rgb(h, acc_s, acc_v)
        accent = (int(ar * 255), int(ag * 255), int(ab * 255))

        # Text stays white for readability
        text = TEXT_PRIMARY

        return bg, text, accent
    except Exception:
        return BG_DEFAULT, TEXT_PRIMARY, ACCENT


def lerp_color(c1, c2, t):
    """Linear interpolate between two RGB tuples. t=0 → c1, t=1 → c2."""
    t = max(0.0, min(1.0, t))
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))
