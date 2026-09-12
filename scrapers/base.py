"""
Wspólne narzędzia dla wszystkich scraperów portali.

WAŻNE: portale nieruchomości regularnie zmieniają strukturę HTML i selektory CSS.
Jeśli scraper przestanie zwracać wyniki, najpierw sprawdź (F12 w przeglądarce na
stronie wyników wyszukiwania) czy selektory w danym pliku scrapers/<portal>.py
nadal pasują do aktualnego HTML - to najczęstsza przyczyna "0 wyników".
"""
import re
import time
import logging
from typing import Optional

import requests

import config

logger = logging.getLogger("immo-bot")


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": config.USER_AGENT,
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    })
    return session


def make_impersonated_session():
    """
    Sesja HTTP, ktora podszywa sie pod prawdziwy "odcisk palca" TLS (JA3/JA4)
    przegladarki Chrome, przy pomocy curl_cffi. Zwykly `requests` ma inny
    handshake TLS niz prawdziwa przegladarka, co niektore portale (np. ImmoScout24)
    wykrywaja i blokuja (401/403) jeszcze zanim przeczytaja jakiekolwiek naglowki.

    Zwraca obiekt zgodny z API requests.Session (ma .get(), .headers, itd.),
    wiec dziala z ta sama funkcja polite_get() co zwykle sesje.
    """
    from curl_cffi import requests as curl_requests
    session = curl_requests.Session(impersonate="chrome124")
    session.headers.update({
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    })
    return session


def polite_get(session: requests.Session, url: str) -> Optional[str]:
    """GET z opóźnieniem i podstawową obsługą błędów. Zwraca None zamiast wywalać cały bot."""
    time.sleep(config.REQUEST_DELAY_SECONDS)
    try:
        resp = session.get(url, timeout=config.REQUEST_TIMEOUT_SECONDS)
        if resp.status_code == 403:
            logger.warning(f"403 Forbidden dla {url} - portal prawdopodobnie blokuje bota "
                            f"(anti-bot/Cloudflare). Rozważ ręczne sprawdzenie tej oferty.")
            return None
        resp.raise_for_status()
        # Wymuszamy wykrywanie kodowania na podstawie zawartosci (chardet/charset_normalizer),
        # bo niektore portale nie deklaruja poprawnie charsetu w naglowku HTTP, przez co polskie
        # i niemieckie znaki (ä, ö, ü, ß) laduja jako "mojibake" typu "GroÃe" zamiast "Große".
        # curl_cffi (uzywane dla ImmoScout24) moze nie miec .apparent_encoding, wiec robimy to
        # bezpiecznie i po cichu pomijamy jesli sie nie uda - lepszy "krzywy" tekst niz crash.
        try:
            resp.encoding = resp.apparent_encoding
        except AttributeError:
            pass
        return resp.text
    except requests.RequestException as exc:
        logger.warning(f"Błąd pobierania {url}: {exc}")
        return None
    except Exception as exc:
        # curl_cffi (ImmoScout24) zglasza wlasne typy wyjatkow, niekoniecznie
        # requests.RequestException - lapiemy szeroko, zeby nic nie wywalilo bota.
        logger.warning(f"Błąd pobierania {url}: {exc}")
        return None


def parse_price(text: str) -> Optional[float]:
    """'650 €' / '650,00 €' / 'VB 650€' -> 650.0"""
    if not text:
        return None
    cleaned = text.replace("\xa0", " ")
    match = re.search(r"([\d.]+)(?:,(\d+))?\s*€", cleaned)
    if not match:
        return None
    whole = match.group(1).replace(".", "")
    try:
        return float(whole)
    except ValueError:
        return None


def parse_rooms(text: str) -> Optional[float]:
    """'2 Zimmer' / '2,5 Zi.' -> 2.0 / 2.5"""
    if not text:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:Zimmer|Zi\.?)", text, re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def parse_size(text: str) -> Optional[float]:
    """'65 m²' -> 65.0"""
    if not text:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*m²", text)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def guess_bathroom(text: str) -> Optional[bool]:
    if not text:
        return None
    low = text.lower()
    if any(k in low for k in ["kein bad", "ohne bad", "badezimmer fehlt"]):
        return False
    if any(k in low for k in ["bad", "badezimmer", "dusche", "wanne"]):
        return True
    return None


def guess_kitchen(text: str) -> Optional[bool]:
    if not text:
        return None
    low = text.lower()
    if any(k in low for k in ["ohne küche", "keine küche", "küche fehlt"]):
        return False
    if any(k in low for k in ["küche", "einbauküche", "ebk"]):
        return True
    return None