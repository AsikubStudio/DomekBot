@echo off
REM Uruchamia lokalna wersje ImmoScout24 (undetected-chromedriver) i wypycha
REM wyniki do repo, zeby GitHub Pages je pokazal razem z wynikami Kleinanzeigen
REM (ktore dokada osobno GitHub Actions w chmurze).
REM
REM Podepnij ten plik pod Windows Task Scheduler (np. co 3-4 godziny w ciagu dnia,
REM tylko kiedy komputer jest wlaczony - to normalne, ze czasem sie nie wykona).

cd /d "%~dp0"

echo === Sprzatam ewentualny zawieszony rebase z poprzedniego, nieudanego uruchomienia ===
REM Jesli poprzedni przebieg utknal w trakcie "git pull --rebase" / "git rebase" przy
REM konflikcie (np. bo chmura dopisala cos do docs\data\latest.json w tym samym momencie),
REM .git\rebase-merge (lub starszy format: rebase-apply) nadal by istnial, a HEAD
REM bylby "odlaczony" (detached) - kolejne uruchomienia scrapowalyby i commitowaly
REM poprawnie, ale NA TEN odlaczony HEAD, nigdy nie trafiajac na "main" ani na GitHub,
REM bez zadnego widocznego bledu (zwlaszcza w ukrytym oknie Task Schedulera). Dlatego
REM na starcie zawsze sprzatamy ewentualna pozostalosc, zanim cokolwiek zrobimy.
if exist ".git\rebase-merge" (
    echo Wykryto niedokonczony rebase sprzed tego uruchomienia - przerywam go.
    git rebase --abort
)
if exist ".git\rebase-apply" (
    echo Wykryto niedokonczony rebase sprzed tego uruchomienia - przerywam go.
    git rebase --abort
)

echo === Synchronizuje repo z GitHubem ===
REM WAZNE: celowo NIE "git reset --hard origin/main" tutaj. Ten skrypt .bat jest
REM SAM plikiem sledzonym przez git - "reset --hard" nadpisuje WSZYSTKIE sledzone
REM pliki w repo, wlacznie z TYM wlasnym plikiem .bat, cofajac go do wersji z
REM GitHuba w trakcie wlasnego wykonywania (przerabione na wlasnej skorze - jesli
REM wprowadzisz tu recznie poprawke i jej jeszcze nie wypchniesz, zadanie samo
REM sobie ja skasuje, zanim zdazy zadzialac). Zamiast tego robimy zwykly
REM "fast-forward" samego brancha (bezpieczny - git odmowi i nic nie ruszy, jesli
REM to nie byloby czystym przewinieciem do przodu), ktory NIE dotyka plikow
REM niezwiazanych ze zmianami z GitHuba - czyli tego skryptu nie tknie, dopoki
REM sam go nie zmienimy przez commit+push.
git fetch origin
git merge --ff-only origin/main
if errorlevel 1 (
    echo BLAD: lokalne repo nie daje sie prosto zrownac z origin/main ^(nie jest to
    echo czyste "fast-forward"^). To nietypowa sytuacja - sprawdz recznie
    echo "git status" i "git log --oneline --all --graph" zanim uruchomisz to
    echo zadanie ponownie. Przerywam ten przebieg, zeby nic nie popsuc.
    exit /b 1
)

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

    echo === Wypycham na GitHub ===
    git push
    if errorlevel 1 (
        echo Push nieudany - najpewniej chmura dopisala cos w miedzyczasie. Probuje raz jeszcze.
        git fetch origin
        git rebase origin/main
        if errorlevel 1 (
            echo Rebase przy ponawianiu tez sie nie powiodl - przerywam go i PORZUCAM
            echo wynik tego przebiegu, zeby NIE zostawic repo w zepsutym stanie na
            echo kolejne uruchomienia. Dane i tak zostana nadpisane swiezymi przy
            echo nastepnym udanym przebiegu.
            git rebase --abort
        ) else (
            git push
        )
    )
)

echo === Gotowe ===