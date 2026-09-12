"""
Scraper dla immowelt.de

Immowelt zwykle ma słabszą ochronę anty-bot niż ImmoScout24, ale też regularnie
zmienia strukturę HTML/klasy CSS (często generowane, np. 'css-xxxxx'). Jeśli
selektory poniżej przestaną łapać wyniki, sprawdź w F12 strukturę <article> lub
elementu z data-testid zawierającym 'serp-list-item' / podobne.
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

BASE_URL = "https://www.immowelt.de"


def _build_search_url(page: int = 1) -> str:
    price_max = int(config.MAX_PRICE_EUR) if config.MAX_PRICE_EUR else ""
    rooms_min = config.MIN_ROOMS or ""
    # geoRadius w km, geoWithoutRadius łączy centerpoint z promieniem
    url = (
        f"{BASE_URL}/liste/{config.CENTER_PLZ}"
        f"/wohnungen/mieten"
        f"?d={config.MAX_DISTANCE_KM}"
        f"&sp={page}"
        f"&prima={price_max}"
        f"&rmi={rooms_min}"
    )
    return url


def search() -> List[Listing]:
    session = make_session()
    results: List[Listing] = []

    for page in range(1, config.MAX_PAGES_PER_SITE + 1):
        url = _build_search_url(page)
        html = polite_get(session, url)
        if not html:
            break

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("[data-testid='serp-card-container'], article.EstateItem")
        if not cards:
            logger.info("Immowelt: 0 kart na stronie %s - koniec wyników lub zmieniony HTML.", page)
            break

        for card in cards:
            link_el = card.select_one("a[href*='/expose/']")
            title_el = card.select_one("h2, [data-testid='card-title']")
            price_el = card.select_one("[data-testid='cardmfe-price-testid']")
            location_el = card.select_one("[data-testid='cardmfe-description-box-address']")
            attrs_el = card.select_one("[data-testid='cardmfe-keyfacts-testid']")

            if not link_el:
                continue

            href = link_el.get("href", "")
            full_url = href if href.startswith("http") else BASE_URL + href
            attrs_text = attrs_el.get_text(" ", strip=True) if attrs_el else card.get_text(" ", strip=True)

            listing = Listing(
                source="Immowelt",
                title=title_el.get_text(strip=True) if title_el else "(bez tytułu)",
                url=full_url,
                price_eur=parse_price(price_el.get_text(strip=True) if price_el else attrs_text),
                rooms=parse_rooms(attrs_text),
                size_sqm=parse_size(attrs_text),
                location_text=location_el.get_text(strip=True) if location_el else config.CENTER_CITY,
                has_bathroom=guess_bathroom(attrs_text),
                has_kitchen=guess_kitchen(attrs_text),
                raw_description=attrs_text,
            )
            results.append(listing)

    logger.info("Immowelt: znaleziono %d ofert (przed filtrowaniem).", len(results))
    return results
