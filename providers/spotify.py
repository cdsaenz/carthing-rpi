"""
Spotify provider — now-playing + playback controls.
Adapted from the existing SpotifyNowPlaying class.
"""

import os
import time
import base64
from io import BytesIO

import requests
from PIL import Image

from providers.library_cache import LibraryCache
from providers import image_cache


def fmt_ms(ms):
    ms = int(ms or 0)
    s = ms // 1000
    m = s // 60
    s = s % 60
    return f"{m}:{str(s).zfill(2)}"


class SpotifyProvider:
    TOKEN_URL = "https://accounts.spotify.com/api/token"
    API_BASE = "https://api.spotify.com/v1/me/player"
    PLAYLISTS_URL = "https://api.spotify.com/v1/me/playlists"
    FOLLOWING_URL = "https://api.spotify.com/v1/me/following?type=artist&limit=50"
    ALBUMS_URL = "https://api.spotify.com/v1/me/albums"

    def __init__(self, client_id, client_secret, refresh_token, env_path=None, this_device_name=""):
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        self.refresh_token = refresh_token or ""
        self.env_path = env_path or os.path.join(os.path.dirname(__file__), "..", ".env")
        self.access_token = None
        self.access_token_exp = 0

        # Which Spotify Connect device is "this Pi" (the raspotify one). An
        # explicit name wins; otherwise anything named like "raspotify(...)",
        # which is the package's default naming.
        self.this_device_name = (this_device_name or "").strip().lower()
        self._previous_device = None  # device that was active before we took over

        # Cover image cache — holds the full-size decoded image, keyed only
        # by URL; each get_cover() call resizes fresh from it. Caching the
        # already-resized image by URL alone was a real bug: NowPlayingScreen
        # and HomeScreen request the same track's art at different sizes
        # (270px vs 150px) from this one shared provider instance, so whoever
        # asked first would "poison" the cache for the other's size.
        self._cover_raw_url = None
        self._cover_raw_img = None

        # Playlists/artists/albums — a browse list, doesn't need to be
        # live. Persisted to disk (providers/library_cache.py) so a cold
        # boot has something to show immediately instead of a blocking
        # fetch the first time each library tab is opened.
        self._library_cache = LibraryCache("spotify_library.json")

    # ── Auth ──────────────────────────────────────

    def _basic_header(self):
        raw = f"{self.client_id}:{self.client_secret}".encode()
        return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}

    def _save_refresh_token(self, token):
        try:
            lines = []
            with open(self.env_path, "r") as f:
                lines = f.readlines()
            with open(self.env_path, "w") as f:
                for line in lines:
                    if line.startswith("SPOTIFY_REFRESH_TOKEN="):
                        f.write(f"SPOTIFY_REFRESH_TOKEN={token}\n")
                    else:
                        f.write(line)
        except Exception as e:
            print(f"[spotify] could not save rotated token: {e}")

    def _refresh_access_token(self):
        if not (self.client_id and self.client_secret and self.refresh_token):
            return False
        try:
            r = requests.post(
                self.TOKEN_URL,
                headers=self._basic_header(),
                data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
                timeout=10,
            )
            if r.status_code != 200:
                print(f"[spotify] token refresh {r.status_code}: {r.text[:200]}")
                return False

            data = r.json()
            self.access_token = data["access_token"]
            self.access_token_exp = time.time() + max(30, int(data.get("expires_in", 3600)) - 60)

            new_rt = data.get("refresh_token")
            if new_rt and new_rt != self.refresh_token:
                self.refresh_token = new_rt
                self._save_refresh_token(new_rt)
            return True
        except Exception as e:
            print(f"[spotify] token exception: {e}")
            return False

    def _ensure_token(self):
        if self.access_token and time.time() < self.access_token_exp:
            return True
        return self._refresh_access_token()

    def _auth_header(self):
        return {"Authorization": f"Bearer {self.access_token}"}

    # ── Now Playing ──────────────────────────────

    def get_now_playing(self):
        """Returns dict with track info or None if nothing playing."""
        if not self._ensure_token():
            return None
        try:
            r = requests.get(
                self.API_BASE,
                headers=self._auth_header(),
                timeout=10,
            )
            if r.status_code == 204:
                return None
            if r.status_code == 401:
                if self._refresh_access_token():
                    return self.get_now_playing()
                return None
            if r.status_code != 200:
                return None

            data = r.json()
            if not data:
                return None

            item = data.get("item") or {}
            if not item:
                return None

            artist_list = item.get("artists") or []
            artists = ", ".join(a["name"] for a in artist_list if a.get("name"))
            primary_artist = artist_list[0] if artist_list else {}
            album_obj = item.get("album") or {}
            images = album_obj.get("images") or []
            device = data.get("device") or {}
            volume = device.get("volume_percent")

            return {
                "on_this_device": self._is_this_device(device),
                "name": item.get("name", ""),
                "artists": artists,
                "album": album_obj.get("name", ""),
                "album_uri": album_obj.get("uri"),
                "artist_uri": primary_artist.get("uri"),
                "release_year": (album_obj.get("release_date") or "")[:4],
                "duration_ms": int(item.get("duration_ms") or 0),
                "progress_ms": int(data.get("progress_ms") or 0),
                "cover_url": images[0]["url"] if images else None,
                "is_playing": bool(data.get("is_playing")),
                "volume_percent": int(volume) if volume is not None else 50,
                "shuffle": data.get("shuffle_state", False),
                "context_type": (data.get("context") or {}).get("type", ""),
                "context_name": "",  # would need extra call
            }
        except Exception as e:
            print(f"[spotify] now playing error: {e}")
            return None

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

    # ── Playback Controls ────────────────────────

    def _put(self, endpoint, params=None, body=None):
        if not self._ensure_token():
            return False
        try:
            r = requests.put(
                f"{self.API_BASE}/{endpoint}" if endpoint else self.API_BASE,
                headers={**self._auth_header(), "Content-Type": "application/json"},
                params=params,
                json=body,
                timeout=10,
            )
            return r.status_code in (200, 202, 204)
        except Exception:
            return False

    def _post(self, endpoint, params=None):
        if not self._ensure_token():
            return False
        try:
            r = requests.post(
                f"{self.API_BASE}/{endpoint}",
                headers=self._auth_header(),
                params=params,
                timeout=10,
            )
            return r.status_code in (200, 202, 204)
        except Exception:
            return False

    def play(self):
        return self._put("play")

    def pause(self):
        return self._put("pause")

    def toggle_playback(self, is_playing):
        return self.pause() if is_playing else self.play()

    def next_track(self):
        return self._post("next")

    def prev_track(self):
        return self._post("previous")

    def toggle_shuffle(self, current_state):
        return self._put("shuffle", params={"state": str(not current_state).lower()})

    def set_volume(self, percent):
        percent = max(0, min(100, int(percent)))
        return self._put("volume", params={"volume_percent": percent})

    # ── Output device (Spotify Connect) ──────────

    def _is_this_device(self, device):
        name = ((device or {}).get("name") or "").lower()
        if not name:
            return False
        if self.this_device_name:
            return name == self.this_device_name
        return "raspotify" in name

    def get_devices(self):
        """List of Connect devices on the account, or None if the call failed."""
        if not self._ensure_token():
            return None
        try:
            r = requests.get(f"{self.API_BASE}/devices", headers=self._auth_header(), timeout=10)
            if r.status_code != 200:
                return None
            return r.json().get("devices") or []
        except Exception as e:
            print(f"[spotify] devices error: {e}")
            return None

    def transfer_playback(self, device_id, play=False):
        """Move playback to device_id. play=False keeps the current
        play/pause state; play=True forces playback to start there."""
        body = {"device_ids": [device_id]}
        if play:
            body["play"] = True
        return self._put("", body=body)

    def _this_device_id(self):
        for d in self.get_devices() or []:
            if self._is_this_device(d):
                return d.get("id")
        return None

    def library_is_fresh(self, category):
        """True if get_<category>() is about to be a cheap disk-cache read
        rather than a live network call — PlaylistsScreen checks this to
        decide whether a fetch is worth showing a spinner for."""
        return self._library_cache.is_fresh(category)

    # ── Playlists ─────────────────────────────────

    def get_playlists(self, force=False):
        """List of the user's playlists: [{id, uri, name, cover_url,
        track_count}, ...]. Cheap to call every frame — only hits the
        network when the disk cache is empty, stale (LibraryCache.TTL), or
        force=True (the library screen's manual refresh button)."""
        cached, fresh = self._library_cache.get("playlists", force=force)
        if fresh:
            return cached

        if not self._ensure_token():
            return cached or []

        items = []
        url, params = self.PLAYLISTS_URL, {"limit": 50}
        try:
            while url and len(items) < 200:
                r = requests.get(url, headers=self._auth_header(), params=params, timeout=10)
                if r.status_code != 200:
                    break
                data = r.json()
                for p in data.get("items") or []:
                    if not p:
                        continue
                    images = p.get("images") or []
                    items.append({
                        "id": p.get("id"),
                        "uri": p.get("uri"),
                        "name": p.get("name", ""),
                        "cover_url": images[0]["url"] if images else None,
                        "track_count": (p.get("tracks") or {}).get("total", 0),
                    })
                url = data.get("next")
                params = None  # 'next' already has query params baked in
            self._library_cache.set("playlists", items)
        except Exception as e:
            print(f"[spotify] playlists error: {e}")
            return cached or items

        return items

    # ── Artists ───────────────────────────────────

    def get_artists(self, force=False):
        """List of followed artists: [{id, uri, name, cover_url,
        track_count}, ...] — same shape as get_playlists so the browse
        screen can treat both tabs identically. track_count is always 0
        (artists don't have one); kept only for shape parity."""
        cached, fresh = self._library_cache.get("artists", force=force)
        if fresh:
            return cached

        if not self._ensure_token():
            return cached or []

        items = []
        url = self.FOLLOWING_URL
        try:
            while url and len(items) < 200:
                r = requests.get(url, headers=self._auth_header(), timeout=10)
                if r.status_code != 200:
                    break
                artists = (r.json() or {}).get("artists") or {}
                for a in artists.get("items") or []:
                    if not a:
                        continue
                    images = a.get("images") or []
                    items.append({
                        "id": a.get("id"),
                        "uri": a.get("uri"),
                        "name": a.get("name", ""),
                        "cover_url": images[0]["url"] if images else None,
                        "track_count": 0,
                    })
                url = artists.get("next")
            self._library_cache.set("artists", items)
        except Exception as e:
            print(f"[spotify] artists error: {e}")
            return cached or items

        return items

    # ── Albums ────────────────────────────────────

    def get_albums(self, force=False):
        """List of saved albums: same [{id, uri, name, cover_url,
        track_count}, ...] shape as get_playlists/get_artists. Unlike those,
        each item nests the actual album data under an "album" key."""
        cached, fresh = self._library_cache.get("albums", force=force)
        if fresh:
            return cached

        if not self._ensure_token():
            return cached or []

        items = []
        url, params = self.ALBUMS_URL, {"limit": 50}
        try:
            while url and len(items) < 200:
                r = requests.get(url, headers=self._auth_header(), params=params, timeout=10)
                if r.status_code != 200:
                    break
                data = r.json()
                for entry in data.get("items") or []:
                    album = (entry or {}).get("album") or {}
                    if not album:
                        continue
                    images = album.get("images") or []
                    artist_names = ", ".join(
                        a["name"] for a in (album.get("artists") or []) if a.get("name")
                    )
                    items.append({
                        "id": album.get("id"),
                        "uri": album.get("uri"),
                        "name": album.get("name", ""),
                        "artist": artist_names,
                        "cover_url": images[0]["url"] if images else None,
                        "track_count": album.get("total_tracks", 0),
                    })
                url = data.get("next")
                params = None  # 'next' already has query params baked in
            self._library_cache.set("albums", items)
        except Exception as e:
            print(f"[spotify] albums error: {e}")
            return cached or items

        return items

    def play_context(self, context_uri):
        """Start a playlist or artist context, targeting this Pi's device
        explicitly so it plays here regardless of whatever was last active
        elsewhere."""
        device_id = self._this_device_id()
        params = {"device_id": device_id} if device_id else None
        return self._put("play", params=params, body={"context_uri": context_uri})

    def switch_output(self):
        """Toggle between this Pi and whichever device was playing before we
        took over. Returns a short status line for the UI to show."""
        devices = self.get_devices()
        if devices is None:
            return "Can't reach Spotify"

        here = next((d for d in devices if self._is_this_device(d)), None)
        if here is None or not here.get("id"):
            print(f"[spotify] Pi not matched; account devices: {[d.get('name') for d in devices]}")
            return "Pi not in Spotify's device list"

        active = next((d for d in devices if d.get("is_active")), None)

        if active and active.get("id") == here["id"]:
            prev = self._previous_device
            target = next((d for d in devices if prev and d.get("id") == prev["id"]), None)
            if target is None:
                return "No other device to go back to"
            ok = self.transfer_playback(target["id"])
            return f"Back to {target.get('name') or 'previous device'}" if ok else "Transfer failed"

        if active and active.get("id"):
            self._previous_device = {"id": active["id"], "name": active.get("name", "")}
        # Nothing active anywhere -> resume the last session here
        ok = self.transfer_playback(here["id"], play=active is None)
        return "Playing on this Pi" if ok else "Transfer failed"
