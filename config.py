"""
Konfiguracja wyszukiwania mieszkań.
Zmieniaj wartości tutaj, żeby dopasować kryteria bez grzebania w kodzie scraperów.
"""

# --- Cena ---
MAX_PRICE_EUR = 650          # Kaltmiete (czynsz bez opłat) - max
MIN_PRICE_EUR = None          # opcjonalnie, np. 300, albo None = brak dolnego limitu

# --- Pokoje ---
MIN_ROOMS = 2
MAX_ROOMS = 2
REQUIRE_SEPARATE_ROOMS = True  # odrzucaj oferty opisane jako "studio"/"1-Zimmer-Wohnung offen"

# --- Lokalizacja ---
CENTER_CITY = "Emmerich am Rhein"
CENTER_PLZ = "46446"
DIRECTION_HINT = "Kleve"  # tylko informacyjnie w logach, filtrowanie i tak jest wg czasu dojazdu

# GŁÓWNE kryterium zasięgu: czas dojazdu AUTEM od CENTER_CITY (nie odległość w linii
# prostej), liczony przez OpenRouteService - patrz utils/geo.py::drive_time_minutes().
# Wymaga darmowego konta + klucza API:
#   - w chmurze (GitHub Actions): sekret repo ORS_API_KEY
#   - lokalnie (ImmoScout24): local_secrets/ors_api_key.txt (patrz README.md)
# Bez klucza (albo gdy ORS zawiedzie - limit/awaria/timeout) automatycznie
# używany jest zapasowy próg MAX_DISTANCE_KM_FALLBACK poniżej.
MAX_DRIVE_TIME_MINUTES = 42

# Używane TYLKO jako zapasowe kryterium, gdy OpenRouteService jest niedostępny -
# dystans w linii prostej z marginesem (żeby przypadkiem nie odrzucić czegoś, co
# w linii prostej wygląda dalej niż promień, ale autem mieści się w ~42 minutach).
MAX_DISTANCE_KM_FALLBACK = 30

# Białą listę miejscowości w zasięgu (w stronę Kleve) można rozszerzyć ręcznie,
# jako ostatnia deska ratunku gdy i geokodowanie, i ORS zawiodą:
KNOWN_NEARBY_PLACES = [
    "emmerich am rhein", "emmerich",
    "rees", "isselburg", "elten",
    "kranenburg", "bedburg-hau", "kellen",
    "praest", "vrasselt", "hüthum", "huethum",
    "zevenaar",  # NL, blisko granicy
    "kleve",  # ~20 km, w zasięgu
]

# --- Wyposażenie ---
# True  -> wymagane
# False -> odrzucaj oferty, które explicite mówią "bez łazienki"/"bez kuchni" (rzadkie)
# None  -> nieistotne, nie filtruj
REQUIRE_BATHROOM = True   # "łazienka już stoi" - preferowane/wymagane
REQUIRE_KITCHEN = None    # kuchnia niekonieczna

# --- Ustawienia techniczne scrapera ---
REQUEST_DELAY_SECONDS = 2.5   # odstęp między requestami - szanuj serwery, zmniejsza ryzyko blokady
REQUEST_TIMEOUT_SECONDS = 15
MAX_PAGES_PER_SITE = 3        # ile stron wyników przeglądać na portal

# --- Szczegóły oferty (karuzela zdjęć + czynsz z mediami w oknie na stronie) ---
# Włącza dodatkowe wejście na PODSTRONĘ każdej nowo znalezionej oferty (Kleinanzeigen
# i ImmoScout24 lokalnie), żeby pobrać wiele zdjęć i "Warmmiete"/czynsz z mediami -
# te dane NIE są dostępne na samej liście wyników wyszukiwania. To realnie zwiększa
# liczbę requestów do portalu, więc:
#  - ustaw False, żeby całkowicie wyłączyć (front-end i tak działa - po prostu pokaże
#    "brak danych" i pojedyncze zdjęcie z karty, bez karuzeli),
#  - wyniki są PAMIĘTANE między uruchomieniami (patrz scrapers/base.py::load_cached_details) -
#    raz pobrana oferta nie jest pobierana ponownie, więc w praktyce dotyczy to tylko
#    NOWO pojawiających się ofert, nie każdego przebiegu.
FETCH_LISTING_DETAILS = True
# Twardy limit nowych (nie-cache'owanych) podstron pobieranych w JEDNYM przebiegu -
# zabezpieczenie przed nagłym skokiem requestów (np. pierwsze uruchomienie po włączeniu
# tej funkcji, albo masowy napływ nowych ofert). Nadmiarowe oferty po prostu poczekają
# do następnego przebiegu (3h dla Kleinanzeigen) - nic się nie gubi, tylko "brak danych"
# przez jeden cykl dłużej.
MAX_DETAIL_FETCHES_PER_RUN = 15

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# --- Ustawienia specyficzne dla portali (na podstawie realnych URLi ze strony) ---

