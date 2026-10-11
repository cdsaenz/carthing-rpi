"""
Reusable pygame UI components — buttons, progress bar, text.
"""

import math

import pygame
from ui.theme import WIDTH


def load_font(path, size):
    try:
        return pygame.font.Font(path, size)
    except Exception:
        return pygame.font.SysFont("dejavusans", size, bold=True)


def render_text(surface, text, font, color, x, y, max_w=None, anchor="left"):
    """Render text, optionally clipped with ellipsis. anchor: left|center|right."""
    if not text:
        return 0

    if max_w:
        text = clip_text(text, font, max_w)

    rendered = font.render(text, True, color)
    rect = rendered.get_rect()

    if anchor == "center":
        rect.centerx = x
        rect.y = y
    elif anchor == "right":
        rect.right = x
        rect.y = y
    else:
        rect.x = x
        rect.y = y

    surface.blit(rendered, rect)
    return rect.height


def clip_text(text, font, max_w):
    if font.size(text)[0] <= max_w:
        return text
    while len(text) > 1:
        text = text[:-1]
        if font.size(text.rstrip() + "…")[0] <= max_w:
            return text.rstrip() + "…"
    return text


def wrap_text(text, font, max_w, max_lines=2):
    """Greedy word-wrap into up to max_lines, ellipsis-clipping any leftover."""
    if not text:
        return []
    words = text.split()
    lines = []
    idx = 0
    n = len(words)
    while idx < n and len(lines) < max_lines:
        current = words[idx]
        idx += 1
        while idx < n:
            trial = f"{current} {words[idx]}"
            if font.size(trial)[0] <= max_w:
                current = trial
                idx += 1
            else:
                break
        lines.append(current)
    if idx < n and lines:
        remainder = " ".join(words[idx:])
        lines[-1] = clip_text(f"{lines[-1]} {remainder}", font, max_w)
    return lines


def render_lines(surface, lines, font, color, x, y, line_gap=4, anchor="left", line_height=None):
    """Render pre-wrapped lines stacked vertically. Returns total height used.

    By default each line advances by its own rendered height + line_gap. Pass
    line_height to force a fixed step instead (tighter than the font's natural
    ascent+descent, for a denser multi-line title look).
    """
    total = 0
    for line in lines:
        h = render_text(surface, line, font, color, x, y + total, anchor=anchor)
        total += (line_height if line_height is not None else h) + line_gap
    return total


def draw_play_icon(surface, center, size, color):
    """Right-pointing triangle."""
    cx, cy = center
    half_h = size * 0.55
    pygame.draw.polygon(surface, color, [
        (cx - size * 0.35, cy - half_h),
        (cx - size * 0.35, cy + half_h),
        (cx + size * 0.45, cy),
    ])


def draw_pause_icon(surface, center, size, color):
    """Two vertical bars."""
    cx, cy = center
    bar_h = size * 1.1
    bar_w = size * 0.26
    gap = size * 0.16
    pygame.draw.rect(surface, color, (cx - gap - bar_w, cy - bar_h / 2, bar_w, bar_h), border_radius=3)
    pygame.draw.rect(surface, color, (cx + gap, cy - bar_h / 2, bar_w, bar_h), border_radius=3)


def draw_skip_icon(surface, center, size, color, forward=True):
    """Two triangles + end bar, pointing forward (next) or backward (prev)."""
    cx, cy = center
    d = 1 if forward else -1
    half_h = size * 0.5
    tri_w = size * 0.4

    def tri(tip_offset):
        base_x = cx + d * tip_offset
        return [
            (base_x - d * tri_w, cy - half_h),
            (base_x - d * tri_w, cy + half_h),
            (base_x, cy),
        ]

    pygame.draw.polygon(surface, color, tri(0))
    pygame.draw.polygon(surface, color, tri(tri_w * 0.9))

    bar_w = size * 0.12
    bar_x = cx + d * (tri_w * 1.35)
    pygame.draw.rect(surface, color, (bar_x - bar_w / 2, cy - half_h, bar_w, half_h * 2), border_radius=2)


def draw_minus_icon(surface, center, size, color, line_w=4):
    """Single horizontal bar (volume down)."""
    cx, cy = center
    half = size * 0.5
    pygame.draw.line(surface, color, (cx - half, cy), (cx + half, cy), line_w)


def draw_plus_icon(surface, center, size, color, line_w=4):
    """Horizontal + vertical bar (volume up)."""
    cx, cy = center
    half = size * 0.5
    pygame.draw.line(surface, color, (cx - half, cy), (cx + half, cy), line_w)
    pygame.draw.line(surface, color, (cx, cy - half), (cx, cy + half), line_w)


