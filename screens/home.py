"""
Home screen — local clock + weather (left) and a compact now-playing
card (right). Tap the cover/track area to jump to the full Now Playing
screen; play/pause and mute act directly without leaving this screen.

Layout (800x480 landscape), both halves vertically centered as a block:
┌─────────────────────────────┬───────────────────────┐
│                             │      ┌──────────┐      │
│            21°C             │      │          │      │
│           14:32             │      │  cover   │      │
│      Wednesday · Sep 16     │      │          │      │
│                             │      └──────────┘      │
│                             │     Track — Artist      │
│                             │        ━━━━━━━━         │
│                             │      (⏵/⏸)   (🔇)       │
└─────────────────────────────┴───────────────────────┘
"""

import random
import time
import datetime

import pygame

from ui import theme
from ui.components import (
    load_font, render_text, wrap_text, draw_progress_bar, TouchButton,
    draw_play_icon, draw_pause_icon, draw_speaker_icon,
)


DOW_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _artist_overlap(album_artist, track_artists):
    """Loose match between an album's artist field and a track's (possibly
    comma-joined, multi-artist) "artists" string — substring either way so
    "Artist A" still matches a track credited to "Artist A, Artist B"."""
    a, b = album_artist.lower(), track_artists.lower()
    return a in b or b in a


