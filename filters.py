"""
Filtrowanie listy ofert (Listing) wg kryteriów zdefiniowanych w config.py.
Każdy filtr jest osobną funkcją, żeby łatwo było dodać/wyłączyć/debugować pojedyncze kryterium.
"""
from typing import List
import config
from models import Listing
from utils.geo import evaluate_location, distance_from_sheerenberg_km


def _price_ok(listing: Listing) -> bool:
    if listing.price_eur is None:
        return True
    if config.MAX_PRICE_EUR is not None and listing.price_eur > config.MAX_PRICE_EUR:
        return False
    if config.MIN_PRICE_EUR is not None and listing.price_eur < config.MIN_PRICE_EUR:
        return False
    return True


def _warm_rent_ok(listing: Listing) -> bool:
    if listing.warm_rent_eur is None:
        return True
    if config.MAX_WARM_RENT_EUR is not None and listing.warm_rent_eur > config.MAX_WARM_RENT_EUR:
        return False
    return True


def _size_ok(listing: Listing) -> bool:
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
        return True
    return listing.has_bathroom == config.REQUIRE_BATHROOM


def _kitchen_ok(listing: Listing) -> bool:
    if config.REQUIRE_KITCHEN is None:
        return True
    if listing.has_kitchen is None:
        return True
    return listing.has_kitchen == config.REQUIRE_KITCHEN


def _location_ok(listing: Listing) -> bool:
    # GŁÓWNE kryterium to teraz czas dojazdu autem (nie km w linii prostej) -
    # patrz utils/geo.py::evaluate_location(). Jeśli portal już podał dystans
    # w linii prostej (np. Kleinanzeigen na karcie wyniku, listing.distance_km),
    # przekazujemy go dalej, żeby nie geokodować drugi raz tylko po to samo.
    ok, drive_minutes, distance_km = evaluate_location(listing.location_text, listing.distance_km)
    listing.drive_minutes = drive_minutes
    listing.distance_km = distance_km
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

    # Dystans do 's-Heerenberg liczymy TYLKO dla ofert, które już przeszły
    # wszystkie inne filtry - po co geokodować (i czekać 1s/request na Nominatim)
    # coś, co i tak zostanie odrzucone.
    for listing in result:
        listing.distance_sheerenberg_km = distance_from_sheerenberg_km(listing.location_text)

    return result
