#!/usr/bin/env python3
"""
Writes public/usage.json with this account's Claude session + weekly usage
percentages, for the CarThing's home-screen meter.

Reads Claude Code's own OAuth token read-only and never refreshes it (a
second process refreshing could invalidate the one Claude Code is using) —
if the token has expired it just leaves the old file alone, which the
meter treats as stale and hides. The token is never written to the output.
"""

import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "public", "usage.json")
CREDS = os.path.expanduser("~/.claude/.credentials.json")


def main():
    with open(CREDS) as f:
        oauth = json.load(f)["claudeAiOauth"]
    if oauth["expiresAt"] / 1000 - time.time() < 60:
        return

    req = urllib.request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={
            "Authorization": "Bearer " + oauth["accessToken"],
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "carthing-meter",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)

    session, week = data["five_hour"], data["seven_day"]
    out = {
        "updated": int(time.time()),
        "session_pct": session["utilization"],
        "session_resets_at": session["resets_at"],
        "week_pct": week["utilization"],
        "week_resets_at": week["resets_at"],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f)
    os.replace(tmp, OUT)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[claude-meter] {e}")
