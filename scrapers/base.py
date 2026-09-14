"""
Wspólne narzędzia dla wszystkich scraperów portali.

WAŻNE: portale nieruchomości regularnie zmieniają strukturę HTML i selektory CSS.
Jeśli scraper przestanie zwracać wyniki, najpierw sprawdź (F12 w przeglądarce na
stronie wyników wyszukiwania) czy selektory w danym pliku scrapers/<portal>.py
nadal pasują do aktualnego HTML - to najczęstsza przyczyna "0 wyników".
"""
import json
import os
import re
import time
import logging
from typing import Callable, Dict, List, Optional

import requests

import config
from models import Listing

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


def extract_image_url(card, base_url: str = "") -> Optional[str]:
    """
    Znajduje URL zdjęcia głównego w karcie wyniku wyszukiwania (BeautifulSoup Tag).

    Portale ładują zdjęcia leniwie (lazy-loading), więc prawdziwy URL częściej
    siedzi w atrybucie data-src/data-imgsrc niż w src (który bywa 1x1 placeholderem
    albo data: URI zanim JS go podmieni) - stąd taka kolejność sprawdzania.

    NIE ZWERYFIKOWANE jeszcze na żywym HTML-u każdego portalu (podobnie jak inne
    selektory w tym projekcie) - jeśli zdjęcia nie pojawią się na stronie mimo że
    oferty się ładują, wyślij outerHTML jednej karty żeby dopracować tę funkcję.
    W najgorszym wypadku po prostu zwraca None, a strona pokazuje ikonę zastępczą
    zamiast połamanego obrazka - nic się nie wywala.
    """
    if card is None:
        return None
    img = card.select_one("img")
    if img is None:
        return None

    for attr in ("data-src", "data-imgsrc", "src"):
        value = img.get(attr)
        if value and not value.startswith("data:"):
            return value if value.startswith("http") else base_url + value

    for attr in ("data-srcset", "srcset"):
        srcset = img.get(attr)
        if srcset:
            first = srcset.split(",")[0].strip().split(" ")[0]
            if first and not first.startswith("data:"):
                return first if first.startswith("http") else base_url + first

    return None


# ---------------------------------------------------------------------------
# Szczegoly oferty (galeria zdjec + czynsz z mediami) - wymagaja wejscia na
# PODSTRONE pojedynczej oferty, nie tylko listy wynikow wyszukiwania. Zobacz
# config.FETCH_LISTING_DETAILS / config.MAX_DETAIL_FETCHES_PER_RUN.
# ---------------------------------------------------------------------------

def load_cached_details(source: str, path: Optional[str] = None) -> Dict[str, dict]:
    """
    Czyta juz opublikowany docs/data/latest.json i zwraca {url: {"images": [...],
    "warm_rent": float|None, "description": str}} dla ofert DANEGO portalu, ktore juz
    maja te dane wypelnione z poprzedniego przebiegu. Dzieki temu nie odpytujemy
    podstrony oferty ponownie dla czegos co juz znamy - tylko dla naprawde nowych ofert.

    Bezpieczne w uzyciu nawet jesli plik jeszcze nie istnieje (np. pierwsze
    uruchomienie) albo jest uszkodzony - wtedy po prostu zwraca pusty slownik
    (wszystko trafi do "nowych" i zostanie pobrane, z zachowaniem limitu
    config.MAX_DETAIL_FETCHES_PER_RUN).
    """
    path = path or config.PUBLISH_JSON_PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("load_cached_details: nie udało się wczytać %s (%s).", path, exc)
        return {}

    cache: Dict[str, dict] = {}
    for row in data.get("listings", []):
        if row.get("Portal") != source:
            continue
        url = row.get("Link")
        if not url:
            continue
        images = row.get("Zdjęcia") or []
        warm_rent = row.get("Czynsz z mediami (€)")
        description = row.get("Opis") or ""
        if description:
            cache[url] = {"images": images, "warm_rent": warm_rent, "description": description}
    return cache


