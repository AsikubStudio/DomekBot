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
import jobs_nl
import notify
import publish
from filters import apply_all_filters
from scrapers import REGISTRY
from utils.geo import commute_minutes_to_job, get_cached_job_commute_minutes

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


def _job_title_excluded(job: dict) -> bool:
    """True jeśli tytuł tej oferty pracy zawiera którąkolwiek z fraz z
    config.JOB_TITLE_EXCLUDE_KEYWORDS (bez rozróżniania wielkości liter,
    dopasowanie fragmentu). Dotyczy ofert z OBU źródeł (Holandia i Niemcy) -
    patrz config.py po komentarz i historię (dodane 21.09.2026, "forklift")."""
    title = (job.get("titel") or "").lower()
    return any(keyword.lower() in title for keyword in config.JOB_TITLE_EXCLUDE_KEYWORDS)


def _job_commute_allowed(listing_location: str, job: dict, lookups_budget: list) -> bool:
    """
    True jeśli ta oferta pracy mieści się w config.MAX_JOB_COMMUTE_MINUTES
    REALNEGO czasu dojazdu autem (ORS) od lokalizacji OFERTY MIESZKANIA -
    w odróżnieniu od promienia/najbliższej kotwicy używanych TYLKO do samego
    wyszukiwania (patrz jobs.py/jobs_nl.py), to jest filtr PO fakcie na
    faktycznej trasie. Dodane na wyraźną prośbę użytkownika 21.09.2026
    (przykład: oferta w Duiven dla mieszkania w Raesfeld mieściła się w
    promieniu wyszukiwania, ale realny dojazd to 52 min z Google Maps).

    lookups_budget to jednoelementowa lista (żeby dało się zmniejszać z
    wnętrza tej funkcji) - limituje NOWE (jeszcze niescache'owane) zapytania
    do ORS na cały przebieg (config.MAX_JOB_COMMUTE_LOOKUPS_PER_RUN), żeby
    to nie powtórzyło incydentu "Quota exceeded" opisanego przy
    DRIVE_TIME_CACHE_PATH w config.py. Cache-hity NIC nie kosztują z tego
    budżetu. Po wyczerpaniu budżetu, jeszcze niepoliczone oferty są
    traktowane jak "nieznany czas dojazdu" (patrz
    config.HIDE_JOB_IF_COMMUTE_UNKNOWN) i spróbują się policzyć w kolejnym
    przebiegu (3h w chmurze).
    """
    job_location = job.get("miejscowosc")
    job_country = job.get("kraj")
    if not job_location:
        return not config.HIDE_JOB_IF_COMMUTE_UNKNOWN

    cached = get_cached_job_commute_minutes(listing_location, job_location, job_country)
    if cached is not None:
        return cached <= config.MAX_JOB_COMMUTE_MINUTES

    if lookups_budget[0] <= 0:
        return not config.HIDE_JOB_IF_COMMUTE_UNKNOWN

    lookups_budget[0] -= 1
    minutes = commute_minutes_to_job(listing_location, job_location, job_country)
    if minutes is None:
        return not config.HIDE_JOB_IF_COMMUTE_UNKNOWN
    return minutes <= config.MAX_JOB_COMMUTE_MINUTES


def attach_nearby_jobs(listings) -> None:
    """
    Dla każdej dopasowanej oferty mieszkania szuka ofert pracy w pobliżu JEJ
    lokalizacji (nie Emmerich) - Holandia (jobs_nl.py, Adzuna) i Niemcy
    (jobs.py, Bundesagentur für Arbeit), scalone w JEDNĄ listę. Oferty z
    Holandii mają priorytet (użytkownik zdecydował 21.09.2026) - są na
    POCZĄTKU listy, więc pokazują się wyżej w dropdownie "Praca w pobliżu"
    na stronie (docs/index.html po prostu renderuje listę w tej kolejności).

    Oferty przechodzą DWA dodatkowe filtry (oba na OBU źródłach jednocześnie)
    zanim trafią do listing.nearby_jobs:
      1. Tytuł nie może pasować do config.JOB_TITLE_EXCLUDE_KEYWORDS -
         patrz _job_title_excluded() (np. "forklift", dodane 21.09.2026).
      2. Realny czas dojazdu autem (ORS) <= config.MAX_JOB_COMMUTE_MINUTES -
         patrz _job_commute_allowed() (dodane 21.09.2026 wieczorem, druga tura).

    Cache'owane po location_text w ramach jednego przebiegu, żeby kilka
    mieszkań w tej samej miejscowości nie odpytywało API kilka razy o to samo.
    """
    if not listings or not (config.JOB_SEARCH_NL_ENABLED or config.JOB_SEARCH_ENABLED):
        return

    lookups_budget = [config.MAX_JOB_COMMUTE_LOOKUPS_PER_RUN]
    cache: dict[str, list] = {}
    for listing in listings:
        key = listing.location_text
        if key not in cache:
            nl_jobs = jobs_nl.search_jobs_near_nl(key) if config.JOB_SEARCH_NL_ENABLED else []
            de_jobs = jobs.search_jobs_near(key) if config.JOB_SEARCH_ENABLED else []
            merged = nl_jobs + de_jobs  # NL pierwsze = wyższy priorytet w dropdownie
            after_title_filter = [job for job in merged if not _job_title_excluded(job)]
            cache[key] = [job for job in after_title_filter if _job_commute_allowed(key, job, lookups_budget)]
        listing.nearby_jobs = cache[key]

    total_jobs = sum(len(l.nearby_jobs) for l in listings)
    total_nl = sum(1 for l in listings for job in l.nearby_jobs if job.get("kraj") == "NL")
    commute_lookups_used = config.MAX_JOB_COMMUTE_LOOKUPS_PER_RUN - lookups_budget[0]
    logger.info(
        "Oferty pracy w pobliżu: %d unikalnych lokalizacji sprawdzonych, %d ofert pracy łącznie "
        "(%d z Holandii), po filtrze <=%d min dojazdu (%d nowych zapytań ORS w tym przebiegu, z limitu %d).",
        len(cache), total_jobs, total_nl,
        config.MAX_JOB_COMMUTE_MINUTES, commute_lookups_used, config.MAX_JOB_COMMUTE_LOOKUPS_PER_RUN,
    )


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
