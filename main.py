#!/usr/bin/env python3
"""
Bot do przeszukiwania ofert mieszkań na wynajem w Niemczech.

Użycie:
    python main.py                  # uruchamia wszystkie włączone scrapery i pokazuje dopasowane oferty
    python main.py --site immoscout24   # tylko jeden portal (do debugowania)
    python main.py --no-save        # nie zapisuj wyników do pliku

Kryteria wyszukiwania edytujesz w config.py.
"""
from __future__ import annotations
import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime

import config
import jobs
import notify
import publish
from filters import apply_all_filters
from scrapers import REGISTRY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("immo-bot")


def parse_args():
    parser = argparse.ArgumentParser(description="Bot do wyszukiwania mieszkań w Niemczech")
    parser.add_argument(
        "--site",
        choices=list(REGISTRY.keys()),
        help="Uruchom tylko jeden portal (przydatne do debugowania selektorów)",
    )
    parser.add_argument("--no-save", action="store_true", help="Nie zapisuj wyników do pliku")
    return parser.parse_args()


def run_scrapers(only_site: str | None):
    all_listings = []
    for key, (label, search_fn) in REGISTRY.items():
        if only_site and key != only_site:
            continue
        if not only_site and not config.ENABLED_SCRAPERS.get(key, False):
            logger.info("Pomijam %s (wyłączony w config.ENABLED_SCRAPERS)", label)
            continue

        logger.info("Szukam na %s...", label)
        try:
            listings = search_fn()
            all_listings.extend(listings)
        except Exception as exc:  # nie pozwól, żeby jeden zepsuty scraper wywalił całość
            logger.error("Scraper %s zawiódł: %s", label, exc, exc_info=True)

    return all_listings


def print_results(listings):
    if not listings:
        print("\nBrak ofert spełniających kryteria. Spróbuj poluzować config.py "
              "(np. MAX_DRIVE_TIME_MINUTES albo REQUIRE_BATHROOM) albo sprawdź czy scrapery "
              "w ogóle zwracają dane (--site <nazwa> pojedynczo, żeby zdebugować).\n")
        return

    listings.sort(key=lambda l: (l.price_eur is None, l.price_eur or 0))

    print(f"\n=== Znaleziono {len(listings)} pasujących ofert ===\n")
    for l in listings:
        dist = f"{l.distance_km} km" if l.distance_km is not None else "? km"
        print(f"[{l.source}] {l.title}")
        print(f"  Cena: {l.price_eur or '?'} €  |  Pokoje: {l.rooms or '?'}  |  "
              f"Powierzchnia: {l.size_sqm or '?'} m²  |  Odległość: {dist}")
        print(f"  Lokalizacja: {l.location_text}")
        print(f"  Łazienka: {l.bool_label(l.has_bathroom)}  |  Kuchnia: {l.bool_label(l.has_kitchen)}")
        print(f"  Link: {l.url}")
        print()


def attach_nearby_jobs(listings) -> None:
    """
    Dla każdej dopasowanej oferty mieszkania szuka ofert pracy w pobliżu JEJ
    lokalizacji (nie Emmerich) - patrz jobs.py. Cache'owane po location_text w
    ramach jednego przebiegu, żeby kilka mieszkań w tej samej miejscowości nie
    odpytywało Bundesagentur API kilka razy o to samo.
    """
    if not config.JOB_SEARCH_ENABLED or not listings:
        return

    cache: dict[str, list] = {}
    for listing in listings:
        key = listing.location_text
        if key not in cache:
            cache[key] = jobs.search_jobs_near(key)
        listing.nearby_jobs = cache[key]

    total_jobs = sum(len(l.nearby_jobs) for l in listings)
    logger.info("Oferty pracy w pobliżu: %d unikalnych lokalizacji sprawdzonych, %d ofert pracy łącznie.",
                len(cache), total_jobs)


def save_results(listings):
    if not listings:
        return
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = os.path.join(config.OUTPUT_DIR, f"wyniki_{timestamp}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([l.as_row() for l in listings], f, ensure_ascii=False, indent=2)

    csv_path = os.path.join(config.OUTPUT_DIR, f"wyniki_{timestamp}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(listings[0].as_row().keys()))
        writer.writeheader()
        for l in listings:
            writer.writerow(l.as_row())

    logger.info("Zapisano wyniki: %s, %s", json_path, csv_path)


def main():
    args = parse_args()
    raw_listings = run_scrapers(args.site)
    logger.info("Łącznie surowych ofert ze wszystkich portali: %d", len(raw_listings))

    matched = apply_all_filters(raw_listings)
    print_results(matched)

    # Praca w pobliżu TYLKO dla ofert, które już przeszły wszystkie inne filtry -
    # patrz jobs.py i attach_nearby_jobs() wyżej.
    attach_nearby_jobs(matched)

    # Zawsze publikujemy najświeższe wyniki dla strony GitHub Pages i sprawdzamy,
    # co jest nowe od ostatniego uruchomienia (do powiadomienia Telegram).
    seen_ids = publish.load_seen_ids()
    new_listings, updated_ids = publish.split_new_listings(matched, seen_ids)
    publish.write_latest_json(matched, first_seen=updated_ids)
    publish.save_seen_ids(updated_ids)
    logger.info("Nowych ofert od ostatniego uruchomienia: %d", len(new_listings))
    notify.notify_new_listings(new_listings)

    if matched and config.SAVE_RESULTS_TO_FILE and not args.no_save:
        save_results(matched)


if __name__ == "__main__":
    main()
