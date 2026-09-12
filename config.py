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
MAX_DISTANCE_KM = 15
DIRECTION_HINT = "Kleve"  # tylko informacyjnie w logach, filtrowanie i tak jest promieniem

# Białą listę miejscowości w promieniu ~15 km od Emmerich (w stronę Kleve) można
# rozszerzyć ręcznie, jeśli geokodowanie zawiedzie albo ogłoszenie nie ma współrzędnych.
# Miejscowości/dzielnice orientacyjnie w promieniu 15 km od Emmerich am Rhein:
KNOWN_NEARBY_PLACES = [
    "emmerich am rhein", "emmerich",
    "rees", "isselburg", "elten",
    "kranenburg", "bedburg-hau", "kellen",
    "praest", "vrasselt", "hüthum", "huethum",
    "zevenaar",  # NL, blisko granicy
    # "kleve" jest ~20 km, dodaj świadomie jeśli chcesz je uwzględnić mimo promienia:
    # "kleve",
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
# 1395 = Emmerich am Rhein, 1122 = Kleve - namierzone z realnych linków wyszukiwania.
KLEINANZEIGEN_LOCATIONS = [
    {"slug": "emmerich-am-rhein", "location_id": "1395", "radius_km": 15},
    {"slug": "kleve", "location_id": "1122", "radius_km": 15},
]

# Które portale mają być przeszukiwane (można wyłączyć pojedynczo do debugowania)
ENABLED_SCRAPERS = {
    "immoscout24": True,
    "immowelt": True,
    "kleinanzeigen": True,
    "wg_gesucht": True,
}

# --- Output ---
SAVE_RESULTS_TO_FILE = True
OUTPUT_DIR = "results"
