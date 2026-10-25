"""
Browse screen — Albums / Random / Playlists / Artists tabs, reached from
Now Playing's cover art. Paginated, either by tapping the </> arrows or
swiping left/right, with a sliding push-transition between pages. Random
is a smaller-cover, higher-density grid pulled from a shuffled slice of
Albums, not its own provider fetch — refreshing it just re-shuffles the
already-cached Albums list rather than re-fetching from the server.

Layout (800x480):
┌─────────────────────────────────────────────┐
│  (home)(note)  Albums  Random  Playlists      │
│                ‾‾‾‾‾‾                          │
│   [  cover  ]   [  cover  ]   [  cover  ]      │
│      name           name           name        │
│                  1 / 14                         │
│   <         (play/pause)   (mute)          >   │
└─────────────────────────────────────────────┘
"""

import random
import time

import pygame

from ui import theme
from ui.components import (
    load_font, render_text, wrap_text, TouchButton,
    draw_clock_icon, draw_note_icon, draw_play_icon, draw_pause_icon, draw_speaker_icon,
    draw_refresh_icon,
)

RANDOM_TAB = "Random"
TABS = ("Albums", RANDOM_TAB, "Playlists", "Artists")
RANDOM_POOL_SIZE = 32  # albums kept in rotation until the next manual refresh


