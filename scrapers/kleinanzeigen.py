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
from typing import List, Optional

from bs4 import BeautifulSoup

import config
from models import Listing
from scrapers.base import (
    make_session, polite_get, parse_price, parse_rooms, parse_size,
    guess_bathroom, guess_kitchen, extract_image_url, enrich_listings_with_details,
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


def _parse_detail_images(html: str) -> List[str]:
    """
    Zbiera adresy WSZYSTKICH zdjęć galerii z podstrony oferty. Kleinanzeigen serwuje
    zdjęcia z CDN pod domeną img.kleinanzeigen.de - to stabilniejszy sposób ich
    namierzenia niż konkretna klasa CSS kontenera galerii (ta bywa zmieniana między
    wersjami strony), ale NIE ZWERYFIKOWANE jeszcze na żywym HTML-u (jak inne
    selektory w tym projekcie) - jeśli zawsze wraca pusta lista mimo że oferta ma
    zdjęcia, wyślij fragment HTML-a strony oferty (np. całe `<div id="viewad-image">`)
    żeby to doprecyzować.
    """
    soup = BeautifulSoup(html, "html.parser")
    urls: List[str] = []
    seen = set()
    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-imgsrc"):
            value = img.get(attr)
            if value and "img.kleinanzeigen.de" in value and value not in seen:
                seen.add(value)
                urls.append(value)
                break
    return urls[:12]


def _extract_amount(text: str) -> Optional[float]:
    if not text:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)", text.replace(".", "").replace(",", "."))
    return float(match.group(1)) if match else None


def _parse_detail_warm_rent(html: str, kaltmiete: Optional[float]) -> Optional[float]:
    """
    Szuka czynszu "z mediami"/"ciepłego" na podstronie oferty. Kleinanzeigen dla
    mieszkań zwykle pokazuje to jako osobną pozycję w liście szczegółów (np.
    "Nebenkosten" = koszty dodatkowe doliczane do Kaltmiete, rzadziej wprost
    "Warmmiete"/"Gesamtmiete"). Jeśli znajdziemy tylko "Nebenkosten", doliczamy je
    do już znanej Kaltmiete (z listy wyników) żeby dostać sumę.

    NIE ZWERYFIKOWANE jeszcze na żywym HTML-u (jak inne selektory w tym projekcie) -
    jeśli zawsze wraca None mimo że oferta ma te dane, wyślij fragment sekcji
    szczegółów (dt/dd albo listę "addetailslist") żeby dopracować.
    """
    soup = BeautifulSoup(html, "html.parser")
    text_pairs = []

    for dt in soup.select("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            text_pairs.append((dt.get_text(" ", strip=True), dd.get_text(" ", strip=True)))
    for li in soup.select("li"):
        parts = li.find_all(["span", "div"], recursive=False)
        if len(parts) == 2:
            text_pairs.append((parts[0].get_text(" ", strip=True), parts[1].get_text(" ", strip=True)))

    nebenkosten = None
    for label, value in text_pairs:
        low = label.lower()
        if "warmmiete" in low or "gesamtmiete" in low:
            amount = _extract_amount(value)
            if amount is not None:
                return amount
        if "nebenkosten" in low:
            nebenkosten = _extract_amount(value)

    if nebenkosten is not None and kaltmiete is not None:
        return round(kaltmiete + nebenkosten, 2)
    return None


def _fetch_detail(session, listing: Listing) -> dict:
    html = polite_get(session, listing.url)
    if not html:
        return {"images": [], "warm_rent": None}
    return {
        "images": _parse_detail_images(html),
        "warm_rent": _parse_detail_warm_rent(html, listing.price_eur),
    }


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

    # Karuzela zdjęć i czynsz z mediami w oknie szczegółów na stronie - wymaga
    # dodatkowego wejścia na podstronę KAŻDEJ nowej oferty (patrz base.py oraz
    # config.FETCH_LISTING_DETAILS / MAX_DETAIL_FETCHES_PER_RUN).
    enrich_listings_with_details(
        results,
        source="Kleinanzeigen",
        fetch_detail_fn=lambda listing: _fetch_detail(session, listing),
    )

    return results
