"""
Pomocnicze funkcje do liczenia odległości i sprawdzania czy oferta mieści się
w zasięgu wyszukiwania. Geokodowanie idzie przez darmowe Nominatim (OpenStreetMap) -
nie wymaga klucza API, ale trzeba szanować limity (1 request/s, ustawiony User-Agent).

GŁÓWNE kryterium zasięgu to CZAS DOJAZDU AUTEM (nie odległość w linii prostej) -
liczony przez OpenRouteService (openrouteservice.org), darmowy plan po rejestracji
(2500 zapytań/dzień - patrz drive_time_minutes()). Jeśli OpenRouteService zawiedzie
(brak klucza API, limit, awaria, timeout) - evaluate_location() automatycznie
WRACA na starą metodę: odległość w linii prostej (config.MAX_DISTANCE_KM_FALLBACK).
Jeśli i geokodowanie się nie uda, ostatni fallback to KNOWN_NEARBY_PLACES z
config.py - dopasowanie tekstowe nazwy miejscowości.
"""
import os
import time
import math
import logging
from functools import lru_cache
from typing import Optional, Tuple

import requests

import config

logger = logging.getLogger("immo-bot")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_last_geocode_call = 0.0

# --- OpenRouteService (czas dojazdu autem) ---
ORS_DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/driving-car"
# Darmowy plan ORS: 40 zapytań/minutę - odstęp 1.6s daje spory zapas.
_ORS_MIN_INTERVAL_SECONDS = 1.6
_last_ors_call = 0.0

# Ten sam wzorzec co local_secrets w notify.py: dla lokalnych uruchomień
# (ImmoScout24 przez Task Scheduler) nie ma sensu ustawiać zmiennych
# środowiskowych systemowych - zamiast tego klucz może leżeć w pliku
# local_secrets/ors_api_key.txt (folder jest w .gitignore, nigdy nie trafia do repo).
LOCAL_SECRETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "local_secrets")


def _read_local_secret(filename: str) -> Optional[str]:
    path = os.path.join(LOCAL_SECRETS_DIR, filename)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            content = f.read().strip()
        return content or None
    except OSError:
        return None


def _get_ors_api_key() -> Optional[str]:
    return os.environ.get("ORS_API_KEY") or _read_local_secret("ors_api_key.txt")

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


@lru_cache(maxsize=256)
def drive_time_minutes(location_text: str) -> Optional[int]:
    """
    Zwraca czas dojazdu autem (w minutach, zaokrąglony) z CENTER_CITY do
    location_text, licząc przez OpenRouteService. None jeśli brak klucza API,
    geokodowanie się nie uda, albo zapytanie do ORS zawiedzie (limit, awaria,
    timeout) - w każdym z tych przypadków evaluate_location() spada na
    zapasowe kryterium (odległość w linii prostej).
    """
    if not location_text:
        return None

    api_key = _get_ors_api_key()
    if not api_key:
        return None

    origin = geocode(f"{config.CENTER_PLZ} {config.CENTER_CITY}, Germany")
    target = geocode(f"{location_text}, Germany")
    if not origin or not target:
        return None

    global _last_ors_call
    elapsed = time.time() - _last_ors_call
    if elapsed < _ORS_MIN_INTERVAL_SECONDS:
        time.sleep(_ORS_MIN_INTERVAL_SECONDS - elapsed)

    try:
        resp = requests.get(
            ORS_DIRECTIONS_URL,
            params={
                # ORS chce (lon, lat), nie (lat, lon) - odwrotnie niż Nominatim.
                "api_key": api_key,
                "start": f"{origin[1]},{origin[0]}",
                "end": f"{target[1]},{target[0]}",
            },
            timeout=config.REQUEST_TIMEOUT_SECONDS,
        )
        _last_ors_call = time.time()
        if resp.status_code == 429:
            logger.warning("OpenRouteService: limit zapytań (429) - ten przebieg spada na dystans w linii prostej.")
            return None
        resp.raise_for_status()
        data = resp.json()
        duration_sec = data["features"][0]["properties"]["segments"][0]["duration"]
        return round(duration_sec / 60)
    except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
        logger.warning("OpenRouteService: nie udało się policzyć czasu dojazdu dla '%s' (%s) - "
                        "spadam na dystans w linii prostej.", location_text, exc)
        return None


def within_radius(location_text: str) -> Tuple[bool, Optional[float]]:
    """
    Stara metoda (tylko odległość w linii prostej) - zostawiona jako budulec
    dla evaluate_location() poniżej i do ew. ręcznego debugowania.
    Zwraca (czy_pasuje, dystans_km_lub_None).
    """
    dist = distance_from_center_km(location_text)
    if dist is not None:
        return dist <= config.MAX_DISTANCE_KM_FALLBACK, dist

    # fallback: brak internetu / brak wyniku geokodowania
    return is_known_nearby_place(location_text), None


def evaluate_location(location_text: str, known_distance_km: Optional[float] = None) -> Tuple[bool, Optional[int], Optional[float]]:
    """
    GŁÓWNA funkcja filtrowania po lokalizacji - używana przez filters.py.
    Zwraca (czy_pasuje, czas_dojazdu_min_lub_None, dystans_km_lub_None).

    known_distance_km - jeśli portal już podał odległość w linii prostej
    (np. Kleinanzeigen na karcie wyniku), przekaż ją tutaj, żeby nie geokodować
    drugi raz tylko po to, by policzyć to samo haversine'em.

    Kolejność prób:
      1. Czas dojazdu autem (OpenRouteService) <= config.MAX_DRIVE_TIME_MINUTES.
      2. Jeśli ORS niedostępny/zawiódł: dystans w linii prostej
         <= config.MAX_DISTANCE_KM_FALLBACK (znany z portalu albo geokodowany).
      3. Jeśli i geokodowanie zawiedzie: dopasowanie tekstowe do KNOWN_NEARBY_PLACES.
    """
    minutes = drive_time_minutes(location_text)
    if minutes is not None:
        distance_km = known_distance_km if known_distance_km is not None else distance_from_center_km(location_text)
        return minutes <= config.MAX_DRIVE_TIME_MINUTES, minutes, distance_km

    distance_km = known_distance_km if known_distance_km is not None else distance_from_center_km(location_text)
    if distance_km is not None:
        return distance_km <= config.MAX_DISTANCE_KM_FALLBACK, None, distance_km

    return is_known_nearby_place(location_text), None, None
