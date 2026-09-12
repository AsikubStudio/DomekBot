"""
Scraper dla kleinanzeigen.de (dawniej eBay Kleinanzeigen).

Zwykle najłatwiejszy portal do scrapowania z tej czwórki - lżejsza ochrona
anty-bot, prostszy HTML. Wyszukiwanie po promieniu wspiera parametr &radius=
i lokalizację przez kod pocztowy w &locationStr=/&locationId=.
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


def _build_search_url(page: int = 1) -> str:
    # Kategoria 203 = Wohnungen (Mieten) w Kleinanzeigen
    price_max = int(config.MAX_PRICE_EUR) if config.MAX_PRICE_EUR else ""
    page_suffix = f"seite:{page}/" if page > 1 else ""
    url = (
        f"{BASE_URL}/s-wohnung-mieten/{page_suffix}"
        f"preis::{price_max}/"
        f"c203l{config.CENTER_PLZ}r{config.MAX_DISTANCE_KM}"
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
        cards = soup.select("article.aditem")
        if not cards:
            logger.info("Kleinanzeigen: 0 kart na stronie %s - koniec wyników lub zmieniony HTML.", page)
            break

        for card in cards:
            link_el = card.select_one("a.ellipsis")
            price_el = card.select_one(".aditem-main--middle--price-shipping--price")
            location_el = card.select_one(".aditem-main--top--left")
            desc_el = card.select_one(".aditem-main--middle--description")
            attrs_text = card.get_text(" ", strip=True)

            if not link_el:
                continue

            href = link_el.get("href", "")
            full_url = href if href.startswith("http") else BASE_URL + href

            listing = Listing(
                source="Kleinanzeigen",
                title=link_el.get_text(strip=True),
                url=full_url,
                price_eur=parse_price(price_el.get_text(strip=True) if price_el else attrs_text),
                rooms=parse_rooms(attrs_text),
                size_sqm=parse_size(attrs_text),
                location_text=location_el.get_text(strip=True) if location_el else config.CENTER_CITY,
                has_bathroom=guess_bathroom(attrs_text),
                has_kitchen=guess_kitchen(attrs_text),
                raw_description=desc_el.get_text(strip=True) if desc_el else attrs_text,
            )
            results.append(listing)

    logger.info("Kleinanzeigen: znaleziono %d ofert (przed filtrowaniem).", len(results))
    return results
