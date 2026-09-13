"""
Powiadomienia o nowych ofertach - Telegram i/lub Web Push (prawdziwe powiadomienia
na ekranie telefonu, wyglądające jak z natywnej appki, wysyłane do strony PWA
w docs/index.html).

--- Telegram ---
Wymaga dwóch zmiennych środowiskowych (w GitHub Actions: repository secrets):
    TELEGRAM_BOT_TOKEN  - token bota od @BotFather
    TELEGRAM_CHAT_ID    - ID czatu/użytkownika, do którego wysyłać wiadomości

--- Web Push ---
Wymaga:
    PUSH_SUBSCRIPTION     - JSON subskrypcji, wygenerowany przez przycisk
                            "Włącz powiadomienia" na stronie (docs/index.html)
                            i wklejony jako sekret GitHub
    VAPID_PRIVATE_KEY_PEM - prywatny klucz VAPID (PEM) - wygenerowany raz,
                            NIE zmieniaj go bez ponownego wygenerowania klucza
                            publicznego w docs/index.html (muszą być parą)
    VAPID_CLAIMS_EMAIL    - opcjonalnie, kontakt w formacie "mailto:ty@example.com"
                            (wymóg specyfikacji VAPID, nie musi być prawdziwym adresem)

Jeśli odpowiednie zmienne nie są ustawione, dana metoda powiadomień jest po
cichu pomijana - main.py działa dalej normalnie.

--- Lokalne sekrety (tylko na komputerze, NIE w GitHub Actions) ---
Dla uruchomień lokalnych (np. ImmoScout24 przez Task Scheduler) zwykle nie ma
sensu ustawiać zmiennych środowiskowych systemowych. Zamiast tego, jeśli
PUSH_SUBSCRIPTION / VAPID_PRIVATE_KEY_PEM nie są ustawione w środowisku,
funkcje poniżej spróbują odczytać je z plików w folderze local_secrets/ obok
tego skryptu:
    local_secrets/push_subscription.json   - treść identyczna jak PUSH_SUBSCRIPTION
    local_secrets/vapid_private_key.pem    - treść identyczna jak VAPID_PRIVATE_KEY_PEM
Ten folder jest wpisany w .gitignore i nigdy nie trafia do repo.
Telegram celowo NIE ma takiego fallbacku z plików - lokalne uruchomienia mają
wysyłać tylko Web Push, bez Telegrama (chyba że ktoś ustawi zmienne środowiskowe
ręcznie).
"""
import os
import json
import logging
import tempfile

import requests

logger = logging.getLogger("immo-bot")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_LISTINGS_IN_MESSAGE = 10  # zeby nie przekroczyc limitu dlugosci wiadomosci Telegrama
DEFAULT_VAPID_CLAIMS_EMAIL = "mailto:example@example.com"

LOCAL_SECRETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_secrets")


def _read_local_secret(filename: str) -> str | None:
    path = os.path.join(LOCAL_SECRETS_DIR, filename)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        return content or None
    except OSError:
        return None


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


def send_web_push(title: str, body: str, url: str = "./") -> bool:
    """Wysyła jedno powiadomienie push do zarejestrowanej przeglądarki (PWA)."""
    sub_json = os.environ.get("PUSH_SUBSCRIPTION") or _read_local_secret("push_subscription.json")
    vapid_private_pem = os.environ.get("VAPID_PRIVATE_KEY_PEM") or _read_local_secret("vapid_private_key.pem")
    claims_email = os.environ.get("VAPID_CLAIMS_EMAIL", DEFAULT_VAPID_CLAIMS_EMAIL)

    if not sub_json or not vapid_private_pem:
        logger.info(
            "Web Push: brak PUSH_SUBSCRIPTION/VAPID_PRIVATE_KEY_PEM w środowisku "
            "ani w local_secrets/ - pomijam."
        )
        return False

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.warning("Web Push: pakiet 'pywebpush' nie jest zainstalowany (dodaj do requirements.txt).")
        return False

    try:
        subscription_info = json.loads(sub_json)
    except json.JSONDecodeError:
        logger.warning("Web Push: PUSH_SUBSCRIPTION nie jest poprawnym JSON-em - pomijam.")
        return False

    # pywebpush oczekuje ścieżki do pliku PEM, więc zapisujemy sekret tymczasowo na dysk.
    key_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
            f.write(vapid_private_pem)
            key_path = f.name

        webpush(
            subscription_info=subscription_info,
            data=json.dumps({"title": title, "body": body, "url": url}),
            vapid_private_key=key_path,
            vapid_claims={"sub": claims_email},
        )
        return True
    except WebPushException as exc:
        logger.warning("Web Push: nie udało się wysłać powiadomienia: %s", exc)
        return False
    finally:
        if key_path and os.path.exists(key_path):
            os.unlink(key_path)


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
        logger.info("Powiadomienia: brak nowych ofert od ostatniego uruchomienia.")
        return

    # --- Telegram (wiadomość ze szczegółami każdej oferty) ---
    if len(new_listings) == 1:
        send_telegram_message(_format_one(new_listings[0]))
    else:
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

    # --- Web Push (krótki banner na telefonie, klik otwiera stronę z listą) ---
    if len(new_listings) == 1:
        l = new_listings[0]
        title = "🏠 Nowa oferta"
        body = f"{l.price_eur or '?'} € · {l.rooms or '?'} pok. · {l.source}"
    else:
        title = f"🏠 {len(new_listings)} nowych ofert"
        cheapest = min((l for l in new_listings if l.price_eur is not None), key=lambda l: l.price_eur, default=None)
        body = f"Od {cheapest.price_eur} €" if cheapest else "Sprawdź szczegóły na stronie."
    send_web_push(title, body, url="./")
