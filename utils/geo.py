"""
Pomocnicze funkcje do liczenia odległości i sprawdzania czy oferta mieści się
w promieniu wyszukiwania. Geokodowanie idzie przez darmowe Nominatim (OpenStreetMap) -
nie wymaga klucza API, ale trzeba szanować limity (1 request/s, ustawiony User-Agent).

Jeśli geokodowanie zawiedzie (brak sieci, brak wyniku), filtr spada na
KNOWN_NEARBY_PLACES z config.py - dopasowanie tekstowe nazwy miejscowości.
"""
import time
import math
from functools import lru_cache
from typing import Optional, Tuple

import requests

import config

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_last_geocode_call = 0.0

# Wspolrzedne 's-Heerenberg (Holandia, Gelderland, tuz przy granicy z Niemcami kolo
# Emmerich) - zaszyte na sztywno zamiast geokodowane przy kazdym uruchomieniu, bo to
# STALY, drugi punkt odniesienia (w odroznieniu od adresow ofert, ktore sie zmieniaja
# i musza byc geokodowane dynamicznie). Zrodlo: Wikipedia ('s-Heerenberg),
# 51°52'35"N 6°14'45"E.
SHEERENBERG_COORDS = (51.87639, 6.24583)


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


@lru_cache(maxsize=256)
def geocode(place_query: str) -> Optional[Tuple[float, float]]:
    """Zwraca (lat, lon) dla zapytania tekstowego, np. '46446 Emmerich am Rhein, Germany'."""
    global _last_geocode_call
    elapsed = time.time() - _last_geocode_call
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)

    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": place_query, "format": "json", "limit": 1},
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.REQUEST_TIMEOUT_SECONDS,
        )
        _last_geocode_call = time.time()
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None
        return float(data[0]["lat"]), float(data[0]["lon"])
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


def geocode_location(location_text: str) -> Optional[Tuple[float, float]]:
    """
    Zwraca (lat, lon) dla tekstowej lokalizacji oferty - do pokazania pinezki na
    mapie na stronie. Korzysta z tego samego lru_cache co distance_from_center_km/
    distance_from_sheerenberg_km, wiec dla lokalizacji juz gdzies policzonej w tym
    samym przebiegu NIE generuje dodatkowego requestu do Nominatim.
    """
    if not location_text:
        return None
    return geocode(f"{location_text}, Germany")


def distance_from_center_km(location_text: str) -> Optional[float]:
    """Próbuje wyliczyć odległość ogłoszenia od CENTER_CITY. None jeśli się nie uda."""
    if not location_text:
        return None

    center = geocode(f"{config.CENTER_PLZ} {config.CENTER_CITY}, Germany")
    target = geocode(f"{location_text}, Germany")
    if not center or not target:
        return None

    return round(_haversine_km(*center, *target), 1)


def distance_from_sheerenberg_km(location_text: str) -> Optional[float]:
    """
    Wylicza odległość oferty od 's-Heerenberg (drugi punkt odniesienia, obok
    CENTER_CITY/Emmerich) - używane TYLKO do wyświetlenia na stronie, nie filtruje
    ofert (w odróżnieniu od within_radius). Zwraca None jeśli geokodowanie adresu
    oferty się nie uda. Dzięki lru_cache na geocode() - jeśli ta sama lokalizacja
    była już geokodowana wcześniej w tym samym przebiegu (np. przez
    distance_from_center_km), nie robimy drugiego requestu do Nominatim.
    """
    if not location_text:
        return None
    target = geocode(f"{location_text}, Germany")
    if not target:
        return None
    return round(_haversine_km(*SHEERENBERG_COORDS, *target), 1)


def is_known_nearby_place(location_text: str) -> bool:
    """Fallback bez geokodowania: sprawdza czy nazwa miejscowości jest na białej liście."""
    if not location_text:
        return False
    text = location_text.lower()
    return any(place in text for place in config.KNOWN_NEARBY_PLACES)


def within_radius(location_text: str) -> Tuple[bool, Optional[float]]:
    """
    Zwraca (czy_pasuje, dystans_km_lub_None).
    Najpierw próbuje geokodowania (dokładny dystans), a jak się nie uda -
    pada na dopasowanie tekstowe do znanych miejscowości.
    """
    dist = distance_from_center_km(location_text)
    if dist is not None:
        return dist <= config.MAX_DISTANCE_KM, dist

    # fallback: brak internetu / brak wyniku geokodowania
    return is_known_nearby_place(location_text), None
