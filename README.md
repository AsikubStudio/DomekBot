# immo-bot

Bot do przeszukiwania ofert mieszkań na wynajem w Niemczech (ImmoScout24, Immowelt,
Kleinanzeigen, WG-Gesucht) wg zadanych kryteriów. Uruchamiany ręcznie, nic nie
działa w tle ani cyklicznie.

## Domyślne kryteria (edytowalne w `config.py`)

- Kaltmiete max **650 €**
- **2 pokoje**, oddzielne (odrzuca oferty opisane jako otwarte studio)
- Lokalizacja: **Emmerich am Rhein** lub do **~42 minut jazdy autem** (w stronę Kleve) -
  liczone przez OpenRouteService, patrz Krok 3c niżej
- Łazienka: preferowana/wymagana
- Kuchnia: nieistotna

## Instalacja

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Użycie

```bash
python main.py
```

Opcje:

```bash
python main.py --site immoscout24   # tylko jeden portal, do debugowania selektorów
python main.py --no-save            # nie zapisuj wyników do pliku (domyślnie zapisuje do results/)
```

Wyniki lądują w konsoli oraz (domyślnie) w `results/wyniki_<data>.json` i `.csv`.

## Jak dopasować kryteria

Wszystko w `config.py` — cena, liczba pokoi, próg czasu dojazdu (`MAX_DRIVE_TIME_MINUTES`),
wymagania co do łazienki/kuchni, lista znanych miejscowości (fallback gdy geokodowanie
i OpenRouteService jednocześnie zawiodą).

## Gdy scraper przestaje działać

To normalne — portale nieruchomości regularnie zmieniają HTML/CSS, żeby utrudnić
scraping. Objawy: "0 kart" w logu dla danego portalu.

1. Otwórz stronę wyników wyszukiwania w przeglądarce.
2. F12 → zakładka Elements → znajdź kartę pojedynczego ogłoszenia.
3. Porównaj klasy CSS / atrybuty `data-testid` z tymi w `scrapers/<portal>.py`.
4. Zaktualizuj selektory (`soup.select(...)`) w odpowiednim pliku.

Każdy portal ma swój osobny plik w `scrapers/`, więc naprawa jednego nie rusza
pozostałych. Jeden zepsuty scraper nie wywala całego bota (błędy są łapane i
logowane w `main.py::run_scrapers`).

**ImmoScout24** ma najsilniejszą ochronę anty-bot (Cloudflare/PerimeterX) i może
zwracać 403 nawet z poprawnymi selektorami. Jeśli to się utrzymuje, jedyne sensowne
obejścia to: prawdziwa przeglądarka (Playwright/Selenium) albo ręczne sprawdzanie
tego portalu od czasu do czasu.

## Uwagi prawne / etyczne (nie jestem prawnikiem, to nie jest porada prawna)

- Scraping stron z ich Warunkami Korzystania (ToS) bywa sprzeczny z tymi warunkami
  nawet jeśli dane są publicznie widoczne — warto samodzielnie sprawdzić ToS każdego
  portalu, jeśli planujesz częstsze/komercyjne użycie.
- Ten bot jest ustawiony na użycie ręczne, jednorazowe uruchomienia — nie odpytuje
  serwerów w pętli ani nie działa jako usługa w tle, co zmniejsza obciążenie
  serwerów portali i ryzyko zablokowania IP.
- `REQUEST_DELAY_SECONDS` w `config.py` celowo wprowadza odstęp między requestami —
  nie zmniejszaj go bezmyślnie.

## Struktura projektu

```
immo-bot/
├── config.py                    # WSZYSTKIE kryteria wyszukiwania - edytuj tutaj
├── models.py                     # model danych Listing
├── filters.py                     # logika filtrowania (cena/pokoje/lokalizacja/wyposażenie)
├── publish.py                     # zapis docs/data/latest.json + pamięć "co już widziano"
├── notify.py                      # powiadomienia Telegram o nowych ofertach
├── main.py                         # CLI - punkt wejścia
├── scrapers/
│   ├── base.py                     # wspólne narzędzia HTTP + parsowanie tekstu
│   ├── immoscout24.py
│   ├── immowelt.py
│   ├── kleinanzeigen.py
│   └── wg_gesucht.py               # nieużywany domyślnie (ENABLED_SCRAPERS w config.py)
├── utils/
│   └── geo.py                      # liczenie odległości (geokodowanie OpenStreetMap + fallback)
├── .github/workflows/scrape.yml    # harmonogram GitHub Actions (co 3h)
├── data/seen_ids.json              # pamięć bota między uruchomieniami (commitowane)
└── docs/                            # strona GitHub Pages
    ├── index.html                   # frontend - czyta data/latest.json, auto-odświeża się
    ├── sw.js                         # Service Worker - obsługa powiadomień push
    ├── manifest.json                 # PWA - "dodaj do ekranu głównego"
    ├── icon-192.png / icon-512.png
    └── data/latest.json              # wyniki bota - nadpisywane przez GitHub Actions
```

