"""Watchlista: pokazuje, jak daleko spółki są od swoich szczytów.

Uruchomienie:  .venv/bin/python watchlista.py
Ze stroną WWW: .venv/bin/python watchlista.py --html _site/index.html
"""

import argparse
import logging
import warnings
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

# Wyciszamy niegroźne ostrzeżenie o starej bibliotece SSL w systemowym Pythonie macOS.
warnings.filterwarnings("ignore", message=".*OpenSSL.*")

import yfinance as yf
from rich.console import Console
from rich.table import Table

# ---------------------------------------------------------------
# USTAWIENIA — możesz je swobodnie zmieniać
# ---------------------------------------------------------------
LOKALNY_OKRES_DNI = 90   # "lokalny szczyt" = najwyższe zamknięcie z ostatnich N dni
PROG_CZERWONY = 20       # spadek większy niż tyle % -> kolor czerwony
PROG_ZOLTY = 10          # spadek większy niż tyle % -> kolor żółty

# Plik z listą spółek leży obok skryptu, więc skrypt działa z dowolnego katalogu.
PLIK_SPOLEK = Path(__file__).parent / "spolki.txt"

console = Console()

# Wyciszamy techniczne komunikaty yfinance — własne, czytelne komunikaty pokazujemy sami.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def wczytaj_spolki(sciezka):
    """Czyta plik spolki.txt i zwraca listę par (ticker, nazwa)."""
    spolki = []
    for linia in sciezka.read_text(encoding="utf-8").splitlines():
        linia = linia.strip()
        if not linia or linia.startswith("#"):
            continue  # pomijamy puste linie i komentarze
        ticker, _, nazwa = linia.partition("#")
        ticker = ticker.strip()
        # Tekst w nawiasie, np. "(cena w pensach GBp)", to tylko notatka — nie pokazujemy go w tabeli.
        nazwa = nazwa.split("(")[0].strip() or ticker
        spolki.append((ticker, nazwa))
    return spolki


def pobierz_dane(ticker):
    """Pobiera historię notowań i liczy wskaźniki. Zwraca słownik albo None."""
    t = yf.Ticker(ticker)
    historia = t.history(period="max", auto_adjust=False)
    if historia.empty or "Close" not in historia:
        return None
    zamkniecia = historia["Close"].dropna()
    if zamkniecia.empty:
        return None

    try:
        waluta = t.fast_info["currency"] or "?"
    except Exception:
        waluta = "?"

    # Notowania w pensach (GBp / GBX) przeliczamy na funty (GBP).
    if waluta in ("GBp", "GBX"):
        zamkniecia = zamkniecia / 100
        waluta = "GBP"

    ath = zamkniecia.max()
    data_ath = zamkniecia.idxmax()  # dzień, w którym padło ATH
    cena = zamkniecia.iloc[-1]
    od_kiedy = zamkniecia.index[-1] - timedelta(days=LOKALNY_OKRES_DNI)
    lokalny_szczyt = zamkniecia[zamkniecia.index >= od_kiedy].max()

    return {
        "waluta": waluta,
        "ath": ath,
        "data_ath": data_ath.strftime("%d.%m.%Y"),
        "cena": cena,
        "od_ath": (cena / ath - 1) * 100,
        "od_lokalnego": (cena / lokalny_szczyt - 1) * 100,
    }


def pokoloruj(procent):
    """Zwraca tekst procentu z kolorem zależnym od wielkości spadku."""
    tekst = f"{procent:+.2f}%"
    if procent < -PROG_CZERWONY:
        return f"[red]{tekst}[/red]"
    if procent < -PROG_ZOLTY:
        return f"[yellow]{tekst}[/yellow]"
    return tekst


def zbierz_wyniki():
    """Pobiera dane dla wszystkich spółek z pliku i zwraca je posortowane."""
    spolki = wczytaj_spolki(PLIK_SPOLEK)
    wyniki = []

    with console.status("Pobieram dane z Yahoo Finance...") as status:
        for ticker, nazwa in spolki:
            status.update(f"Pobieram {ticker}...")
            try:
                dane = pobierz_dane(ticker)
            except Exception as blad:
                dane = None
                console.print(f"[yellow]⚠ {ticker}: błąd pobierania ({blad})[/yellow]")
            if dane is None:
                console.print(f"[yellow]⚠ {ticker} ({nazwa}): brak danych — pomijam[/yellow]")
                continue
            wyniki.append({"nazwa": nazwa, "ticker": ticker, **dane})

    # Największy spadek od lokalnego szczytu na górze.
    wyniki.sort(key=lambda w: w["od_lokalnego"])
    return wyniki


