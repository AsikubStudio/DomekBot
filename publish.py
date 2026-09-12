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
    path = path or config.PUBLISH_JSON_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(listings),
        "listings": [l.as_row() for l in listings],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info("Zapisano %d ofert do %s (dla strony GitHub Pages).", len(listings), path)
