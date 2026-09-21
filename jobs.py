"""
Wyszukiwanie ofert pracy w pobliĹĽu ZNALEZIONYCH ofert mieszkaĹ„, przez darmowe,
publiczne API Bundesagentur fĂĽr Arbeit (niemiecki urzÄ…d pracy) - "Jobsuche".

WAĹ»NE: to NIE jest osobny, staĹ‚y harmonogram - wyszukiwanie odpala siÄ™ TYLKO dla
lokalizacji mieszkaĹ„, ktĂłre juĹĽ przeszĹ‚y wszystkie inne filtry (main.py, po
apply_all_filters()). DziÄ™ki temu nie szukamy pracy "w ogĂłle wokĂłĹ‚ Emmerich",
tylko konkretnie w pobliĹĽu KAĹ»DEJ oferty, ktĂłra faktycznie wyglÄ…da na dobrÄ….
Wyniki NIE wysyĹ‚ajÄ… osobnych powiadomieĹ„ (Telegram/Web Push) - tylko dropdown
"Praca w pobliĹĽu" w modalu danej oferty na stronie.

API: https://github.com/bundesAPI/jobsuche-api (reverse-engineered z oficjalnej
apki mobilnej "Jobsuche" Bundesagentur fĂĽr Arbeit, ale stabilne i szeroko uĹĽywane
w spoĹ‚ecznoĹ›ci - NIE wymaga zakĹ‚adania konta/klucza, tylko wspĂłlny, publicznie
znany nagĹ‚Ăłwek X-API-Key poniĹĽej, dokĹ‚adnie tak jak w oficjalnej apce).

ZWERYFIKOWANE na ĹĽywym przebiegu 20.09.2026: pierwsza wersja uĹĽywaĹ‚a bĹ‚Ä™dnej
Ĺ›cieĹĽki ".../pc/v4/app/jobs" (z dodatkowym segmentem "/app/"), co dawaĹ‚o
403 "No match found for request for url" na KAĹ»DYM zapytaniu (bĹ‚Ä…d routingu
API gateway, nie autoryzacji). Poprawna Ĺ›cieĹĽka to ".../pc/v4/jobs" - potwierdzona
niezaleĹĽnie w oficjalnym przykĹ‚adowym kodzie (api_example.py) i README repo
bundesAPI/jobsuche-api.

PO POPRAWCE ĹšCIEĹ»KI 403 DALEJ WYSTÄPOWAĹ na kolejnym przebiegu (ten sam bĹ‚Ä…d
"No match found", teraz przeciwko juĹĽ poprawnemu URL-owi z ?pav=false). Drugi
podejrzany: nagĹ‚Ăłwek User-Agent. Reszta scraperĂłw w tym projekcie (Kleinanzeigen,
ImmoScout24) Ĺ›wiadomie podszywa siÄ™ pod zwykĹ‚Ä… przeglÄ…darkÄ™ desktopowÄ… przez
config.USER_AGENT - ale to API jest przeznaczone dla APKI MOBILNEJ, nie
przeglÄ…darki, i bramka API najwyraĹşniej odrzuca ruch, ktĂłry nie wyglÄ…da jak ta
apka (stÄ…d "No match found for request" zamiast zwykĹ‚ego 401/403 autoryzacji -
to brzmi jak reguĹ‚a WAF/gateway po User-Agent, nie jak bĹ‚Ä…d autoryzacji klucza).
Dlatego JOBS_API_USER_AGENT poniĹĽej NIE uĹĽywa juĹĽ config.USER_AGENT, tylko
osobnego, dedykowanego stringa skopiowanego z oficjalnego api_example.py repo
bundesAPI/jobsuche-api: "Jobsuche/2.9.2 (de.arbeitsagentur.jobboerse; build:1077;
iOS 15.1.0)". JeĹ›li PO tej zmianie 403 nadal siÄ™ powtarza na nastÄ™pnym przebiegu,
to oznacza ĹĽe User-Agent NIE byĹ‚ (jedynÄ…) przyczynÄ… i trzeba sprawdziÄ‡ surowÄ…
odpowiedĹş rÄ™cznie (np. curl -H "X-API-Key: jobboerse-jobsuche" -H "User-Agent:
Jobsuche/2.9.2 (de.arbeitsagentur.jobboerse; build:1077; iOS 15.1.0)"
"https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs?was=Lagerhelfer&wo=Kleve&umkreis=30&pav=false")
z komputera uĹĽytkownika (nie z chmurowego Ĺ›rodowiska - IP centrĂłw danych bywa
tu teĹĽ blokowane, jak przy ImmoScout24) - zobacz dokĹ‚adny kod odpowiedzi i treĹ›Ä‡.

Nazwy pĂłl w odpowiedzi JSON (beruf/arbeitgeber/arbeitsort.ort/externeUrl) wciÄ…ĹĽ
nie byĹ‚y rÄ™cznie zweryfikowane na ĹĽywej, udanej odpowiedzi - jeĹ›li dropdown
dalej jest pusty mimo ĹĽe w logach nie ma juĹĽ bĹ‚Ä™dĂłw 403, dopasuj _parse_job()
do realnych nazw pĂłl z rzeczywistej odpowiedzi.
"""
import time
import logging
from typing import Dict, List, Optional

