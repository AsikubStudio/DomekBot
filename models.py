"""
Wspólny model danych dla ogłoszenia mieszkania, używany przez wszystkie scrapery,
żeby filtrowanie i wyświetlanie wyników działało tak samo niezależnie od portalu.
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Listing:
    source: str                     # nazwa portalu, np. "ImmoScout24"
    title: str
    url: str
    price_eur: Optional[float] = None
    rooms: Optional[float] = None
    size_sqm: Optional[float] = None
    location_text: str = ""         # np. "46446 Emmerich am Rhein"
    has_bathroom: Optional[bool] = None   # None = nieznane/nie wspomniane w ogłoszeniu
    has_kitchen: Optional[bool] = None
    raw_description: str = ""
    distance_km: Optional[float] = None   # wyliczane później względem CENTER_CITY
    image_url: Optional[str] = None       # zdjęcie główne z karty wyniku wyszukiwania (jeśli scraper je znalazł)

    # Poniższe pola NIE są wypełniane przy zwykłym parsowaniu listy wyników -
    # wymagają wejścia na podstronę pojedynczej oferty (patrz scrapers/base.py::
    # enrich_with_details i wywołania w scrapers/kleinanzeigen.py / immoscout24_local.py).
    # Domyślnie puste/None dopóki enrichment się nie uda (np. brak w ogłoszeniu, albo
    # portal zablokował/zmienił HTML) - front-end (docs/index.html) traktuje to jako
    # "brak danych" i nic się nie wywraca.
    images: List[str] = field(default_factory=list)     # galeria zdjęć z podstrony oferty
    warm_rent_eur: Optional[float] = None                # "Warmmiete"/czynsz z mediami (ciepły)
    full_description: str = ""                           # pełny opis oferty z podstrony (nie z karty wyników)

    # Wyliczane w filters.py, tak samo jak distance_km, ale względem 's-Heerenberg
    # zamiast Emmerich am Rhein - patrz utils/geo.py.
    distance_sheerenberg_km: Optional[float] = None

    # Czas dojazdu autem od CENTER_CITY (Emmerich am Rhein), liczony przez
    # OpenRouteService w filters.py::_location_ok - patrz utils/geo.py::
    # drive_time_minutes(). None jeśli brak klucza API albo ORS zawiódł
    # (wtedy filtr i tak zadziałał, tylko na zapasowym kryterium - dystans_km).
    drive_minutes: Optional[int] = None

    # Oferty pracy w pobliżu TEJ konkretnej oferty (nie wokół Emmerich) - wypełniane
    # w main.py PO apply_all_filters(), przez jobs.py::search_jobs_near(location_text).
    # Puste jeśli JOB_SEARCH_ENABLED=False, brak lokalizacji, albo Bundesagentur API
    # zawiodło - front-end (docs/index.html) po prostu nie pokazuje wtedy dropdownu.
    nearby_jobs: List[dict] = field(default_factory=list)

    def as_row(self) -> dict:
        return {
            "Portal": self.source,
            "Tytuł": self.title,
            "Cena (€)": self.price_eur,
            "Pokoje": self.rooms,
            "Powierzchnia (m²)": self.size_sqm,
            "Lokalizacja": self.location_text,
            "Odległość (km)": self.distance_km,
            "Czas dojazdu (min)": self.drive_minutes,
            "Odległość od 's-Heerenberg (km)": self.distance_sheerenberg_km,
            "Łazienka": self.bool_label(self.has_bathroom),
            "Kuchnia": self.bool_label(self.has_kitchen),
            "Link": self.url,
            "Zdjęcie": self.image_url,
            "Zdjęcia": self.images,
            "Czynsz z mediami (€)": self.warm_rent_eur,
            "Opis": self.full_description,
            "OfertyPracy": self.nearby_jobs,
        }

    @staticmethod
    def bool_label(value: Optional[bool]) -> str:
        if value is None:
            return "?"
        return "tak" if value else "nie"