class PlaylistsScreen:
    COVER_RADIUS = 8
    CTRL_R = 40
    GRID_TOP = 70  # row-0 touch padding extends 6px above this — must clear y=62 (brightness zone)
    TRANSITION_SECS = 0.22
    ROW_GAP = 12

    # Per-tab grid shape. RANDOM_TAB is deliberately smaller/denser (8 at
    # once) since it's a "browse a big shuffled pile" moment, not the main
    # collection.
    DEFAULT_GRID = {"cols": 3, "rows": 1, "cover_size": 210}
    GRID_CONFIGS = {
        RANDOM_TAB: {"cols": 4, "rows": 2, "cover_size": 100},
    }

    # tab name -> provider method name that returns [{id, uri, name,
    # cover_url, track_count}, ...]. RANDOM_TAB has no entry — it's derived
    # from Albums, not its own fetch.
    FETCHERS = {"Playlists": "get_playlists", "Artists": "get_artists", "Albums": "get_albums"}

    def __init__(self, player):
        self.player = player
        self._data = {}          # tab name -> items list, populated lazily
        self._loaded_tabs = set()
        self.page = 0
        self.active_tab = "Albums"
        self.buttons = []
        self._cover_surfaces = {}  # (cover_url, size) -> pygame.Surface, fetched once each and kept
        self._transition = None    # in-flight page-change slide animation

        self.track_data = None
        self.last_track_poll = 0
        self.track_poll_interval = 3
        self.muted = False
        self.pre_mute_volume = 50
        self._force_next_fetch = False  # set by the manual refresh button

        self._random_items = []  # a shuffled slice of Albums, re-rolled on refresh

        self.f_tab = load_font(theme.FONT_SEMIBOLD, 20)
        self.f_name = load_font(theme.FONT_MEDIUM, 16)
        self.f_counter = load_font(theme.FONT_REGULAR, 14)
        self.f_arrow = load_font(theme.FONT_REGULAR, 30)

        self._gradient_surf = None

    def _grid(self):
        return self.GRID_CONFIGS.get(self.active_tab, self.DEFAULT_GRID)

    def _per_page(self):
        g = self._grid()
        return g["cols"] * g["rows"]

    def _current_items(self):
        if self.active_tab == RANDOM_TAB:
            return self._random_items
        return self._data.get(self.active_tab, [])

    def _page_needs_covers(self):
        items = self._current_items()
        per_page = self._per_page()
        size = self._grid()["cover_size"]
        start = self.page * per_page
        return any(
            it.get("cover_url") and (it["cover_url"], size) not in self._cover_surfaces
            for it in items[start:start + per_page]
        )

    def needs_fetch(self):
        """True if the active tab's data isn't cached yet, or the current
        page's cover art isn't — a page swipe doesn't reload the tab, but
        _ensure_covers() below still downloads each page's images lazily on
        first visit. main.py checks this to decide whether a spinner is
        warranted before that network call."""
        if self.active_tab == RANDOM_TAB:
            if "Albums" not in self._loaded_tabs:
                if hasattr(self.player, "library_is_fresh") and self.player.library_is_fresh("albums"):
                    return False
                return True
            return self._page_needs_covers()

        fetcher_name = self.FETCHERS.get(self.active_tab)
        if not fetcher_name:
            return False
        if self.active_tab not in self._loaded_tabs:
            # Not pulled into this screen instance yet this run — but if
            # the provider's disk cache already has it fresh, that pull is
            # a cheap local read, not a network call, so no spinner needed.
            category = fetcher_name[len("get_"):]
            if hasattr(self.player, "library_is_fresh") and self.player.library_is_fresh(category):
                return False
            return True
        return self._page_needs_covers()

    def update(self):
        # RANDOM_TAB rides on Albums's data rather than fetching its own.
        fetch_tab = "Albums" if self.active_tab == RANDOM_TAB else self.active_tab
        fetcher_name = self.FETCHERS.get(fetch_tab)
        if fetcher_name and fetch_tab not in self._loaded_tabs:
            fetcher = getattr(self.player, fetcher_name, None)
            self._data[fetch_tab] = fetcher(force=self._force_next_fetch) if fetcher else []
            self._loaded_tabs.add(fetch_tab)
            self._force_next_fetch = False
            self._random_items = []  # Albums data changed — reroll below
        if fetcher_name:
            self._ensure_covers()

        now = time.time()
        if now - self.last_track_poll >= self.track_poll_interval:
            self.last_track_poll = now
            self.track_data = self.player.get_now_playing()

        self._ensure_random_items()

    def _ensure_random_items(self):
        """Picks (or keeps) a shuffled slice of Albums. Only rolls a new
        one when empty — on first load, after Albums data changes, or
        after the manual refresh button clears it — never every frame."""
        if self._random_items:
            return
        albums = self._data.get("Albums", [])
        if not albums:
            return
        self._random_items = random.sample(albums, min(RANDOM_POOL_SIZE, len(albums)))

    def _ensure_covers(self):
        items = self._current_items()
        per_page = self._per_page()
        size = self._grid()["cover_size"]
        start = self.page * per_page
        for pl in items[start:start + per_page]:
            url = pl.get("cover_url")
            if not url or (url, size) in self._cover_surfaces:
                continue
            pil_img = self.player.get_cover(url, size=(size, size))
            if not pil_img:
                continue
            raw = pil_img.tobytes()
            flat = pygame.image.fromstring(raw, pil_img.size, "RGB").convert_alpha()
            mask = pygame.Surface(pil_img.size, pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=self.COVER_RADIUS)
            flat.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            self._cover_surfaces[(url, size)] = flat

    def _row_h(self):
        return self._grid()["cover_size"] + 10 + self.f_name.size("Ay")[1]

    def _content_height(self):
        g = self._grid()
        row_h = self._row_h()
        return g["rows"] * row_h + (g["rows"] - 1) * self.ROW_GAP

    def draw(self, surface):
        W, H = theme.WIDTH, theme.HEIGHT
        self.buttons.clear()
        self._ensure_gradient(W, H)
        surface.blit(self._gradient_surf, (0, 0))

        self._draw_header(surface, W)

        is_random_tab = self.active_tab == RANDOM_TAB
        if not is_random_tab and self.active_tab not in self.FETCHERS:
            render_text(
                surface, f"{self.active_tab} — coming soon", self.f_name, theme.TEXT_DIM,
                W // 2, H // 2, anchor="center",
            )
            self._draw_footer(surface, W, H, total_pages=1, show_pagination=False)
            return

        items = self._current_items()
        if not items:
            msg = "No albums found" if is_random_tab else f"No {self.active_tab.lower()} found"
            render_text(surface, msg, self.f_name, theme.TEXT_DIM, W // 2, H // 2, anchor="center")
            self._draw_footer(surface, W, H, total_pages=1, show_pagination=False)
            return

        g = self._grid()
        per_page = self._per_page()
        total_pages = max(1, (len(items) + per_page - 1) // per_page)
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * per_page
        page_items = items[start:start + per_page]

        cell_w = W // g["cols"]
        content_h = self._content_height()

        tr = self._transition
        if tr and time.time() - tr["start"] < tr["duration"]:
            t = (time.time() - tr["start"]) / tr["duration"]
            eased = 1 - (1 - t) ** 2
            d = tr["dir"]
            old_surf = self._render_grid_layer(tr["old_items"], W, cell_w, content_h)
            new_surf = self._render_grid_layer(page_items, W, cell_w, content_h)
            surface.blit(old_surf, (int(-d * eased * W), self.GRID_TOP))
            surface.blit(new_surf, (int(d * (1 - eased) * W), self.GRID_TOP))
        else:
            self._transition = None
            surface.blit(self._render_grid_layer(page_items, W, cell_w, content_h), (0, self.GRID_TOP))

        # Touch targets always reflect the final/current page immediately,
        # regardless of whether the slide animation is still finishing.
        row_h = self._row_h()
        for i, pl in enumerate(page_items):
            col, row = i % g["cols"], i // g["cols"]
            cx = col * cell_w + cell_w // 2
            cover_x = cx - g["cover_size"] // 2
            cell_y = self.GRID_TOP + row * (row_h + self.ROW_GAP)
            self.buttons.append(TouchButton(
                (cover_x - 6, cell_y - 6, g["cover_size"] + 12, row_h + 12),
                f"play:{pl.get('uri')}",
            ))

        self._draw_footer(surface, W, H, total_pages, content_bottom=self.GRID_TOP + content_h)

    def _render_grid_layer(self, items, W, cell_w, content_h):
        """One page's covers+labels, pre-composited onto the matching slice
        of the cached background gradient so it can be blitted at any x
        offset during the slide transition with no visible seam."""
        g = self._grid()
        size = g["cover_size"]
        row_h = self._row_h()
        surf = self._gradient_surf.subsurface((0, self.GRID_TOP, W, content_h)).copy()
        for i, pl in enumerate(items):
            col, row = i % g["cols"], i // g["cols"]
            cx = col * cell_w + cell_w // 2
            cover_x = cx - size // 2
            cell_y = row * (row_h + self.ROW_GAP)

            cov = self._cover_surfaces.get((pl.get("cover_url"), size))
            if cov:
                surf.blit(cov, (cover_x, cell_y))
            else:
                pygame.draw.rect(
                    surf, theme.TEXT_DIM, (cover_x, cell_y, size, size),
                    2, border_radius=self.COVER_RADIUS,
                )

            name_lines = wrap_text(pl.get("name", ""), self.f_name, cell_w - 16, max_lines=1)
            render_text(
                surf, name_lines[0] if name_lines else "", self.f_name, theme.TEXT_PRIMARY,
                cx, cell_y + size + 10, anchor="center", max_w=cell_w - 16,
            )
        return surf

    def _draw_header(self, surface, W):
        """Home + now-playing icons share the same row as main.py's global
        brightness icon (top-left) instead of a separate row below it — only
        needs to stay right of x=62, since that's the brightness button's
        hit-zone width; y doesn't matter for that overlap at all.
        """
        icon_cy = 26
        draw_clock_icon(surface, (100, icon_cy), 28, theme.TEXT_SECONDARY)
        self.buttons.append(TouchButton((65, 0, 70, 55), "go_home"))

        draw_note_icon(surface, (172, icon_cy), 28, theme.TEXT_SECONDARY)
        now_playing_action = "go_now_playing" if hasattr(self.player, "get_devices") else "go_squeeze"
        self.buttons.append(TouchButton((140, 0, 65, 55), now_playing_action))

        tab_x = 222  # clear of go_now_playing's touch rect, which ends at x=205
        tab_y = icon_cy - self.f_tab.size("Playlists")[1] // 2
        for tab in TABS:
            tw, th = self.f_tab.size(tab)
            active = tab == self.active_tab
            color = theme.TEXT_PRIMARY if active else theme.TEXT_DIM
            render_text(surface, tab, self.f_tab, color, tab_x, tab_y)
            if active:
                pygame.draw.rect(surface, theme.ACCENT, (tab_x, tab_y + th + 4, tw, 3), border_radius=2)
            self.buttons.append(TouchButton((tab_x - 10, tab_y - 10, tw + 20, th + 24), f"tab:{tab}"))
            tab_x += tw + 32

        # Manual refresh — far right of the header row, well clear of the
        # tabs regardless of their combined width.
        refresh_x = W - 42
        draw_refresh_icon(surface, (refresh_x, icon_cy), 32, theme.TEXT_SECONDARY)
        self.buttons.append(TouchButton((refresh_x - 35, 0, 70, 55), "refresh"))

    def _draw_footer(self, surface, W, H, total_pages, show_pagination=True, content_bottom=None):
        """Positioned relative to where the grid content actually ends,
        not a fixed distance from the bottom — keeps the gap tight
        regardless of cover size."""
        content_bottom = content_bottom if content_bottom is not None else H // 2
        show_pagination = show_pagination and total_pages > 1

        counter_h = self.f_counter.size("1 / 1")[1]
        counter_y = content_bottom + 14
        nav_cy = counter_y + counter_h + 14 + self.CTRL_R

        if show_pagination:
            render_text(
                surface, f"{self.page + 1} / {total_pages}", self.f_counter, theme.TEXT_DIM,
                W // 2, counter_y, anchor="center",
            )
            arrow_h = self.f_arrow.size("<")[1]
            arrow_y = nav_cy - arrow_h // 2
            render_text(surface, "<", self.f_arrow, theme.TEXT_PRIMARY, 26, arrow_y)
            self.buttons.append(TouchButton((0, nav_cy - self.CTRL_R, 90, self.CTRL_R * 2), "prev_page"))
            render_text(surface, ">", self.f_arrow, theme.TEXT_PRIMARY, W - 26, arrow_y, anchor="right")
            self.buttons.append(TouchButton((W - 90, nav_cy - self.CTRL_R, 90, self.CTRL_R * 2), "next_page"))

        # Quick play/pause + mute — same widget style as Home's mini card
        play_x, mute_x = W // 2 - 64, W // 2 + 64
        R = self.CTRL_R

        is_playing = bool(self.track_data and self.track_data.get("is_playing"))
        pygame.draw.circle(surface, theme.TEXT_PRIMARY, (play_x, nav_cy), R)
        if is_playing:
            draw_pause_icon(surface, (play_x, nav_cy), R, theme.BG_DEFAULT)
        else:
            draw_play_icon(surface, (play_x, nav_cy), R, theme.BG_DEFAULT)

        mute_fill = theme.ACCENT if self.muted else theme.TEXT_PRIMARY
        pygame.draw.circle(surface, mute_fill, (mute_x, nav_cy), R)
        draw_speaker_icon(surface, (mute_x, nav_cy), R * 1.15, theme.BG_DEFAULT, muted=self.muted)

        touch = R * 2 + 12
        self.buttons.append(TouchButton((play_x - touch // 2, nav_cy - touch // 2, touch, touch), "toggle"))
        self.buttons.append(TouchButton((mute_x - touch // 2, nav_cy - touch // 2, touch, touch), "mute"))

    def handle_touch(self, pos, hold_secs=0):
        for btn in self.buttons:
            if btn.hit(pos):
                return self._do_action(btn.action)
        return None

    def handle_swipe(self, direction):
        """direction: 'left' (finger moved left -> advance to next page) or
        'right' (finger moved right -> go back a page) — standard mobile
        paging convention."""
        if self.active_tab != RANDOM_TAB and self.active_tab not in self.FETCHERS:
            return
        if not self._current_items():
            return
        self._go_page(1 if direction == "left" else -1)

    def _go_page(self, delta):
        items = self._current_items()
        per_page = self._per_page()
        total_pages = max(1, (len(items) + per_page - 1) // per_page)
        new_page = max(0, min(self.page + delta, total_pages - 1))
        if new_page == self.page:
            return
        old_start = self.page * per_page
        self._transition = {
            "start": time.time(),
            "duration": self.TRANSITION_SECS,
            "dir": 1 if delta > 0 else -1,
            "old_items": items[old_start:old_start + per_page],
        }
        self.page = new_page

    def _do_action(self, action):
        if action == "refresh":
            if self.active_tab == RANDOM_TAB:
                # No server round-trip needed — just re-shuffle the
                # already-cached Albums list for a new random slice.
                self._random_items = []
                self.page = 0
                return None
            self._loaded_tabs.discard(self.active_tab)
            self._force_next_fetch = True
            self._cover_surfaces.clear()  # stale covers would otherwise linger for renamed/removed items
            return None
        if action == "prev_page":
            self._go_page(-1)
            return None
        if action == "next_page":
            self._go_page(1)
            return None
        if action.startswith("tab:"):
            new_tab = action[len("tab:"):]
            if new_tab != self.active_tab:
                self.active_tab = new_tab
                self.page = 0
                self._transition = None
            return None
        if action.startswith("play:"):
            uri = action[len("play:"):]
            if uri and hasattr(self.player, "play_context"):
                self.player.play_context(uri)
            return "played_playlist"  # distinct from go_now_playing — needs a delayed re-poll
        if action == "toggle" and self.track_data:
            self.player.toggle_playback(self.track_data.get("is_playing", False))
            self.last_track_poll = 0
            return "toggle"  # let main.py's cross-source-pause safety net see this too
        if action == "mute" and self.track_data:
            if self.muted:
                self.player.set_volume(self.pre_mute_volume)
                self.muted = False
            else:
                self.pre_mute_volume = self.track_data.get("volume_percent", self.pre_mute_volume)
                self.player.set_volume(0)
                self.muted = True
            return None
        return action

    def _ensure_gradient(self, w, h):
        if self._gradient_surf is not None:
            return
        surf = pygame.Surface((w, h))
        top, bottom = (16, 16, 24), (4, 4, 8)
        for y in range(h):
            t = y / h
            r = int(top[0] + (bottom[0] - top[0]) * t)
            g = int(top[1] + (bottom[1] - top[1]) * t)
            b = int(top[2] + (bottom[2] - top[2]) * t)
            pygame.draw.line(surf, (r, g, b), (0, y), (w, y))
        self._gradient_surf = surf
