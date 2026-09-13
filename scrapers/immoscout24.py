"""
Scraper dla immobilienscout24.de

WERSJA 4 - uzywa prawdziwej przegladarki (Playwright), nie zwyklych zapytan HTTP.

Historia prob: zwykly `requests` dawal 401 nawet na samej stronie glownej.
Podszycie sie pod TLS fingerprint Chrome (`curl_cffi`) rowniez dalo 401 - to
sugeruje, ze ochrona wymaga faktycznego wykonania JavaScriptu (typowe dla
Akamai/PerimeterX/Datadome), czego zadna biblioteka HTTP nie jest w stanie
zrobic. Stad przejscie na prawdziwa przegladarke headless.

UWAGA: to nie gwarantuje sukcesu - adres IP GitHub Actions to nadal adres
chmurowy, ktory moze dostac dodatkowe wyzwanie (CAPTCHA) niezaleznie od tego,
ze to prawdziwa przegladarka. Traktuj to jako eksperyment.

Selektory HTML kart (funkcje _parse_card/_parse_cards) sa identyczne jak w
poprzedniej wersji - zmienil sie tylko SPOSOB pobierania HTML-a (search()).
"""
import logging
import re
import time
from typing import List, Optional

from bs4 import BeautifulSoup

import config
from models import Listing
from scrapers.base import extract_image_url

logger = logging.getLogger("immo-bot")

BASE_URL = "https://www.immobilienscout24.de"
PARAMS_EXTRA = ""  # np. "&pricetype=calculatedtotalrent" jeśli wolisz filtrować po Warmmiete

CARD_SELECTOR = "a[href*='/expose/']"

# Maskuje najbardziej oczywiste slady automatyzacji, zanim strona zdazy je sprawdzic.
STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['de-DE', 'de', 'en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


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
        image_url=extract_image_url(card, BASE_URL),
    )


def _parse_cards(html: str, location_slug: str) -> List[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(CARD_SELECTOR)
    listings = []
    for card in cards:
        if not card.select_one("h2[data-testid='headline']"):
            continue
        listing = _parse_card(card)
        if listing:
            listings.append(listing)
    return listings


def search() -> List[Listing]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("ImmoScout24: pakiet 'playwright' nie jest zainstalowany "
                        "(pip install playwright && playwright install chromium) - pomijam.")
        return []

    results: List[Listing] = []
    seen_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=config.USER_AGENT,
            locale="de-DE",
            viewport={"width": 1366, "height": 900},
        )
        context.add_init_script(STEALTH_INIT_SCRIPT)
        page = context.new_page()

        # "Rozgrzewka" - naturalny wzorzec przegladania: najpierw strona glowna.
        try:
            page.goto(BASE_URL, timeout=30000, wait_until="domcontentloaded")
            time.sleep(1.5)
        except Exception as exc:
            logger.warning("ImmoScout24 (Playwright): błąd ładowania strony głównej: %s", exc)

        for location_slug in config.IMMOSCOUT24_LOCATION_SLUGS:
            for page_num in range(1, config.MAX_PAGES_PER_SITE + 1):
                url = _build_search_url(location_slug, page_num)
                try:
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    try:
                        page.wait_for_selector(CARD_SELECTOR, timeout=8000)
                    except Exception:
                        pass  # moze po prostu nie byc wynikow - sprawdzimy przez parsowanie
                    time.sleep(1.5)  # bufor na ewentualny JS challenge anty-bot
                    html = page.content()
                except Exception as exc:
                    logger.warning("ImmoScout24 (Playwright): błąd ładowania %s: %s", url, exc)
                    break

                listings = _parse_cards(html, location_slug)
                if not listings:
                    try:
                        page_title = page.title()
                        body_snippet = page.inner_text("body")[:400].replace("\n", " ").strip()
                    except Exception:
                        page_title, body_snippet = "?", "?"
                    logger.info(
                        "ImmoScout24 [%s]: 0 kart na stronie %s. Tytuł strony: %r | Fragment treści: %r",
                        location_slug.split("/")[-1], page_num, page_title, body_snippet,
                    )
                    # Zrzut ekranu tylko raz (pierwsza lokalizacja/strona) - do wizualnej diagnozy
                    # (np. CAPTCHA, baner cookies) - trafia jako artefakt workflow w GitHub Actions.
                    if location_slug == config.IMMOSCOUT24_LOCATION_SLUGS[0] and page_num == 1:
                        try:
                            page.screenshot(path="immoscout24_debug.png", full_page=True)
                            logger.info("ImmoScout24: zapisano zrzut ekranu do immoscout24_debug.png")
                        except Exception as exc:
                            logger.warning("ImmoScout24: nie udało się zapisać zrzutu ekranu: %s", exc)
                    break

                for listing in listings:
                    if listing.url not in seen_urls:
                        seen_urls.add(listing.url)
                        results.append(listing)

                time.sleep(config.REQUEST_DELAY_SECONDS)

        browser.close()

    logger.info("ImmoScout24: znaleziono %d ofert łącznie (przed filtrowaniem).", len(results))
    return results


