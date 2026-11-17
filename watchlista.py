"""Watchlista: pokazuje, jak daleko spółki są od swoich szczytów.

Uruchomienie:  .venv/bin/python watchlista.py
Ze stroną WWW: .venv/bin/python watchlista.py --html _site/index.html
"""

import argparse
import json
import logging
import os
import urllib.request
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

# Grupy aktywów (jak w spolki.txt, linie "## GRUPA") i ich progi spadku od lokalnego szczytu (w %).
# Przekroczenie progu = etykieta "przyjrzyj się" (kolor czerwony) i powiadomienie na telefon.
PROGI_GRUP = {
    "TRZON": 15,     # duże, stabilne spółki i ETF-y
    "SREDNIE": 25,
    "OKAZJE": 40,    # mniejsze spółki, kupowane okazyjnie
    "KRYPTO": 30,
}
NAZWY_GRUP = {"TRZON": "Trzon", "SREDNIE": "Średnie", "OKAZJE": "Okazje", "KRYPTO": "Krypto"}
ZOLTY_OD = 0.5           # kolor żółty od połowy progu grupy (np. TRZON: spadek > 7,5%)
PROG_DZIEN = 5           # powiadomienie, gdy spółka zmieni się w ciągu dnia o więcej niż tyle %

# Pasek rynku na górze strony: (nazwa, ticker w Yahoo, jednostka).
# Yahoo nie ma ceny spot uranu — Sprott Physical Uranium Trust (SRUUF) trzyma fizyczny uran i podąża za spotem.
RYNEK = [
    ("Uran (SPUT)", "SRUUF", "USD"),
    ("Złoto", "GC=F", "USD/oz"),
    ("Srebro", "SI=F", "USD/oz"),
    ("Ropa Brent", "BZ=F", "USD/bbl"),
    ("Miedź", "HG=F", "USD/lb"),
    ("USD/PLN", "USDPLN=X", ""),
    ("GBP/PLN", "GBPPLN=X", ""),
]

# Powiadomienia na telefon przez ntfy.sh. Nazwa kanału NIE jest w kodzie: skrypt bierze ją
# ze zmiennej środowiskowej NTFY_TOPIC (na GitHubie: sekret repozytorium). Bez niej — brak powiadomień.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
ADRES_STRONY = "https://jaceknowak0407.github.io/watchlista/"   # link w powiadomieniu

# Pliki leżą obok skryptu, więc skrypt działa z dowolnego katalogu.
FOLDER = Path(__file__).parent
PLIK_SPOLEK = FOLDER / "spolki.txt"
PLIK_SZABLONU = FOLDER / "szablon.html"   # wygląd strony WWW
STREFA = ZoneInfo("Europe/Warsaw")

console = Console()

# Wyciszamy techniczne komunikaty yfinance — własne, czytelne komunikaty pokazujemy sami.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


# ---------------------------------------------------------------
# Lista spółek
# ---------------------------------------------------------------
def wczytaj_aktywa(sciezka):
    """Czyta spolki.txt i zwraca listę czwórek (ticker, nazwa, grupa, sektor)."""
    aktywa = []
    grupa = "TRZON"
    for linia in sciezka.read_text(encoding="utf-8").splitlines():
        linia = linia.strip()
        if linia.startswith("##"):
            grupa = linia.lstrip("#").strip().upper()   # nagłówek grupy, np. "## OKAZJE"
            if grupa not in PROGI_GRUP:
                console.print(f"[yellow]⚠ Nieznana grupa „{grupa}” w spolki.txt — dodaj ją do PROGI_GRUP[/yellow]")
            continue
        if not linia or linia.startswith("#"):
            continue  # pomijamy puste linie i komentarze
        ticker, _, reszta = linia.partition("#")
        nazwa, _, sektor = reszta.partition("|")
        ticker = ticker.strip()
        # Tekst w nawiasie, np. "(cena w pensach GBp)", to tylko notatka — nie pokazujemy go w tabeli.
        nazwa = nazwa.split("(")[0].strip() or ticker
        aktywa.append((ticker, nazwa, grupa, sektor.strip() or "Inne"))
    return aktywa


