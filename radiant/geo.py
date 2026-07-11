"""Tiny offline gazetteer: place name -> (lat, lon).

So external agents can emit "Tehran" or "Nigeria" instead of coordinates and
the globe still plots the pin — no geocoding API, no key. Covers major world
cities, tech hubs, and country/region centroids; extend as needed. Falls back
to None when unknown (the caller decides what to do).
"""

from __future__ import annotations

import re
import unicodedata

# name -> (lat, lon). Keep lowercase keys; aliases point at the same tuple.
PLACES: dict[str, tuple[float, float]] = {
    # --- cities / tech hubs ---
    "san francisco": (37.77, -122.42), "sf": (37.77, -122.42),
    "silicon valley": (37.39, -122.08), "palo alto": (37.44, -122.14),
    "new york": (40.71, -74.01), "nyc": (40.71, -74.01), "boston": (42.36, -71.06),
    "austin": (30.27, -97.74), "seattle": (47.61, -122.33), "los angeles": (34.05, -118.24),
    "toronto": (43.65, -79.38), "london": (51.51, -0.13), "paris": (48.85, 2.35),
    "berlin": (52.52, 13.40), "amsterdam": (52.37, 4.90), "stockholm": (59.33, 18.06),
    "zurich": (47.37, 8.54), "tel aviv": (32.08, 34.78), "dubai": (25.20, 55.27),
    "abu dhabi": (24.45, 54.38), "doha": (25.29, 51.53), "riyadh": (24.71, 46.68),
    "bangalore": (12.97, 77.59), "bengaluru": (12.97, 77.59), "mumbai": (19.08, 72.88),
    "delhi": (28.61, 77.21), "new delhi": (28.61, 77.21), "hyderabad": (17.39, 78.49),
    "singapore": (1.35, 103.82), "hong kong": (22.32, 114.17), "shenzhen": (22.54, 114.06),
    "beijing": (39.90, 116.40), "shanghai": (31.23, 121.47), "tokyo": (35.68, 139.69),
    "seoul": (37.57, 126.98), "taipei": (25.03, 121.57), "bangkok": (13.76, 100.50),
    "jakarta": (-6.21, 106.85), "sydney": (-33.87, 151.21), "melbourne": (-37.81, 144.96),
    "lagos": (6.52, 3.37), "nairobi": (-1.29, 36.82), "cape town": (-33.92, 18.42),
    "johannesburg": (-26.20, 28.05), "cairo": (30.04, 31.24), "accra": (5.60, -0.19),
    "sao paulo": (-23.55, -46.63), "são paulo": (-23.55, -46.63), "rio de janeiro": (-22.91, -43.17),
    "mexico city": (19.43, -99.13), "buenos aires": (-34.60, -58.38), "bogota": (4.71, -74.07),
    "tehran": (35.69, 51.39), "istanbul": (41.01, 28.98), "moscow": (55.76, 37.62),
    "kyiv": (50.45, 30.52), "kiev": (50.45, 30.52), "warsaw": (52.23, 21.01),
    "dublin": (53.35, -6.26), "helsinki": (60.17, 24.94), "lisbon": (38.72, -9.14),
    "madrid": (40.42, -3.70), "barcelona": (41.39, 2.17), "milan": (45.46, 9.19),
    "munich": (48.14, 11.58), "gaza": (31.50, 34.47), "jerusalem": (31.78, 35.22),
    # --- countries / regions (centroid or capital) ---
    "usa": (39.83, -98.58), "united states": (39.83, -98.58), "america": (39.83, -98.58),
    "uk": (54.0, -2.0), "united kingdom": (54.0, -2.0), "britain": (54.0, -2.0),
    "france": (46.6, 2.2), "germany": (51.2, 10.4), "india": (22.0, 79.0),
    "china": (35.9, 104.2), "japan": (36.2, 138.3), "iran": (32.4, 53.7),
    "israel": (31.5, 34.8), "nigeria": (9.1, 8.7), "kenya": (0.0, 37.9),
    "south africa": (-30.6, 22.9), "brazil": (-14.2, -51.9), "canada": (56.1, -106.3),
    "australia": (-25.3, 133.8), "south korea": (36.5, 127.8), "korea": (36.5, 127.8),
    "russia": (61.5, 105.3), "ukraine": (48.4, 31.2), "uae": (23.4, 53.8),
    "saudi arabia": (23.9, 45.1), "indonesia": (-0.8, 113.9), "mexico": (23.6, -102.5),
    "argentina": (-38.4, -63.6), "turkey": (39.0, 35.2), "spain": (40.5, -3.7),
    "italy": (41.9, 12.6), "netherlands": (52.1, 5.3), "sweden": (60.1, 18.6),
    "poland": (51.9, 19.1), "ireland": (53.4, -8.2), "egypt": (26.8, 30.8),
    "thailand": (15.9, 100.9), "vietnam": (14.1, 108.3), "taiwan": (23.7, 120.9),
    "singapore ": (1.35, 103.82),
    "europe": (50.0, 10.0), "africa": (7.2, 20.0), "asia": (34.0, 100.0),
    "middle east": (29.3, 45.0), "latin america": (-15.0, -60.0),
}

_CLEAN = re.compile(r"[^a-z\s]")


def _normkey(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))   # drop accents
    return _CLEAN.sub("", s.lower()).strip()


def geocode(place: str | None) -> tuple[float, float] | None:
    """Resolve a place name to (lat, lon), or None if unknown."""
    if not place:
        return None
    key = _normkey(place)
    if key in PLACES:
        return PLACES[key]
    key2 = key[4:] if key.startswith("the ") else key
    if key2 in PLACES:
        return PLACES[key2]
    # try the last word (e.g. "riots in France" -> "france")
    for token in reversed(key.split()):
        if token in PLACES:
            return PLACES[token]
    return None