# ImmoScout24 nie wspiera dobrze promienia przez URL (radius-search dawał 401),
# więc przeszukujemy listę konkretnych miejscowości zamiast promienia.
# Format: "wojewodztwo/kreis/miejscowosc" dokładnie jak w URLu ImmoScout24.
IMMOSCOUT24_LOCATION_SLUGS = [
    "nordrhein-westfalen/kleve-kreis/emmerich-am-rhein",
    "nordrhein-westfalen/kleve-kreis/kleve",
    "nordrhein-westfalen/kleve-kreis/rees",
    "nordrhein-westfalen/kleve-kreis/isselburg",
    "nordrhein-westfalen/kleve-kreis/bedburg-hau",
    "nordrhein-westfalen/kleve-kreis/kranenburg",
]

# Kleinanzeigen używa własnych wewnętrznych ID lokalizacji (nie PLZ!).
# 1395 = Emmerich am Rhein, 1122 = Kleve, 1387 = Rees - namierzone z realnych
# linków wyszukiwania (1387 potwierdzone przez /s-ort-empfehlungen.json?query=Rees).
# radius_km to promień ZAPYTANIA do samego portalu (żeby portal w ogóle zwrócił
# oferty do rozpatrzenia) - podbity z 20 do 30 km, żeby nie odciąć z góry ofert,
# które w linii prostej są dalej niż dawny promień, ale mieszczą się w
# MAX_DRIVE_TIME_MINUTES (patrz wyżej) - to WŁAŚCIWY filtr stosowany później
# w filters.py, ten promień to tylko "zarzucenie szerszej siatki".
KLEINANZEIGEN_LOCATIONS = [
    {"slug": "emmerich-am-rhein", "location_id": "1395", "radius_km": 30},
    {"slug": "kleve", "location_id": "1122", "radius_km": 30},
    {"slug": "rees", "location_id": "1387", "radius_km": 30},
]

# Które portale mają być przeszukiwane (można wyłączyć pojedynczo do debugowania)
ENABLED_SCRAPERS = {
    "immoscout24": False,  # blokada "Ich bin kein Roboter" dla IP centrow danych - nie do obejscia etycznie
    "immowelt": False,  # wyjebane - stabilnie 403, nie warto walczyc
    "kleinanzeigen": True,
    "wg_gesucht": False,  # pomijamy - zbyt uciążliwy do naprawy (paywall/login-wall)
}

# --- Output ---
SAVE_RESULTS_TO_FILE = True
OUTPUT_DIR = "results"

# --- Publikacja wynikow (dla strony GitHub Pages) i sledzenie nowych ofert ---
PUBLISH_JSON_PATH = "docs/data/latest.json"   # czyta to strona w docs/index.html
SEEN_IDS_PATH = "data/seen_ids.json"          # pamiec "co juz widzielismy" miedzy uruchomieniami

# Trwaly cache czasu dojazdu autem (OpenRouteService) miedzy uruchomieniami - patrz
# utils/geo.py::drive_time_minutes(). Bez tego kazde uruchomienie (co 3h w chmurze
# I co godzine lokalnie dla ImmoScout24 = ~32x dziennie) liczylo od nowa czas
# dojazdu dla tych samych ~30-40 miejscowosci w promieniu, co szybko wyczerpalo
# darmowy dzienny limit ORS (21.09.2026: "Quota exceeded" na WSZYSTKICH zapytaniach).
# Trasa Emmerich->dana miejscowosc praktycznie sie nie zmienia, wiec raz policzony
# wynik jest cache'owany NA STALE (bez wygasania) - tylko naprawde NOWE miejscowosci
# (nowe oferty w nieznanym wczesniej miejscu) wywoluja kolejne zapytanie do ORS.
DRIVE_TIME_CACHE_PATH = "data/drive_time_cache.json"

# Co ile godzin (w teorii) kazde zrodlo sie odswieza - uzywane TYLKO do wyswietlenia
# odliczania na stronie ("kolejne sprawdzenie za..."), nie steruje samym scraperem.
# Kleinanzeigen: harmonogram GitHub Actions (.github/workflows/scrape.yml).
# ImmoScout24: harmonogram Windows Task Scheduler na komputerze uzytkownika.
SOURCE_REFRESH_INTERVAL_HOURS = {
    "Kleinanzeigen": 3,
    "ImmoScout24": 1,
}

