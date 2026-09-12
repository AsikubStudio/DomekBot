"""
Scraper dla immobilienscout24.de

WERSJA 3 - selektory dopasowane do realnego HTML karty ogłoszenia:

    <div class="grid-item font-ellipsis one-half grid grid-flex row-gap-2">
      <h2 data-testid="headline" ...>50 m² maisonette apartment...</h2>
      <div class="grid ... listing-card__attributes" data-testid="attributes">
        <dl><dd>€680</dd></dl><dl><dd>50 m²</dd></dl><dl><dd><span>2 rms</span></dd></dl>
      </div>
      <div data-testid="hybridViewAddress">Kleve, Kleve (Kreis)</div>
    </div>

TODO: brakuje jeszcze linku do ogłoszenia (href="/expose/...") - ten fragment
najwyraźniej nie zawiera go bezpośrednio, musi być na elemencie-rodzicu (prawdopodobnie
<a> lub <article> opakowujący cały ten <div class="grid-item...">). Selektor CARD_SELECTOR
poniżej zakłada, że rodzicem jest <a href="/expose/...">, ale to wymaga potwierdzenia na
żywym HTML-u - jeśli po aktualizacji nadal 0 wyników, to jest najbardziej prawdopodobna
przyczyna.
"""
import logging
import re
from typing import List, Optional

from bs4 import BeautifulSoup

import config
from models import Listing
from scrapers.base import make_session, polite_get

logger = logging.getLogger("immo-bot")

BASE_URL = "https://www.immobilienscout24.de"
PARAMS_EXTRA = ""  # np. "&pricetype=calculatedtotalrent" jeśli wolisz filtrować po Warmmiete

# Zakładany selektor karty - element <a> (lub inny) opakowujący cały wpis.
# TODO: potwierdzić po otrzymaniu HTML-a jeden poziom wyżej.
CARD_SELECTOR = "a[href*='/expose/']"


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


def _extract_number(text: str) -> Optional[float]:
    if not text:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)", text.replace(".", "").replace(",", "."))
    return float(match.group(1)) if match else None


def _parse_card(card) -> Optional[Listing]:
    href = card.get("href", "")
    if not href:
        return None
    full_url = href if href.startswith("http") else BASE_URL + href

    title_el = card.select_one("h2[data-testid='headline']")
    address_el = card.select_one("[data-testid='hybridViewAddress']")
    attr_dds = card.select("[data-testid='attributes'] dd")

    price_eur = rooms = size_sqm = None
    for dd in attr_dds:
        text = dd.get_text(" ", strip=True)
        if "€" in text:
            price_eur = _extract_number(text.replace("€", ""))
        elif "m²" in text:
            size_sqm = _extract_number(text.replace("m²", ""))
        elif "rm" in text.lower() or "zi" in text.lower():
            rooms = _extract_number(text)

    return Listing(
        source="ImmoScout24",
        title=title_el.get_text(strip=True) if title_el else "(bez tytułu)",
        url=full_url,
        price_eur=price_eur,
        rooms=rooms,
        size_sqm=size_sqm,
        location_text=address_el.get_text(strip=True) if address_el else "",
        has_bathroom=None,
        has_kitchen=None,
        raw_description=title_el.get_text(strip=True) if title_el else "",
    )


def _parse_cards(html: str, location_slug: str) -> List[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(CARD_SELECTOR)
    listings = []
    for card in cards:
        # karta musi zawierać headline, inaczej to inny link (np. do agencji, mapy itp.)
        if not card.select_one("h2[data-testid='headline']"):
            continue
        listing = _parse_card(card)
        if listing:
            listings.append(listing)
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