class HomeScreen:
    MINI_COVER = 240
    COVER_RADIUS = 18
    MISS_TOLERANCE = 2  # consecutive empty polls before trusting "nothing
    # playing" — a single flaky poll shouldn't flash the mini card to idle.
    QUICK_PICK_SIZE = 144
    QUICK_PICK_COLS = 2
    QUICK_PICK_CYCLE_SECS = 420  # 7 min — a fresh set every so often, not so often it feels twitchy

    def __init__(self, spotify, weather, dollar=None, lms=None):
        self.spotify = spotify
        self.weather = weather
        self.dollar = dollar
        self.lms = lms
        self.buttons = []

        self.track_data = None
        self.lms_track_data = None
        self._track_miss = 0
        self._lms_miss = 0
        self.mini_cover_surface = None
        self.last_cover_url = None

        self.muted = False
        self.pre_mute_volume = 50

        # Idle-panel quick picks — a few random items from the active
        # source's library, shown instead of a dead "Nothing playing"
        # label. Re-rolled when playback stops, and again every
        # QUICK_PICK_CYCLE_SECS while it stays idle — not every frame, so
        # covers aren't flickering constantly.
        self.quick_picks = []
        self.quick_picks_source = None
        self.quick_picks_loaded_at = 0
        self.quick_pick_covers = {}
        self._last_artist = None  # last-known "artists" string, kept across the
        # transition to idle so quick picks can lean toward what you were just hearing
        self._active_source = "spotify"  # kept in sync by draw(); backs the player property below

        self.weather_data = None
        self.last_weather_poll = 0
        self.weather_poll_interval = 180  # seconds — weather doesn't need to be fresher

        self.mep_rate = None
        self.last_mep_poll = 0
        self.mep_poll_interval = 120

        self.last_track_poll = 0
        self.track_poll_interval = 3

        self.f_time = load_font(theme.FONT_BOLD, theme.SIZE_CLOCK)
        self.f_date = load_font(theme.FONT_SEMIBOLD, theme.SIZE_DATE)
        self.f_temp = load_font(theme.FONT_MEDIUM, theme.SIZE_TEMP)
        self.f_feels = load_font(theme.FONT_MEDIUM, 20)
        self.f_mep = load_font(theme.FONT_SEMIBOLD, 22)
        self.f_mini_title = load_font(theme.FONT_BOLD, 26)
        self.f_mini_artist = load_font(theme.FONT_MEDIUM, 20)

        self._gradient_surf = None

    @property
    def player(self):
        """Resolves to whichever provider is active — main.py's
        "played_playlist" handler expects any screen returning that action
        to expose .player, same as NowPlayingScreen/PlaylistsScreen."""
        return self.spotify if self._active_source == "spotify" else self.lms

    def update(self, active_source="spotify"):
        now = time.time()
        self._active_source = active_source

        if now - self.last_track_poll >= self.track_poll_interval:
            self.last_track_poll = now

            spotify_data = self.spotify.get_now_playing()
            if spotify_data:
                self._track_miss = 0
                self.track_data = spotify_data
            else:
                self._track_miss += 1
                if self._track_miss > self.MISS_TOLERANCE:
                    self.track_data = None

            if self.lms:
                lms_data = self.lms.get_now_playing()
                if lms_data:
                    self._lms_miss = 0
                    self.lms_track_data = lms_data
                else:
                    self._lms_miss += 1
                    if self._lms_miss > self.MISS_TOLERANCE:
                        self.lms_track_data = None

            # The mini card only ever shows one cover — whichever source is
            # actually active — so only that side needs the image fetched.
            active_data = self.track_data if active_source == "spotify" else self.lms_track_data
            if active_data:
                url = active_data.get("cover_url")
                if url != self.last_cover_url:
                    self._update_mini_cover(url, active_source)
            else:
                self.mini_cover_surface = None
                self.last_cover_url = None

            if active_data:
                self.quick_picks_source = None  # will reroll next time it goes idle
                if active_data.get("artists"):
                    self._last_artist = active_data["artists"]
            elif (
                self.quick_picks_source != active_source
                or now - self.quick_picks_loaded_at >= self.QUICK_PICK_CYCLE_SECS
            ):
                self._load_quick_picks(active_source)

        if now - self.last_weather_poll >= self.weather_poll_interval:
            self.last_weather_poll = now
            wd = self.weather.get_temperature()
            if wd is not None:
                self.weather_data = wd

        if self.dollar and now - self.last_mep_poll >= self.mep_poll_interval:
            self.last_mep_poll = now
            rate = self.dollar.get_mep_rate()
            if rate is not None:
                self.mep_rate = rate

    def needs_fetch(self):
        """True if the next update() is about to re-poll (stale by more
        than track_poll_interval) — main.py's cue to show a spinner."""
        return time.time() - self.last_track_poll >= self.track_poll_interval

    def _load_quick_picks(self, source):
        player = self.spotify if source == "spotify" else self.lms
        if not player:
            return
        pool = (hasattr(player, "get_albums") and player.get_albums()) or []
        if not pool:
            pool = (hasattr(player, "get_playlists") and player.get_playlists()) or []

        # "Recommendations" here just means: lean on what you were just
        # listening to. Spotify killed its real recommendations endpoint
        # for apps like this back in 2024, and LMS never had one — but we
        # already know the last artist, and albums/playlists already carry
        # an "artist" field, so a same-artist bias is free.
        matches = [
            p for p in pool
            if p.get("artist") and self._last_artist and _artist_overlap(p["artist"], self._last_artist)
        ]
        picks = matches[:4]
        rest = [p for p in pool if p not in picks]
        if len(picks) < 4 and rest:
            picks += random.sample(rest, min(4 - len(picks), len(rest)))
        self.quick_picks = picks

        self.quick_picks_source = source
        self.quick_picks_loaded_at = time.time()
        self.quick_pick_covers = {}
        self._ensure_quick_pick_covers(player)

    def _ensure_quick_pick_covers(self, player):
        for pick in self.quick_picks:
            url = pick.get("cover_url")
            if not url or url in self.quick_pick_covers:
                continue
            pil_img = player.get_cover(url, size=(self.QUICK_PICK_SIZE, self.QUICK_PICK_SIZE))
            if not pil_img:
                continue
            raw = pil_img.tobytes()
            flat = pygame.image.fromstring(raw, pil_img.size, "RGB").convert_alpha()
            mask = pygame.Surface(pil_img.size, pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=self.COVER_RADIUS)
            flat.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            self.quick_pick_covers[url] = flat

    def _update_mini_cover(self, url, source="spotify"):
        provider = self.spotify if source == "spotify" else self.lms
        pil_img = provider.get_cover(url, size=(self.MINI_COVER, self.MINI_COVER))
        if pil_img:
            raw = pil_img.tobytes()
            flat = pygame.image.fromstring(raw, pil_img.size, "RGB").convert_alpha()
            mask = pygame.Surface(pil_img.size, pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=self.COVER_RADIUS)
            flat.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            self.mini_cover_surface = flat
            self.last_cover_url = url
        else:
            self.mini_cover_surface = None

    def draw(self, surface, active_source="spotify"):
        W, H = theme.WIDTH, theme.HEIGHT
        self.buttons.clear()
        self._active_source = active_source

        self._draw_background(surface, W, H)
        self._draw_clock(surface, W, H, active_source)
        self._draw_mini_now_playing(surface, W, H, active_source)

    def _draw_source_switch(self, surface, cx, y, active_source):
        """One pill track with a sliding thumb. The thumb is a small,
        fully independent rounded rect nested inside the track — not a
        half-rounded shape — so it's just as safe from partial-rounding
        bugs as two separate pills, while reading as one merged widget."""
        track_w, track_h, margin = 230, 48, 4
        thumb_w = track_w // 2 - margin - margin // 2
        thumb_h = track_h - margin * 2

        x = cx - track_w // 2
        pygame.draw.rect(surface, theme.ACCENT, (x, y, track_w, track_h), border_radius=track_h // 2)

        is_spotify = active_source == "spotify"
        thumb_x = (x + margin) if is_spotify else (x + track_w - margin - thumb_w)
        pygame.draw.rect(surface, theme.TEXT_PRIMARY, (thumb_x, y + margin, thumb_w, thumb_h), border_radius=thumb_h // 2)

        label_y = y + track_h // 2 - self.f_date.size("Spotify")[1] // 2
        spotify_color = theme.BG_DEFAULT if is_spotify else theme.TEXT_PRIMARY
        lms_color = theme.TEXT_PRIMARY if is_spotify else theme.BG_DEFAULT
        render_text(surface, "Spotify", self.f_date, spotify_color, x + track_w // 4, label_y, anchor="center")
        render_text(surface, "LMS", self.f_date, lms_color, x + track_w - track_w // 4, label_y, anchor="center")

        # Nothing playing on Spotify means "now_playing" would just bounce
        # straight back here (idle-redirect) — send the tap to the library
        # instead so there's actually a way to queue something up.
        spotify_action = "go_now_playing" if self.track_data else "go_playlists"
        lms_action = "go_squeeze" if self.lms_track_data else "go_squeeze_library"
        self.buttons.append(TouchButton((x, y, track_w // 2, track_h), spotify_action))
        self.buttons.append(TouchButton((x + track_w // 2, y, track_w - track_w // 2, track_h), lms_action))

        return track_h

    def _draw_clock(self, surface, W, H, active_source="spotify"):
        """Temp on top, big time in the middle, date + MEP rate + source
        switch at the bottom — the whole block vertically centered
        (measured, not guessed).
        """
        left_cx = W // 4
        now = datetime.datetime.now()
        time_str = now.strftime("%H:%M")
        date_str = f"{DOW_LABELS[now.weekday()]} · {now.strftime('%b')} {now.day}"
        temp_str = self._format_temp()
        feels_str = self._format_feels()
        mep_str = self._format_mep()

        gap_temp_feels = 2
        gap_feels_time = 6
        gap_temp_time = 4
        gap_time_date = 16
        gap_date_mep = 10
        gap_mep_switch = 20
        switch_h = 48

        temp_h = self.f_temp.size(temp_str)[1]
        feels_h = self.f_feels.size(feels_str)[1] if feels_str else 0
        time_h = self.f_time.size(time_str)[1]
        date_h = self.f_date.size(date_str)[1]
        mep_h = self.f_mep.size(mep_str)[1] if mep_str else 0

        total_h = temp_h + gap_temp_time + time_h + gap_time_date + date_h + gap_mep_switch + switch_h
        if feels_str:
            total_h += gap_temp_feels + feels_h + gap_feels_time - gap_temp_time
        if mep_str:
            total_h += gap_date_mep + mep_h

        y = (H - total_h) // 2
        render_text(surface, temp_str, self.f_temp, theme.ACCENT, left_cx, y, anchor="center")
        y += temp_h

        if feels_str:
            y += gap_temp_feels
            render_text(surface, feels_str, self.f_feels, theme.TEXT_SECONDARY, left_cx, y, anchor="center")
            y += feels_h + gap_feels_time
        else:
            y += gap_temp_time

        render_text(surface, time_str, self.f_time, theme.TEXT_PRIMARY, left_cx, y, anchor="center")
        y += time_h + gap_time_date

        render_text(surface, date_str, self.f_date, theme.TEXT_SECONDARY, left_cx, y, anchor="center")
        y += date_h

        if mep_str:
            y += gap_date_mep
            render_text(surface, mep_str, self.f_mep, theme.ACCENT, left_cx, y, anchor="center")
            y += mep_h

        y += gap_mep_switch
        self._draw_source_switch(surface, left_cx, y, active_source)

    def _format_mep(self):
        if self.mep_rate is None:
            return ""
        return f"MEP ${round(self.mep_rate)}"

    def _format_temp(self):
        if not self.weather_data:
            return "--°"
        return f"{self.weather_data.get('temp', '--')}°C"

    def _format_feels(self):
        """Empty when there's nothing worth showing separately — same
        temp as feelslike, or no data at all."""
        if not self.weather_data:
            return ""
        temp = self.weather_data.get("temp", "--")
        feel = self.weather_data.get("feelslike", "--")
        if str(temp) == str(feel) or feel in (None, "--"):
            return ""
        return f"feels {feel}°"

    def _draw_mini_now_playing(self, surface, W, H, active_source="spotify"):
        panel_x = W // 2
        panel_w = W - panel_x
        panel_cx = panel_x + panel_w // 2
        cover_size = self.MINI_COVER

        data = self.track_data if active_source == "spotify" else self.lms_track_data
        if not data:
            self._draw_idle_panel(surface, panel_cx, panel_w, H, active_source)
            return

        text_max_w = panel_w - 60

        title_lines = wrap_text(data["name"], self.f_mini_title, text_max_w, max_lines=1)
        title = title_lines[0] if title_lines else ""
        title_h = self.f_mini_title.size(title)[1]
        artist_h = self.f_mini_artist.size(data["artists"])[1]

        gap_cover_title = 18
        gap_title_artist = 4
        gap_artist_progress = 16
        progress_h = 6
        gap_progress_controls = 24
        CTRL_R = 44  # matches Now Playing's primary play/pause button size
        controls_h = CTRL_R * 2

        total_h = (
            cover_size + gap_cover_title + title_h + gap_title_artist + artist_h
            + gap_artist_progress + progress_h + gap_progress_controls + controls_h
        )
        y = (H - total_h) // 2

        cover_x = panel_cx - cover_size // 2
        cover_y = y
        if self.mini_cover_surface:
            surface.blit(self.mini_cover_surface, (cover_x, cover_y))
        else:
            pygame.draw.rect(
                surface, theme.TEXT_DIM, (cover_x, cover_y, cover_size, cover_size),
                2, border_radius=self.COVER_RADIUS,
            )
        y += cover_size + gap_cover_title

        render_text(surface, title, self.f_mini_title, theme.TEXT_PRIMARY, panel_cx, y, anchor="center")
        y += title_h + gap_title_artist

        render_text(surface, data["artists"], self.f_mini_artist, theme.ACCENT, panel_cx, y, anchor="center")
        y += artist_h + gap_artist_progress

        prog_w = cover_size
        prog_x = panel_cx - prog_w // 2
        duration = max(1, data["duration_ms"])
        progress = data["progress_ms"] / duration
        draw_progress_bar(surface, prog_x, y, prog_w, progress_h, progress, theme.PROGRESS_BG, theme.PROGRESS_FILL)

        # Cover/title/artist/progress block — tap it to open the full screen
        open_action = "go_now_playing" if active_source == "spotify" else "go_squeeze"
        self.buttons.append(TouchButton(
            (cover_x, cover_y, cover_size, cover_size + gap_cover_title + title_h + gap_title_artist + artist_h),
            open_action,
        ))

        y += progress_h + gap_progress_controls

        # Play/pause + mute — big filled circles, same visual weight as the
        # primary button on the full Now Playing screen. Centered, and kept
        # separate from the tap-to-open region above so they don't compete.
        ctrl_offset = 64
        ctrl_touch = 100
        play_x = panel_cx - ctrl_offset
        mute_x = panel_cx + ctrl_offset
        ctrl_cy = y + CTRL_R

        pygame.draw.circle(surface, theme.TEXT_PRIMARY, (play_x, ctrl_cy), CTRL_R)
        if data.get("is_playing"):
            draw_pause_icon(surface, (play_x, ctrl_cy), CTRL_R, theme.BG_DEFAULT)
        else:
            draw_play_icon(surface, (play_x, ctrl_cy), CTRL_R, theme.BG_DEFAULT)

        mute_fill = theme.ACCENT if self.muted else theme.TEXT_PRIMARY
        pygame.draw.circle(surface, mute_fill, (mute_x, ctrl_cy), CTRL_R)
        draw_speaker_icon(surface, (mute_x, ctrl_cy), CTRL_R * 1.15, theme.BG_DEFAULT, muted=self.muted)

        self.buttons.append(TouchButton(
            (play_x - ctrl_touch // 2, ctrl_cy - ctrl_touch // 2, ctrl_touch, ctrl_touch), "toggle"
        ))
        self.buttons.append(TouchButton(
            (mute_x - ctrl_touch // 2, ctrl_cy - ctrl_touch // 2, ctrl_touch, ctrl_touch), "mute"
        ))

    def _draw_idle_panel(self, surface, panel_cx, panel_w, H, active_source="spotify"):
        """Nothing playing on the active source — a few random picks from
        its library instead of a dead "Nothing playing" label. Tapping one
        starts it; Spotify's play_context already targets this Pi's device
        explicitly, so that doubles as the old standalone "Play on this
        Pi" button, which is gone now that there's actual content to tap."""
        if not self.quick_picks:
            title_h = self.f_mini_artist.size("Nothing playing")[1]
            render_text(
                surface, "Nothing playing", self.f_mini_artist, theme.TEXT_DIM,
                panel_cx, (H - title_h) // 2, anchor="center",
            )
            return

        size = self.QUICK_PICK_SIZE
        cols = self.QUICK_PICK_COLS
        n = len(self.quick_picks)
        rows = (n + cols - 1) // cols
        gap_x, gap_y = 20, 16
        title_h = self.f_mini_artist.size("Pick something")[1]
        name_h = self.f_mini_artist.size("Ay")[1]
        gap_title_grid = 18
        gap_cover_name = 8
        row_h = size + gap_cover_name + name_h

        total_w = cols * size + (cols - 1) * gap_x
        total_h = title_h + gap_title_grid + rows * row_h + (rows - 1) * gap_y
        start_x = panel_cx - total_w // 2
        y = (H - total_h) // 2

        render_text(surface, "Pick something", self.f_mini_artist, theme.TEXT_DIM, panel_cx, y, anchor="center")
        y += title_h + gap_title_grid

        for i, pick in enumerate(self.quick_picks):
            col, row = i % cols, i // cols
            x = start_x + col * (size + gap_x)
            cell_y = y + row * (row_h + gap_y)

            cov = self.quick_pick_covers.get(pick.get("cover_url"))
            if cov:
                surface.blit(cov, (x, cell_y))
            else:
                pygame.draw.rect(surface, theme.TEXT_DIM, (x, cell_y, size, size), 2, border_radius=self.COVER_RADIUS)

            name_lines = wrap_text(pick.get("name", ""), self.f_mini_artist, size, max_lines=1)
            render_text(
                surface, name_lines[0] if name_lines else "", self.f_mini_artist, theme.TEXT_SECONDARY,
                x + size // 2, cell_y + size + gap_cover_name, anchor="center", max_w=size,
            )
            self.buttons.append(TouchButton(
                (x, cell_y, size, size + gap_cover_name + name_h), f"play:{pick.get('uri')}"
            ))

    def handle_touch(self, pos):
        for btn in self.buttons:
            if btn.hit(pos):
                return self._do_action(btn.action)
        return None

    def _do_action(self, action):
        source = getattr(self, "_active_source", "spotify")
        player = self.spotify if source == "spotify" else self.lms
        data = self.track_data if source == "spotify" else self.lms_track_data

        if action.startswith("play:"):
            uri = action[len("play:"):]
            if uri and hasattr(player, "play_context"):
                player.play_context(uri)
                self.last_track_poll = time.time() - self.track_poll_interval + 1.5
            return "played_playlist"  # main.py: navigate to the now-playing screen, cross-pause, delayed re-poll
        elif action == "toggle" and data:
            player.toggle_playback(data.get("is_playing", False))
            self.last_track_poll = 0
        elif action == "mute" and data:
            if self.muted:
                player.set_volume(self.pre_mute_volume)
                self.muted = False
            else:
                self.pre_mute_volume = data.get("volume_percent", self.pre_mute_volume)
                player.set_volume(0)
                self.muted = True
        return action

    def _draw_background(self, surface, w, h):
        if self._gradient_surf is None:
            surf = pygame.Surface((w, h))
            top, bottom = (16, 16, 24), (4, 4, 8)
            for y in range(h):
                t = y / h
                r = int(top[0] + (bottom[0] - top[0]) * t)
                g = int(top[1] + (bottom[1] - top[1]) * t)
                b = int(top[2] + (bottom[2] - top[2]) * t)
                pygame.draw.line(surf, (r, g, b), (0, y), (w, y))
            self._gradient_surf = surf
        surface.blit(self._gradient_surf, (0, 0))
