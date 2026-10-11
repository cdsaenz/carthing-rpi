"""Small on-disk JSON cache for library browse data (playlists/artists/
albums), shared by SpotifyProvider and LMSProvider so a cold boot doesn't
have to re-fetch everything live before the library screens have something
to show. Each category is cached independently with its own timestamp.
"""

import json
import os
import time

TTL = 10800  # 3 hours — short enough to notice new additions, long enough
             # that the manual refresh button is doing the real work.


class LibraryCache:
    def __init__(self, filename):
        self.path = os.path.join(os.path.dirname(__file__), "..", ".cache", filename)
        self._data = {}  # category -> {"items": [...], "time": epoch}
        self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                self._data = json.load(f)
        except Exception:
            self._data = {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as f:
                json.dump(self._data, f)
        except Exception as e:
            print(f"[library_cache] save error: {e}")

    def is_fresh(self, category):
        """True if this category is cached and within TTL — a cheap check
        callers use to decide whether the upcoming fetch will actually hit
        the network (worth a spinner) or just read this in-memory dict."""
        entry = self._data.get(category)
        return bool(entry) and time.time() - entry.get("time", 0) < TTL

    def get(self, category, force=False):
        """Returns (items, is_fresh). items is None if nothing's cached yet."""
        entry = self._data.get(category)
        if not entry:
            return None, False
        fresh = not force and (time.time() - entry.get("time", 0) < TTL)
        return entry.get("items"), fresh

    def set(self, category, items):
        self._data[category] = {"items": items, "time": time.time()}
        self._save()
