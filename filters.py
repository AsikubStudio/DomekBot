"""
Filtrowanie listy ofert (Listing) wg kryteriów zdefiniowanych w config.py.
Każdy filtr jest osobną funkcją, żeby łatwo było dodać/wyłączyć/debugować pojedyncze kryterium.
"""
from typing import List
import config
from models import Listing
from utils.geo import within_radius, distance_from_sheerenberg_km


def _price_ok(listing: Listing) -> bool:
    if listing.price_eur is None:
        return True  # brak danych - nie odrzucaj automatycznie, niech user oceni ręcznie
    if config.MAX_PRICE_EUR is not None and listing.price_eur > config.MAX_PRICE_EUR:
        return False
    if config.MIN_PRICE_EUR is not None and listing.price_eur < config.MIN_PRICE_EUR:
        return False
    return True


def _warm_rent_ok(listing: Listing) -> bool:
    """
    Górny limit czynszu z mediami (Warmmiete). Wypełniany dopiero po enrichmencie
    (wejście na podstronę oferty) - jeśli jeszcze go nie mamy (None), NIE odrzucamy
    oferty automatycznie, tylko czekamy aż dane się pojawią przy kolejnym przebiegu.
    """
    if listing.warm_rent_eur is None:
        return True
    if config.MAX_WARM_RENT_EUR is not None and listing.warm_rent_eur > config.MAX_WARM_RENT_EUR:
        return False
    return True


def _size_ok(listing: Listing) -> bool:
    """Minimalna powierzchnia. Brak danych o powierzchni - nie odrzucaj."""
    if listing.size_sqm is None:
        return True
    if config.MIN_SIZE_SQM is not None and listing.size_sqm <= config.MIN_SIZE_SQM:
        return False
    return True


def _rooms_ok(listing: Listing) -> bool:
    if listing.rooms is None:
        return True
    if config.MIN_ROOMS is not None and listing.rooms < config.MIN_ROOMS:
        return False
    if config.MAX_ROOMS is not None and listing.rooms > config.MAX_ROOMS:
        return False
    return True


def _separate_rooms_ok(listing: Listing) -> bool:
    if not config.REQUIRE_SEPARATE_ROOMS:
        return True
    text = (listing.title + " " + listing.raw_description).lower()
    red_flags = ["offene wohnküche", "1-zimmer-wohnung offen", "loftcharakter", "studio-wohnung"]
    return not any(flag in text for flag in red_flags)


def _bathroom_ok(listing: Listing) -> bool:
    if config.REQUIRE_BATHROOM is None:
        return True
    if listing.has_bathroom is None:
        return True  # brak informacji - nie odrzucaj, tylko oznacz "?" w wynikach
    return listing.has_bathroom == config.REQUIRE_BATHROOM


def _kitchen_ok(listing: Listing) -> bool:
    if config.REQUIRE_KITCHEN is None:
        return True
    if listing.has_kitchen is None:
        return True
    return listing.has_kitchen == config.REQUIRE_KITCHEN


def _location_ok(listing: Listing) -> bool:
    # Niektóre portale (np. Kleinanzeigen) już podają odległość od centrum wyszukiwania -
    # jeśli tak, ufamy tej wartości zamiast dogeokodowywać adres od nowa.
    if listing.distance_km is not None:
        return listing.distance_km <= config.MAX_DISTANCE_KM
    ok, distance = within_radius(listing.location_text)
    listing.distance_km = distance
    return ok


def apply_all_filters(listings: List[Listing]) -> List[Listing]:
    checks = [
        _price_ok, _warm_rent_ok, _size_ok, _rooms_ok,
        _separate_rooms_ok, _bathroom_ok, _kitchen_ok, _location_ok,
    ]
    result = []
    for listing in listings:
        if all(check(listing) for check in checks):
            result.append(listing)
    return result
