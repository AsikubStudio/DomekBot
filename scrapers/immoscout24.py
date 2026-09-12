"""
Scraper dla immobilienscout24.de

UWAGA: ImmoScout24 ma jedne z najmocniejszych zabezpieczeń anty-bot na rynku
niemieckim (Cloudflare / PerimeterX). Ten scraper może być blokowany (403) mimo
poprawnych selektorów - to nie zawsze błąd w kodzie. Jeśli regularnie dostajesz
403, rozważ:
  - dodanie losowego opóźnienia (zwiększ REQUEST_DELAY_SECONDS w config.py),
  - użycie Playwright/Selenium zamiast requests (prawdziwa przeglądarka),
  - traktowanie tego portalu jako "sprawdzam ręcznie raz na jakiś czas".

Selektory HTML poniżej są oparte o strukturę stosowaną przez ImmoScout24 - jeśli
przestaną działać, otwórz stronę wyników w przeglądarce, wciśnij F12 i sprawdź
aktualne klasy CSS dla kart ogłoszeń (szukaj czegoś w stylu 'result-list-entry').
"""
import logging
from typing import List
from urllib.parse import quote

from bs4 import BeautifulSoup

import config
from models import Listing
from scrapers.base import (
    make_session, polite_get, parse_price, parse_rooms, parse_size,
    guess_bathroom, guess_kitchen,
)

logger = logging.getLogger("immo-bot")

BASE_URL = "https://www.immobilienscout24.de"


def _build_search_url(page: int = 1) -> str:
    # Format geografii ImmoScout24 opiera się o slug regionu; dla Emmerich am Rhein
    # (Kreis Kleve, NRW) używamy promienia wokół kodu pocztowego, co jest bardziej
    # niezawodne niż zgadywanie sluga miasta.
    geo = quote(f"{config.CENTER_PLZ}")
    price_max = int(config.MAX_PRICE_EUR) if config.MAX_PRICE_EUR else ""
    rooms_min = config.MIN_ROOMS or ""
    url = (
        f"{BASE_URL}/Suche/radius/wohnung-mieten"
        f"?centerofsearchaddress={geo};;;;"
        f"&radius={config.MAX_DISTANCE_KM}"
        f"&price=-{price_max}"
        f"&numberofrooms={rooms_min}.0-"
        f"&pagenumber={page}"
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
        cards = soup.select("article, div.result-list-entry")
        if not cards:
            logger.info("ImmoScout24: 0 kart na stronie %s - koniec wyników lub zmieniony HTML.", page)
            break

        for card in cards:
            title_el = card.select_one("h5, .result-list-entry__brand-title, a[data-go-to-expose-button]")
            link_el = card.select_one("a[href*='/expose/']")
            price_el = card.select_one(".result-list-entry__criteria dd, [data-is='result-list-entry-primary-criterion']")
            attrs_text = card.get_text(" ", strip=True)

            if not link_el:
                continue

            href = link_el.get("href", "")
            full_url = href if href.startswith("http") else BASE_URL + href

            listing = Listing(
                source="ImmoScout24",
                title=title_el.get_text(strip=True) if title_el else "(bez tytułu)",
                url=full_url,
                price_eur=parse_price(price_el.get_text(strip=True) if price_el else attrs_text),
                rooms=parse_rooms(attrs_text),
                size_sqm=parse_size(attrs_text),
                location_text=config.CENTER_CITY,  # ImmoScout24 często nie pokazuje pełnego adresu na liście
                has_bathroom=guess_bathroom(attrs_text),
                has_kitchen=guess_kitchen(attrs_text),
                raw_description=attrs_text,
            )
            results.append(listing)

        if len(cards) == 0:
            break

    logger.info("ImmoScout24: znaleziono %d ofert (przed filtrowaniem).", len(results))
    return results