def wczytaj_spolki(sciezka):
    """Same pary (ticker, nazwa) — używane przez newsy.py."""
    return [(t, n) for t, n, _, _ in wczytaj_aktywa(sciezka)]


def prog_grupy(grupa):
    return PROGI_GRUP.get(grupa, 20)   # 20% dla grupy spoza listy


def strefa(procent, grupa):
    """0 = spokojnie, 1 = zbliża się do progu (żółty), 2 = próg przekroczony (czerwony, "przyjrzyj się")."""
    prog = prog_grupy(grupa)
    if procent < -prog:
        return 2
    if procent < -prog * ZOLTY_OD:
        return 1
    return 0


# ---------------------------------------------------------------
# Notowania
# ---------------------------------------------------------------
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
    # Zmiana dzienna = ostatnie zamknięcie (lub bieżąca cena w trakcie sesji) vs poprzednie zamknięcie.
    poprzednia = float(zamkniecia.iloc[-2]) if len(zamkniecia) > 1 else cena

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
        "dzien": (cena / poprzednia - 1) * 100,
        "data_ceny": zamkniecia.index[-1].strftime("%d.%m.%Y"),
        "ath": ath,
        "data_ath": data_ath.strftime("%d.%m.%Y"),
        "szczyt": szczyt,
        "data_szczytu": data_szczytu.strftime("%d.%m.%Y"),
        "od_ath": (cena / ath - 1) * 100,
        "od_lokalnego": (cena / szczyt - 1) * 100,
        # Notowania z ostatnich N dni — do wykresu na stronie: [data, cena].
        "wykres": [[d.strftime("%Y-%m-%d"), round(float(v), 4)] for d, v in ostatnie.items()],
    }


def pobierz_rynek():
    """Ceny surowców i kursów walut do paska na górze strony."""
    wynik = []
    for nazwa, ticker, jednostka in RYNEK:
        try:
            zamkniecia = yf.Ticker(ticker).history(period="5d")["Close"].dropna()
            if len(zamkniecia) < 2:
                raise ValueError("za mało danych")
            cena, poprzednia = float(zamkniecia.iloc[-1]), float(zamkniecia.iloc[-2])
            wynik.append({"nazwa": nazwa, "ticker": ticker, "jednostka": jednostka,
                          "cena": cena, "dzien": (cena / poprzednia - 1) * 100})
        except Exception:
            console.print(f"[yellow]⚠ Pasek rynku: brak danych dla {nazwa} ({ticker})[/yellow]")
    return wynik


def pokoloruj(procent, grupa):
    """Zwraca tekst procentu z kolorem zależnym od progu grupy."""
    tekst = f"{procent:+.2f}%"
    kolor = {2: "red", 1: "yellow"}.get(strefa(procent, grupa))
    return f"[{kolor}]{tekst}[/{kolor}]" if kolor else tekst


def zbierz_wyniki():
    """Pobiera dane dla wszystkich spółek z pliku i zwraca je posortowane."""
    aktywa = wczytaj_aktywa(PLIK_SPOLEK)
    wyniki = []

    with console.status("Pobieram dane z Yahoo Finance...") as status:
        for ticker, nazwa, grupa, sektor in aktywa:
            status.update(f"Pobieram {ticker}...")
            try:
                dane = pobierz_dane(ticker)
            except Exception as blad:
                dane = None
                console.print(f"[yellow]⚠ {ticker}: błąd pobierania ({blad})[/yellow]")
            if dane is None:
                console.print(f"[yellow]⚠ {ticker} ({nazwa}): brak danych — pomijam[/yellow]")
                continue
            wyniki.append({
                "nazwa": nazwa, "ticker": ticker, "grupa": grupa, "sektor": sektor, **dane,
                "przyjrzyj": strefa(dane["od_lokalnego"], grupa) == 2,   # przekroczony próg grupy
            })

    # Kolejność grup jak w PROGI_GRUP, w grupie największy spadek od lokalnego szczytu na górze.
    kolejnosc = list(PROGI_GRUP)
    wyniki.sort(key=lambda w: (kolejnosc.index(w["grupa"]) if w["grupa"] in kolejnosc else 99, w["od_lokalnego"]))
    return wyniki


