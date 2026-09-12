"""
Scraper dla kleinanzeigen.de (dawniej eBay Kleinanzeigen)

WERSJA 2 - poprawiona na podstawie realnych URLi z ręcznego wyszukiwania:

    https://www.kleinanzeigen.de/s-wohnung-mieten/emmerich-am-rhein/preis::550/
    c203l1395r15+wohnung_mieten.zimmer_d:2%2C

Kluczowy wniosek: lokalizacja w Kleinanzeigen to NIE kod pocztowy tylko wewnętrzne
ID (`l1395` = Emmerich am Rhein, `l1122` = Kleve) - stąd 0 wyników w wersji 1,
gdzie użyłem PLZ zamiast tego ID. Lista w config.KLEINANZEIGEN_LOCATIONS.

Struktura URL: /s-wohnung-mieten/{page}{slug}/preis::{max}/c203l{id}r{radius}+wohnung_mieten.zimmer_d:{min},{max}
- c203 = kategoria "Wohnungen mieten"
- r{radius} = promień w km od danego location_id
- zimmer_d:{min}, = filtr liczby pokoi (min, otwarty zakres); dla dokładnie 2
  pokoi używamy "2,2"

Selektory HTML kart ogłoszeń NIE zostały jeszcze zweryfikowane na żywym HTML-u -
wyślij outerHTML jednej karty żeby to dopracować (art.aditem to najlepsza
dotychczasowa hipoteza, ale mogła się zmienić).
"""
import logging
from typing import List

from bs4 import BeautifulSoup

import config
from models import Listing
from scrapers.base import (
    make_session, polite_get, parse_price, parse_rooms, parse_size,
    guess_bathroom, guess_kitchen,
)

logger = logging.getLogger("immo-bot")

BASE_URL = "https://www.kleinanzeigen.de"


def _build_search_url(slug: str, location_id: str, radius_km: int, page: int = 1) -> str:
    price_max = int(config.MAX_PRICE_EUR) if config.MAX_PRICE_EUR else ""
    rooms_min = int(config.MIN_ROOMS) if config.MIN_ROOMS else ""
    rooms_max = int(config.MAX_ROOMS) if config.MAX_ROOMS else ""
    page_prefix = f"seite:{page}/" if page > 1 else ""

    url = (
        f"{BASE_URL}/s-wohnung-mieten/{page_prefix}{slug}"
        f"/preis::{price_max}"
        f"/c203l{location_id}r{radius_km}"
        f"+wohnung_mieten.zimmer_d:{rooms_min}%2C{rooms_max}"
    )
    return url


def _parse_cards(html: str, slug: str) -> List[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    # TODO: zweryfikować selektor na realnym HTML-u (wyślij outerHTML karty ogłoszenia)
    cards = soup.select("article.aditem")
    listings = []

    for card in cards:
        link_el = card.select_one("a.ellipsis")
        if not link_el:
            continue

        price_el = card.select_one(".aditem-main--middle--price-shipping--price")
        location_el = card.select_one(".aditem-main--top--left")
        desc_el = card.select_one(".aditem-main--middle--description")
        attrs_text = card.get_text(" ", strip=True)

        href = link_el.get("href", "")
        full_url = href if href.startswith("http") else BASE_URL + href

        listings.append(Listing(
            source="Kleinanzeigen",
            title=link_el.get_text(strip=True),
            url=full_url,
            price_eur=parse_price(price_el.get_text(strip=True) if price_el else attrs_text),
            rooms=parse_rooms(attrs_text),
            size_sqm=parse_size(attrs_text),
            location_text=location_el.get_text(strip=True) if location_el else slug.replace("-", " "),
            has_bathroom=guess_bathroom(attrs_text),
            has_kitchen=guess_kitchen(attrs_text),
            raw_description=desc_el.get_text(strip=True) if desc_el else attrs_text,
        ))

    return listings


def search() -> List[Listing]:
    session = make_session()
    results: List[Listing] = []
    seen_urls = set()

    for loc in config.KLEINANZEIGEN_LOCATIONS:
        for page in range(1, config.MAX_PAGES_PER_SITE + 1):
            url = _build_search_url(loc["slug"], loc["location_id"], loc["radius_km"], page)
            html = polite_get(session, url)
            if not html:
                break

            listings = _parse_cards(html, loc["slug"])
            if not listings:
                logger.info("Kleinanzeigen [%s]: 0 kart na stronie %s - koniec lub zmieniony HTML.",
                            loc["slug"], page)
                break

            for listing in listings:
                if listing.url not in seen_urls:
                    seen_urls.add(listing.url)
                    results.append(listing)

    logger.info("Kleinanzeigen: znaleziono %d ofert łącznie (przed filtrowaniem).", len(results))
    return results
