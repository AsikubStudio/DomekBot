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
REM data\drive_time_cache.json (trwaly cache czasu dojazdu OpenRouteService) moze
REM jeszcze NIE ISTNIEC na dysku (np. dopoki limit ORS jest wyczerpany). "git add"
REM z pathspecem ktory nie pasuje do zadnego pliku przerywa CALA komende, wiec
REM docs\data\latest.json i data\seen_ids.json (ktore istnieja zawsze) tez nigdy
REM by sie nie zacommitowaly. Dlatego dodajemy ten plik warunkowo.
git add docs\data\latest.json data\seen_ids.json
if exist data\drive_time_cache.json git add data\drive_time_cache.json
if exist data\job_commute_cache.json git add data\job_commute_cache.json
git diff --cached --quiet
if %errorlevel% equ 0 (
    echo Brak zmian - nic do zacommitowania.
) else (
    git commit -m "Aktualizacja ofert ImmoScout24 (lokalnie) %date% %time%"
    git pull --rebase
    git push
)

echo === Gotowe ===
