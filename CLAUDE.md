# Watchlista

Prosty skrypt w Pythonie, który pobiera notowania z Yahoo Finance (yfinance) i pokazuje w terminalu
tabelę: nazwa | ticker | waluta | ATH | cena | % od ATH | % od lokalnego szczytu (ostatnie N dni).

## Pliki
- `watchlista.py` — cały program; ustawienia (`LOKALNY_OKRES_DNI`, progi kolorów) na górze pliku.
- `szablon.html` — wygląd strony WWW (karty + okienko z wykresem 90 dni, czysty JS/SVG bez bibliotek); Python wstawia dane JSON w miejsce `__DANE__`.
- `newsy.py` + `szablon_newsy.html` — podstrona Newsy: RSS z Yahoo Finance (kanał na ticker), portali (Mining.com, OilPrice, CoinDesk, Cointelegraph, WNN) i Google News EN/PL; filtr słów kluczowych `TEMATY` (Uran, Krypto, Złoto i srebro, Ropa i gaz) + nazwy spółek w tytule. Tylko biblioteka standardowa (urllib, ElementTree). Tytuły EN tłumaczone przez DeepL API Free (env `DEEPL_API_KEY`, sekret w GitHub Actions); cache tłumaczeń = poprzednia opublikowana newsy.html (pole `tytul_en`).
- `spolki.txt` — lista tickerów: `TICKER  # Nazwa`; tekst w nawiasie to notatka (nie jest wyświetlany).
- `.venv/` — wirtualne środowisko (nie w gicie); zależności w `requirements.txt` (yfinance, rich).

## Uruchamianie
`.venv/bin/python watchlista.py` (terminal), `--html _site/index.html` dodatkowo zapisuje stronę na telefon.
`.venv/bin/python newsy.py --html _site/newsy.html` — newsy.
`.github/workflows/strona.yml` — GitHub Actions co 2h generuje stronę i publikuje ją na GitHub Pages (Python 3.12 na serwerze).

## Konwencje
- Użytkownik jest początkujący: kod prosty, komentarze i komunikaty po polsku.
- Ceny w GBp/GBX przeliczane na GBP. Brak danych dla tickera = komunikat i dalsze działanie.
- Systemowy Python 3.9 (macOS) — nie używać składni z nowszych wersji (np. `match`, `X | Y` w typach).
