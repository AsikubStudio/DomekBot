"""
Dwie odpowiedzialności potrzebne do automatyzacji (GitHub Actions + GitHub Pages):

1. write_latest_json() - zapisuje aktualne dopasowane oferty do pliku, który
   czyta statyczna strona w docs/index.html (GitHub Pages). Ten plik JEST
   commitowany do repo (w przeciwieństwie do results/, które jest w .gitignore) -
   dzięki temu strona zawsze pokazuje świeże dane bez żadnego ręcznego kroku.

2. load_seen_ids() / save_seen_ids() / split_new_listings() - pamięć "co już
   widzieliśmy" między uruchomieniami bota, żeby wysyłać powiadomienie Telegram
   tylko o NOWYCH ofertach, a nie za każdym razem o wszystkich pasujących.
   Identyfikatorem ogłoszenia jest jego URL (wystarczająco unikalny w praktyce).
"""
import json
import os
import logging
from typing import List, Set, Tuple
from datetime import datetime, timezone

import config
from models import Listing

logger = logging.getLogger("immo-bot")


def load_seen_ids(path: str = None) -> Set[str]:
    path = path or config.SEEN_IDS_PATH
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Nie udało się wczytać %s (%s) - zaczynam z pustą listą.", path, exc)
        return set()


def save_seen_ids(ids: Set[str], path: str = None) -> None:
    path = path or config.SEEN_IDS_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=2)


def split_new_listings(listings: List[Listing], seen_ids: Set[str]) -> Tuple[List[Listing], Set[str]]:
    """Zwraca (nowe_oferty, zaktualizowany_zbior_id)."""
    new_listings = [l for l in listings if l.url not in seen_ids]
    updated_ids = {l.url for l in listings} | seen_ids
    return new_listings, updated_ids


def write_latest_json(listings: List[Listing], path: str = None) -> None:
    """
    Zapisuje wyniki do pliku, ktory czyta strona GitHub Pages.

    WAZNE: to MERGE po polu "Portal", a nie zwykle nadpisanie. Dzieki temu jesli
    ten sam plik jest aktualizowany z dwoch niezaleznych miejsc (np. Kleinanzeigen
    z GitHub Actions w chmurze i ImmoScout24 lokalnie z Twojego komputera przez
    Windows Task Scheduler), kazde z nich nadpisuje TYLKO wlasne wyniki, a wyniki
    innego zrodla, wpisane przy poprzednim uruchomieniu, zostaja nietkniete.

    Dodatkowo zapisuje w kluczu "sources" znacznik czasu OSTATNIEGO zapisu KAZDEGO
    zrodla z osobna (nie tylko globalny "generated_at") - dzieki temu strona moze
    pokazac osobny zegar "ostatnio sprawdzono / kolejne sprawdzenie za..." dla
    Kleinanzeigen i dla ImmoScout24, mimo ze aktualizuja sie w zupelnie innym rytmie.
    """
    path = path or config.PUBLISH_JSON_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    existing_rows = []
    existing_sources = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                existing_rows = existing_data.get("listings", [])
                existing_sources = existing_data.get("sources", {})
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Nie udało się wczytać istniejącego %s (%s) - zaczynam od zera.", path, exc)

    sources_in_this_run = {l.source for l in listings}
    kept_rows = [row for row in existing_rows if row.get("Portal") not in sources_in_this_run]
    new_rows = [l.as_row() for l in listings]
    combined_rows = kept_rows + new_rows

    now_iso = datetime.now(timezone.utc).isoformat()
    for source in sources_in_this_run:
        existing_sources[source] = {
            "last_updated": now_iso,
            "interval_hours": config.SOURCE_REFRESH_INTERVAL_HOURS.get(source, 3),
        }

    payload = {
        "generated_at": now_iso,
        "count": len(combined_rows),
        "sources": existing_sources,
        "listings": combined_rows,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info("Zapisano %d ofert (%d nowych z tego przebiegu + %d zachowanych z innych źródeł) do %s.",
                len(combined_rows), len(new_rows), len(kept_rows), path)