# Immowelt uzywa wewnetrznych kodow lokalizacji (nie PLZ). AD08DE2123 = Emmerich am Rhein.
# Dodaj wiecej kodow tutaj jesli zdobedziesz je dla Kleve/Rees/itd (skopiuj z URL po recznym wyszukaniu).
IMMOWELT_LOCATION_CODES = ["AD08DE2123"]
# --- Górny limit czynszu z mediami (opcjonalny) ---
# Jeśli oferta MA znany czynsz z mediami (Warmmiete) i przekracza tę wartość - odrzuć.
# Brak danych o czynszu z mediami (None) - NIE odrzucaj, zostaw ofertę.
MAX_WARM_RENT_EUR = 800

# --- Minimalna powierzchnia (opcjonalna) ---
# Jeśli oferta MA znaną powierzchnię i jest <= tej wartości - odrzuć.
# Brak danych o powierzchni (None) - NIE odrzucaj, zostaw ofertę.
MIN_SIZE_SQM = 30

# --- Oferty pracy w pobliżu ZNALEZIONYCH mieszkań (Bundesagentur für Arbeit) ---
# WAŻNE: to NIE jest osobny, stały harmonogram wyszukiwania - patrz jobs.py i
# main.py. Szukamy pracy TYLKO w promieniu od lokalizacji ofert mieszkań, które
# już przeszły wszystkie inne filtry (apply_all_filters()) - nie wokół Emmerich
# ogólnie. Wyniki pokazują się jako dropdown "Praca w pobliżu" w modalu danej
# oferty na stronie (docs/index.html), BEZ osobnych powiadomień Telegram/Push -
# tylko do przeglądania.
# API jest darmowe i publiczne (reverse-engineered z oficjalnej apki mobilnej
# Bundesagentur für Arbeit, ale stabilne, szeroko używane) - nie wymaga
# zakładania konta ani własnego klucza, patrz jobs.py.
#
# PONOWNIE WŁĄCZONE 21.09.2026 na prośbę użytkownika, RAZEM z nowym
# wyszukiwaniem pracy w Holandii (patrz jobs_nl.py i JOB_SEARCH_NL_* niżej).
# Znany, nierozwiązany problem (powód wcześniejszego wyłączenia): dobór ofert
# niemieckich jest za mało precyzyjny - część zwracanych ofert wymaga
# niemieckiego na poziomie native/C1 mimo doboru słów kluczowych pod branże
# "bez niemieckiego" (np. "Sehr gute Deutschkenntnisse auf Muttersprachenniveau"
# w treści konkretnej oferty). Żeby to naprawić, trzeba by sprawdzać PEŁNY opis
# każdej oferty przez osobny endpoint szczegółów (/pc/v4/jobdetails/{kod},
# NIEZWERYFIKOWANY jeszcze na żywo) - nie wdrożone. Użytkownik zaakceptował to
# ograniczenie świadomie: oferty z Holandii (JOB_SEARCH_NL_ENABLED) mają
# priorytet i pokazują się WYŻEJ w dropdownie "Praca w pobliżu" (patrz
# main.py::attach_nearby_jobs), niemieckie oferty trzeba i tak przejrzeć ręcznie.
JOB_SEARCH_ENABLED = True
JOB_SEARCH_RADIUS_KM = 30   # promień wokół KAŻDEJ oferty mieszkania (nie Emmerich)
JOB_SEARCH_EMPLOYMENT_TYPES = ["vz", "tz"]   # vz=pełny etat, tz=część etatu (kody Bundesagentur)
JOB_SEARCH_MAX_RESULTS_PER_KEYWORD = 10      # limit wyników na słowo kluczowe - dropdown ma być czytelny, nie zalany

