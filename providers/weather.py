"""
Weather provider — hits the same personal API service the legacy pizero
infoscreen used, reusing the existing API_KEY from .env. No new credentials
needed.
"""

import requests


class WeatherProvider:
    API_URL = "https://csdemos.com.ar/services/weather/api/weather/temperature"

    def __init__(self, api_key):
        self.api_key = api_key or ""

    def get_temperature(self):
        """Returns dict like {'temp': .., 'feelslike': ..} or None on failure."""
        try:
            r = requests.get(
                self.API_URL,
                headers={"X-API-Key": self.api_key},
                params={"refresh": "true"},
                timeout=5,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"[weather] error: {e}")
            return None
