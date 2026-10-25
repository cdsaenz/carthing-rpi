#!/usr/bin/env python3
"""
CarThing — Spotify touch player for RPi 3B + 5" HDMI LCD (800x480).
"""

import os
import sys
import threading
import time

# Load env before anything else
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import pygame

from ui.theme import WIDTH, HEIGHT
from ui.components import draw_brightness_icon, TouchButton, draw_spinner
from providers.spotify import SpotifyProvider
from providers.weather import WeatherProvider
from providers.dollar import DollarProvider
from providers.lms import LMSProvider
from screens.now_playing import NowPlayingScreen
from screens.home import HomeScreen
from screens.playlists import PlaylistsScreen

DIM_OVERLAY_ALPHA = 165  # how dark the software dim layer is (0-255)
SPINNER_COLOR = (255, 149, 40)  # orange — visually distinct from the accent green used elsewhere

# Swipe detection thresholds (pixels)
SWIPE_MIN_DX = 60   # horizontal movement to count as a swipe at all
SWIPE_MAX_DY = 90   # allowed vertical wobble during a horizontal swipe
TAP_MAX_MOVE = 20   # movement under this is a tap, not a drag
SLEEP_HOLD_SECS = 0.7  # long-press on the brightness icon for a near-black screen


def _event_pos(event):
    if event.type in (pygame.FINGERDOWN, pygame.FINGERUP, pygame.FINGERMOTION):
        return (int(event.x * WIDTH), int(event.y * HEIGHT))  # finger events are 0-1 normalized
    return event.pos


def _wait_with_spinner(scr, screen_surf, clock, *update_args, force=False, delay=0):
    """Whatever just happened — a screen switch, a tab switch, a page swipe
    that landed on covers not downloaded yet — check whether scr's next
    update() is about to hit the network for something uncached. If so, run
    that update() on a background thread while animating a spinner in the
    top-right, instead of just freezing on the old frame until it returns.

    force=True skips the needs_fetch() check and always spins (used right
    after triggering playback, where the delay isn't about a cache miss but
    about giving the source a beat to register the new play command before
    polling — showing nothing for that beat read as a black screen)."""
    if not force and not (hasattr(scr, "needs_fetch") and scr.needs_fetch()):
        return

    done = threading.Event()

    def worker():
        try:
            if delay:
                time.sleep(delay)
            scr.update(*update_args)
        finally:
            done.set()  # always set, even on failure — an infinite spinner is worse than a stale one

    threading.Thread(target=worker, daemon=True).start()

    center, radius = (WIDTH - 30, 26), 14
    pad = radius + 8  # covers the dots' full swing, including their size
    snap_rect = pygame.Rect(center[0] - pad, center[1] - pad, pad * 2, pad * 2)
    snapshot = screen_surf.subsurface(snap_rect).copy()  # restored each frame — drawing is additive

    start = time.time()
    while not done.is_set():
        pygame.event.pump()  # keep the OS happy; actual events stay queued for the next real pass
        screen_surf.blit(snapshot, snap_rect.topleft)
        draw_spinner(screen_surf, center, radius, SPINNER_COLOR, angle=(time.time() - start) * 6)
        pygame.display.flip()
        clock.tick(30)


def _init_display():
    """Try video drivers in order until one actually initializes."""
    forced = os.environ.get("SDL_VIDEODRIVER")
    candidates = [forced] if forced else ["kmsdrm", "fbcon", "directfb", "x11"]

    for driver in candidates:
        if not driver:
            continue
        os.environ["SDL_VIDEODRIVER"] = driver
        pygame.display.quit()
        try:
            pygame.display.init()
        except pygame.error as e:
            print(f"[main] driver '{driver}' failed: {e}")
            continue
        print(f"[main] video driver: {pygame.display.get_driver()}")
        return
    raise RuntimeError(
        "No SDL video driver could initialize. Checks to run on the Pi:\n"
        "  ls /dev/dri            (empty/missing -> no KMS/DRM device)\n"
        "  groups                 (need to include 'video' and 'render')\n"
        "  cat /boot/firmware/config.txt | grep vc4\n"
    )