import requests

import config

logger = logging.getLogger("immo-bot")

JOBS_API_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"

# Ten string to DOKĹADNA wartoĹ›Ä‡ User-Agent oficjalnej apki mobilnej "Jobsuche",
# skopiowana z api_example.py w repo bundesAPI/jobsuche-api. Celowo NIE uĹĽywamy
# tu config.USER_AGENT (to desktopowy Chrome, do podszywania siÄ™ pod przeglÄ…darkÄ™
# w innych scraperach) - to API jest zrobione dla apki mobilnej i bramka API
# prawdopodobnie odrzuca ruch z innym User-Agentem (patrz docstring moduĹ‚u).
JOBS_API_USER_AGENT = "Jobsuche/2.9.2 (de.arbeitsagentur.jobboerse; build:1077; iOS 15.1.0)"

JOBS_API_HEADERS = {
    # Publicznie znany, wspĂłlny klucz uĹĽywany przez oficjalnÄ… apkÄ™ mobilnÄ… - NIE
    # jest to sekret uĹĽytkownika, nie trzeba niczego zakĹ‚adaÄ‡/generowaÄ‡.
    "X-API-Key": "jobboerse-jobsuche",
    "User-Agent": JOBS_API_USER_AGENT,
}

# Brak udokumentowanego limitu zapytaĹ„, ale szanujemy serwer - maĹ‚y odstÄ™p miÄ™dzy
# wywoĹ‚aniami (te same sĹ‚owa kluczowe lecÄ… raz na kaĹĽdÄ… UNIKALNÄ„ lokalizacjÄ™
# mieszkania w danym przebiegu, wiÄ™c to i tak niewiele zapytaĹ„ na przebieg).
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
            "Jobsuche API: zapytanie zawiodĹ‚o (%s, params=%s) - pomijam ten fragment wyszukiwania pracy.",
            exc, params,
        )
        return None


def _parse_job(raw: dict) -> Optional[Dict]:
    """Zamienia jeden surowy wpis z 'stellenangebote' na prosty sĹ‚ownik do JSON-a
    strony. Zwraca None jeĹ›li brakuje minimum (refnr I externeUrl jednoczeĹ›nie -
    wtedy nie mamy dokÄ…d zalinkowaÄ‡)."""
    try:
        refnr = raw.get("refnr")
        title = raw.get("beruf") or "(bez tytuĹ‚u)"
        employer = raw.get("arbeitgeber") or "?"
        arbeitsort = raw.get("arbeitsort") or {}
        ort = arbeitsort.get("ort") or ""

        url = raw.get("externeUrl") or None
        if not url and refnr:
            # Publiczna wyszukiwarka Bundesagentur przyjmuje refnr bezpoĹ›rednio w URL-u.
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
            "kraj": "DE",
        }
    except (AttributeError, TypeError):
        return None


def search_jobs_near(location_text: str) -> List[Dict]:
    """
    Szuka ofert pracy w promieniu config.JOB_SEARCH_RADIUS_KM od location_text,
    po wszystkich sĹ‚owach z config.JOB_SEARCH_KEYWORDS, scalone i odduplikowane
    po numerze referencyjnym (refnr). Zwraca listÄ™ sĹ‚ownikĂłw gotowych do
    zapisania w Listing.nearby_jobs / JSON-ie strony ("OfertyPracy").

    JeĹ›li JOB_SEARCH_ENABLED=False, location_text jest puste, albo WSZYSTKIE
    zapytania do API zawiodÄ… (np. brak internetu) - zwraca po prostu pustÄ… listÄ™,
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
            "angebotsart": 1,  # 1 = zwykĹ‚a praca (nie samozatrudnienie/szkolenie/praktyka)
            "size": config.JOB_SEARCH_MAX_RESULTS_PER_KEYWORD,
            "page": 1,
            "pav": "false",  # wyklucz agencje poĹ›rednictwa pracy - tak jak w oficjalnych przykĹ‚adach API
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