def enrich_listings_with_details(
    listings: List[Listing],
    source: str,
    fetch_detail_fn: Callable[[Listing], Optional[dict]],
    max_fetches: Optional[int] = None,
    force_refresh: bool = False,
) -> None:
    """
    Wzbogaca liste ofert (IN PLACE - modyfikuje liste `listings`, w tym MOZE Z NIEJ
    USUWAC oferty wykryte jako dezaktywowane) o galerie zdjec, czynsz z mediami,
    pelny opis oferty oraz status dezaktywacji. Dla kazdej oferty:
      1. jesli force_refresh=False i mamy juz jej dane z poprzedniego przebiegu
         (patrz load_cached_details) - uzywamy ich, BEZ zadnego dodatkowego
         requestu do portalu,
      2. w przeciwnym razie (force_refresh=True, albo brak cache) wywoluje
         fetch_detail_fn(listing), ktore powinno zwrocic
         {"images": [...], "warm_rent": float|None, "description": str, "deactivated": bool}
         (albo None/rzucic wyjatek przy bledzie - wtedy oferta po prostu zostaje
         bez tych danych na razie).

    force_refresh=True (uzywane przez ImmoScout24 lokalnie) POMIJA cache calkowicie
    i limit max_fetches - kazda oferta z `listings` dostaje swiezy fetch_detail_fn()
    przy KAZDYM przebiegu. To kosztuje wiecej requestow i czasu, ale jest bezpieczne
    dla scrapera dzialajacego lokalnie (bez limitu czasu jak w GitHub Actions).

    Oferty, dla ktorych fetch_detail_fn() zwroci {"deactivated": True} (wykryte
    np. po znaczniku "Deactivated N days ago" na podstronie oferty), sa USUWANE
    z listy `listings` PO ZAKONCZENIU petli - nie trafiaja wiec do publikowanego
    docs/data/latest.json.

    fetch_detail_fn jest specyficzne dla portalu (inny klient HTTP / przegladarka),
    dlatego jest przekazywane przez wywolujacego, a nie zaszyte tutaj na sztywno.

    Respektuje config.FETCH_LISTING_DETAILS (globalny wylacznik) oraz - gdy
    force_refresh=False - limit config.MAX_DETAIL_FETCHES_PER_RUN - nadmiarowe
    NOWE oferty (te bez cache) po prostu czekaja do nastepnego przebiegu, zamiast
    zalewac portal requestami.
    """
    if not getattr(config, "FETCH_LISTING_DETAILS", True):
        return

    cached = {} if force_refresh else load_cached_details(source)
    if max_fetches is None:
        max_fetches = len(listings) if force_refresh else getattr(config, "MAX_DETAIL_FETCHES_PER_RUN", 15)

    cached_count = 0
    fetched_count = 0
    skipped_count = 0
    deactivated_urls = set()

    for listing in listings:
        cached_entry = None if force_refresh else cached.get(listing.url)
        if cached_entry:
            listing.images = cached_entry.get("images") or []
            listing.warm_rent_eur = cached_entry.get("warm_rent")
            listing.full_description = cached_entry.get("description") or ""
            cached_count += 1
            continue

        if fetched_count >= max_fetches:
            skipped_count += 1
            continue  # limit na ten przebieg osiagniety - poczeka do nastepnego razu

        details = None
        try:
            details = fetch_detail_fn(listing)
        except Exception as exc:
            logger.warning("%s: błąd pobierania szczegółów oferty %s: %s", source, listing.url, exc)
        fetched_count += 1

        if details:
            listing.images = details.get("images") or []
            listing.warm_rent_eur = details.get("warm_rent")
            listing.full_description = details.get("description") or ""
            if details.get("deactivated"):
                deactivated_urls.add(listing.url)

    if deactivated_urls:
        listings[:] = [l for l in listings if l.url not in deactivated_urls]
        logger.info(
            "%s: usunięto %d dezaktywowaną/dezaktywowane ofertę/oferty (znacznik \"Deactivated\" "
            "na podstronie oferty): %s",
            source, len(deactivated_urls), ", ".join(sorted(deactivated_urls)),
        )

    logger.info(
        "%s: szczegóły ofert (zdjęcia/czynsz z mediami/opis) - %d z pamięci, %d nowo pobranych, "
        "%d odłożonych do następnego przebiegu (limit: %d).",
        source, cached_count, fetched_count, skipped_count, max_fetches,
    )