def pokaz_w_terminalu(wyniki):
    """Rysuje kolorową tabelę w terminalu."""
    tabela = Table(title=f"Watchlista (lokalny szczyt = ostatnie {LOKALNY_OKRES_DNI} dni)")
    tabela.add_column("Grupa", style="magenta")
    tabela.add_column("Nazwa", no_wrap=True)
    tabela.add_column("Ticker", style="cyan")
    tabela.add_column("Waluta")
    tabela.add_column("Cena", justify="right", style="bold")
    tabela.add_column("Dziś", justify="right")
    tabela.add_column(f"Szczyt {LOKALNY_OKRES_DNI}d", justify="right")
    tabela.add_column("Data szczytu", justify="right", style="dim")
    tabela.add_column("ATH", justify="right")
    tabela.add_column("Data ATH", justify="right", style="dim")
    tabela.add_column("% od ATH", justify="right")
    tabela.add_column(f"% od szczytu {LOKALNY_OKRES_DNI}d", justify="right")
    tabela.add_column("Próg", justify="right", style="dim")
    tabela.add_column("Uwaga")

    for w in wyniki:
        kolor_dnia = "green" if w["dzien"] > 0 else "red" if w["dzien"] < 0 else "white"
        tabela.add_row(
            NAZWY_GRUP.get(w["grupa"], w["grupa"]),
            w["nazwa"],
            w["ticker"],
            w["waluta"],
            f"{w['cena']:,.2f}",
            f"[{kolor_dnia}]{w['dzien']:+.2f}%[/{kolor_dnia}]",
            f"{w['szczyt']:,.2f}",
            w["data_szczytu"],
            f"{w['ath']:,.2f}",
            w["data_ath"],
            f"{w['od_ath']:+.2f}%",
            pokoloruj(w["od_lokalnego"], w["grupa"]),
            f"{prog_grupy(w['grupa'])}%",
            "[bold red]przyjrzyj się[/bold red]" if w["przyjrzyj"] else "",
        )

    console.print(tabela)


# ---------------------------------------------------------------
# Powiadomienia (ntfy.sh)
# ---------------------------------------------------------------
def wczytaj_poprzednie_dane(sciezka):
    """Czyta dane z poprzednio opublikowanej strony (do porównania, co się zmieniło)."""
    try:
        tekst = Path(sciezka).read_text(encoding="utf-8")
        return json.loads(tekst.split("const DANE = ", 1)[1].split(";\n", 1)[0].replace("<\\/", "</"))
    except (OSError, IndexError, ValueError):
        return None


