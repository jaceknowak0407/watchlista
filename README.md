# Watchlista

Skrypt pokazuje w terminalu tabelę obserwowanych spółek: jak daleko każda jest od swojego
historycznego szczytu (ATH) i od lokalnego szczytu z ostatnich 90 dni.
Spadki powyżej 20% są na czerwono, powyżej 10% na żółto. Na górze tabeli są największe spadki.

## Wymagania
- macOS z `python3` (sprawdź: `python3 --version`). Jeśli go brak, wpisz `xcode-select --install`
  albo zainstaluj z https://www.python.org/downloads/
- Internet (dane pobierane są z Yahoo Finance).

## Instalacja (tylko raz)
```bash
cd ~/projekty/watchlista
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Uruchomienie
```bash
~/projekty/watchlista/.venv/bin/python ~/projekty/watchlista/watchlista.py
```

### Jeszcze prościej: komenda `watchlista`
Dopisz alias do pliku `~/.zshrc` (jednorazowo):
```bash
echo "alias watchlista='~/projekty/watchlista/.venv/bin/python ~/projekty/watchlista/watchlista.py'" >> ~/.zshrc
source ~/.zshrc
```
Od teraz w dowolnym oknie terminala wystarczy wpisać: `watchlista`

## Na telefonie (GitHub Pages)
Plik `.github/workflows/strona.yml` każe GitHubowi co 2 godziny uruchamiać skrypt
(`python watchlista.py --html _site/index.html`) i publikować wynik jako stronę
`https://<twoj-login>.github.io/watchlista/`. Strona odświeża się też po każdym `git push`.
Ręczne odświeżenie: na GitHubie zakładka **Actions** → „Odśwież stronę watchlisty” → **Run workflow**.

Na iPhonie: otwórz stronę w Safari → przycisk Udostępnij → **Do ekranu początkowego**.

Lokalny podgląd strony: `.venv/bin/python watchlista.py --html _site/index.html && open _site/index.html`

## Dostosowanie
- **Lista spółek** — edytuj `spolki.txt`: jeden ticker w linii, po `#` nazwa.
  Tickery sprawdzisz na https://finance.yahoo.com (np. giełda londyńska ma końcówkę `.L`).
- **Okres lokalnego szczytu** — w `watchlista.py` zmień `LOKALNY_OKRES_DNI = 90`.
- **Progi kolorów** — `PROG_CZERWONY` i `PROG_ZOLTY` w tym samym miejscu.

## Uwagi
- ATH liczone jest z cen zamknięcia (skorygowanych o splity, bez korekty o dywidendy).
- Ceny w pensach (GBp) są przeliczane na funty (GBP).
- Jeśli dla któregoś tickera nie ma danych, skrypt wypisze ostrzeżenie i pokaże resztę.
