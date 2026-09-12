# immo-bot

Bot do przeszukiwania ofert mieszkań na wynajem w Niemczech (ImmoScout24, Immowelt,
Kleinanzeigen, WG-Gesucht) wg zadanych kryteriów. Uruchamiany ręcznie, nic nie
działa w tle ani cyklicznie.

## Domyślne kryteria (edytowalne w `config.py`)

- Kaltmiete max **650 €**
- **2 pokoje**, oddzielne (odrzuca oferty opisane jako otwarte studio)
- Lokalizacja: **Emmerich am Rhein** lub w promieniu **15 km** (w stronę Kleve)
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

Wszystko w `config.py` — cena, liczba pokoi, promień, wymagania co do łazienki/kuchni,
lista znanych miejscowości w promieniu (fallback gdy geokodowanie zawiedzie).

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
├── config.py           # WSZYSTKIE kryteria wyszukiwania - edytuj tutaj
├── models.py            # model danych Listing
├── filters.py            # logika filtrowania (cena/pokoje/lokalizacja/wyposażenie)
├── main.py                # CLI - punkt wejścia
├── scrapers/
│   ├── base.py            # wspólne narzędzia HTTP + parsowanie tekstu
│   ├── immoscout24.py
│   ├── immowelt.py
│   ├── kleinanzeigen.py
│   └── wg_gesucht.py
└── utils/
    └── geo.py             # liczenie odległości (geokodowanie OpenStreetMap + fallback)
```

## Pomysły na rozwój (opcjonalnie, na przyszłość)

- Zapamiętywanie już widzianych ofert (np. plik `seen_ids.json`), żeby przy kolejnym
  uruchomieniu pokazywało tylko **nowe** ogłoszenia od ostatniego razu.
- Powiadomienia (Telegram bot / e-mail) zamiast czytania w konsoli.
- Playwright zamiast `requests` dla portali z silną ochroną anty-bot (ImmoScout24).
