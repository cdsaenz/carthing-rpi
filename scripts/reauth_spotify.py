#!/usr/bin/env python3
"""
One-time (or occasional) re-authorization to mint a new Spotify refresh
token with an updated scope list. Needed whenever a new feature requires a
scope the existing token was never granted (e.g. user-follow-read for the
Artists tab and user-library-read for Albums, added after the original
token was issued).

Usage:
  1. Fill in REDIRECT_URI below with whatever's registered for this app in
     the Spotify Developer Dashboard (developer.spotify.com/dashboard).
  2. Run this on the Pi: python scripts/reauth_spotify.py
  3. Open the printed URL in any browser (phone/PC — doesn't need to be the
     Pi) and approve. The redirect may fail to load — that's fine, the
     "code=" value is in the address bar regardless.
  4. Paste that code back into this script's prompt.
  5. Copy the new refresh token into .env's SPOTIFY_REFRESH_TOKEN, then
     restart the carthing service.
"""

import base64
import os

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
REDIRECT_URI = ""  # <-- fill in: must exactly match what's registered for this app

# Superset of every scope this app's SpotifyProvider methods touch, so the
# new token doesn't lose anything the old one already had.
SCOPES = (
    "user-read-playback-state user-modify-playback-state user-read-currently-playing "
    "playlist-read-private playlist-read-collaborative user-follow-read user-library-read"
)


def main():
    if not REDIRECT_URI:
        print("Fill in REDIRECT_URI at the top of this script first — check the")
        print("Spotify Developer Dashboard for this app's registered redirect URI.")
        return
    if not CLIENT_ID or not CLIENT_SECRET:
        print("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET missing from .env")
        return

    auth_url = (
        "https://accounts.spotify.com/authorize"
        f"?client_id={CLIENT_ID}&response_type=code&redirect_uri={REDIRECT_URI}"
        f"&scope={SCOPES.replace(' ', '%20')}"
    )
    print("1. Open this URL in any browser and approve:\n")
    print(auth_url)
    print("\n2. After approving, copy the 'code=' value from the resulting URL")
    print("   (the page itself may fail to load — that's expected, ignore it).\n")

    code = input("Paste the code here: ").strip()
    if not code:
        print("No code entered, aborting.")
        return

    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={
            "Authorization": "Basic "
            + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        },
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
        timeout=10,
    )
    data = resp.json()

    if "refresh_token" in data:
        print("\nNew refresh token — put this in .env as SPOTIFY_REFRESH_TOKEN:\n")
        print(data["refresh_token"])
        print("\nThen: sudo systemctl restart carthing")
    else:
        print("Error from Spotify:", data)


if __name__ == "__main__":
    main()
