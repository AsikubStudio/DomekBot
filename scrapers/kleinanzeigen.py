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
import re
from typing import List

from bs4 import BeautifulSoup

import config
from models import Listing
from scrapers.base import (
    make_session, polite_get, parse_price, parse_rooms, parse_size,
    guess_bathroom, guess_kitchen, extract_image_url,
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
    cards = soup.select("article[data-adid]")
    listings = []

    for card in cards:
        href = card.get("data-href")
        if not href:
            link_el = card.select_one("h3 a")
            href = link_el.get("href") if link_el else None
        if not href:
            continue

        title_el = card.select_one("h3 a")
        price_el = card.select_one("p.my-xsmall.text-title3.font-strong.text-secondary")
        meta_el = card.select_one("p.font-strong.text-onSurfaceSubdued")  # np. "70 m² · 2 Zi."
        desc_el = card.select_one("p.mb-xsmall.text-bodyRegular.text-onSurfaceSubdued")
        location_container = card.select_one("div.text-onSurfaceNonessential")

        meta_text = meta_el.get_text(" ", strip=True) if meta_el else ""
        desc_text = desc_el.get_text(" ", strip=True) if desc_el else ""

        location_text = slug.replace("-", " ")
        distance_km = None
        if location_container:
            spans = location_container.select("span")
            if spans:
                location_text = spans[0].get_text(strip=True)
            if len(spans) > 1:
                dist_match = re.search(r"(\d+(?:[.,]\d+)?)", spans[1].get_text())
                if dist_match:
                    distance_km = float(dist_match.group(1).replace(",", "."))

        full_url = href if href.startswith("http") else BASE_URL + href

        listings.append(Listing(
            source="Kleinanzeigen",
            title=title_el.get_text(strip=True) if title_el else "(bez tytułu)",
            url=full_url,
            price_eur=parse_price(price_el.get_text(strip=True) if price_el else meta_text),
            rooms=parse_rooms(meta_text),
            size_sqm=parse_size(meta_text),
            location_text=location_text,
            distance_km=distance_km,  # Kleinanzeigen sam podaje odległość od centrum wyszukiwania
            has_bathroom=guess_bathroom(desc_text),
            has_kitchen=guess_kitchen(desc_text),
            raw_description=desc_text,
            image_url=extract_image_url(card, BASE_URL),
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
