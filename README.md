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

Na górze pasek rynku (uran, złoto, srebro, ropa, miedź, USD/PLN, GBP/PLN), pod nim sortowanie i filtr sektorów.
Każda spółka ma kartę (ze zmianą dzienną): cena z walutą, szczyt z ostatnich 90 dni (cena i data), ATH (cena i data).
Dotknięcie karty otwiera wykres z ostatnich 90 dni. Wygląd strony zmieniasz w `szablon.html`.

Na iPhonie: otwórz stronę w Safari → przycisk Udostępnij → **Do ekranu początkowego**.

Lokalny podgląd strony: `.venv/bin/python watchlista.py --html _site/index.html && open _site/index.html`

## Newsy
Zakładka **Newsy** zbiera wiadomości z ostatnich 3 dni z Yahoo Finance (dla każdej spółki z listy),
Mining.com, OilPrice.com, CoinDesk, Cointelegraph, World Nuclear News oraz z Google News
(po angielsku i po polsku). Zostają tylko te o Twoich spółkach albo tematach: uran, krypto,
złoto i srebro, ropa i gaz. Na stronie filtrujesz po temacie, spółce i języku.

Uruchomienie lokalnie: `.venv/bin/python newsy.py` (lista w terminalu) lub z `--html _site/newsy.html`.
Skróty newsów (lead artykułu) są na razie wyłączone — włączysz je ustawieniem `SKROTY = True` w `newsy.py`.
Angielskie tytuły są tłumaczone na polski przez **DeepL API Free** (oryginał widać pod spodem).
Klucz jest zapisany na GitHubie jako sekret `DEEPL_API_KEY` (Settings → Secrets and variables → Actions).
Tłumaczone są tylko nowe tytuły (stare skrypt bierze z poprzedniej wersji strony), więc darmowy
limit 500 000 znaków/mies. wystarcza. Zużycie: https://www.deepl.com/your-account/usage
Bez klucza lub po wyczerpaniu limitu tytuły zostają po angielsku.

Słowa kluczowe, tematy i listę portali zmieniasz na górze pliku `newsy.py`.

## Powiadomienia na telefon (ntfy)
Co 2 godziny skrypt sprawdza, czy któraś spółka weszła w strefę spadku > 10% / > 20% od szczytu
90 dni albo zmieniła się w ciągu dnia o ≥ 5% (`PROG_DZIEN`), i wysyła zbiorcze powiadomienie przez
darmową aplikację **ntfy**. Nazwa kanału jest zapisana na GitHubie jako sekret `NTFY_TOPIC`.

## Dostosowanie
- **Lista spółek** — edytuj `spolki.txt`: jeden ticker w linii, po `#` nazwa; linia `## Nazwa` zaczyna sektor.
  Tickery sprawdzisz na https://finance.yahoo.com (np. giełda londyńska ma końcówkę `.L`).
- **Okres lokalnego szczytu** — w `watchlista.py` zmień `LOKALNY_OKRES_DNI = 90`.
- **Progi kolorów** — `PROG_CZERWONY` i `PROG_ZOLTY` w tym samym miejscu.

## Uwagi
- ATH liczone jest z cen zamknięcia (skorygowanych o splity, bez korekty o dywidendy).
- Ceny w pensach (GBp) są przeliczane na funty (GBP).
- Jeśli dla któregoś tickera nie ma danych, skrypt wypisze ostrzeżenie i pokaże resztę.