def pokaz_w_terminalu(wyniki):
    """Rysuje kolorową tabelę w terminalu."""
    tabela =Table(title=f"Watchlista (lokalny szczyt = ostatnie {LOKALNY_OKRES_DNI} dni)")
    tabela.add_column("Nazwa", no_wrap=True)
    tabela.add_column("Ticker", style="cyan")
    tabela.add_column("Waluta")
    tabela.add_column("ATH", justify="right")
    tabela.add_column("Data ATH", justify="right")
    tabela.add_column("Cena", justify="right")
    tabela.add_column("% od ATH", justify="right")
    tabela.add_column(f"% od szczytu {LOKALNY_OKRES_DNI}d", justify="right")

    for w in wyniki:
        tabela.add_row(
            w["nazwa"],
            w["ticker"],
            w["waluta"],
            f"{w['ath']:,.2f}",
            w["data_ath"],
            f"{w['cena']:,.2f}",
            pokoloruj(w["od_ath"]),
            pokoloruj(w["od_lokalnego"]),
        )

    console.print(tabela)


def klasa_koloru(procent):
    """Nazwa klasy CSS dla strony HTML (ten sam podział co kolory w terminalu)."""
    if procent < -PROG_CZERWONY:
        return "czerwony"
    if procent < -PROG_ZOLTY:
        return "zolty"
    return ""


def kwota(liczba):
    """Formatuje cenę na stronę: duże kwoty bez groszy, żeby zmieściły się na telefonie."""
    if liczba >= 1000:
        return f"{liczba:,.0f}"
    return f"{liczba:,.2f}"


def zapisz_html(wyniki, sciezka):
    """Zapisuje tabelę jako stronę HTML wygodną do oglądania na telefonie."""
    teraz = datetime.now(ZoneInfo("Europe/Warsaw")).strftime("%d.%m.%Y %H:%M")
    wiersze = []
    for w in wyniki:
        wiersze.append(
            "<tr>"
            f"<td><b>{escape(w['nazwa'])}</b><small>{escape(w['ticker'])}</small></td>"
            f"<td class='l'>{kwota(w['cena'])}<small>{escape(w['waluta'])}</small></td>"
            f"<td class='l'>{kwota(w['ath'])}<small>{w['data_ath']}</small></td>"
            f"<td class='l {klasa_koloru(w['od_ath'])}'>{w['od_ath']:+.1f}%</td>"
            f"<td class='l {klasa_koloru(w['od_lokalnego'])}'>{w['od_lokalnego']:+.1f}%</td>"
            "</tr>"
        )
    strona = SZABLON_HTML.format(
        dni=LOKALNY_OKRES_DNI,
        teraz=teraz,
        wiersze="\n".join(wiersze),
    )
    sciezka = Path(sciezka)
    sciezka.parent.mkdir(parents=True, exist_ok=True)
    sciezka.write_text(strona, encoding="utf-8")
    console.print(f"Zapisano stronę: {sciezka}")


# Wygląd strony. Podwójne {{ }} to zwykłe nawiasy klamrowe w CSS (pojedyncze { } to miejsca na dane).
SZABLON_HTML = """<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Watchlista">
<title>Watchlista</title>
<style>
  :root {{ --tlo:#fff; --tekst:#111; --szary:#777; --linia:#e5e5e5;
          --czerwony:#d1242f; --zolty:#9a6700; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --tlo:#111; --tekst:#eee; --szary:#999; --linia:#2a2a2a;
            --czerwony:#ff6b6b; --zolty:#f0c040; }}
  }}
  body {{ margin:0; padding:16px 12px; background:var(--tlo); color:var(--tekst);
         font:15px -apple-system, system-ui, sans-serif; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  p {{ margin:0 0 12px; color:var(--szary); font-size:13px; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ text-align:left; font-size:12px; color:var(--szary); font-weight:600;
       padding:6px 4px; border-bottom:1px solid var(--linia); }}
  td {{ padding:8px 3px; border-bottom:1px solid var(--linia); vertical-align:top; }}
  .l {{ text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }}
  small {{ display:block; color:var(--szary); font-size:12px; font-weight:normal; }}
  .czerwony {{ color:var(--czerwony); font-weight:600; }}
  .zolty {{ color:var(--zolty); font-weight:600; }}
</style>
</head>
<body>
<h1>Watchlista</h1>
<p>Aktualizacja: {teraz} · szczyt lokalny = ostatnie {dni} dni</p>
<table>
<thead><tr><th>Spółka</th><th class="l">Cena</th><th class="l">ATH / data</th><th class="l">od ATH</th><th class="l">od {dni}d</th></tr></thead>
<tbody>
{wiersze}
</tbody>
</table>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Watchlista spółek")
    parser.add_argument("--html", metavar="PLIK", help="zapisz też stronę HTML do podanego pliku")
    argumenty = parser.parse_args()

    wyniki = zbierz_wyniki()
    pokaz_w_terminalu(wyniki)
    if argumenty.html:
        zapisz_html(wyniki, argumenty.html)


if __name__ == "__main__":
    main()
