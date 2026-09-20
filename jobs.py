"""
Wyszukiwanie ofert pracy w pobliżu ZNALEZIONYCH ofert mieszkań, przez darmowe,
publiczne API Bundesagentur für Arbeit (niemiecki urząd pracy) - "Jobsuche".

WAŻNE: to NIE jest osobny, stały harmonogram - wyszukiwanie odpala się TYLKO dla
lokalizacji mieszkań, które już przeszły wszystkie inne filtry (main.py, po
apply_all_filters()). Dzięki temu nie szukamy pracy "w ogóle wokół Emmerich",
tylko konkretnie w pobliżu KAŻDEJ oferty, która faktycznie wygląda na dobrą.
Wyniki NIE wysyłają osobnych powiadomień (Telegram/Web Push) - tylko dropdown
"Praca w pobliżu" w modalu danej oferty na stronie.

API: https://github.com/bundesAPI/jobsuche-api (reverse-engineered z oficjalnej
apki mobilnej "Jobsuche" Bundesagentur für Arbeit, ale stabilne i szeroko używane
w społeczności - NIE wymaga zakładania konta/klucza, tylko wspólny, publicznie
znany nagłówek X-API-Key poniżej, dokładnie tak jak w oficjalnej apce).

ZWERYFIKOWANE na żywym przebiegu 20.09.2026: pierwsza wersja używała błędnej
ścieżki ".../pc/v4/app/jobs" (z dodatkowym segmentem "/app/"), co dawało
403 "No match found for request for url" na KAŻDYM zapytaniu (błąd routingu
API gateway, nie autoryzacji). Poprawna ścieżka to ".../pc/v4/jobs" - potwierdzona
niezależnie w oficjalnym przykładowym kodzie (api_example.py) i README repo
bundesAPI/jobsuche-api.

PO POPRAWCE ŚCIEŻKI 403 DALEJ WYSTĘPOWAŁ na kolejnym przebiegu (ten sam błąd
"No match found", teraz przeciwko już poprawnemu URL-owi z ?pav=false). Drugi
podejrzany: nagłówek User-Agent. Reszta scraperów w tym projekcie (Kleinanzeigen,
ImmoScout24) świadomie podszywa się pod zwykłą przeglądarkę desktopową przez
config.USER_AGENT - ale to API jest przeznaczone dla APKI MOBILNEJ, nie
przeglądarki, i bramka API najwyraźniej odrzuca ruch, który nie wygląda jak ta
apka (stąd "No match found for request" zamiast zwykłego 401/403 autoryzacji -
to brzmi jak reguła WAF/gateway po User-Agent, nie jak błąd autoryzacji klucza).
Dlatego JOBS_API_USER_AGENT poniżej NIE używa już config.USER_AGENT, tylko
osobnego, dedykowanego stringa skopiowanego z oficjalnego api_example.py repo
bundesAPI/jobsuche-api: "Jobsuche/2.9.2 (de.arbeitsagentur.jobboerse; build:1077;
iOS 15.1.0)". Jeśli PO tej zmianie 403 nadal się powtarza na następnym przebiegu,
to oznacza że User-Agent NIE był (jedyną) przyczyną i trzeba sprawdzić surową
odpowiedź ręcznie (np. curl -H "X-API-Key: jobboerse-jobsuche" -H "User-Agent:
Jobsuche/2.9.2 (de.arbeitsagentur.jobboerse; build:1077; iOS 15.1.0)"
"https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs?was=Lagerhelfer&wo=Kleve&umkreis=30&pav=false")
z komputera użytkownika (nie z chmurowego środowiska - IP centrów danych bywa
tu też blokowane, jak przy ImmoScout24) - zobacz dokładny kod odpowiedzi i treść.

Nazwy pól w odpowiedzi JSON (beruf/arbeitgeber/arbeitsort.ort/externeUrl) wciąż
nie były ręcznie zweryfikowane na żywej, udanej odpowiedzi - jeśli dropdown
dalej jest pusty mimo że w logach nie ma już błędów 403, dopasuj _parse_job()
do realnych nazw pól z rzeczywistej odpowiedzi.
"""
import time
import logging
from typing import Dict, List, Optional

import requests

import config

logger = logging.getLogger("immo-bot")

JOBS_API_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"

# Ten string to DOKŁADNA wartość User-Agent oficjalnej apki mobilnej "Jobsuche",
# skopiowana z api_example.py w repo bundesAPI/jobsuche-api. Celowo NIE używamy
# tu config.USER_AGENT (to desktopowy Chrome, do podszywania się pod przeglądarkę
# w innych scraperach) - to API jest zrobione dla apki mobilnej i bramka API
# prawdopodobnie odrzuca ruch z innym User-Agentem (patrz docstring modułu).
JOBS_API_USER_AGENT = "Jobsuche/2.9.2 (de.arbeitsagentur.jobboerse; build:1077; iOS 15.1.0)"

