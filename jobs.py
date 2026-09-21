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

HISTORIA DEBUGOWANIA (żeby nie powtarzać prób w przyszłości):
1) Pierwsza wersja używała błędnej ścieżki ".../pc/v4/app/jobs" -> 403 "No match
   found for request for url" na każdym zapytaniu.
2) Zmiana na ".../pc/v4/jobs" (bez "/app/") - dalej 403 "No match found", teraz
   na "poprawionym" URL-u. Podejrzewaliśmy User-Agent (API jest dla apki mobilnej,
   nie przeglądarki) - zmiana User-Agenta na dokładny string z oficjalnej apki
   NIE pomogła, 403 wystąpił ponownie na kolejnym przebiegu.
3) Podejrzewaliśmy blokadę IP centrów danych (GitHub Actions), tak jak przy
   ImmoScout24 - PRZETESTOWANE I OBALONE: identyczny 403 wystąpił nawet przy
   zapytaniu z domowego IP użytkownika (curl -v z jego komputera).
4) OSTATECZNA PRZYCZYNA (potwierdzona 21.09.2026 żywym, udanym zapytaniem curl -v
   z komputera użytkownika): ".../pc/v4/jobs" to po prostu NIEISTNIEJĄCA ścieżka
   w obecnym API. Poprawna, oficjalna ścieżka (wg opublikowanej specyfikacji
   OpenAPI: https://jobsuche.api.bund.dev/openapi.yaml) to ".../pc/v6/jobs".
   Zapytanie na v6 z tymi samymi nagłówkami (X-API-Key + User-Agent apki mobilnej)
   zwróciło HTTP 200 OK z realnymi ofertami pracy.
5) Po przejściu na v6 okazało się, że realna struktura JSON-a odpowiedzi jest
   INNA niż zakładała pierwotna wersja tego pliku (patrz niżej) - to zostało
   poprawione w tej wersji _parse_job()/search_jobs_near() na podstawie
   faktycznej, zweryfikowanej odpowiedzi API, a nie dokumentacji/zgadywania.

RZECZYWISTA STRUKTURA ODPOWIEDZI /pc/v6/jobs (zweryfikowana na żywo):
- Lista ofert jest pod kluczem "ergebnisliste" (NIE "stellenangebote").
- Każda oferta ma m.in.:
    "referenznummer"        - numer referencyjny (NIE "refnr")
    "stellenangebotsTitel"  - tytuł oferty (np. "Lagerhelfer (m/w/d)")
    "hauptberuf"            - kategoria zawodu, zapasowo gdy brak tytułu
    "firma"                 - nazwa pracodawcy (NIE "arbeitgeber")
    "stellenlokationen"     - LISTA lokalizacji, każda ma "adresse" z polami
                              "ort", "plz", "strasse", "hausnummer", "region",
                              "land" (NIE płaski "arbeitsort.ort")
    "externeURL"            - link zewnętrzny, wielka litera "URL" (NIE "externeUrl")
    "datumErsteVeroeffentlichung" LUB "veroeffentlichungszeitraum": {"von": "..."}
                              - data publikacji (NIE "aktuelleVeroeffentlichungsdatum")
"""
import time
import logging
from typing import Dict, List, Optional

import requests

import config

logger = logging.getLogger("immo-bot")

JOBS_API_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"

# Ten string to DOKŁADNA wartość User-Agent oficjalnej apki mobilnej "Jobsuche",
# skopiowana z api_example.py w repo bundesAPI/jobsuche-api. Celowo NIE używamy
# tu config.USER_AGENT (to desktopowy Chrome, do podszywania się pod przeglądarkę
# w innych scraperach) - to API jest zrobione dla apki mobilnej. To NIE był
# faktyczny powód wcześniejszych błędów 403 (patrz docstring modułu, punkt 4),
# ale to wciąż poprawny, autentyczny nagłówek zgodny z oficjalną apką - zostaje.
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
    """Zamienia jeden surowy wpis z 'ergebnisliste' na prosty słownik do JSON-a
    strony. Zwraca None jeśli brakuje minimum (referenznummer I externeURL
    jednocześnie - wtedy nie mamy dokąd zalinkować)."""
    try:
        refnr = raw.get("referenznummer")
        title = raw.get("stellenangebotsTitel") or raw.get("hauptberuf") or "(bez tytułu)"
        employer = raw.get("firma") or "?"

        ort = ""
        lokalizacje = raw.get("stellenlokationen") or []
        if lokalizacje:
            adresse = lokalizacje[0].get("adresse") or {}
            ort = adresse.get("ort") or ""

        opublikowano = raw.get("datumErsteVeroeffentlichung")
        if not opublikowano:
            okres = raw.get("veroeffentlichungszeitraum") or {}
            opublikowano = okres.get("von")

        url = raw.get("externeURL") or None
        if not url and refnr:
            # Publiczna wyszukiwarka Bundesagentur przyjmuje referenznummer bezpośrednio w URL-u.
            url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
        if not url:
            return None

        return {
            "refnr": refnr,
            "titel": title,
            "pracodawca": employer,
            "miejscowosc": ort,
            "link": url,
            "opublikowano": opublikowano,
        }
    except (AttributeError, TypeError, IndexError):
        return None


def search_jobs_near(location_text: str) -> List[Dict]:
    """
    Szuka ofert pracy w promieniu config.JOB_SEARCH_RADIUS_KM od location_text,
    po wszystkich słowach z config.JOB_SEARCH_KEYWORDS, scalone i odduplikowane
    po numerze referencyjnym (referenznummer). Zwraca listę słowników gotowych do
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

        for raw in data.get("ergebnisliste", []):
            refnr = raw.get("referenznummer")
            if refnr and refnr in seen_refnr:
                continue
            job = _parse_job(raw)
            if not job:
                continue
            if refnr:
                seen_refnr.add(refnr)
            results.append(job)

    return results
