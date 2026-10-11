"""On-disk cache for downloaded cover art bytes, shared by SpotifyProvider
and LMSProvider. Each provider's get_cover() already keeps a single
most-recently-used image in memory (see the comment there on why it's only
one slot); this adds a disk layer beneath that so a cover already seen once
doesn't get re-downloaded from Spotify's CDN / the LMS server on every
restart — which is what was still showing the spinner on page 2+ even
after the playlist/artist/album list itself started loading from disk.
"""

import hashlib
import os

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", ".cache", "covers")


def get_cached_bytes(url):
    try:
        with open(_path_for(url), "rb") as f:
            return f.read()
    except Exception:
        return None


def save_bytes(url, data):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_path_for(url), "wb") as f:
            f.write(data)
    except Exception as e:
        print(f"[image_cache] save error: {e}")


def _path_for(url):
    digest = hashlib.sha1(url.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{digest}.img")
