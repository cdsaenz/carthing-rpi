import os
import time
import base64
from io import BytesIO

import requests
from PIL import Image


def _fmt_ms(ms):
    ms = int(ms or 0)
    s = ms // 1000
    m = s // 60
    s = s % 60
    return f"{m}:{str(s).zfill(2)}"


class SpotifyNowPlaying:
    def __init__(self, client_id, client_secret, refresh_token, env_path=None):
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        self.refresh_token = refresh_token or ""
        self.env_path = env_path or os.path.join(os.path.dirname(__file__), ".env")
        self.access_token = None
        self.access_token_exp = 0
        self.last_cover_url = None
        self.last_cover_img = None

    def _basic_auth_header(self):
        raw = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        b64 = base64.b64encode(raw).decode("utf-8")
        return {"Authorization": f"Basic {b64}"}

    def _save_refresh_token(self, token):
        try:
            with open(self.env_path, "r") as f:
                lines = f.readlines()
            with open(self.env_path, "w") as f:
                for line in lines:
                    if line.startswith("SPOTIFY_REFRESH_TOKEN="):
                        f.write(f"SPOTIFY_REFRESH_TOKEN={token}\n")
                    else:
                        f.write(line)
            print("Spotify: refresh token rotated and saved to .env")
        except Exception as e:
            print(f"Spotify: could not save new refresh token: {e}")

    def _refresh_access_token(self):
        if not (self.client_id and self.client_secret and self.refresh_token):
            return False

        try:
            r = requests.post(
                "https://accounts.spotify.com/api/token",
                headers=self._basic_auth_header(),
                data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
                timeout=10,
            )
            if r.status_code != 200:
                print(f"Spotify token refresh failed: {r.status_code} {r.text}")
                return False

            data = r.json()
            self.access_token = data.get("access_token")
            expires_in = int(data.get("expires_in", 3600))
            self.access_token_exp = time.time() + max(30, expires_in - 60)

            # Save new refresh token if Spotify rotated it
            new_refresh = data.get("refresh_token")
            if new_refresh and new_refresh != self.refresh_token:
                self.refresh_token = new_refresh
                self._save_refresh_token(new_refresh)

            return True
        except Exception as e:
            print(f"Spotify: token refresh exception: {e}")
            return False

    def _ensure_token(self):
        if self.access_token and time.time() < self.access_token_exp:
            return True
        return self._refresh_access_token()

    def get_current(self):
        if not self._ensure_token():
            return None

        try:
            r = requests.get(
                "https://api.spotify.com/v1/me/player/currently-playing",
                headers={"Authorization": f"Bearer {self.access_token}"},
                timeout=10,
            )

            if r.status_code == 204:
                return None

            if r.status_code == 401:
                if self._refresh_access_token():
                    return self.get_current()
                return None

            if r.status_code != 200:
                return None

            data = r.json()
            if not data or not data.get("is_playing"):
                return None

            item = data.get("item") or {}
            if not item:
                return None

            artists = ", ".join(
                a.get("name", "") for a in (item.get("artists") or []) if a.get("name")
            )
            album_obj = item.get("album") or {}
            album = album_obj.get("name", "")
            release_date = album_obj.get("release_date", "")
            name = item.get("name", "")

            duration_ms = int(item.get("duration_ms") or 0)
            progress_ms = int(data.get("progress_ms") or 0)

            images = (album_obj.get("images") or [])
            cover_url = images[0]["url"] if images else None

            return {
                "name": name,
                "artists": artists,
                "album": album,
                "release_date": release_date,
                "duration_ms": duration_ms,
                "progress_ms": progress_ms,
                "cover_url": cover_url,
            }
        except Exception:
            return None

    def get_cover_image(self, url, size=(84, 84)):
        if not url:
            return None

        if url == self.last_cover_url and self.last_cover_img is not None:
            return self.last_cover_img

        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            img = Image.open(BytesIO(r.content)).convert("RGB").resize(size)
            self.last_cover_url = url
            self.last_cover_img = img
            return img
        except Exception:
            return None

    def fmt_progress(self, data):
        if not data:
            return ""
        return f"{_fmt_ms(data.get('progress_ms'))} / {_fmt_ms(data.get('duration_ms'))}"