"""
Wspólny model danych dla ogłoszenia mieszkania, używany przez wszystkie scrapery,
żeby filtrowanie i wyświetlanie wyników działało tak samo niezależnie od portalu.
"""
from dataclasses import dataclass, field
from typing import Optional


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

    def as_row(self) -> dict:
        return {
            "Portal": self.source,
            "Tytuł": self.title,
            "Cena (€)": self.price_eur,
            "Pokoje": self.rooms,
            "Powierzchnia (m²)": self.size_sqm,
            "Lokalizacja": self.location_text,
            "Odległość (km)": self.distance_km,
            "Łazienka": self.bool_label(self.has_bathroom),
            "Kuchnia": self.bool_label(self.has_kitchen),
            "Link": self.url,
        }

    @staticmethod
    def bool_label(value: Optional[bool]) -> str:
        if value is None:
            return "?"
        return "tak" if value else "nie"
