"""
Scraper dla immobilienscout24.de

WERSJA 2 - poprawiona na podstawie realnego URLa wygenerowanego przez ręczne
wyszukiwanie w przeglądarce:

    https://www.immobilienscout24.de/en/search/de/nordrhein-westfalen/
    kleve-kreis/emmerich-am-rhein/apartments-for-rent
    ?numberofrooms=-3.0&price=-770.0&pricetype=calculatedtotalrent&enteredFrom=result_list

Wniosek: promień (`radius=`) w URL dawał 401 Unauthorized - ImmoScout24 najwyraźniej
nie wspiera tego tak jak wcześniej zakładałem. Zamiast tego przeszukujemy listę
konkretnych miejscowości z config.IMMOSCOUT24_LOCATION_SLUGS (Emmerich + sąsiednie
gminy w promieniu ~15 km w stronę Kleve).

`numberofrooms=-3.0` w przykładzie znaczy "maks. 3 pokoje, bez minimum". Dla
dokładnie 2 pokoi używamy zakresu `2.0-2.0`.

`pricetype=calculatedtotalrent` = Warmmiete (czynsz z opłatami). Domyślnie (bez
tego parametru) ImmoScout24 filtruje po Kaltmiete - to chcemy, więc go pomijamy.
Jeśli jednak wolisz filtrować po Warmmiete, dodaj pricetype=calculatedtotalrent
do PARAMS_EXTRA poniżej.

Selektory HTML kart ogłoszeń NIE zostały jeszcze zweryfikowane na żywym HTML-u -
to następny krok (wyślij mi outerHTML jednej karty ogłoszenia z wyników).
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

BASE_URL = "https://www.immobilienscout24.de"
PARAMS_EXTRA = ""  # np. "&pricetype=calculatedtotalrent" jeśli wolisz filtrować po Warmmiete


def _build_search_url(location_slug: str, page: int = 1) -> str:
    rooms_min = config.MIN_ROOMS or ""
    rooms_max = config.MAX_ROOMS or ""
    price_max = int(config.MAX_PRICE_EUR) if config.MAX_PRICE_EUR else ""

    url = (
        f"{BASE_URL}/en/search/de/{location_slug}/apartments-for-rent"
        f"?numberofrooms={rooms_min}.0-{rooms_max}.0"
        f"&price=-{price_max}.0"
        f"{PARAMS_EXTRA}"
        f"&enteredFrom=result_list"
    )
    if page > 1:
        url += f"&pagenumber={page}"
    return url


def _parse_cards(html: str, location_slug: str) -> List[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    # TODO: zweryfikować selektor na realnym HTML-u (wyślij outerHTML karty ogłoszenia)
    cards = soup.select("article, div.result-list-entry, li[data-item='result']")
    listings = []

    for card in cards:
        link_el = card.select_one("a[href*='/expose/']")
        if not link_el:
            continue

        title_el = card.select_one("h5, [data-testid='result-list-entry-brand-title']")
        attrs_text = card.get_text(" ", strip=True)

        href = link_el.get("href", "")
        full_url = href if href.startswith("http") else BASE_URL + href

        listings.append(Listing(
            source="ImmoScout24",
            title=title_el.get_text(strip=True) if title_el else "(bez tytułu)",
            url=full_url,
            price_eur=parse_price(attrs_text),
            rooms=parse_rooms(attrs_text),
            size_sqm=parse_size(attrs_text),
            location_text=location_slug.split("/")[-1].replace("-", " "),
            has_bathroom=guess_bathroom(attrs_text),
            has_kitchen=guess_kitchen(attrs_text),
            raw_description=attrs_text,
        ))

    return listings


def search() -> List[Listing]:
    session = make_session()
    results: List[Listing] = []
    seen_urls = set()

    for location_slug in config.IMMOSCOUT24_LOCATION_SLUGS:
        for page in range(1, config.MAX_PAGES_PER_SITE + 1):
            url = _build_search_url(location_slug, page)
            html = polite_get(session, url)
            if not html:
                break

            listings = _parse_cards(html, location_slug)
            if not listings:
                logger.info("ImmoScout24 [%s]: 0 kart na stronie %s - koniec lub zmieniony HTML.",
                            location_slug.split("/")[-1], page)
                break

            for listing in listings:
                if listing.url not in seen_urls:
                    seen_urls.add(listing.url)
                    results.append(listing)

    logger.info("ImmoScout24: znaleziono %d ofert łącznie (przed filtrowaniem).", len(results))
    return results