def draw_clock_icon(surface, center, size, color, line_w=3):
    """Clock face — circle + two hands. Used for "home" since home is the
    clock screen. A circle is trivially symmetric (one center + one radius,
    no independent left/width rounding), which sidesteps the exact bug that
    made a polygon+rect house icon come out lopsided: pygame truncates float
    coordinates to ints independently per argument, so a rect's left edge
    and its width can round in ways that don't land back on the same true
    center, and at small icon sizes that shows up as a visibly uneven shape.
    """
    cx, cy = int(round(center[0])), int(round(center[1]))
    r = int(round(size * 0.5))
    pygame.draw.circle(surface, color, (cx, cy), r, line_w)
    pygame.draw.line(surface, color, (cx, cy), (cx, cy - int(r * 0.55)), line_w)
    pygame.draw.line(surface, color, (cx, cy), (cx + int(r * 0.7), cy), line_w)


def draw_speaker_icon(surface, center, size, color, muted=False, line_w=4):
    """Speaker body + cone; unmuted shows two short tick marks (sound),
    muted shows a clean X. All coordinates are integer-rounded up front
    (see draw_clock_icon) so the shape can't drift off-center like the
    old arc-based version could.
    """
    cx, cy = int(round(center[0])), int(round(center[1]))
    s = int(round(size))
    if not muted:
        # The unmuted glyph spans cx-0.40s .. cx+0.22s (ticks are shorter than
        # the muted X), so its visual center sits left of cx; nudge it back.
        cx += int(s * 0.09)

    body_w = max(2, int(s * 0.22))
    body_h = int(s * 0.36)
    body_x = cx - int(s * 0.4)
    body_y = cy - body_h // 2

    pygame.draw.rect(surface, color, (body_x, body_y, body_w, body_h))

    cone_x = body_x + body_w
    pygame.draw.polygon(surface, color, [
        (cone_x, body_y),                        # top-left, at the body
        (cone_x + int(s * 0.22), cy - int(s * 0.3)),   # top-right, flared out
        (cone_x + int(s * 0.22), cy + int(s * 0.3)),   # bottom-right, flared out
        (cone_x, body_y + body_h),                # bottom-left, at the body
    ])

    if muted:
        x0, y0 = cx + int(s * 0.08), cy - int(s * 0.26)
        x1, y1 = cx + int(s * 0.4), cy + int(s * 0.26)
        pygame.draw.line(surface, color, (x0, y0), (x1, y1), line_w)
        pygame.draw.line(surface, color, (x0, y1), (x1, y0), line_w)
    else:
        tick_x = cone_x + int(s * 0.3)
        pygame.draw.line(surface, color, (tick_x, cy - int(s * 0.16)), (tick_x + int(s * 0.1), cy - int(s * 0.24)), line_w)
        pygame.draw.line(surface, color, (tick_x, cy + int(s * 0.16)), (tick_x + int(s * 0.1), cy + int(s * 0.24)), line_w)