## Pomysły na rozwój (opcjonalnie, na przyszłość)

- Playwright zamiast `requests` dla portali z silną ochroną anty-bot, jeśli GitHub Actions
  zacznie dostawać blokady (patrz sekcja "Ograniczenia" niżej).

---

## Automatyzacja: GitHub Actions + GitHub Pages + Telegram

Ten projekt jest już skonfigurowany żeby działać **w pełni automatycznie w chmurze**, za darmo:

- **GitHub Actions** odpala bota co 3 godziny (`.github/workflows/scrape.yml`) i commituje
  świeże wyniki z powrotem do repo (`docs/data/latest.json`).
- **GitHub Pages** serwuje statyczną stronę (`docs/index.html`), która czyta ten plik i
  pokazuje oferty - zawsze aktualne, bez żadnego ręcznego kroku.
- **Telegram** dostaje wiadomość, gdy pojawi się **nowa** pasująca oferta (dzięki
  `data/seen_ids.json`, który pamięta co już było).

### Krok 1 - wrzuć repo na GitHub

```bash
# w folderze immo-bot
git remote add origin https://github.com/<twoj-login>/immo-bot.git
git branch -M main
git push -u origin main
```

Jeśli nie masz jeszcze repo na GitHubie - stwórz nowe (Public, bez README/licencji, bo już je masz) na github.com/new, potem powyższe komendy.

### Krok 2 - włącz GitHub Pages

Settings → Pages → Source: **Deploy from a branch** → Branch: **main**, folder: **/docs** → Save.

Po chwili strona będzie dostępna pod `https://<twoj-login>.github.io/immo-bot/`.

### Krok 3 - (opcjonalnie, ale polecane) skonfiguruj powiadomienia Telegram

1. Otwórz Telegram, wyszukaj **@BotFather**, wyślij `/newbot` i postępuj wg instrukcji.
   Dostaniesz **token** (ciąg znaków typu `123456789:ABC-...`) - to Twój `TELEGRAM_BOT_TOKEN`.
2. Wyślij do swojego nowego bota dowolną wiadomość (np. "cześć") - inaczej bot nie będzie
   mógł Ci odpisać.
3. W przeglądarce otwórz:
   `https://api.telegram.org/bot<TWOJ_TOKEN>/getUpdates`
   Znajdź w odpowiedzi JSON pole `"chat":{"id": ...}` - ta liczba to Twój `TELEGRAM_CHAT_ID`.
4. W repo na GitHubie: Settings → Secrets and variables → Actions → **New repository secret**,
   dodaj dwa sekrety:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

Jeśli pominiesz ten krok, wszystko inne działa normalnie - po prostu nie dostaniesz powiadomień
(bot wykrywa brak tych zmiennych i po cichu pomija wysyłkę).

### Krok 3b - (opcjonalnie) prawdziwe powiadomienia push na telefon

Zamiast/obok Telegrama możesz dostawać powiadomienia wyglądające jak z natywnej appki -
banner na ekranie telefonu, bez pośrednictwa Telegrama. To wymaga jednorazowej konfiguracji:

1. Otwórz stronę (`https://<twoj-login>.github.io/immo-bot/`) **na telefonie**, najlepiej
   po dodaniu jej do ekranu głównego (patrz Krok 5) - na iOS powiadomienia push działają
   tylko gdy strona jest otwarta jako dodana ikona, nie w zwykłej karcie Safari.
2. Kliknij **"Włącz powiadomienia"** w panelu na górze strony i zaakceptuj zgodę przeglądarki.
3. Pojawi się pole tekstowe z danymi subskrypcji (JSON) - skopiuj całość.
4. W repo na GitHubie dodaj sekrety (Settings → Secrets and variables → Actions):
   - `PUSH_SUBSCRIPTION` - wklej to, co skopiowałeś w kroku 3
   - `VAPID_PRIVATE_KEY_PEM` - klucz prywatny wygenerowany specjalnie dla tej appki (wygenerowany
     razem z kluczem publicznym już wpisanym w `docs/index.html` - **nie zmieniaj jednego bez
     drugiego**, muszą być parą). Poproś o niego w rozmowie z Claude, jeśli go nie zapisałeś.
   - `VAPID_CLAIMS_EMAIL` *(opcjonalnie)* - dowolny adres w formacie `mailto:ty@example.com`,
     wymagany formalnie przez specyfikację Web Push. Jeśli pominiesz, użyty zostanie placeholder.

