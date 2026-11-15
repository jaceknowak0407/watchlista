"""Watchlista: pokazuje, jak daleko spółki są od swoich szczytów.

Uruchomienie:  .venv/bin/python watchlista.py
"""

import logging
import warnings
from datetime import timedelta
from pathlib import Path

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
    cena = zamkniecia.iloc[-1]
    od_kiedy = zamkniecia.index[-1] - timedelta(days=LOKALNY_OKRES_DNI)
    lokalny_szczyt = zamkniecia[zamkniecia.index >= od_kiedy].max()

    return {
        "waluta": waluta,
        "ath": ath,
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


def main():
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

    tabela = Table(title=f"Watchlista (lokalny szczyt = ostatnie {LOKALNY_OKRES_DNI} dni)")
    tabela.add_column("Nazwa", no_wrap=True)
    tabela.add_column("Ticker", style="cyan")
    tabela.add_column("Waluta")
    tabela.add_column("ATH", justify="right")
    tabela.add_column("Cena", justify="right")
    tabela.add_column("% od ATH", justify="right")
    tabela.add_column(f"% od szczytu {LOKALNY_OKRES_DNI}d", justify="right")

    for w in wyniki:
        tabela.add_row(
            w["nazwa"],
            w["ticker"],
            w["waluta"],
            f"{w['ath']:,.2f}",
            f"{w['cena']:,.2f}",
            pokoloruj(w["od_ath"]),
            pokoloruj(w["od_lokalnego"]),
        )

    console.print(tabela)


if __name__ == "__main__":
    main()