def draw_shuffle_icon(surface, center, size, color, line_w=3):
    """Crossing arrows — the traditional shuffle glyph. Two straight
    diagonals (no curves, to stay simple) each ending in a small chevron
    arrowhead on the right — kept to short lines only, no filled shapes,
    after draw_cast_icon's lesson that extra detail turns to mush at small
    icon sizes."""
    cx, cy = int(round(center[0])), int(round(center[1]))
    half = int(round(size)) // 2
    tick = max(3, int(round(size)) // 4)

    # bottom-left -> top-right
    pygame.draw.line(surface, color, (cx - half, cy + half), (cx + half, cy - half), line_w)
    tip = (cx + half, cy - half)
    pygame.draw.line(surface, color, tip, (tip[0] - tick, tip[1]), line_w)
    pygame.draw.line(surface, color, tip, (tip[0], tip[1] + tick), line_w)

    # top-left -> bottom-right
    pygame.draw.line(surface, color, (cx - half, cy - half), (cx + half, cy + half), line_w)
    tip2 = (cx + half, cy + half)
    pygame.draw.line(surface, color, tip2, (tip2[0] - tick, tip2[1]), line_w)
    pygame.draw.line(surface, color, tip2, (tip2[0], tip2[1] - tick), line_w)


def draw_refresh_icon(surface, center, size, color, line_w=3):
    """One hooked arrow — up the left edge, a rounded corner, across the
    top, ending in a right-pointing arrowhead. The single-arm half of the
    classic two-arrow 'repeat' glyph, simplified down to just one since
    two of them at icon size read as a cramped tangle."""
    cx, cy = int(round(center[0])), int(round(center[1]))
    s = int(round(size))
    r = int(s * 0.32)
    top_y = cy - int(s * 0.26)
    bot_y = cy + int(s * 0.32)
    left_x = cx - int(s * 0.38)
    right_x = cx + int(s * 0.44)
    tick = max(3, r)

    pygame.draw.line(surface, color, (left_x, bot_y), (left_x, top_y + r), line_w)
    pygame.draw.arc(surface, color, pygame.Rect(left_x, top_y, r * 2, r * 2), math.pi / 2, math.pi, line_w)
    pygame.draw.line(surface, color, (left_x + r, top_y), (right_x, top_y), line_w)
    pygame.draw.line(surface, color, (right_x - tick, top_y - tick), (right_x, top_y), line_w)
    pygame.draw.line(surface, color, (right_x - tick, top_y + tick), (right_x, top_y), line_w)


def draw_cast_icon(surface, center, size, color, line_w=3):
    """Small monitor-on-a-stand glyph — "this device" — distinct from the
    speaker cone used for mute, since this button transfers Spotify's
    output device rather than changing volume. A Chromecast-style fan of
    signal arcs was tried first but read as illegible clutter at this icon
    size; a plain screen shape reads cleanly even small."""
    cx, cy = int(round(center[0])), int(round(center[1]))
    s = int(round(size))

    screen_w, screen_h = int(s * 0.9), int(s * 0.6)
    screen_x = cx - screen_w // 2
    screen_y = cy - int(s * 0.42)
    pygame.draw.rect(surface, color, (screen_x, screen_y, screen_w, screen_h), line_w, border_radius=4)

    neck_bottom = screen_y + screen_h + int(s * 0.16)
    stand_half = int(s * 0.22)
    pygame.draw.line(surface, color, (cx, screen_y + screen_h), (cx, neck_bottom), line_w)
    pygame.draw.line(surface, color, (cx - stand_half, neck_bottom), (cx + stand_half, neck_bottom), line_w)


def draw_note_icon(surface, center, size, color, line_w=3):
    """Simple music note — filled circle (notehead) + straight stem. Only
    a circle and a line, same safe-primitive family as draw_clock_icon."""
    cx, cy = int(round(center[0])), int(round(center[1]))
    r = max(2, int(size * 0.16))
    note_x = cx - int(size * 0.14)
    note_y = cy + int(size * 0.28)
    pygame.draw.circle(surface, color, (note_x, note_y), r)
    stem_x = note_x + r - 1
    pygame.draw.line(surface, color, (stem_x, note_y), (stem_x, cy - int(size * 0.35)), line_w)


def draw_brightness_icon(surface, center, size, color, line_w=3):
    """Sun glyph — filled circle + 8 radiating rays. Rays are plain lines
    (not a polygon), so there's no winding-order or rect-rounding risk at
    small sizes — the same class of bug that hit the house and speaker icons.
    """
    cx, cy = int(round(center[0])), int(round(center[1]))
    r = max(2, int(size * 0.22))
    pygame.draw.circle(surface, color, (cx, cy), r)

    ray_inner = r + int(size * 0.1)
    ray_outer = r + int(size * 0.32)
    for i in range(8):
        angle = i * (math.pi / 4)
        x0 = cx + int(ray_inner * math.cos(angle))
        y0 = cy + int(ray_inner * math.sin(angle))
        x1 = cx + int(ray_outer * math.cos(angle))
        y1 = cy + int(ray_outer * math.sin(angle))
        pygame.draw.line(surface, color, (x0, y0), (x1, y1), line_w)


def draw_progress_bar(surface, x, y, w, h, progress, bg_color, fill_color, radius=4):
    """Draw a rounded progress bar. progress: 0.0–1.0."""
    # Background
    bar_rect = pygame.Rect(x, y, w, h)
    pygame.draw.rect(surface, bg_color, bar_rect, border_radius=radius)

    # Fill
    fill_w = max(0, int(w * min(1.0, max(0.0, progress))))
    if fill_w > 0:
        fill_rect = pygame.Rect(x, y, fill_w, h)
        pygame.draw.rect(surface, fill_color, fill_rect, border_radius=radius)


def draw_spinner(surface, center, radius, color, angle=0.0, count=8, dot_r=3):
    """Ring of dots with a fading tail, rotated by `angle` (radians) — the
    caller drives the rotation frame-to-frame while a background thread
    does the actual blocking network call. Drawing is additive (no
    background fill), so the caller must restore whatever was there before
    calling this again next frame, or the trail smears into a solid ring."""
    cx, cy = center
    r, g, b = color[:3]
    for i in range(count):
        a = angle + (2 * math.pi * i / count)
        x = cx + radius * math.cos(a)
        y = cy + radius * math.sin(a)
        fade = 1.0 - (i / count)  # lead dot brightest, tail dims out
        alpha = int(60 + 195 * fade)
        size = max(2, int(dot_r * (0.5 + 0.5 * fade)))
        dot = pygame.Surface((size * 2, size * 2), pygame.SRCALPHA)
        pygame.draw.circle(dot, (r, g, b, alpha), (size, size), size)
        surface.blit(dot, (int(x - size), int(y - size)))


class TouchButton:
    """Simple rectangular touch/click target."""

    def __init__(self, rect, action, label=""):
        self.rect = pygame.Rect(rect)
        self.action = action
        self.label = label

    def hit(self, pos):
        return self.rect.collidepoint(pos)

    def draw_debug(self, surface, color=(255, 0, 0)):
        pygame.draw.rect(surface, color, self.rect, 1)
