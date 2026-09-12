"""
Rejestr scraperów. Dodanie nowego portalu = nowy plik scrapers/<nazwa>.py
z funkcją search() -> List[Listing], plus wpis tutaj i w config.ENABLED_SCRAPERS.
"""
from scrapers import immoscout24, immowelt, kleinanzeigen, wg_gesucht

REGISTRY = {
    "immoscout24": ("ImmoScout24", immoscout24.search),
    "immowelt": ("Immowelt", immowelt.search),
    "kleinanzeigen": ("Kleinanzeigen", kleinanzeigen.search),
    "wg_gesucht": ("WG-Gesucht", wg_gesucht.search),
}
