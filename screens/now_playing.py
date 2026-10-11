"""
Now Playing screen — Car Thing style. Works with any provider exposing
get_now_playing/get_cover/toggle_playback/next_track/prev_track/set_volume
(SpotifyProvider or LMSProvider). The output-switch button only appears if
the provider also has switch_output (Spotify-only — LMS playback is always
local, nothing to switch to).

Layout (800x480 landscape):
┌─────────────────────────────────────────────┐
│   ┌──────────┐   Album · 2024               │
│   │          │   Track Name                 │
│   │  Cover   │   Artist                     │
│   │  270x270 │                              │
│   └──────────┘                              │
├── panel ──────────────────────────────────── │
│    elapsed ━━━━━━━━━━━  remaining            │
│ home -    ◁◁      ⏵/⏸   ▷▷     +   out       │
└─────────────────────────────────────────────┘

Top area: gradient derived from album art dominant color.
Bottom strip: flat panel background, distinct from the gradient.
"""

import pygame
import time
from PIL import Image

from ui import theme
from ui.components import (
    load_font, render_text, render_lines, wrap_text, draw_progress_bar, TouchButton,
    draw_play_icon, draw_pause_icon, draw_skip_icon, draw_minus_icon, draw_plus_icon,
    draw_clock_icon, draw_cast_icon, draw_shuffle_icon,
)
from providers.spotify import fmt_ms


