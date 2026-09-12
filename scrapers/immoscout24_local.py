"""
Wersja ImmoScout24 do uruchamiania WYŁĄCZNIE LOKALNIE (Twój komputer przez
Windows Task Scheduler) - NIE w GitHub Actions.

Dlaczego osobny plik: potwierdziliśmy, że ekran "Ich bin kein Roboter" pojawia
się tylko z adresów IP centrów danych (GitHub Actions). Z domowego adresu IP +
prawdziwej przeglądarki strona działa normalnie - trzeba tylko zaakceptować
baner cookies (Usercentrics), co robią funkcje poniżej.

Wymaga pakietu, którego NIE MA w requirements.txt (celowo - to lokalny wyjątek):
    pip install seleniumbase

Rejestracja: scrapers/__init__.py rejestruje to pod kluczem "immoscout24_local",
którego NIE MA w config.ENABLED_SCRAPERS - dzięki temu ani zwykłe `python main.py`,
ani GitHub Actions nigdy tego nie uruchomią przypadkiem. Jedyny sposób odpalenia:

    python main.py --site immoscout24_local

Do automatyzacji przez Windows Task Scheduler: patrz run_immoscout24_local.bat
i README.md (sekcja "ImmoScout24 lokalnie").

Logika parsowania HTML (_build_search_url, _parse_cards) jest importowana z
scrapers/immoscout24.py, żeby nie duplikować kodu - obie wersje różnią się TYLKO
sposobem pobierania strony (Playwright w chmurze vs. przeglądarka lokalnie).

HISTORIA (12.09.2026): pierwotnie ten plik używał pakietu "undetected-chromedriver"
bezpośrednio, ale po aktualizacji Chrome do wersji 153.x przestał się łączyć
z przeglądarką ("cannot connect to chrome") - problem występował niezależnie od
wersji Pythona (3.13/3.14), wersji selenium, czy własnych opcji Chrome, a więc
leżał w samym mechanizmie uruchamiania tego pakietu. Przełączenie na SeleniumBase
(SB(uc=True)) - osobny, aktywniej rozwijany projekt oparty na tej samej idei -
rozwiązało problem od razu.
"""
import logging
import time
from typing import List

import config
from models import Listing
from scrapers.immoscout24 import _build_search_url, _parse_cards, CARD_SELECTOR

logger = logging.getLogger("immo-bot")

# Ścieżki do przycisku "Akceptuj wszystkie" w banerze cookies Usercentrics.
# Dwie metody, bo struktura bywa różna (zwykły DOM vs. Shadow DOM) - próbujemy obu.
COOKIE_BUTTON_XPATH = '//*[@id="uc-center-container"]/div[2]/div/div/div/button[2]'
COOKIE_SHADOW_DOM_JS = """
let shadowRoot = document.querySelector('#usercentrics-root');
if (shadowRoot && shadowRoot.shadowRoot) {
    let acceptBtn = shadowRoot.shadowRoot.querySelector('button[data-testid="uc-accept-all-button"]');
    if (acceptBtn) {
        acceptBtn.click();
        return true;
    }
}
return false;
"""

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['de-DE', 'de', 'en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4]});
"""


def _accept_cookies(driver) -> bool:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

    try:
        button = WebDriverWait(driver, 4).until(
            EC.presence_of_element_located((By.XPATH, COOKIE_BUTTON_XPATH))
        )
        driver.execute_script("arguments[0].click();", button)
        logger.info("ImmoScout24 (lokalnie): zaakceptowano cookies (XPath).")
        return True
    except TimeoutException:
        try:
            success = driver.execute_script(COOKIE_SHADOW_DOM_JS)
            if success:
                logger.info("ImmoScout24 (lokalnie): zaakceptowano cookies (Shadow DOM).")
            else:
                logger.info("ImmoScout24 (lokalnie): nie znaleziono banera cookies (może już zaakceptowany).")
            return success
        except Exception as exc:
            logger.warning("ImmoScout24 (lokalnie): błąd przy Shadow DOM: %s", exc)
            return False


def search() -> List[Listing]:
    try:
        from seleniumbase import SB
    except ImportError:
        logger.warning("ImmoScout24 (lokalnie): brak pakietu 'seleniumbase' - "
                        "zainstaluj: pip install seleniumbase. Pomijam.")
        return []

    results: List[Listing] = []
    seen_urls = set()

    # UWAGA: headless zostało przetestowane i wywołuje CAPTCHA (obrazkowy test
    # "Ich bin kein Roboter"), mimo dzialania w trybie zwyklym (widocznym oknem) z
    # tego samego adresu IP. Dlatego NIE uzywamy headless - zamiast tego, zeby uruchamiac
    # to w tle bez pokazywania okna, skonfiguruj Windows Task Scheduler z opcja
    # "Uruchom niezaleznie od tego, czy uzytkownik jest zalogowany" (patrz README) -
    # wtedy okno przegladarki nie pojawi sie na pulpicie, mimo ze to nie headless.
    with SB(uc=True, headless=False) as sb:
        driver = sb.driver
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": STEALTH_INIT_SCRIPT})

        # Pierwsze wejście - żeby obsłużyć baner cookies raz, na początku.
        first_url = _build_search_url(config.IMMOSCOUT24_LOCATION_SLUGS[0], 1)
        driver.get(first_url)
        time.sleep(2)
        _accept_cookies(driver)
        time.sleep(1.5)
        # Powtórz to samo zapytanie po zaakceptowaniu cookies - pierwsza próba mogła
        # zwrócić stronę zasłoniętą banerem zanim kliknięcie zdążyło zadziałać.
        driver.get(first_url)
        time.sleep(2)

        for location_slug in config.IMMOSCOUT24_LOCATION_SLUGS:
            for page_num in range(1, config.MAX_PAGES_PER_SITE + 1):
                url = _build_search_url(location_slug, page_num)
                try:
                    driver.get(url)
                    time.sleep(2.5)
                    html = driver.page_source
                except Exception as exc:
                    logger.warning("ImmoScout24 (lokalnie): błąd ładowania %s: %s", url, exc)
                    break

                listings = _parse_cards(html, location_slug)
                if not listings:
                    try:
                        page_title = driver.title
                        body_text = driver.execute_script("return document.body.innerText;") or ""
                        body_snippet = body_text[:400].replace("\n", " ").strip()
                    except Exception:
                        page_title, body_snippet = "?", "?"
                    logger.info(
                        "ImmoScout24 (lokalnie) [%s]: 0 kart na stronie %s. Tytuł: %r | Fragment: %r",
                        location_slug.split("/")[-1], page_num, page_title, body_snippet,
                    )
                    if location_slug == config.IMMOSCOUT24_LOCATION_SLUGS[0] and page_num == 1:
                        try:
                            driver.save_screenshot("immoscout24_local_debug.png")
                            logger.info("ImmoScout24 (lokalnie): zapisano zrzut ekranu do immoscout24_local_debug.png")
                        except Exception as exc:
                            logger.warning("ImmoScout24 (lokalnie): nie udało się zapisać zrzutu ekranu: %s", exc)
                    break

                for listing in listings:
                    if listing.url not in seen_urls:
                        seen_urls.add(listing.url)
                        results.append(listing)

                time.sleep(config.REQUEST_DELAY_SECONDS)

    logger.info("ImmoScout24 (lokalnie): znaleziono %d ofert łącznie (przed filtrowaniem).", len(results))
    return results