JOBS_API_HEADERS = {
    # Publicznie znany, wspólny klucz używany przez oficjalną apkę mobilną - NIE
    # jest to sekret użytkownika, nie trzeba niczego zakładać/generować.
    "X-API-Key": "jobboerse-jobsuche",
    "User-Agent": JOBS_API_USER_AGENT,
}

# Brak udokumentowanego limitu zapytań, ale szanujemy serwer - mały odstęp między
# wywołaniami (te same słowa kluczowe lecą raz na każdą UNIKALNĄ lokalizację
# mieszkania w danym przebiegu, więc to i tak niewiele zapytań na przebieg).
_MIN_INTERVAL_SECONDS = 0.8
_last_call = 0.0


def _throttled_get(params: dict) -> Optional[dict]:
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < _MIN_INTERVAL_SECONDS:
        time.sleep(_MIN_INTERVAL_SECONDS - elapsed)

    try:
        resp = requests.get(
            JOBS_API_URL,
            params=params,
            headers=JOBS_API_HEADERS,
            timeout=config.REQUEST_TIMEOUT_SECONDS,
        )
        _last_call = time.time()
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning(
            "Jobsuche API: zapytanie zawiodło (%s, params=%s) - pomijam ten fragment wyszukiwania pracy.",
            exc, params,
        )
        return None


def _parse_job(raw: dict) -> Optional[Dict]:
    """Zamienia jeden surowy wpis z 'stellenangebote' na prosty słownik do JSON-a
    strony. Zwraca None jeśli brakuje minimum (refnr I externeUrl jednocześnie -
    wtedy nie mamy dokąd zalinkować)."""
    try:
        refnr = raw.get("refnr")
        title = raw.get("beruf") or "(bez tytułu)"
        employer = raw.get("arbeitgeber") or "?"
        arbeitsort = raw.get("arbeitsort") or {}
        ort = arbeitsort.get("ort") or ""

        url = raw.get("externeUrl") or None
        if not url and refnr:
            # Publiczna wyszukiwarka Bundesagentur przyjmuje refnr bezpośrednio w URL-u.
            url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
        if not url:
            return None

        return {
            "refnr": refnr,
            "titel": title,
            "pracodawca": employer,
            "miejscowosc": ort,
            "link": url,
            "opublikowano": raw.get("aktuelleVeroeffentlichungsdatum"),
        }
    except (AttributeError, TypeError):
        return None


def search_jobs_near(location_text: str) -> List[Dict]:
    """
    Szuka ofert pracy w promieniu config.JOB_SEARCH_RADIUS_KM od location_text,
    po wszystkich słowach z config.JOB_SEARCH_KEYWORDS, scalone i odduplikowane
    po numerze referencyjnym (refnr). Zwraca listę słowników gotowych do
    zapisania w Listing.nearby_jobs / JSON-ie strony ("OfertyPracy").

    Jeśli JOB_SEARCH_ENABLED=False, location_text jest puste, albo WSZYSTKIE
    zapytania do API zawiodą (np. brak internetu) - zwraca po prostu pustą listę,
    nigdy nie wywala reszty przebiegu (tak samo jak inne integracje w tym projekcie).
    """
    if not config.JOB_SEARCH_ENABLED or not location_text:
        return []

    seen_refnr = set()
    results: List[Dict] = []

    for keyword in config.JOB_SEARCH_KEYWORDS:
        params = {
            "wo": location_text,
            "umkreis": config.JOB_SEARCH_RADIUS_KM,
            "was": keyword,
            "arbeitszeit": ";".join(config.JOB_SEARCH_EMPLOYMENT_TYPES),
            "angebotsart": 1,  # 1 = zwykła praca (nie samozatrudnienie/szkolenie/praktyka)
            "size": config.JOB_SEARCH_MAX_RESULTS_PER_KEYWORD,
            "page": 1,
            "pav": "false",  # wyklucz agencje pośrednictwa pracy - tak jak w oficjalnych przykładach API
        }
        data = _throttled_get(params)
        if not data:
            continue

        for raw in data.get("stellenangebote", []):
            refnr = raw.get("refnr")
            if refnr and refnr in seen_refnr:
                continue
            job = _parse_job(raw)
            if not job:
                continue
            if refnr:
                seen_refnr.add(refnr)
            results.append(job)

    return results
