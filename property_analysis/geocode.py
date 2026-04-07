from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional, Tuple


def geocode_nominatim(query: str, *, user_agent: str = "PropertyMasterApp/1.0 (contact: local)") -> Optional[Tuple[float, float]]:
    """
    Free geocoding via OpenStreetMap Nominatim (please respect 1 req/s).
    Returns (lon, lat) for KML <coordinates>lon,lat,0</coordinates>.
    """
    q = (query or "").strip()
    if not q:
        return None
    params = urllib.parse.urlencode({"q": q, "format": "json", "limit": "1"})
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        time.sleep(1.0)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None
    if not data:
        return None
    try:
        lon = float(data[0]["lon"])
        lat = float(data[0]["lat"])
        return (lon, lat)
    except (KeyError, TypeError, ValueError):
        return None