class NowPlayingScreen:
    COVER_SIZE = 270
    COVER_RADIUS = 20
    VOLUME_STEP = 10
    MISS_TOLERANCE = 2  # consecutive empty polls before trusting "idle" — a
    # single flaky poll to a player on the LAN shouldn't bounce you back to
    # the home screen mid-playback.
    LIBRARY_SHUFFLE_COLOR = (255, 149, 40)  # orange — distinct from the
    # green queue-shuffle state, same tone as main.py's loading spinner

    def __init__(self, player):
        self.player = player
        self.track_data = None
        self.cover_surface = None
        self.last_cover_url = None
        self.buttons = []
        self.volume_percent = 50
        self.toast_text = ""  # brief floating status pill (volume %, output switch result)
        self.toast_until = 0
        self.library_shuffle_on = False  # LMS-only third shuffle state; tracked here
        # since LMS has no query to read RandomPlay's status back reliably

        # Adaptive palette
        self.bg_color = theme.BG_DEFAULT
        self.text_color = theme.TEXT_PRIMARY
        self.accent_color = theme.ACCENT
        self.target_bg = theme.BG_DEFAULT
        self.target_accent = theme.ACCENT
        self.lerp_t = 1.0

        # Fonts
        self.f_toplabel = load_font(theme.FONT_SEMIBOLD, theme.SIZE_TOPLABEL)
        self.f_track = load_font(theme.FONT_BOLD, theme.SIZE_TRACK)
        self.f_artist = load_font(theme.FONT_MEDIUM, theme.SIZE_ARTIST)
        self.f_time = load_font(theme.FONT_REGULAR, theme.SIZE_TIME)
        self.f_source = load_font(theme.FONT_SEMIBOLD, 18)

        # Cover drop-shadow — geometry never changes, so pre-render once
        # instead of redrawing several translucent layers every frame.
        self._shadow_surf, self._shadow_pad = self._build_shadow(self.COVER_SIZE, self.COVER_RADIUS)
        self._shadow_offset = (0, 10)

        # Gradient cache — regenerated only when the top color actually
        # changes, instead of redrawing 480 scanlines every single frame.
        self._gradient_surf = None
        self._gradient_top = None

        # Refresh timing
        self.last_poll = 0
        self.poll_interval = 2  # seconds

        # Idle state — main.py hands off to the home/clock screen whenever
        # this is True, so NowPlayingScreen never actually renders an idle
        # placeholder itself anymore.
        self.idle = True
        self._miss_count = 0

    def update(self):
        """Poll Spotify for current track."""
        now = time.time()
        if now - self.last_poll < self.poll_interval:
            return

        self.last_poll = now
        data = self.player.get_now_playing()

        if data:
            self._miss_count = 0
            self.idle = False
            old_url = (self.track_data or {}).get("cover_url")
            self.track_data = data
            self.volume_percent = data.get("volume_percent", self.volume_percent)

            # New track? Update cover + palette
            if data["cover_url"] != old_url:
                self._update_cover(data["cover_url"])
        else:
            self._miss_count += 1
            if self._miss_count > self.MISS_TOLERANCE:
                self.idle = True
                self.track_data = None

    def needs_fetch(self):
        """True if the next update() is about to re-poll — main.py's cue to
        show a spinner before that call blocks on the network."""
        return time.time() - self.last_poll >= self.poll_interval

    def _update_cover(self, url):
        """Download cover, mask to rounded corners once, cache as a surface."""
        pil_img = self.player.get_cover(url, size=(self.COVER_SIZE, self.COVER_SIZE))
        if pil_img:
            raw = pil_img.tobytes()
            flat = pygame.image.fromstring(raw, pil_img.size, "RGB").convert_alpha()

            mask = pygame.Surface(pil_img.size, pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=self.COVER_RADIUS)
            flat.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)

            self.cover_surface = flat
            self.last_cover_url = url

            # Adaptive colors
            self.target_bg, _, self.target_accent = theme.extract_palette(pil_img)
            self.lerp_t = 0.0
        else:
            self.cover_surface = None

    def _build_shadow(self, size, radius, layers=5, max_alpha=90, pad=20):
        """Soft drop shadow via stacked translucent rounded rects."""
        surf = pygame.Surface((size + pad * 2, size + pad * 2), pygame.SRCALPHA)
        for i in range(layers, 0, -1):
            grow = i * 3
            alpha = int(max_alpha * (1 - (i - 1) / layers))
            rect = pygame.Rect(pad - grow, pad - grow, size + grow * 2, size + grow * 2)
            pygame.draw.rect(surf, (0, 0, 0, alpha), rect, border_radius=radius + grow)
        return surf, pad

    def draw(self, surface):
        """Render the now-playing screen."""
        W, H = theme.WIDTH, theme.HEIGHT

        # Smooth color transition
        if self.lerp_t < 1.0:
            self.lerp_t = min(1.0, self.lerp_t + 0.08)
            self.bg_color = theme.lerp_color(self.bg_color, self.target_bg, self.lerp_t)
            self.accent_color = theme.lerp_color(self.accent_color, self.target_accent, self.lerp_t)

        # Background — vertical gradient
        self._draw_gradient(surface, self.bg_color, (0, 0, 0), W, H)

        data = self.track_data
        self.buttons.clear()

        if not data:
            # Optimistically marked "not idle" (e.g. right after telling the
            # player to play something) but the real poll hasn't landed yet.
            # Show just the background for this one beat instead of crashing
            # on dict access below — the delayed poll fills it in shortly.
            return

        # ── Layout constants ──────────────────
        COVER_SIZE = self.COVER_SIZE
        COVER_X = 40
        COVER_Y = 30
        TEXT_X = COVER_X + COVER_SIZE + 60
        TEXT_MAX_W = W - TEXT_X - 30
        PROGRESS_Y = H - 128  # bottom-anchored, independent of cover sizing
        CONTROLS_CY = PROGRESS_Y + 8 + 22 + 42  # bar height + gap + button radius
        PANEL_Y = PROGRESS_Y - 22  # top of the time labels — panel starts exactly there

        # ── Controls panel background ────────
        # A lighter, flat tint of the adaptive color — distinct from the
        # gradient above, which is already faded near-black by this point.
        panel_color = theme.lerp_color((0, 0, 0), self.bg_color, 0.65)
        pygame.draw.rect(surface, panel_color, (0, PANEL_Y, W, H - PANEL_Y))

        # ── Album cover — drop shadow, then the pre-rounded cover ────
        shadow_x = COVER_X - self._shadow_pad + self._shadow_offset[0]
        shadow_y = COVER_Y - self._shadow_pad + self._shadow_offset[1]
        surface.blit(self._shadow_surf, (shadow_x, shadow_y))

        if self.cover_surface:
            surface.blit(self.cover_surface, (COVER_X, COVER_Y))
        else:
            pygame.draw.rect(
                surface, theme.TEXT_DIM,
                (COVER_X, COVER_Y, COVER_SIZE, COVER_SIZE),
                2, border_radius=self.COVER_RADIUS,
            )

        # Tap the cover to browse the library — routes to whichever
        # PlaylistsScreen instance matches this provider (Spotify vs LMS).
        if hasattr(self.player, "get_playlists"):
            browse_action = "go_playlists" if hasattr(self.player, "switch_output") else "go_squeeze_library"
            self.buttons.append(TouchButton(
                (COVER_X, COVER_Y, COVER_SIZE, COVER_SIZE), browse_action
            ))

        # ── Track info (top label → track → artist, Car Thing order) ──
        text_y = COVER_Y + 16

        # Album · year — small label on top, tappable to play that album
        album_str = data["album"]
        if data.get("release_year"):
            album_str += f"  ·  {data['release_year']}"
        album_y = text_y
        album_h = render_text(
            surface, album_str, self.f_toplabel,
            theme.TEXT_SECONDARY, TEXT_X, text_y, max_w=TEXT_MAX_W,
        )
        if data.get("album_uri"):
            self.buttons.append(TouchButton(
                (TEXT_X, album_y - 6, TEXT_MAX_W, album_h + 10), f"play:{data['album_uri']}"
            ))
        text_y += album_h + 16

        # Track name — wraps onto up to 2 lines instead of clipping to one.
        # Tight fixed line height (not the font's full ascent+descent) to
        # match SCT's dense multi-line title look instead of looking loose.
        track_lines = wrap_text(data["name"], self.f_track, TEXT_MAX_W, max_lines=2)
        text_y += render_lines(
            surface, track_lines, self.f_track,
            theme.TEXT_PRIMARY, TEXT_X, text_y,
            line_gap=0, line_height=int(theme.SIZE_TRACK * 1.05),
        ) + 18

        # Artist — tappable to play that artist
        artist_y = text_y
        artist_h = render_text(
            surface, data["artists"], self.f_artist,
            self.accent_color, TEXT_X, text_y, max_w=TEXT_MAX_W,
        )
        if data.get("artist_uri"):
            # Width capped short of the full column and no bottom padding —
            # the shuffle button sits in the row directly below, right-
            # aligned, and would otherwise overlap this rect's bottom-right.
            self.buttons.append(TouchButton(
                (TEXT_X, artist_y - 6, TEXT_MAX_W - 70, artist_h), f"play:{data['artist_uri']}"
            ))
        text_y += artist_h + 8

        # Source — purely informative here; the only place to actually
        # switch is the pill on the home screen.
        render_text(
            surface, self._source_label(), self.f_source,
            theme.ACCENT, TEXT_X, text_y,
        )

        # Shuffle — same row, far right of the text column, plenty of room
        # since "Spotify"/"LMS" is short. Works for both providers.
        SHUFFLE_SIZE = 26
        SHUFFLE_TOUCH = 60
        shuffle_x = TEXT_X + TEXT_MAX_W - SHUFFLE_SIZE
        shuffle_y = text_y + self.f_source.size(self._source_label())[1] // 2
        if self.library_shuffle_on:
            shuffle_color = self.LIBRARY_SHUFFLE_COLOR
        elif data.get("shuffle"):
            shuffle_color = theme.ACCENT
        else:
            shuffle_color = theme.TEXT_SECONDARY
        draw_shuffle_icon(surface, (shuffle_x, shuffle_y), SHUFFLE_SIZE, shuffle_color)
        self.buttons.append(TouchButton(
            (shuffle_x - SHUFFLE_TOUCH // 2, shuffle_y - SHUFFLE_TOUCH // 2, SHUFFLE_TOUCH, SHUFFLE_TOUCH),
            "shuffle",
        ))

        # ── Progress bar ─────────────────────
        prog_x = COVER_X
        prog_w = W - COVER_X * 2
        duration = max(1, data["duration_ms"])
        progress = data["progress_ms"] / duration

        # Time labels
        render_text(
            surface, fmt_ms(data["progress_ms"]), self.f_time,
            theme.TEXT_SECONDARY, prog_x, PROGRESS_Y - 22,
        )
        render_text(
            surface, f"-{fmt_ms(duration - data['progress_ms'])}", self.f_time,
            theme.TEXT_SECONDARY, prog_x + prog_w, PROGRESS_Y - 22,
            anchor="right",
        )

        draw_progress_bar(
            surface, prog_x, PROGRESS_Y, prog_w, 8,
            progress, theme.PROGRESS_BG, theme.PROGRESS_FILL,
        )

        # ── Transport controls ───────────────
        # Big central play/pause "puck" flanked by skip buttons, with
        # volume -/+ further out in the corners. All vector-drawn (no
        # font-glyph gaps) and sized for touch.
        center_x = W // 2
        cy = CONTROLS_CY

        PLAY_R = 42          # primary button radius
        PLAY_TOUCH = 116     # square touch target around it
        SKIP_OFFSET = 110    # prev/next center distance from center_x
        SKIP_SIZE = 34
        SKIP_TOUCH = 96
        OUTER_OFFSET = 225   # volume -/+ center distance from center_x
        OUTER_SIZE = 30
        OUTER_TOUCH = 84
        HOME_OFFSET = 330    # further out than volume -, far-left of the row
        HOME_TOUCH = 92
        OUTPUT_OFFSET = 330  # mirror of the home button, far-right of the row
        OUTPUT_TOUCH = 92

        # Home — far left of the control row (bigger/clearer touch target
        # than the old top-right corner spot)
        home_x = center_x - HOME_OFFSET
        draw_clock_icon(surface, (home_x, cy), 36, theme.TEXT_SECONDARY)
        self.buttons.append(TouchButton(
            (home_x - HOME_TOUCH // 2, cy - HOME_TOUCH // 2, HOME_TOUCH, HOME_TOUCH), "go_home"
        ))

        # Play/Pause — filled circle, icon drawn in bg color for contrast
        pygame.draw.circle(surface, theme.TEXT_PRIMARY, (center_x, cy), PLAY_R)
        if data.get("is_playing"):
            draw_pause_icon(surface, (center_x, cy), PLAY_R, self.bg_color)
        else:
            draw_play_icon(surface, (center_x, cy), PLAY_R, self.bg_color)
        self.buttons.append(TouchButton(
            (center_x - PLAY_TOUCH // 2, cy - PLAY_TOUCH // 2, PLAY_TOUCH, PLAY_TOUCH), "toggle"
        ))

        # Previous / Next
        prev_x = center_x - SKIP_OFFSET
        next_x = center_x + SKIP_OFFSET
        draw_skip_icon(surface, (prev_x, cy), SKIP_SIZE, theme.TEXT_PRIMARY, forward=False)
        draw_skip_icon(surface, (next_x, cy), SKIP_SIZE, theme.TEXT_PRIMARY, forward=True)
        self.buttons.append(TouchButton(
            (prev_x - SKIP_TOUCH // 2, cy - SKIP_TOUCH // 2, SKIP_TOUCH, SKIP_TOUCH), "prev"
        ))
        self.buttons.append(TouchButton(
            (next_x - SKIP_TOUCH // 2, cy - SKIP_TOUCH // 2, SKIP_TOUCH, SKIP_TOUCH), "next"
        ))

        # Volume down / up — corners, replacing shuffle/like for now
        vol_dn_x = center_x - OUTER_OFFSET
        vol_up_x = center_x + OUTER_OFFSET
        draw_minus_icon(surface, (vol_dn_x, cy), OUTER_SIZE, theme.TEXT_PRIMARY)
        draw_plus_icon(surface, (vol_up_x, cy), OUTER_SIZE, theme.TEXT_PRIMARY)
        self.buttons.append(TouchButton(
            (vol_dn_x - OUTER_TOUCH // 2, cy - OUTER_TOUCH // 2, OUTER_TOUCH, OUTER_TOUCH), "volume_down"
        ))
        self.buttons.append(TouchButton(
            (vol_up_x - OUTER_TOUCH // 2, cy - OUTER_TOUCH // 2, OUTER_TOUCH, OUTER_TOUCH), "volume_up"
        ))

        # Output device — far right, Spotify only (LMS playback is always
        # local, nothing to switch to). Ring = audio is currently playing on
        # this Pi's DAC; tap to pull playback here, or (if already here) to go back.
        if hasattr(self.player, "switch_output"):
            out_x = center_x + OUTPUT_OFFSET
            if data.get("on_this_device"):
                pygame.draw.circle(surface, theme.TEXT_PRIMARY, (out_x, cy), 30, 3)
                draw_cast_icon(surface, (out_x, cy), 30, theme.TEXT_PRIMARY)
            else:
                draw_cast_icon(surface, (out_x, cy), 34, theme.TEXT_SECONDARY)
            self.buttons.append(TouchButton(
                (out_x - OUTPUT_TOUCH // 2, cy - OUTPUT_TOUCH // 2, OUTPUT_TOUCH, OUTPUT_TOUCH), "switch_output"
            ))

        # Toast — briefly shown after a volume tap or output switch. Centered
        # over the text column (not the screen) so the longer messages don't
        # run into the cover art's corner.
        if time.time() < self.toast_until:
            toast_cx = TEXT_X + TEXT_MAX_W // 2
            toast_w, toast_h = self.f_toplabel.size(self.toast_text)
            pad_x, pad_y = 18, 8
            pill_w, pill_h = toast_w + pad_x * 2, toast_h + pad_y * 2
            pill_x = toast_cx - pill_w // 2
            pill_y = PANEL_Y - 8 - pill_h
            pygame.draw.rect(surface, panel_color, (pill_x, pill_y, pill_w, pill_h), border_radius=pill_h // 2)
            render_text(
                surface, self.toast_text, self.f_toplabel, theme.TEXT_PRIMARY,
                toast_cx, pill_y + pad_y, anchor="center",
            )

    def _source_label(self):
        return "Spotify" if hasattr(self.player, "switch_output") else "LMS"

    def handle_touch(self, pos):
        """Handle a touch/click event. Returns action name or None."""
        for btn in self.buttons:
            if btn.hit(pos):
                return self._do_action(btn.action)
        return None

    def _do_action(self, action):
        if not self.track_data:
            return action

        if action == "toggle":
            self.player.toggle_playback(self.track_data.get("is_playing", False))
        elif action == "next":
            self.player.next_track()
            self.last_poll = 0  # force refresh
        elif action == "prev":
            self.player.prev_track()
            self.last_poll = 0
        elif action == "volume_down":
            self.volume_percent = max(0, self.volume_percent - self.VOLUME_STEP)
            self.player.set_volume(self.volume_percent)
            self._show_toast(f"{self.volume_percent}%")
        elif action == "volume_up":
            self.volume_percent = min(100, self.volume_percent + self.VOLUME_STEP)
            self.player.set_volume(self.volume_percent)
            self._show_toast(f"{self.volume_percent}%")
        elif action == "switch_output":
            self._show_toast(self.player.switch_output(), secs=2.5)
            # Spotify takes a moment to report the new active device; look again shortly
            self.last_poll = time.time() - self.poll_interval + 1.5
        elif action == "shuffle":
            if hasattr(self.player, "toggle_library_shuffle"):
                # LMS gets a 3-way cycle: off -> shuffle queue -> shuffle
                # library -> off. Spotify has no library-wide option, so it
                # stays a plain toggle in the else branch below.
                if self.library_shuffle_on:
                    self.player.toggle_library_shuffle(True)
                    self.library_shuffle_on = False
                elif self.track_data.get("shuffle"):
                    self.player.toggle_shuffle(True)
                    self.player.toggle_library_shuffle(False)
                    self.library_shuffle_on = True
                else:
                    self.player.toggle_shuffle(False)
            else:
                self.player.toggle_shuffle(self.track_data.get("shuffle", False))
            self.last_poll = 0  # force refresh so the icon flips right away
        elif action.startswith("play:"):
            uri = action[len("play:"):]
            if uri and hasattr(self.player, "play_context"):
                self.player.play_context(uri)
                self.last_poll = time.time() - self.poll_interval + 1.5
                self._show_toast("Playing…")
            return "toggle"  # reuse main.py's cross-source-pause safety net

        return action

    def _show_toast(self, text, secs=1.6):
        self.toast_text = text
        self.toast_until = time.time() + secs

    def _draw_gradient(self, surface, top_color, bottom_color, w, h):
        """Vertical gradient fill, cached — only redrawn when top_color changes.

        Bottom is always (0, 0, 0) at every call site here, so top_color alone
        is a safe cache key. Regenerating this via 480 individual draw.line
        calls every frame was the main frame-rate drag on a Pi 3B; a plain
        blit of the cached surface is orders of magnitude cheaper.
        """
        if self._gradient_surf is None or self._gradient_top != top_color or self._gradient_surf.get_size() != (w, h):
            surf = pygame.Surface((w, h))
            for y in range(h):
                t = y / h
                r = int(top_color[0] + (bottom_color[0] - top_color[0]) * t)
                g = int(top_color[1] + (bottom_color[1] - top_color[1]) * t)
                b = int(top_color[2] + (bottom_color[2] - top_color[2]) * t)
                pygame.draw.line(surf, (r, g, b), (0, y), (w, y))
            self._gradient_surf = surf
            self._gradient_top = top_color

        surface.blit(self._gradient_surf, (0, 0))
