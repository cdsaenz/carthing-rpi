"""
MEP dollar rate — queried directly from the public dolarapi.com endpoint.
No proxy, no API key. dolarapi.com is the actual underlying source the
legacy infoscreen's own server-side proxy was itself forwarding to
(it passed source=dolarapi), so this just cuts out the middleman.
"""

import requests


class DollarProvider:
    API_URL = "https://dolarapi.com/v1/dolares/bolsa"  # "bolsa" = MEP

    def get_mep_rate(self):
        """Returns the current MEP rate as a float, or None on failure.

        Uses "compra", matching legacy/dollatracker.py — that's the field
        the rest of this user's tooling (Stream Deck, old infoscreen) has
        always treated as "the" MEP rate, not "venta".
        """
        try:
            r = requests.get(self.API_URL, timeout=5)
            r.raise_for_status()
            compra = r.json().get("compra")
            return float(compra) if compra is not None else None
        except Exception as e:
            print(f"[dollar] error: {e}")
            return None
