"""Watchlista: pokazuje, jak daleko spółki są od swoich szczytów.

Uruchomienie:  .venv/bin/python watchlista.py
Ze stroną WWW: .venv/bin/python watchlista.py --html _site/index.html
"""

import argparse
import json
import logging
import warnings
from datetime import datetime, timedelta
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

# Pliki leżą obok skryptu, więc skrypt działa z dowolnego katalogu.
FOLDER = Path(__file__).parent
PLIK_SPOLEK = FOLDER / "spolki.txt"
PLIK_SZABLONU = FOLDER / "szablon.html"   # wygląd strony WWW

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

    cena = float(zamkniecia.iloc[-1])

    # ATH = najwyższe zamknięcie w całej historii (i dzień, w którym padło).
    ath = float(zamkniecia.max())
    data_ath = zamkniecia.idxmax()

    # Lokalny szczyt = najwyższe zamknięcie z ostatnich N dni.
    od_kiedy = zamkniecia.index[-1] - timedelta(days=LOKALNY_OKRES_DNI)
    ostatnie = zamkniecia[zamkniecia.index >= od_kiedy]
    szczyt = float(ostatnie.max())
    data_szczytu = ostatnie.idxmax()

    return {
        "waluta": waluta,
        "cena": cena,
        "ath": ath,
        "data_ath": data_ath.strftime("%d.%m.%Y"),
        "szczyt": szczyt,
        "data_szczytu": data_szczytu.strftime("%d.%m.%Y"),
        "od_ath": (cena / ath - 1) * 100,
        "od_lokalnego": (cena / szczyt - 1) * 100,
        # Notowania z ostatnich N dni — do wykresu na stronie: [data, cena].
        "wykres": [[d.strftime("%Y-%m-%d"), round(float(v), 4)] for d, v in ostatnie.items()],
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
    tabela = Table(title=f"Watchlista (lokalny szczyt = ostatnie {LOKALNY_OKRES_DNI} dni)")
    tabela.add_column("Nazwa", no_wrap=True)
    tabela.add_column("Ticker", style="cyan")
    tabela.add_column("Waluta")
    tabela.add_column("Cena", justify="right", style="bold")
    tabela.add_column(f"Szczyt {LOKALNY_OKRES_DNI}d", justify="right")
    tabela.add_column("Data szczytu", justify="right", style="dim")
    tabela.add_column("ATH", justify="right")
    tabela.add_column("Data ATH", justify="right", style="dim")
    tabela.add_column("% od ATH", justify="right")
    tabela.add_column(f"% od szczytu {LOKALNY_OKRES_DNI}d", justify="right")

    for w in wyniki:
        tabela.add_row(
            w["nazwa"],
            w["ticker"],
            w["waluta"],
            f"{w['cena']:,.2f}",
            f"{w['szczyt']:,.2f}",
            w["data_szczytu"],
            f"{w['ath']:,.2f}",
            w["data_ath"],
            pokoloruj(w["od_ath"]),
            pokoloruj(w["od_lokalnego"]),
        )

    console.print(tabela)


def zapisz_html(wyniki, sciezka):
    """Wkłada dane do szablonu strony (szablon.html) i zapisuje gotową stronę."""
    dane = {
        "aktualizacja": datetime.now(ZoneInfo("Europe/Warsaw")).strftime("%d.%m.%Y %H:%M"),
        "dni": LOKALNY_OKRES_DNI,
        "prog_czerwony": PROG_CZERWONY,
        "prog_zolty": PROG_ZOLTY,
        "spolki": wyniki,
    }
    # "<\/" zamiast "</" — żeby tekst z danych nie mógł przypadkiem zamknąć znacznika <script>.
    dane_json = json.dumps(dane, ensure_ascii=False).replace("</", "<\\/")
    strona = PLIK_SZABLONU.read_text(encoding="utf-8").replace("__DANE__", dane_json)

    sciezka = Path(sciezka)
    sciezka.parent.mkdir(parents=True, exist_ok=True)
    sciezka.write_text(strona, encoding="utf-8")
    console.print(f"Zapisano stronę: {sciezka}")


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
