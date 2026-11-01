"""
Claude usage meter — reads session (5-hour) and weekly usage percentages from
a small usage.json served somewhere on the LAN (see scripts/claude_usage_collect.py).
The Pi never holds a Claude login; the collector runs on an always-on
machine that already has one. Anthropic publishes no official API for
subscription limits, so this depends on an undocumented endpoint and can
break without notice — the meter just hides itself when that happens.
"""

import time
from datetime import datetime, timedelta, timezone

import requests


class ClaudeUsageProvider:
    STALE_SECS = 15 * 60  # collector runs every few minutes; older than this means it's stuck

    def __init__(self, url):
        self.url = url

    def get_usage(self):
        """Returns {session_pct, session_resets_in, week_pct, week_resets_in} or None when
        unavailable/stale — callers hide the meter on None."""
        try:
            r = requests.get(self.url, timeout=5)
            r.raise_for_status()
            d = r.json()
            if time.time() - d["updated"] > self.STALE_SECS:
                return None
            now = datetime.now(timezone.utc)
            # Pace: the week is 7 equal daily budgets of 100/7 %. On day N
            # you "should" be at or under N * 100/7 — over that means burning
            # faster than an even spread.
            week_start = datetime.fromisoformat(d["week_resets_at"]) - timedelta(days=7)
            day_n = min(7, max(1, int((now - week_start).total_seconds() // 86400) + 1))
            return {
                "week_budget": day_n * 100 / 7,
                "session_pct": float(d["session_pct"]),
                "session_resets_in": max(0, (datetime.fromisoformat(d["session_resets_at"]) - now).total_seconds()),
                "week_pct": float(d["week_pct"]),
                "week_resets_in": max(0, (datetime.fromisoformat(d["week_resets_at"]) - now).total_seconds()),
            }
        except Exception as e:
            print(f"[claude] error: {e}")
            return None
