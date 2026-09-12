@echo off
REM Uruchamia lokalna wersje ImmoScout24 (undetected-chromedriver) i wypycha
REM wyniki do repo, zeby GitHub Pages je pokazal razem z wynikami Kleinanzeigen
REM (ktore dokada osobno GitHub Actions w chmurze).
REM
REM Podepnij ten plik pod Windows Task Scheduler (np. co 3-4 godziny w ciagu dnia,
REM tylko kiedy komputer jest wlaczony - to normalne, ze czasem sie nie wykona).

cd /d "%~dp0"

echo === Pobieram najnowsze zmiany z repo ===
git pull --rebase

echo === Uruchamiam bota (tylko ImmoScout24, lokalnie) ===
python main.py --site immoscout24_local --no-save

echo === Zapisuje wyniki do repo ===
git add docs\data\latest.json data\seen_ids.json
git diff --cached --quiet
if %errorlevel% equ 0 (
    echo Brak zmian - nic do zacommitowania.
) else (
    git commit -m "Aktualizacja ofert ImmoScout24 (lokalnie) %date% %time%"
    git pull --rebase
    git push
)

echo === Gotowe ===