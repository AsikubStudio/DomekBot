"""
Scraper dla wg-gesucht.de

Uwaga: WG-Gesucht jest głównie znany z pokoi we wspólnych mieszkaniach (WG),
ale ma też kategorię całych mieszkań na wynajem ("1-Zimmer-Wohnungen" itd. -
w praktyce filtrujemy po pokojach tak jak wszędzie indziej). Część treści bywa
ukrywana za loginem/paywallem (ograniczona liczba wyników bez konta) - to
ograniczenie samego portalu, nie błąd scrapera.
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

BASE_URL = "https://www.wg-gesucht.de"


def _build_search_url(page: int = 0) -> str:
    # 0 = WG, 1 = 1-Zimmer-Wohnung, 2 = Wohnung (kategoria "cała mieszkanie")
    # req_rMax w km promień, offer_filter na miasto/PLZ
    url = (
        f"{BASE_URL}/wg-zimmer-und-wohnungen-in-Emmerich-am-Rhein.html"
        f"?offer_filter=1&city_id=0&sort_order=0"
        f"&noDeact=1&categories%5B%5D=2"
        f"&rMax={config.MAX_DISTANCE_KM}"
        f"&rent_types%5B%5D=2"
        f"&pagination={page}"
    )
    return url


def search() -> List[Listing]:
    session = make_session()
    results: List[Listing] = []

    for page in range(0, config.MAX_PAGES_PER_SITE):
        url = _build_search_url(page)
        html = polite_get(session, url)
        if not html:
            break

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("div.wgg_card, div.offer_list_item")
        if not cards:
            logger.info("WG-Gesucht: 0 kart na stronie %s - koniec wyników, login-wall, lub zmieniony HTML.", page)
            break

        for card in cards:
            link_el = card.select_one("a.detailansicht")
            title_el = card.select_one("h3, .truncate_title")
            price_el = card.select_one(".col-xs-3 b, .middle b")
            attrs_text = card.get_text(" ", strip=True)

            if not link_el:
                continue

            href = link_el.get("href", "")
            full_url = href if href.startswith("http") else BASE_URL + "/" + href.lstrip("/")

            listing = Listing(
                source="WG-Gesucht",
                title=title_el.get_text(strip=True) if title_el else "(bez tytułu)",
                url=full_url,
                price_eur=parse_price(price_el.get_text(strip=True) if price_el else attrs_text),
                rooms=parse_rooms(attrs_text),
                size_sqm=parse_size(attrs_text),
                location_text=config.CENTER_CITY,
                has_bathroom=guess_bathroom(attrs_text),
                has_kitchen=guess_kitchen(attrs_text),
                raw_description=attrs_text,
            )
            results.append(listing)

    logger.info("WG-Gesucht: znaleziono %d ofert (przed filtrowaniem).", len(results))
    return results
