"""
Pomocnicze funkcje do liczenia odległości i sprawdzania czy oferta mieści się
w zasięgu wyszukiwania. Geokodowanie idzie przez darmowe Nominatim (OpenStreetMap) -
nie wymaga klucza API, ale trzeba szanować limity (1 request/s, ustawiony User-Agent).

GŁÓWNE kryterium zasięgu to CZAS DOJAZDU AUTEM (nie odległość w linii prostej) -
liczony przez OpenRouteService (openrouteservice.org), darmowy plan po rejestracji.
Jeśli OpenRouteService zawiedzie (brak klucza API, limit, awaria, timeout) -
evaluate_location() automatycznie WRACA na starą metodę: odległość w linii prostej
(config.MAX_DISTANCE_KM_FALLBACK). Jeśli i geokodowanie się nie uda, ostatni fallback
to KNOWN_NEARBY_PLACES z config.py - dopasowanie tekstowe nazwy miejscowości.

WAŻNE (od 21.09.2026): drive_time_minutes() ma TRWAŁY cache na dysku
(config.DRIVE_TIME_CACHE_PATH), bo darmowy limit ORS okazał się za mały na
~32 uruchomienia dziennie (co 3h w chmurze + co godzinę lokalnie dla
ImmoScout24) licząc od nowa te same ~30-40 miejscowości za każdym razem -
skończyło się to błędem "Quota exceeded" na WSZYSTKICH zapytaniach. Raz
policzony wynik dla danej miejscowości jest zapamiętywany NA STAŁE (trasa
Emmerich->dana miejscowość praktycznie się nie zmienia) - patrz
_load_drive_time_cache()/_save_drive_time_cache() niżej. Plik cache jest
commitowany do repo (tak jak data/seen_ids.json), żeby chmura i lokalne
uruchomienia dzieliły tę samą wiedzę zamiast liczyć osobno.
"""
import json
import os
import time
import math
import logging
from functools import lru_cache
from typing import Dict, Optional, Tuple

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


def _load_drive_time_cache() -> Dict[str, int]:
    path = config.DRIVE_TIME_CACHE_PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Nie udało się wczytać %s (%s) - zaczynam z pustym cache czasu dojazdu.", path, exc)
    return {}


def _save_drive_time_cache() -> None:
    path = config.DRIVE_TIME_CACHE_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dict(sorted(_DRIVE_TIME_CACHE.items())), f, ensure_ascii=False, indent=2)
    except OSError as exc:
        logger.warning("Nie udało się zapisać %s (%s) - cache zostaje tylko w pamięci tego przebiegu.", path, exc)


# Wczytywany RAZ przy imporcie modułu, aktualizowany (i zapisywany na dysk) przy
# każdym nowo policzonym czasie dojazdu - patrz drive_time_minutes() niżej.
_DRIVE_TIME_CACHE: Dict[str, int] = _load_drive_time_cache()


# --- Trwały cache czasu dojazdu do OFERT PRACY (para lokalizacji) ---
# W odróżnieniu od _DRIVE_TIME_CACHE wyżej (klucz to JEDNA miejscowość, bo
# drugi punkt jest zawsze stały - CENTER_CITY), tu klucz musi być PARĄ
# lokalizacji (mieszkanie<->oferta pracy), bo obie strony się zmieniają -
# patrz commute_minutes_to_job() niżej. Dodane 21.09.2026 na prośbę
# użytkownika (filtr ~45 min realnego dojazdu do oferty pracy, nie tylko
# promień/kotwica używane do samego wyszukiwania - patrz jobs.py/jobs_nl.py).
def _load_job_commute_cache() -> Dict[str, int]:
    path = config.JOB_COMMUTE_CACHE_PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Nie udało się wczytać %s (%s) - zaczynam z pustym cache dojazdu do ofert pracy.", path, exc)
    return {}


def _save_job_commute_cache() -> None:
    path = config.JOB_COMMUTE_CACHE_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dict(sorted(_JOB_COMMUTE_CACHE.items())), f, ensure_ascii=False, indent=2)
    except OSError as exc:
        logger.warning("Nie udało się zapisać %s (%s) - cache zostaje tylko w pamięci tego przebiegu.", path, exc)


_JOB_COMMUTE_CACHE: Dict[str, int] = _load_job_commute_cache()

