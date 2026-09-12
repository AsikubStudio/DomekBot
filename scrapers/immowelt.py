"""
Scraper dla immowelt.de

WERSJA 2 - przepisana na podstawie realnego fragmentu HTML z wyników wyszukiwania:

    <a href="https://www.immowelt.de/expose/..." title="Wohnung zur Miete -
    Emmerich am Rhein - 550&nbsp;€ - 3 Zimmer, 70 m², EG, frei ab 01.10.2026"
    data-testid="card-mfe-covering-link-testid" ...></a>

Kluczowy wniosek: Immowelt umieszcza WSZYSTKIE kluczowe dane (typ, miasto, cena,
pokoje, metraż, piętro, dostępność) w atrybucie `title` jednego linku
("covering link" - przezroczysty link nałożony na całą kartę). To dużo bardziej
niezawodne niż poleganie na klasach CSS w stylu `css-w5uu0r`, które Immowelt
zmienia przy każdym redeployu frontendu. Dlatego NIE szukamy już kontenera karty -
wystarczy zebrać wszystkie takie linki ze strony.

Format tekstu w title (rozdzielany " - "):
    "{typ nieruchomości} - {miejscowość} - {cena} € - {pokoje} Zimmer, {metraż} m², ..."

UWAGA - brak promienia (radius) w URL: przykładowy link użytkownika
(locations=AD08DE2123&numberOfRoomsMax=3&priceMax=770...) nie zawiera parametru
promienia. Jeśli w interfejsie Immowelt da się ustawić "Umkreis"/promień wyszukiwania,
warto to zrobić ręcznie i podać nowy URL, żeby zaktualizować IMMOWELT_LOCATION_CODES
i ewentualny parametr promienia w config.py. Na razie przeszukujemy tylko lokalizacje
z listy (domyślnie Emmerich am Rhein).
"""
import logging
import re
from typing import List, Optional

from bs4 import BeautifulSoup

import config
from models import Listing
from scrapers.base import make_session, polite_get, parse_price, parse_rooms, parse_size

logger = logging.getLogger("immo-bot")

BASE_URL = "https://www.immowelt.de"


def _build_search_url(location_code: str, page: int = 1) -> str:
    rooms_max = config.MAX_ROOMS or ""
    price_max = int(config.MAX_PRICE_EUR) if config.MAX_PRICE_EUR else ""

    url = (
        f"{BASE_URL}/classified-search"
        f"?distributionTypes=Rent&estateTypes=Apartment"
        f"&locations={location_code}"
        f"&numberOfRoomsMax={rooms_max}"
        f"&priceMax={price_max}"
        f"&priceType=Rent"  # Kaltmiete; zmień na "Warmrent" jeśli wolisz filtrować po czynszu z opłatami
    )
    if page > 1:
        url += f"&page={page}"
    return url


def _parse_title_attr(title_attr: str) -> dict:
    """'Wohnung zur Miete - Emmerich am Rhein - 550 € - 3 Zimmer, 70 m², EG, ...' -> pola"""
    parts = [p.strip() for p in title_attr.split(" - ")]
    location_text = parts[1] if len(parts) > 1 else config.CENTER_CITY
    price_eur = parse_price(parts[2]) if len(parts) > 2 else None
    rest = parts[3] if len(parts) > 3 else ""
    return {
        "location_text": location_text,
        "price_eur": price_eur,
        "rooms": parse_rooms(rest),
        "size_sqm": parse_size(rest),
    }


def _parse_links(html: str) -> List[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    links = soup.select("a[data-testid='card-mfe-covering-link-testid']")
    listings = []

    for link in links:
        title_attr = link.get("title", "")
        href = link.get("href", "")
        if not href or not title_attr:
            continue

        fields = _parse_title_attr(title_attr)
        listings.append(Listing(
            source="Immowelt",
            title=title_attr,
            url=href.split("?")[0],  # obcinamy tracking params z linku
            price_eur=fields["price_eur"],
            rooms=fields["rooms"],
            size_sqm=fields["size_sqm"],
            location_text=fields["location_text"],
            has_bathroom=None,  # niedostępne w tym fragmencie danych - wymaga wejścia w ogłoszenie
            has_kitchen=None,
            raw_description=title_attr,
        ))

    return listings


def search() -> List[Listing]:
    session = make_session()
    results: List[Listing] = []
    seen_urls = set()

    location_codes = getattr(config, "IMMOWELT_LOCATION_CODES", ["AD08DE2123"])  # domyślnie Emmerich am Rhein

    for location_code in location_codes:
        for page in range(1, config.MAX_PAGES_PER_SITE + 1):
            url = _build_search_url(location_code, page)
            html = polite_get(session, url)
            if not html:
                break

            listings = _parse_links(html)
            if not listings:
                logger.info("Immowelt [%s]: 0 ofert na stronie %s - koniec lub zmieniony HTML.",
                            location_code, page)
                break

            for listing in listings:
                if listing.url not in seen_urls:
                    seen_urls.add(listing.url)
                    results.append(listing)

    logger.info("Immowelt: znaleziono %d ofert łącznie (przed filtrowaniem).", len(results))
    return results
