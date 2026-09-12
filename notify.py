"""
Powiadomienia Telegram o nowych ofertach.

Wymaga dwóch zmiennych środowiskowych - w GitHub Actions ustawianych jako
repository secrets (Settings > Secrets and variables > Actions):

    TELEGRAM_BOT_TOKEN  - token bota, dostajesz od @BotFather na Telegramie
    TELEGRAM_CHAT_ID    - ID czatu/konta, na które bot ma pisać

Jak je zdobyć - patrz README.md, sekcja "Powiadomienia Telegram".

Jeśli te zmienne nie są ustawione (np. odpalasz main.py lokalnie bez nich),
funkcje po prostu nic nie robią - main.py działa dalej normalnie.
"""
import os
import logging

import requests

logger = logging.getLogger("immo-bot")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_LISTINGS_IN_MESSAGE = 10  # zeby nie przekroczyc limitu dlugosci wiadomosci Telegrama


def _get_credentials():
    return os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")


def send_telegram_message(text: str) -> bool:
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        logger.info("Telegram: brak TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID w środowisku - pomijam powiadomienie.")
        return False

    try:
        resp = requests.post(
            TELEGRAM_API.format(token=token),
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.warning("Telegram: nie udało się wysłać powiadomienia: %s", exc)
        return False


def _format_one(listing) -> str:
    dist = f"{listing.distance_km} km" if listing.distance_km is not None else "? km"
    return (
        f"🏠 <b>Nowa oferta - {listing.source}</b>\n"
        f"{listing.title}\n"
        f"{listing.price_eur or '?'} € · {listing.rooms or '?'} pok. · "
        f"{listing.size_sqm or '?'} m² · {dist}\n"
        f"{listing.url}"
    )


def notify_new_listings(new_listings) -> None:
    if not new_listings:
        logger.info("Telegram: brak nowych ofert od ostatniego uruchomienia - bez powiadomienia.")
        return

    if len(new_listings) == 1:
        send_telegram_message(_format_one(new_listings[0]))
        return

    header = f"🏠 <b>{len(new_listings)} nowych ofert</b>\n\n"
    blocks = []
    for listing in new_listings[:MAX_LISTINGS_IN_MESSAGE]:
        dist = f"{listing.distance_km} km" if listing.distance_km is not None else "? km"
        blocks.append(
            f"• {listing.price_eur or '?'} € · {listing.rooms or '?'} pok. · {dist} · {listing.source}\n{listing.url}"
        )
    text = header + "\n\n".join(blocks)
    if len(new_listings) > MAX_LISTINGS_IN_MESSAGE:
        text += f"\n\n...i {len(new_listings) - MAX_LISTINGS_IN_MESSAGE} więcej - pełna lista na stronie."

    send_telegram_message(text)