def sprawdz_alerty(wyniki, poprzednie):
    """Porównuje obecne dane z poprzednimi. Zwraca (lista komunikatów, stan do zapamiętania)."""
    dzis = datetime.now(STREFA).strftime("%Y-%m-%d")
    stary_stan = (poprzednie or {}).get("alerty") or {}
    wyslane_dzis = set(stary_stan.get("wyslane", [])) if stary_stan.get("data") == dzis else set()

    if not poprzednie or "spolki" not in poprzednie:
        # Pierwsze uruchomienie: nie ma z czym porównać — tylko zapamiętujemy stan (bez zalewu powiadomień).
        return [], {"data": dzis, "wyslane": sorted(wyslane_dzis)}

    stare = {s["ticker"]: s for s in poprzednie["spolki"]}
    komunikaty = []
    for w in wyniki:
        t = w["ticker"]
        # 1) Aktywo przekroczyło próg spadku swojej grupy -> "przyjrzyj się".
        if t in stare and w["przyjrzyj"] and strefa(stare[t]["od_lokalnego"], w["grupa"]) < 2:
            komunikaty.append(f"🔴 Przyjrzyj się: {w['nazwa']} ({t}, {NAZWY_GRUP.get(w['grupa'], w['grupa'])}) — "
                              f"spadek > {prog_grupy(w['grupa'])}% od szczytu {LOKALNY_OKRES_DNI}d "
                              f"({w['od_lokalnego']:+.1f}%)")
        # 2) Duży ruch w ciągu dnia — najwyżej raz dziennie na spółkę.
        if abs(w["dzien"]) >= PROG_DZIEN and f"{t}:dzien" not in wyslane_dzis:
            ikona = "📈" if w["dzien"] > 0 else "📉"
            komunikaty.append(f"{ikona} {w['nazwa']} ({t}): {w['dzien']:+.1f}% dziś, "
                              f"cena {w['cena']:,.2f} {w['waluta']}")
            wyslane_dzis.add(f"{t}:dzien")
    return komunikaty, {"data": dzis, "wyslane": sorted(wyslane_dzis)}


def wyslij_powiadomienie(komunikaty):
    """Wysyła jedno zbiorcze powiadomienie na telefon przez ntfy.sh."""
    if not komunikaty:
        console.print("Powiadomienia: brak nowych alertów")
        return
    console.print(f"Powiadomienia: {len(komunikaty)} alert(y):")
    for k in komunikaty:
        console.print("  " + k)
    if not NTFY_TOPIC:
        console.print("[yellow]⚠ Brak NTFY_TOPIC — nie wysyłam na telefon.[/yellow]")
        return
    tresc = json.dumps({
        "topic": NTFY_TOPIC,
        "title": f"Watchlista: {len(komunikaty)} alert(y)",
        "message": "\n".join(komunikaty),
        "click": ADRES_STRONY,
        "tags": ["chart_with_downwards_trend"],
    }).encode("utf-8")
    zapytanie = urllib.request.Request("https://ntfy.sh/", data=tresc, method="POST",
                                       headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(zapytanie, timeout=20).close()
        console.print("Wysłano powiadomienie na telefon.")
    except Exception as blad:
        console.print(f"[yellow]⚠ Nie udało się wysłać powiadomienia ({blad})[/yellow]")


# ---------------------------------------------------------------
# Strona WWW
# ---------------------------------------------------------------
def zapisz_html(wyniki, rynek, alerty, sciezka):
    """Wkłada dane do szablonu strony (szablon.html) i zapisuje gotową stronę."""
    sektory = []
    for _, _, _, sektor in wczytaj_aktywa(PLIK_SPOLEK):
        if sektor not in sektory:
            sektory.append(sektor)   # kolejność jak w spolki.txt
    dane = {
        "aktualizacja": datetime.now(STREFA).strftime("%d.%m.%Y %H:%M"),
        "dni": LOKALNY_OKRES_DNI,
        # Grupy z progami — w kolejności sekcji na stronie.
        "grupy": [{"id": g, "nazwa": NAZWY_GRUP.get(g, g), "prog": p} for g, p in PROGI_GRUP.items()],
        "zolty_od": ZOLTY_OD,
        "sektory": sektory,
        "rynek": rynek,
        "spolki": wyniki,
        "alerty": alerty,   # pamięć wysłanych powiadomień (dla kolejnego uruchomienia)
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
        # Poprzednia wersja strony (jeśli istnieje) służy do wykrycia zmian -> powiadomienia.
        poprzednie = wczytaj_poprzednie_dane(argumenty.html)
        komunikaty, alerty = sprawdz_alerty(wyniki, poprzednie)
        wyslij_powiadomienie(komunikaty)
        zapisz_html(wyniki, pobierz_rynek(), alerty, argumenty.html)


if __name__ == "__main__":
    main()
