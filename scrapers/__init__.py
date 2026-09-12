"""
Rejestr scraperów. Dodanie nowego portalu = nowy plik scrapers/<nazwa>.py
z funkcją search() -> List[Listing], plus wpis tutaj i w config.ENABLED_SCRAPERS.
"""
from scrapers import immoscout24, immowelt, kleinanzeigen, wg_gesucht, immoscout24_local

REGISTRY = {
    "immoscout24": ("ImmoScout24", immoscout24.search),
    "immowelt": ("Immowelt", immowelt.search),
    "kleinanzeigen": ("Kleinanzeigen", kleinanzeigen.search),
    "wg_gesucht": ("WG-Gesucht", wg_gesucht.search),
    # Nie w config.ENABLED_SCRAPERS - celowo nieosiagalny przez zwykle "python main.py"
    # ani przez GitHub Actions. Uruchamiany TYLKO recznie/przez Task Scheduler:
    #     python main.py --site immoscout24_local
    "immoscout24_local": ("ImmoScout24", immoscout24_local.search),
}