Uwaga: subskrypcja jest przypisana do jednej przeglądarki/urządzenia. Jeśli zmienisz telefon
albo wyczyścisz dane przeglądarki, powtórz kroki 1-4 z nowym urządzeniem.

**iOS (iPhone):** Web Push na Safari wymaga iOS 16.4+ i strony dodanej do ekranu głównego
("Do ekranu początkowego" w menu udostępniania) - powiadomienia nie zadziałają z poziomu
zwykłej karty przeglądarki.

### Krok 3c - klucz do OpenRouteService (czas dojazdu autem)

Filtr lokalizacji sprawdza czas dojazdu autem (nie odległość w linii prostej) przez
darmowe API OpenRouteService. Bez klucza bot i tak działa - automatycznie wraca na
starą metodę (odległość w linii prostej, `MAX_DISTANCE_KM_FALLBACK` w `config.py`) -
ale z kluczem filtrowanie jest dokładniejsze.

1. Załóż darmowe konto na [openrouteservice.org](https://openrouteservice.org/dev/#/signup)
   i wygeneruj klucz API (Dashboard → Request a token → "Standard", darmowy plan:
   2500 zapytań/dzień, w zupełności wystarczy).
2. **W chmurze (Kleinanzeigen przez GitHub Actions):** Settings → Secrets and variables →
   Actions → **New repository secret** → nazwa `ORS_API_KEY`, wartość: Twój klucz.
3. **Lokalnie (ImmoScout24 przez Task Scheduler):** stwórz plik `local_secrets/ors_api_key.txt`
   obok `main.py` i wklej do niego sam klucz (bez cudzysłowów) - ten folder jest w
   `.gitignore`, nigdy nie trafia do repo. Ten sam mechanizm jak dla lokalnych powiadomień
   Web Push (Krok 3b) - jeśli już masz folder `local_secrets/`, po prostu dodaj do niego
   ten jeden plik.

### Krok 4 - pierwsze uruchomienie

Zakładka **Actions** w repo na GitHubie → workflow "Szukaj mieszkań" → **Run workflow**
(przycisk po prawej) - żeby nie czekać do najbliższego zaplanowanego przebiegu. Potem workflow
odpala się już sam co 3 godziny.

### Krok 5 - dodaj stronę do ekranu głównego telefonu

Wejdź na `https://<twoj-login>.github.io/immo-bot/` w przeglądarce telefonu → menu przeglądarki →
"Dodaj do ekranu głównego" (Android/Chrome) lub "Do ekranu początkowego" (iOS/Safari, przycisk
udostępniania). Otworzy się jak osobna appka, bez paska adresu.

### Jak zmienić częstotliwość sprawdzania

Edytuj linię `cron:` w `.github/workflows/scrape.yml`. Przykłady:
- `"0 * * * *"` - co godzinę
- `"0 */6 * * *"` - co 6 godzin
- `"0 8,20 * * *"` - 2x dziennie, o 8:00 i 20:00 UTC

### Ograniczenia tego podejścia

- **Adresy IP GitHub Actions to adresy chmurowe (datacenter)**, które niektóre portale
  (zwłaszcza ImmoScout24) mogą blokować agresywniej niż zwykły domowy adres IP. Jeśli
  zauważysz w logach Actions częste błędy 403/401 na danym portalu mimo poprawnych
  selektorów, to najprawdopodobniej właśnie to - rozwiązaniem byłoby przejście na
  Playwright z technikami maskowania (jak w Twoim fragmencie z undetected-chromedriver),
  co jest możliwe, ale cięższe do utrzymania w CI (wymaga instalacji przeglądarki w
  workflow) - daj znać jeśli chcesz to dodać.
- GitHub Pages jest **publiczne** (chyba że masz płatny plan GitHub z prywatnymi Pages) -
  każdy ze znajomym linkiem zobaczy Twoje wyniki wyszukiwania (nie dane osobowe, tylko
  oferty mieszkań). Jeśli to problem, można dodać prostą ochronę hasłem po stronie
  klienta albo hostować gdzie indziej.
