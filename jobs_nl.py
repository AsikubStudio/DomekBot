"""
Wyszukiwanie ofert pracy w Holandii w poblizu ZNALEZIONYCH ofert mieszkan,
przez darmowe API Adzuna (https://developer.adzuna.com/). Dziala na tej samej
zasadzie co jobs.py (Bundesagentur fur Arbeit, Niemcy) - wyszukiwanie odpala
sie TYLKO dla lokalizacji mieszkan, ktore juz przeszly wszystkie inne filtry
(patrz main.py::attach_nearby_jobs) i TAK SAMO NIE wysyla osobnych
powiadomien (Telegram/Web Push) - wyniki traja do tego samego dropdownu
"Praca w pobliżu" na stronie, oznaczone "kraj": "NL".

Priorytet: uzytkownik zdecydowal (21.09.2026), ze oferty pracy z Holandii maja
byc pokazywane NAD niemieckimi w dropdownie - patrz main.py::attach_nearby_jobs,
kolejnosc scalania listy (NL przed DE). Powod: szukanie pracy bez wymaganego
niemieckiego jest po holenderskiej stronie granicy zazwyczaj prostsze, a
niemieckie wyszukiwanie (jobs.py) ma znany problem z czescia ofert wymagajaca
niemieckiego mimo doboru slow kluczowych (patrz komentarz w config.py przy
JOB_SEARCH_ENABLED).

Adzuna (w odroznieniu od Bundesagentur) NIE przyjmuje wspolrzednych lat/lon w
darmowym publicznym API - trzeba podac tekstowa nazwe miejscowosci w "where"
i promien w km w "distance". Zeby mimo to zachowac TA SAMA logike co
niemieckie wyszukiwanie (kazda oferta mieszkania ma WLASNY punkt odniesienia,
a nie jeden staly punkt dla calej okolicy), kazdej ofercie mieszkania
przypisywana jest NAJBLIZSZA jej holenderska "kotwica" graniczna - patrz
utils/geo.py::nearest_dutch_job_anchor() / DUTCH_JOB_ANCHORS.

Rejestracja (darmowa, natychmiastowa, bez karty platniczej): https://developer.adzuna.com/
Klucze (App ID + App Key) wczytywane tak samo jak ORS_API_KEY w utils/geo.py:
  - w chmurze (GitHub Actions): sekrety repo ADZUNA_APP_ID / ADZUNA_APP_KEY
  - lokalnie (ImmoScout24): local_secrets/adzuna_app_id.txt / adzuna_app_key.txt
    (folder jest w .gitignore, nigdy nie trafia do repo)
"""
import os
import time
import logging
from typing import Dict, List, Optional, Tuple

import requests

import config
from utils.geo import nearest_dutch_job_anchor

logger = logging.getLogger("immo-bot")

ADZUNA_SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"

# Ten sam wzorzec co local_secrets w utils/geo.py/notify.py.
LOCAL_SECRETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_secrets")


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


def _get_adzuna_credentials() -> Optional[Tuple[str, str]]:
    app_id = os.environ.get("ADZUNA_APP_ID") or _read_local_secret("adzuna_app_id.txt")
    app_key = os.environ.get("ADZUNA_APP_KEY") or _read_local_secret("adzuna_app_key.txt")
    if not app_id or not app_key:
        return None
    return app_id, app_key


# Adzuna nie publikuje twardego limitu dla darmowego planu ("hundreds of calls
# per day" wg dokumentacji) - mimo to szanujemy serwer tak samo jak resztę
# integracji w tym projekcie, maly odstep miedzy wywolaniami.
_MIN_INTERVAL_SECONDS = 1.0
_last_call = 0.0


def _throttled_get(params: dict) -> Optional[dict]:
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < _MIN_INTERVAL_SECONDS:
        time.sleep(_MIN_INTERVAL_SECONDS - elapsed)

    try:
        resp = requests.get(
            ADZUNA_SEARCH_URL.format(country=config.JOB_SEARCH_NL_COUNTRY),
            params=params,
            timeout=config.REQUEST_TIMEOUT_SECONDS,
        )
        _last_call = time.time()
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        safe_params = {k: v for k, v in params.items() if k not in ("app_id", "app_key")}
        logger.warning(
            "Adzuna API: zapytanie zawiodlo (%s, params=%s) - pomijam ten fragment wyszukiwania pracy w Holandii.",
            exc, safe_params,
        )
        return None


def _parse_job(raw: dict) -> Optional[Dict]:
    """Zamienia jeden surowy wpis z Adzuna 'results' na ten sam ksztalt
    slownika co jobs.py::_parse_job (zeby front-end na stronie mogl je
    wyswietlac identycznie), plus pole "kraj": "NL" do priorytetyzacji/
    oznaczenia. Zwraca None jesli brakuje linku (nie mamy dokad zalinkowac)."""
    try:
        job_id = raw.get("id")
        title = raw.get("title") or "(bez tytulu)"
        company = (raw.get("company") or {}).get("display_name") or "?"
        location = (raw.get("location") or {}).get("display_name") or ""
        url = raw.get("redirect_url")
        if not url:
            return None

        return {
            "refnr": job_id,
            "titel": title,
            "pracodawca": company,
            "miejscowosc": location,
            "link": url,
            "opublikowano": raw.get("created"),
            "kraj": "NL",
        }
    except (AttributeError, TypeError):
        return None


def search_jobs_near_nl(location_text: str) -> List[Dict]:
    """
    Szuka ofert pracy w Holandii w poblizu location_text (adres oferty
    mieszkania - patrz nearest_dutch_job_anchor() w utils/geo.py, ktora
    wybiera najblizsza "kotwice" graniczna jako punkt "where" dla Adzuna),
    po wszystkich slowach z config.JOB_SEARCH_NL_KEYWORDS, scalone i
    odduplikowane po id.

    Zwraca pusta liste [] jesli JOB_SEARCH_NL_ENABLED=False, brak
    skonfigurowanych kluczy Adzuna, brak location_text, geokodowanie sie nie
    uda, albo WSZYSTKIE zapytania do API zawioda - nigdy nie wywala reszty
    przebiegu (tak samo jak jobs.py i inne integracje w tym projekcie).
    """
    if not config.JOB_SEARCH_NL_ENABLED or not location_text:
        return []

    creds = _get_adzuna_credentials()
    if not creds:
        return []
    app_id, app_key = creds

    anchor = nearest_dutch_job_anchor(location_text)
    if not anchor:
        return []
    anchor_name, _anchor_distance_km = anchor

    seen_ids = set()
    results: List[Dict] = []

    for keyword in config.JOB_SEARCH_NL_KEYWORDS:
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": config.JOB_SEARCH_NL_MAX_RESULTS_PER_KEYWORD,
            "what": keyword,
            "where": anchor_name,
            "distance": config.JOB_SEARCH_NL_RADIUS_KM,
            "content-type": "application/json",
        }
        data = _throttled_get(params)
        if not data:
            continue

        for raw in data.get("results", []):
            job_id = raw.get("id")
            if job_id and job_id in seen_ids:
                continue
            job = _parse_job(raw)
            if not job:
                continue
            if job_id:
                seen_ids.add(job_id)
            results.append(job)

    return results