def main():
    # ── Init pygame ──────────────────────────
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    pygame.init()
    _init_display()
    pygame.mouse.set_visible(False)

    # Try fullscreen, fall back to windowed for dev
    try:
        screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
    except pygame.error:
        print("[main] fullscreen failed, using windowed mode")
        screen = pygame.display.set_mode((WIDTH, HEIGHT))

    pygame.display.set_caption("CarThing")
    clock = pygame.time.Clock()

    # ── Providers ─────────────────────────────
    spotify = SpotifyProvider(
        client_id=os.getenv("SPOTIFY_CLIENT_ID", ""),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET", ""),
        refresh_token=os.getenv("SPOTIFY_REFRESH_TOKEN", ""),
        this_device_name=os.getenv("SPOTIFY_DEVICE_NAME", ""),  # optional; defaults to matching "raspotify"
    )
    weather = WeatherProvider(api_key=os.getenv("API_KEY", ""))
    # MEP dollar rate — an Argentina-specific exchange rate most people
    # cloning this won't want; off unless explicitly enabled.
    dollar = DollarProvider() if os.getenv("SHOW_MEP_RATE", "").lower() == "true" else None
    lms = LMSProvider(
        server_ip=os.getenv("LMS_SERVER_IP", "192.168.1.211"),
        player_name=os.getenv("LMS_PLAYER_NAME", "rpi3b"),
    )

    # ── Screens ──────────────────────────────
    screens = {
        "now_playing": NowPlayingScreen(spotify),
        "squeeze": NowPlayingScreen(lms),
        "home": HomeScreen(spotify, weather, dollar, lms),
        "playlists": PlaylistsScreen(spotify),
        "squeeze_library": PlaylistsScreen(lms),
    }
    active_key = "now_playing"
    PLAYBACK_SCREENS = ("now_playing", "squeeze")

    # ── Brightness toggle — global, drawn/hit-tested above whichever
    # screen is active, since it's display chrome, not screen content.
    # Purely a software dim overlay — this panel has no real backlight
    # control (confirmed: /sys/class/backlight is empty on this Pi). ──
    is_dimmed = False
    # Now Playing's cover art starts at (40, 30) — keep the icon's visible
    # extent clear of it (touch rect can be generous, it's invisible)
    brightness_btn = TouchButton((0, 0, 62, 62), "toggle_dim")
    dim_overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    dim_overlay.fill((0, 0, 0, DIM_OVERLAY_ALPHA))

    # "Sleep" — there's no real power control for this panel (no dpms in
    # DRM, no backlight sysfs, no software hook for its physical power
    # button), so this is just a much darker overlay than the normal dim,
    # triggered by a long-press on the brightness icon. Any tap wakes it;
    # that waking tap is swallowed rather than also acted on.
    is_asleep = False
    sleep_overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    sleep_overlay.fill((0, 0, 0, 250))

    # ── Source tracking. raspotify and squeezelite share the DAC via dmix,
    # which happily mixes both if both are live at once, so pressing play
    # on either playback screen auto-pauses the other as a safety net (in
    # case playback was started from Spotify's/LMS's own apps instead).
    # Switching sources is only ever done from the pill on the home screen —
    # this is just the state that tracks which one's "active" for that.
    SOURCE_PLAYER = {"spotify": spotify, "lms": lms}
    active_source = "spotify"

    print(f"[main] CarThing running at {WIDTH}x{HEIGHT}")

    # Tracks an in-progress touch so we can tell a tap from a swipe on
    # release — our panel only ever sends us down/up, no drag deltas mid-
    # gesture, so the whole gesture has to be measured at the up event.
    touch_down_pos = None
    touch_down_time = 0.0

    # This panel can bounce a single physical tap into two rapid down/up
    # pairs. Left alone, the echo lands on whatever screen the first tap's
    # action just switched to — and since Now Playing's cover and the
    # Playlists grid's first tile occupy roughly the same screen position,
    # a bounced tap on the cover can immediately "choose" and play the
    # first playlist before you ever see the grid. Swallow taps for a short
    # window after any screen switch to absorb the echo.
    NAV_DEBOUNCE_SECS = 0.35
    last_screen_change = 0.0

    # ── Main loop ────────────────────────────
    running = True
    while running:
        active_screen = screens[active_key]

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False

            elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                touch_down_pos = _event_pos(event)
                touch_down_time = time.time()

            elif event.type in (pygame.MOUSEBUTTONUP, pygame.FINGERUP):
                if touch_down_pos is None:
                    continue
                pos = touch_down_pos
                up_pos = _event_pos(event)
                dx, dy = up_pos[0] - pos[0], up_pos[1] - pos[1]
                hold_secs = time.time() - touch_down_time
                touch_down_pos = None

                if is_asleep:
                    # Any tap wakes it — swallow the tap itself rather than
                    # also acting on whatever it landed on.
                    is_asleep = False
                    continue

                if abs(dx) >= SWIPE_MIN_DX and abs(dy) <= SWIPE_MAX_DY:
                    if hasattr(active_screen, "handle_swipe"):
                        active_screen.handle_swipe("left" if dx < 0 else "right")
                        _wait_with_spinner(active_screen, screen, clock)
                    continue

                if abs(dx) > TAP_MAX_MOVE or abs(dy) > TAP_MAX_MOVE:
                    continue  # an ambiguous drag — not a clean tap or swipe, ignore it

                if brightness_btn.hit(pos):
                    if hold_secs >= SLEEP_HOLD_SECS:
                        is_asleep = True
                    else:
                        is_dimmed = not is_dimmed
                    continue

                if time.time() - last_screen_change < NAV_DEBOUNCE_SECS:
                    continue  # likely a bounce-echo of the tap that just switched screens

                prev_key = active_key
                action = active_screen.handle_touch(pos, hold_secs)
                if action == "go_home":
                    active_key = "home"
                elif action == "go_now_playing":
                    active_key = "now_playing"
                    active_source = "spotify"
                    screens["now_playing"].last_poll = 0  # fresh data right away
                    # Landing on this source's screen means it's the one
                    # you're listening to now — stop the other one even if
                    # you're not about to press play yourself (e.g. LMS's
                    # library shuffle keeps running server-side regardless
                    # of what this app is showing).
                    SOURCE_PLAYER["lms"].pause()
                elif action == "go_squeeze":
                    active_key = "squeeze"
                    active_source = "lms"
                    SOURCE_PLAYER["spotify"].pause()
                elif action == "go_playlists":
                    active_key = "playlists"
                    active_source = "spotify"
                elif action == "go_squeeze_library":
                    active_key = "squeeze_library"
                    active_source = "lms"
                elif action == "played_playlist":
                    is_spotify = hasattr(active_screen.player, "get_devices")
                    # Picking something new to play here didn't used to pause
                    # the other source — only the inline play/pause button
                    # did — so playing an LMS album while Spotify was still
                    # going left both feeding the shared DAC at once.
                    SOURCE_PLAYER["lms" if is_spotify else "spotify"].pause()
                    active_key = "now_playing" if is_spotify else "squeeze"
                    active_source = "spotify" if is_spotify else "lms"
                    np = screens[active_key]
                    # Optimistic — we just told the player to play something.
                    # Without this, a screen that's never had real data yet
                    # (idle defaults True) gets bounced home by the idle
                    # check below before the poll below ever lands.
                    np.idle = False
                    np.library_shuffle_on = False  # a specific pick replaces the queue, ending any random mix
                    # The source needs a beat to register the new play
                    # command — an immediate poll could still read "nothing
                    # playing". Spin instead of showing the blank background
                    # for that gap (used to look like a black screen); force
                    # last_poll so the delayed update() below actually polls
                    # rather than skipping since it's within its own interval.
                    np.last_poll = 0
                    _wait_with_spinner(np, screen, clock, force=True, delay=1.5)
                elif action == "toggle" and active_key in (
                    "now_playing", "squeeze", "playlists", "squeeze_library"
                ):
                    # Pressing play here — make sure the other source isn't
                    # also feeding the shared DAC.
                    lms_side = active_key in ("squeeze", "squeeze_library")
                    other = "spotify" if lms_side else "lms"
                    SOURCE_PLAYER[other].pause()
                    active_source = "lms" if lms_side else "spotify"

                if active_key != prev_key:
                    last_screen_change = time.time()

                if active_key == "home":
                    _wait_with_spinner(screens[active_key], screen, clock, active_source)
                else:
                    _wait_with_spinner(screens[active_key], screen, clock)

        active_screen = screens[active_key]

        # Update data
        if active_key == "home":
            active_screen.update(active_source)  # needs to know which source's cover/data to poll for the mini card
        else:
            active_screen.update()

        # Nothing actually playing? Hand off to the clock/home screen
        # instead of sitting on a static "nothing playing" placeholder —
        # nicer to look at, and avoids a static image sitting for hours.
        if active_key in PLAYBACK_SCREENS and screens[active_key].idle:
            active_key = "home"
            active_screen = screens[active_key]

        # Draw
        if active_key == "home":
            active_screen.draw(screen, active_source)  # Home has its own switch under MEP
        else:
            active_screen.draw(screen)
        if is_asleep:
            screen.blit(sleep_overlay, (0, 0))
        elif is_dimmed:
            screen.blit(dim_overlay, (0, 0))
        icon_color = (90, 90, 100) if (is_dimmed or is_asleep) else (230, 230, 235)
        # Center/size chosen so the icon's visible rays stay left of x=40 —
        # Now Playing's cover art starts right there.
        draw_brightness_icon(screen, (22, 22), 30, icon_color)
        pygame.display.flip()

        # ~30 FPS is plenty for this UI
        clock.tick(30)

    pygame.quit()
    print("[main] exited cleanly")
    sys.exit(0)


if __name__ == "__main__":
    main()