# Słowa kluczowe dopasowane pod konkretny profil (przekazany przez użytkownika):
# brak wymaganego niemieckiego jako priorytet (angielski płynny, polski ojczysty),
# prawo jazdy kat. B, lubi zwierzęta, technikum graficzne, pakiety Office,
# podstawy Blendera, zainteresowania pieniądze/firmy/e-commerce/modeling 3D,
# 21 lat, najlepiej bez wymaganego doświadczenia.
# UWAGA: Bundesagentur NIE MA filtra "bez wymaganego niemieckiego" ani "bez
# doświadczenia" - to tylko dobór BRANŻ, gdzie taka oferta jest statystycznie
# bardziej prawdopodobna (magazyny/logistyka i e-commerce w regionie przygranicznym
# z Holandią często biorą bez niemieckiego; "Quereinsteiger" to niemiecki termin
# na "bez wymaganego doświadczenia/przebranżowienie"), NIE gwarancja - wyniki
# trzeba i tak przejrzeć ręcznie.
JOB_SEARCH_KEYWORDS = [
    "Lagerhelfer",
    "Kommissionierer",
    "E-Commerce",
    "Kundenservice",
    "Grafikdesign",
    "Mediengestalter",
    "3D Visualisierung",
    "Quereinsteiger",
    "Tierpfleger",
    "Fahrer",
]

# --- Oferty pracy w Holandii w pobliżu ZNALEZIONYCH mieszkań (Adzuna API) ---
# DODANE 21.09.2026 na prośbę użytkownika: priorytet dla ofert pracy w Holandii,
# bo szukanie bez wymaganego niemieckiego jest tam zazwyczaj prostsze niż po
# niemieckiej stronie (patrz JOB_SEARCH_ENABLED wyżej). Działa RÓWNOLEGLE z
# niemieckim wyszukiwaniem (jobs.py), NIE zamiast niego - main.py::
# attach_nearby_jobs scala obie listy, wyniki z Holandii na początku (wyżej
# w dropdownie "Praca w pobliżu" na stronie).
#
# Ta sama logika "promienia wokół KAŻDEJ oferty mieszkania" co niemieckie
# wyszukiwanie, tylko że Adzuna (w odróżnieniu od Bundesagentur) nie przyjmuje
# współrzędnych lat/lon w darmowym publicznym API - trzeba podać nazwę
# miejscowości. Dlatego każda oferta mieszkania dostaje NAJBLIŻSZĄ jej
# holenderską "kotwicę" graniczną jako punkt wyszukiwania - patrz
# utils/geo.py::nearest_dutch_job_anchor() / DUTCH_JOB_ANCHORS.
#
# Rejestracja (darmowa, natychmiastowa, bez karty płatniczej):
# https://developer.adzuna.com/ - klucze (App ID + App Key) wczytywane tak
# samo jak ORS_API_KEY (patrz utils/geo.py):
#   - w chmurze (GitHub Actions): sekrety repo ADZUNA_APP_ID / ADZUNA_APP_KEY
#   - lokalnie (ImmoScout24): local_secrets/adzuna_app_id.txt / adzuna_app_key.txt
JOB_SEARCH_NL_ENABLED = True
JOB_SEARCH_NL_COUNTRY = "nl"     # kod kraju Adzuna (endpoint /v1/api/jobs/{country}/search/...)
JOB_SEARCH_NL_RADIUS_KM = 20     # promień (km) wokół najbliższej "kotwicy" (patrz utils/geo.py)
JOB_SEARCH_NL_MAX_RESULTS_PER_KEYWORD = 10

# Słowa kluczowe po angielsku - Adzuna w Holandii agreguje dużo ogłoszeń
# publikowanych po angielsku (region przygraniczny/logistyka/e-commerce często
# nie wymaga niderlandzkiego), więc angielskie słowa trafiają szerzej niż
# niderlandzkie tłumaczenia dosłowne. Dobrane pod ten sam profil co
# JOB_SEARCH_KEYWORDS wyżej (magazyn/logistyka, e-commerce, obsługa klienta,
# grafika/3D, "bez doświadczenia", opieka nad zwierzętami, kierowca).
JOB_SEARCH_NL_KEYWORDS = [
    "warehouse",
    "order picker",
    "logistics",
    "e-commerce",
    "customer service",
    "graphic design",
    "3D visualization",
    "no experience required",
    "animal care",
    "driver",
]

# --- Wykluczenia z ofert pracy (dotyczy OBU źródeł: Holandia i Niemcy) ---
# Oferta, której tytuł zawiera (bez rozróżniania wielkości liter, dopasowanie
# fragmentu, nie całego słowa) którąkolwiek z poniższych fraz, jest całkowicie
# pomijana zanim trafi do dropdownu "Praca w pobliżu" na stronie - patrz
# main.py::attach_nearby_jobs. Dodane na prośbę użytkownika 21.09.2026
# ("forklift operator") - lista jest do rozszerzania w przyszłości, jedna
# fraza na linię, bez potrzeby zmian w kodzie.
JOB_TITLE_EXCLUDE_KEYWORDS = [
    "forklift",
]