# Wspolrzedne 's-Heerenberg (Holandia, Gelderland, tuz przy granicy z Niemcami kolo
# Emmerich) - zaszyte na sztywno zamiast geokodowane przy kazdym uruchomieniu, bo to
# STALY, drugi punkt odniesienia (w odroznieniu od adresow ofert, ktore sie zmieniaja
# i musza byc geokodowane dynamicznie). Zrodlo: Wikipedia ('s-Heerenberg),
# 51°52'35"N 6°14'45"E.
SHEERENBERG_COORDS = (51.87639, 6.24583)

# Kilka "kotwic" po holenderskiej stronie granicy, uzywanych do wyszukiwania
# ofert pracy w Holandii (patrz jobs_nl.py) - ten sam pomysl co
# SHEERENBERG_COORDS wyzej, tylko kilka punktow zamiast jednego, zeby kazda
# oferta mieszkania dostala NAJBLIZSZY sobie punkt odniesienia (patrz
# nearest_dutch_job_anchor() nizej), tak samo jak niemieckie wyszukiwanie
# pracy w jobs.py uzywa lokalizacji KAZDEJ oferty osobno, a nie jednego
# stalego miasta. Wspolrzedne przyblizone (centrum miejscowosci), zrodlo:
# Wikipedia / OpenStreetMap.
DUTCH_JOB_ANCHORS: Dict[str, Tuple[float, float]] = {
    "'s-Heerenberg": SHEERENBERG_COORDS,
    "Zevenaar": (51.9303, 6.0736),
    "Doetinchem": (51.9647, 6.2880),
    "Arnhem": (51.9851, 5.8987),
    "Nijmegen": (51.8425, 5.8528),
}


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


def nearest_dutch_job_anchor(location_text: str) -> Optional[Tuple[str, float]]:
    """
    Zwraca (nazwa_miejscowosci, dystans_km) najblizszej "kotwicy" z
    DUTCH_JOB_ANCHORS wzgledem geokodowanej lokalizacji oferty mieszkania.
    Uzywane przez jobs_nl.py jako punkt "where" dla Adzuna API (Adzuna nie
    przyjmuje wspolrzednych lat/lon bezposrednio w darmowym publicznym API,
    tylko nazwe miejscowosci + promien w km) - dzieki temu wyszukiwanie pracy
    w Holandii jest zwiazane z konkretna lokalizacja KAZDEJ oferty, tak samo
    jak niemieckie wyszukiwanie w jobs.py, a nie ze stalym jednym miastem.

    Korzysta z tego samego geocode() co reszta modulu (lru_cache) - jesli ta
    lokalizacja byla juz geokodowana wczesniej w tym przebiegu (np. przez
    distance_from_center_km albo distance_from_sheerenberg_km), nie robi
    drugiego requestu do Nominatim.

    Zwraca None jesli geokodowanie sie nie uda (np. brak internetu) - wtedy
    jobs_nl.py po prostu pomija te oferte, tak jak przy braku klucza API.
    """
    if not location_text:
        return None
    target = geocode(f"{location_text}, Germany")
    if not target:
        return None

    nearest_name: Optional[str] = None
    nearest_dist: Optional[float] = None
    for name, coords in DUTCH_JOB_ANCHORS.items():
        dist = _haversine_km(*coords, *target)
        if nearest_dist is None or dist < nearest_dist:
            nearest_dist = dist
            nearest_name = name

    if nearest_name is None or nearest_dist is None:
        return None
    return nearest_name, round(nearest_dist, 1)


def _job_commute_cache_key(origin_location_text: str, job_location_text: str, job_country: str) -> str:
    return f"{origin_location_text}|{job_location_text}|{job_country}"


def get_cached_job_commute_minutes(origin_location_text: str, job_location_text: str, job_country: str) -> Optional[int]:
    """Zwraca TYLKO wynik już zapisany w cache (bez żadnego zapytania sieciowego) -
    używane przez main.py do liczenia budżetu nowych zapytań ORS na przebieg
    (patrz config.MAX_JOB_COMMUTE_LOOKUPS_PER_RUN), żeby cache-hity nic nie kosztowały."""
    return _JOB_COMMUTE_CACHE.get(_job_commute_cache_key(origin_location_text, job_location_text, job_country))