# ---------------------------------------------------------------------------
# Parsowanie PODSTRONY pojedynczej oferty (expose) - karuzela zdjęć + czynsz
# z mediami. Współdzielone przez wersję chmurową (wyłączoną w config) i lokalną
# (scrapers/immoscout24_local.py, ktora faktycznie tego uzywa) - obie roznia sie
# tylko sposobem pobrania HTML-a, parsowanie jest identyczne.
# ---------------------------------------------------------------------------

def _extract_amount(text: str) -> Optional[float]:
    """
    '500 €' -> 500.0. '€475–525' (zakres, np. Warmmiete widelkowe) -> średnia (500.0) -
    to tylko orientacyjna wartość informacyjna w oknie oferty, nie kryterium filtrowania,
    więc średnia z widełek jest rozsądnym kompromisem zamiast pokazywać tylko dolną granicę.
    """
    if not text:
        return None
    cleaned = text.replace(".", "").replace(",", ".")
    numbers = [float(m) for m in re.findall(r"\d+(?:\.\d+)?", cleaned)]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def _parse_detail_images(html: str) -> List[str]:
    """
    Galeria zdjęć na podstronie oferty (expose) ImmoScout24. Zdjęcia są serwowane
    z CDN pod domeną pictures.immobilienscout24.de - to stabilniejszy sposób ich
    namierzenia niż konkretna klasa CSS kontenera galerii (bywa zmieniana między
    wersjami strony), ale NIE ZWERYFIKOWANE jeszcze na żywym HTML-u (jak inne
    selektory w tym projekcie) - jeśli zawsze wraca pusta lista mimo że oferta ma
    zdjęcia, wyślij fragment HTML-a sekcji galerii (zwykle w okolicy elementu
    o id/klasie zawierającej "gallery") żeby to doprecyzować.
    """
    soup = BeautifulSoup(html, "html.parser")
    urls: List[str] = []
    seen = set()
    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-imgsrc"):
            value = img.get(attr)
            if value and "pictures.immobilienscout24.de" in value and value not in seen:
                seen.add(value)
                urls.append(value)
                break
    return urls[:12]


def _parse_detail_warm_rent(html: str) -> Optional[float]:
    """
    ZWERYFIKOWANE na żywym HTML-u (12.09.2026, przykładowa oferta ImmoScout24) -
    "czynsz z mediami" jest oznaczony klasą CSS zawierającą "rentincludingutilities",
    np.:
        <div class="is24qa-maincriteria-rentincludingutilities-label-main ...">
          <span class="">€475–525</span>
        </div>
    (nie atrybutem `data-qa`, jak pierwotnie zakładałem - poprawione po realnym
    fragmencie HTML-a przysłanym przez użytkownika). Wartość bywa WIDEŁKOWA
    (np. "€475–525" zamiast jednej liczby) - _extract_amount liczy wtedy średnią.

    Jeśli w przyszłości portal znów zmieni nazewnictwo klas i to zacznie zawsze
    wracać None mimo że oferta ma czynsz z mediami, wyślij nowy fragment sekcji
    z ceną (Inspect na tym polu) żeby dopracować.
    """
    soup = BeautifulSoup(html, "html.parser")

    el = soup.select_one('[class*="rentincludingutilities"]')
    if el:
        amount = _extract_amount(el.get_text(" ", strip=True))
        if amount is not None:
            return amount

    # Fallback (niezweryfikowany) na wypadek innej wersji strony - suma "zimnego"
    # czynszu i kosztów dodatkowych, jeśli oba są oznaczone podobnym wzorcem klas.
    kalt_el = soup.select_one('[class*="maincriteria-baserent"], [data-qa="is24qa-kaltmiete"]')
    neben_el = soup.select_one('[class*="maincriteria-additionalcosts"], [data-qa="is24qa-nebenkosten"]')
    kalt = _extract_amount(kalt_el.get_text(" ", strip=True)) if kalt_el else None
    neben = _extract_amount(neben_el.get_text(" ", strip=True)) if neben_el else None
    if kalt is not None and neben is not None:
        return round(kalt + neben, 2)
    return None
