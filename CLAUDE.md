# Watchlista

Prosty skrypt w Pythonie, który pobiera notowania z Yahoo Finance (yfinance) i pokazuje w terminalu
tabelę: nazwa | ticker | waluta | ATH | cena | % od ATH | % od lokalnego szczytu (ostatnie N dni).

## Pliki
- `watchlista.py` — cały program; ustawienia (`LOKALNY_OKRES_DNI`, progi kolorów) na górze pliku.
- `szablon.html` — wygląd strony WWW (karty + okienko z wykresem 90 dni, czysty JS/SVG bez bibliotek); Python wstawia dane JSON w miejsce `__DANE__`.
- `spolki.txt` — lista tickerów: `TICKER  # Nazwa`; tekst w nawiasie to notatka (nie jest wyświetlany).
- `.venv/` — wirtualne środowisko (nie w gicie); zależności w `requirements.txt` (yfinance, rich).

## Uruchamianie
`.venv/bin/python watchlista.py` (terminal), `--html _site/index.html` dodatkowo zapisuje stronę na telefon.
`.github/workflows/strona.yml` — GitHub Actions co 2h generuje stronę i publikuje ją na GitHub Pages (Python 3.12 na serwerze).

## Konwencje
- Użytkownik jest początkujący: kod prosty, komentarze i komunikaty po polsku.
- Ceny w GBp/GBX przeliczane na GBP. Brak danych dla tickera = komunikat i dalsze działanie.
- Systemowy Python 3.9 (macOS) — nie używać składni z nowszych wersji (np. `match`, `X | Y` w typach).