def commute_minutes_to_job(origin_location_text: str, job_location_text: str, job_country: str) -> Optional[int]:
    """
    Zwraca rzeczywisty czas dojazdu autem (ORS, w minutach) z lokalizacji OFERTY
    MIESZKANIA (origin_location_text, zawsze Niemcy) do lokalizacji OFERTY PRACY
    (job_location_text, Niemcy albo Holandia - job_country "DE"/"NL"). W
    odróżnieniu od drive_time_minutes() wyżej (który liczy TYLKO z jednego
    stałego CENTER_CITY), ta funkcja liczy między DWOMA dowolnymi punktami, bo
    tu OBIE strony się zmieniają (różne mieszkania, różne oferty pracy).

    Używane przez main.py::attach_nearby_jobs() do odfiltrowania ofert pracy,
    które wg promienia/najbliższej kotwicy (patrz jobs.py/jobs_nl.py - to
    tylko "zarzucenie siatki" do samego WYSZUKIWANIA) wyglądają na bliskie, ale
    realna trasa autem jest znacznie dłuższa niż config.MAX_JOB_COMMUTE_MINUTES
    (przykład zgłoszony przez użytkownika 21.09.2026: oferta pracy w Duiven dla
    mieszkania w Raesfeld - w promieniu wyszukiwania, ale 52 min realnej jazdy).

    Trwały cache na dysku (config.JOB_COMMUTE_CACHE_PATH), klucz to PARA
    lokalizacji (mieszkanie<->oferta pracy) - patrz _JOB_COMMUTE_CACHE wyżej.
    Dzieli throttle (_last_ors_call) z drive_time_minutes(), żeby oba razem
    nie przekroczyły limitu zapytań/minutę ORS.

    Zwraca None jeśli brak klucza ORS, geokodowanie któregokolwiek punktu się
    nie uda, albo zapytanie do ORS zawiedzie (limit/awaria/timeout) - w każdym
    z tych przypadków main.py CHOWA taką ofertę pracy w tym przebiegu (patrz
    config.HIDE_JOB_IF_COMMUTE_UNKNOWN), bo bez potwierdzonego czasu nie da się
    zagwarantować, że mieści się w limicie.
    """
    if not origin_location_text or not job_location_text:
        return None

    cache_key = _job_commute_cache_key(origin_location_text, job_location_text, job_country)
    if cache_key in _JOB_COMMUTE_CACHE:
        return _JOB_COMMUTE_CACHE[cache_key]

    api_key = _get_ors_api_key()
    if not api_key:
        return None

    dest_country_name = "Netherlands" if job_country == "NL" else "Germany"
    origin = geocode(f"{origin_location_text}, Germany")
    target = geocode(f"{job_location_text}, {dest_country_name}")
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
                "api_key": api_key,
                "start": f"{origin[1]},{origin[0]}",
                "end": f"{target[1]},{target[0]}",
            },
            timeout=config.REQUEST_TIMEOUT_SECONDS,
        )
        _last_ors_call = time.time()
        if resp.status_code == 429:
            logger.warning(
                "OpenRouteService: limit zapytań (429) przy liczeniu dojazdu do oferty pracy w '%s' - "
                "oferta zostanie ukryta w tym przebiegu, spróbujemy ponownie następnym razem.",
                job_location_text,
            )
            return None
        resp.raise_for_status()
        data = resp.json()
        duration_sec = data["features"][0]["properties"]["segments"][0]["duration"]
        minutes = round(duration_sec / 60)
        _JOB_COMMUTE_CACHE[cache_key] = minutes
        _save_job_commute_cache()
        return minutes
    except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
        logger.warning(
            "OpenRouteService: nie udało się policzyć dojazdu do oferty pracy w '%s' (%s) - "
            "oferta zostanie ukryta w tym przebiegu.",
            job_location_text, exc,
        )
        return None


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
    location_text. Najpierw sprawdza TRWAŁY cache na dysku (_DRIVE_TIME_CACHE,
    patrz wyżej) - jeśli ta miejscowość była już kiedyś policzona, zwraca
    zapamiętany wynik BEZ pytania OpenRouteService. Tylko dla naprawdę nowych
    miejscowości leci zapytanie do ORS; udany wynik od razu trafia do cache
    (w pamięci i na dysk), żeby kolejne uruchomienia (za 3h w chmurze, za
    godzinę lokalnie) go już nie przeliczały.

    Zwraca None jeśli brak klucza API, geokodowanie się nie uda, albo zapytanie
    do ORS zawiedzie (limit/quota, awaria, timeout) - w każdym z tych przypadków
    NIE cache'ujemy (żeby po ustąpieniu problemu kolejny przebieg spróbował
    znowu), a evaluate_location() spada na zapasowe kryterium (odległość w
    linii prostej).
    """
    if not location_text:
        return None

    if location_text in _DRIVE_TIME_CACHE:
        return _DRIVE_TIME_CACHE[location_text]

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
        minutes = round(duration_sec / 60)
        _DRIVE_TIME_CACHE[location_text] = minutes
        _save_drive_time_cache()
        return minutes
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
