"""
LMS (Lyrion/Logitech Media Server) provider — talks to a squeezelite player
over LMS's JSON-RPC API. Unlike Spotify, playback here is always local
(squeezelite -> this Pi's own DAC), so there's no "on another device" concept
and no get_devices method — NowPlayingScreen skips that button accordingly.
"""

from io import BytesIO

import requests
from PIL import Image

from providers.library_cache import LibraryCache
from providers import image_cache


class LMSProvider:
    def __init__(self, server_ip, server_port=9000, player_name="rpi3b"):
        self.base_url = f"http://{server_ip}:{server_port}"
        self.player_name = player_name
        self._player_id = None

        self._cover_raw_url = None
        self._cover_raw_img = None

        # Playlists/artists/albums — persisted to disk so a cold boot has
        # something to show immediately instead of a blocking fetch the
        # first time each library tab is opened (see providers/spotify.py,
        # same pattern).
        self._library_cache = LibraryCache("lms_library.json")

    # ── RPC ───────────────────────────────────────

    def _call(self, player_id, command):
        try:
            r = requests.post(
                f"{self.base_url}/jsonrpc.js",
                json={"id": 1, "method": "slim.request", "params": [player_id, command]},
                timeout=5,
            )
            r.raise_for_status()
            return r.json().get("result")
        except Exception as e:
            print(f"[lms] error: {e}")
            return None

    def _ensure_player_id(self):
        if self._player_id:
            return True
        result = self._call("", ["players", "0", "100"])
        # LMS keeps stale entries (e.g. a 00:00:00:00:00:00 ghost from a
        # squeezelite that started before the network was up) under the same
        # name, so only a currently connected player counts.
        for p in (result or {}).get("players_loop") or []:
            if p.get("name") == self.player_name and p.get("connected"):
                self._player_id = p.get("playerid")
                return True
        return False

    def _player_call(self, command):
        if not self._ensure_player_id():
            return None
        return self._call(self._player_id, command)

    # ── Now Playing ───────────────────────────────

    def get_now_playing(self):
        result = self._player_call(["status", "-", 1, "tags:aclKNdtyes"])
        if not result or result.get("mode", "stop") == "stop":
            return None

        tracks = result.get("playlist_loop") or []
        if not tracks:
            return None
        track = tracks[0]

        coverid = track.get("coverid")
        cover_url = f"{self.base_url}/music/{coverid}/cover.jpg" if coverid else None
        duration = float(track.get("duration") or result.get("duration") or 0)

        return {
            "name": track.get("title", ""),
            "artists": track.get("artist", ""),
            "album": track.get("album", ""),
            "album_uri": f"album_id:{track['album_id']}" if track.get("album_id") else None,
            "artist_uri": f"artist_id:{track['artist_id']}" if track.get("artist_id") else None,
            "release_year": str(track.get("year") or ""),
            "duration_ms": int(duration * 1000),
            "progress_ms": int(float(result.get("time") or 0) * 1000),
            "cover_url": cover_url,
            "is_playing": result.get("mode") == "play",
            "volume_percent": int(result.get("mixer volume", 50)),
            "shuffle": bool(result.get("playlist shuffle", 0)),
            "context_type": "",
            "context_name": "",
        }

    # ── Cover Art ─────────────────────────────────

    def get_cover(self, url, size=(300, 300)):
        """Download (cached by URL, in memory and on disk) and resize cover
        art as a PIL Image."""
        if not url:
            return None
        try:
            if url != self._cover_raw_url or self._cover_raw_img is None:
                raw = image_cache.get_cached_bytes(url)
                if raw is None:
                    r = requests.get(url, timeout=10)
                    r.raise_for_status()
                    raw = r.content
                    image_cache.save_bytes(url, raw)
                self._cover_raw_img = Image.open(BytesIO(raw)).convert("RGB")
                self._cover_raw_url = url
            return self._cover_raw_img.resize(size, Image.LANCZOS)
        except Exception:
            return None

    # ── Playback Controls ─────────────────────────

    def play(self):
        return self._player_call(["play"]) is not None

    def pause(self):
        return self._player_call(["pause", "1"]) is not None

    def toggle_playback(self, is_playing):
        return self.pause() if is_playing else self.play()

    def next_track(self):
        return self._player_call(["playlist", "index", "+1"]) is not None

    def prev_track(self):
        return self._player_call(["playlist", "index", "-1"]) is not None

    def set_volume(self, percent):
        percent = max(0, min(100, int(percent)))
        return self._player_call(["mixer", "volume", str(percent)]) is not None

    def toggle_shuffle(self, current_state):
        # LMS's shuffle mode is 0=off/1=by song/2=by album; toggling just
        # flips between off and by-song, matching the plain bool this app
        # already tracks (album-shuffle isn't exposed anywhere in the UI).
        return self._player_call(["playlist", "shuffle", "0" if current_state else "1"]) is not None

    def toggle_library_shuffle(self, current_state):
        # The RandomPlay plugin's "tracks" mix replaces the queue with a
        # continuous random stream pulled from the whole library — distinct
        # from toggle_shuffle above, which only reorders whatever's already
        # queued. Spotify has no equivalent (its shuffle is always
        # context-scoped), so this is LMS-only.
        cmd = ["randomplay", "disable"] if current_state else ["randomplay", "tracks"]
        return self._player_call(cmd) is not None

    # ── Library browsing ───────────────────────────
    # Same item shape as SpotifyProvider's get_playlists/get_artists/
    # get_albums ({id, uri, name, cover_url, track_count}) so PlaylistsScreen
    # can browse either provider unmodified. "uri" here is a playlistcontrol
    # tagged parameter (e.g. "album_id:123"), passed straight through by
    # play_context.

    def library_is_fresh(self, category):
        """True if get_<category>() is about to be a cheap disk-cache read
        rather than a live network call — PlaylistsScreen checks this to
        decide whether a fetch is worth showing a spinner for."""
        return self._library_cache.is_fresh(category)

    def get_playlists(self, force=False):
        cached, fresh = self._library_cache.get("playlists", force=force)
        if fresh:
            return cached

        result = self._call("", ["playlists", "0", 300])
        if result is None:
            return cached or []

        items = []
        for p in result.get("playlists_loop") or []:
            items.append({
                "id": p.get("id"),
                "uri": f"playlist_id:{p.get('id')}",
                "name": p.get("playlist", ""),
                "cover_url": None,
                "track_count": None,
            })
        self._library_cache.set("playlists", items)
        return items

    def get_artists(self, force=False):
        cached, fresh = self._library_cache.get("artists", force=force)
        if fresh:
            return cached

        result = self._call("", ["artists", "0", 300])
        if result is None:
            return cached or []

        items = []
        for a in result.get("artists_loop") or []:
            items.append({
                "id": a.get("id"),
                "uri": f"artist_id:{a.get('id')}",
                "name": a.get("artist", ""),
                "cover_url": None,
                "track_count": None,
            })
        self._library_cache.set("artists", items)
        return items

    def get_albums(self, force=False):
        cached, fresh = self._library_cache.get("albums", force=force)
        if fresh:
            return cached

        result = self._call("", ["albums", "0", 300, "tags:aj", "sort:album"])
        if result is None:
            return cached or []

        items = []
        for al in result.get("albums_loop") or []:
            art_id = al.get("artwork_track_id")
            items.append({
                "id": al.get("id"),
                "uri": f"album_id:{al.get('id')}",
                "name": al.get("album", ""),
                "artist": al.get("artist", ""),
                "cover_url": f"{self.base_url}/music/{art_id}/cover.jpg" if art_id else None,
                "track_count": None,
            })
        self._library_cache.set("albums", items)
        return items

    def play_context(self, uri):
        """uri is a playlistcontrol tagged param, e.g. 'album_id:123' —
        replaces the current queue with that item's tracks and plays it."""
        if not uri:
            return False
        return self._player_call(["playlistcontrol", "cmd:load", uri]) is not None
