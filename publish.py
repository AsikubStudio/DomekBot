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

   Od wprowadzenia sortowania "Najnowsze" na stronie, seen_ids to już nie zbiór
   (Set[str]) URLi, tylko słownik {url: data_pierwszego_zobaczenia_iso_lub_None}.
   Dzięki temu publish.py może dopisać do każdej oferty w latest.json znacznik
   "PierwszyRaz", po którym front-end sortuje. Stary format pliku (płaska lista
   URLi, sprzed tej zmiany) jest nadal wczytywany poprawnie - load_seen_ids()
   migruje go na {url: None}, a data pierwszego zobaczenia (None) jest
   uzupełniana "najlepszym dostępnym przybliżeniem" (czasem bieżącego
   uruchomienia) przy najbliższym razie, gdy dana oferta znów się pojawi
   w split_new_listings().
"""
import json
import os
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone

import config
from models import Listing

logger = logging.getLogger("immo-bot")


def load_seen_ids(path: str = None) -> Dict[str, Optional[str]]:
    path = path or config.SEEN_IDS_PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Nie udało się wczytać %s (%s) - zaczynam z pustą listą.", path, exc)
        return {}

    if isinstance(data, list):
        # Stary format (plaska lista URLi, sprzed dodania sortowania po dacie) -
        # migrujemy na słownik. Prawdziwa data pierwszego zobaczenia jest
        # nieznana, więc None - zostanie uzupełniona w split_new_listings()
        # przy najbliższym uruchomieniu, w którym dana oferta znów wystąpi.
        return {url: None for url in data}
    if isinstance(data, dict):
        return data
    logger.warning("Nieoczekiwany format %s - zaczynam z pustą listą.", path)
    return {}


def save_seen_ids(ids: Dict[str, Optional[str]], path: str = None) -> None:
    path = path or config.SEEN_IDS_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(ids.items())), f, ensure_ascii=False, indent=2)


def split_new_listings(
    listings: List[Listing], seen_ids: Dict[str, Optional[str]]
) -> Tuple[List[Listing], Dict[str, Optional[str]]]:
    """Zwraca (nowe_oferty, zaktualizowany_slownik_id_z_data_pierwszego_zobaczenia)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    new_listings = [l for l in listings if l.url not in seen_ids]

    updated_ids = dict(seen_ids)
    for l in listings:
        if not updated_ids.get(l.url):
            # Albo naprawdę nowa oferta, albo stary wpis zmigrowany ze
            # spłaszczonego formatu (wartość None) - w obu przypadkach
            # zapisujemy "teraz" jako najlepsze dostępne przybliżenie daty
            # pierwszego zobaczenia.
            updated_ids[l.url] = now_iso

    return new_listings, updated_ids


def write_latest_json(
    listings: List[Listing], path: str = None, first_seen: Dict[str, Optional[str]] = None
) -> None:
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

    first_seen (opcjonalny) to slownik {url: data_iso} - zazwyczaj to samo
    updated_ids zwrocone przez split_new_listings() w main.py. Kazdemu wierszowi
    z tego przebiegu dopisywany jest klucz "PierwszyRaz" na jego podstawie, zeby
    front-end mogl sortowac oferty od najnowszej. Jesli nie podano, "PierwszyRaz"
    wychodzi None (front-end traktuje to jak brak danych, tak jak inne pola).
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

    new_rows = []
    for l in listings:
        row = l.as_row()
        row["PierwszyRaz"] = (first_seen or {}).get(l.url)
        new_rows.append(row)

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
