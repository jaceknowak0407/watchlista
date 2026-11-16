"""Newsy: zbiera wiadomości z Yahoo Finance i portali branżowych,
zostawia tylko te o Twoich spółkach i tematach (uran, krypto, złoto, ropa).

Uruchomienie:  .venv/bin/python newsy.py
Ze stroną WWW: .venv/bin/python newsy.py --html _site/newsy.html
"""

import argparse
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console

from watchlista import PLIK_SPOLEK, wczytaj_spolki

# ---------------------------------------------------------------
# USTAWIENIA — możesz je swobodnie zmieniać
# ---------------------------------------------------------------
NEWSY_Z_OSTATNICH_DNI = 3     # starsze wiadomości pomijamy
MAKS_NA_TEMAT = 80            # ile najwyżej newsów z jednego tematu (żeby krypto nie zalało reszty)

# Tematy i słowa kluczowe. Słowo pasuje, jeśli wyraz w tytule/opisie od niego się ZACZYNA
# (np. "uranium" pasuje też do "uranium's", "nuclear" do "nuclear-powered").
TEMATY = {
    "Uran": ["uranium", "nuclear", "yellowcake", "kazatomprom", "reactor", "smr",
             "uran", "atom", "jądrow", "elektrowni jądrow"],
    "Krypto": ["bitcoin", "btc", "crypto", "ethereum", "ether ", "stablecoin", "blockchain",
               "kryptowalut", "etf bitcoin"],
    "Złoto i srebro": ["gold", "silver", "precious metal", "bullion",
                       "złoto", "złota", "złocie", "złotem", "srebr", "kruszc"],
    "Ropa i gaz": ["oil", "crude", "brent", "wti", "opec", "natural gas", "lng", "refiner",
                   "ropa", "ropy", "ropie", "ropą", "naftow", "gaz ziemn", "paliw"],
}

# Wyrazy, które wyglądają jak temat, ale nim nie są (np. "Goldman Sachs" to nie złoto).
WYKLUCZ = ["Goldman"]

# Tytuły zawierające te frazy pomijamy całkiem (automatycznie generowany szum).
POMIJAJ_TYTULY = ["Prediction Market", "price prediction", "Price Prediction"]

# Portale z kanałami RSS (nazwa, adres). Dopisz własne, jeśli chcesz.
PORTALE = [
    ("Mining.com", "https://www.mining.com/feed/"),
    ("OilPrice.com", "https://oilprice.com/rss/main"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("World Nuclear News", "https://www.world-nuclear-news.org/rss"),
]

# Google News zbiera wiadomości z setek portali — wyszukiwania po angielsku i po polsku.
GOOGLE_NEWS = [
    ("en", "uranium OR \"nuclear fuel\""),
    ("en", "\"gold price\" OR \"silver price\" OR \"gold miners\""),
    ("en", "\"oil price\" OR OPEC OR \"crude oil\""),
    ("en", "bitcoin OR crypto market"),
    ("pl", "uran OR \"energetyka jądrowa\""),
    ("pl", "złoto OR srebro cena"),
    ("pl", "\"ropa naftowa\" OR OPEC"),
    ("pl", "bitcoin OR kryptowaluty"),
]

PLIK_SZABLONU = Path(__file__).parent / "szablon_newsy.html"

# Tłumaczenie tytułów EN -> PL przez DeepL API Free. Klucz NIE jest w kodzie: skrypt bierze go
# ze zmiennej środowiskowej DEEPL_API_KEY (na GitHubie: sekret repozytorium o tej nazwie).
# Bez klucza tytuły zostają po angielsku.
DEEPL_KLUCZ = os.environ.get("DEEPL_API_KEY", "").strip()
STATUS_TLUMACZENIA = ""   # krótki opis wyniku tłumaczenia — pokazywany w stopce strony
# Zwykła przeglądarkowa nazwa klienta — niektóre portale odrzucają zapytania bez niej.
NAGLOWKI = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) watchlista-rss"}

console = Console()


# ---------------------------------------------------------------
# Pobieranie i czytanie kanałów RSS
# ---------------------------------------------------------------
def pobierz_rss(url):
    """Pobiera kanał RSS i zwraca listę słowników {tytul, link, opis, czas, zrodlo_rss}."""
    zapytanie = urllib.request.Request(url, headers=NAGLOWKI)
    with urllib.request.urlopen(zapytanie, timeout=20) as odp:
        korzen = ET.fromstring(odp.read())

    wpisy = []
    for item in korzen.iter("item"):
        tytul = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not tytul or not link.startswith("http"):
            continue
        try:
            czas = parsedate_to_datetime(item.findtext("pubDate") or "")
            if czas.tzinfo is None:
                czas = czas.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        opis = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")  # bez znaczników HTML
        zrodlo = item.find("source")   # Google News podaje tu nazwę portalu
        wpisy.append({
            "tytul": tytul,
            "link": link,
            "opis": " ".join(opis.split())[:300],
            "czas": czas,
            "portal": zrodlo.text.strip() if zrodlo is not None and zrodlo.text else "",
        })
    return wpisy


def lista_zrodel(spolki):
    """Buduje listę wszystkich kanałów do pobrania: (nazwa, url, język, ticker albo None)."""
    zrodla = []
    # Yahoo Finance: osobny kanał dla każdej spółki z listy.
    for ticker, _ in spolki:
        url = "https://feeds.finance.yahoo.com/rss/2.0/headline?" + urllib.parse.urlencode(
            {"s": ticker, "region": "US", "lang": "en-US"})
        zrodla.append(("Yahoo Finance", url, "en", ticker))
    for nazwa, url in PORTALE:
        zrodla.append((nazwa, url, "en", None))
    for jezyk, fraza in GOOGLE_NEWS:
        if jezyk == "pl":
            parametry = {"q": fraza + " when:2d", "hl": "pl", "gl": "PL", "ceid": "PL:pl"}
        else:
            parametry = {"q": fraza + " when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"}
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(parametry)
        zrodla.append(("Google News", url, jezyk, None))
    return zrodla


# ---------------------------------------------------------------
# Dopasowanie do tematów i spółek
# ---------------------------------------------------------------
def wzorzec(slowa):
    """Jedno wyrażenie regularne: którekolwiek słowo na początku wyrazu."""
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(s) for s in slowa) + ")", re.IGNORECASE)


WZORCE_TEMATOW = {temat: wzorzec(slowa) for temat, slowa in TEMATY.items()}
WZORZEC_WYKLUCZ = wzorzec(WYKLUCZ)


def wzorce_spolek(spolki):
    """Dla każdej spółki: wzorzec szukający jej nazwy (lub tickera) w tytule."""
    wzorce = {}
    for ticker, nazwa in spolki:
        if "-" in ticker:          # np. BTC-USD — tym zajmuje się temat "Krypto"
            continue
        # "BHP Group" -> "BHP", "Yellow Cake plc" -> "Yellow Cake"; ETF-y pomijamy (rzadko w tytułach).
        krotka = re.sub(r"\s+(Group|plc|Inc\.?|Corp\.?)$", "", nazwa, flags=re.IGNORECASE)
        if "ETF" in krotka:
            continue
        czesci = [re.escape(krotka)]
        if " " in krotka:   # "Exxon Mobil" pasuje też do "ExxonMobil"
            czesci.append(re.escape(krotka.replace(" ", "")))
        # Ticker wielkimi literami (min. 3 znaki), np. "CCJ", "UUUU" — krótsze typu "EU", "MO" dają fałszywe trafienia.
        sam_ticker = ticker.split(".")[0]
        if len(sam_ticker) >= 3:
            czesci.append(r"(?-i:\b" + re.escape(sam_ticker) + r"\b)")
        wzorce[ticker] = re.compile(r"(?<!\w)(" + "|".join(czesci) + r")(?!\w)", re.IGNORECASE)
    return wzorce


def normalizuj(tytul):
    """Uproszczony tytuł — do wykrywania tej samej wiadomości z kilku źródeł."""
    return re.sub(r"[^a-ząćęłńóśźż0-9]+", "", tytul.lower())[:70]


# ---------------------------------------------------------------
# Główna logika
# ---------------------------------------------------------------
def zbierz_newsy():
    spolki = wczytaj_spolki(PLIK_SPOLEK)
    zrodla = lista_zrodel(spolki)
    wz_spolek = wzorce_spolek(spolki)
    granica = datetime.now(timezone.utc) - timedelta(days=NEWSY_Z_OSTATNICH_DNI)

    def pobierz(zrodlo):
        nazwa, url, jezyk, ticker = zrodlo
        try:
            return zrodlo, pobierz_rss(url)
        except Exception as blad:
            opis = ticker or nazwa
            console.print(f"[yellow]⚠ {opis}: nie udało się pobrać newsów ({type(blad).__name__})[/yellow]")
            return zrodlo, []

    with console.status(f"Pobieram newsy z {len(zrodla)} kanałów..."):
        with ThreadPoolExecutor(max_workers=8) as pula:
            wyniki = list(pula.map(pobierz, zrodla))

    newsy = {}
    for (nazwa, _, jezyk, ticker), wpisy in wyniki:
        for w in wpisy:
            if w["czas"] < granica:
                continue
            tytul = w["tytul"]
            portal = w["portal"]
            if nazwa == "Google News" and portal and tytul.endswith(" - " + portal):
                tytul = tytul[: -len(" - " + portal)]   # Google dokleja nazwę portalu do tytułu
            if not portal:
                portal = nazwa
            if nazwa == "Yahoo Finance":
                domena = urllib.parse.urlparse(w["link"]).netloc.replace("www.", "")
                portal = "Yahoo Finance" + (f" · {domena}" if domena and "yahoo" not in domena else "")

            if any(f.lower() in tytul.lower() for f in POMIJAJ_TYTULY):
                continue
            tekst = tytul + " " + w["opis"]
            tekst_tematow = WZORZEC_WYKLUCZ.sub(" ", tekst)
            tematy = [t for t, wz in WZORCE_TEMATOW.items() if wz.search(tekst_tematow)]
            # Spółki rozpoznajemy po nazwie w TYTULE (w opisach wspomina się je często przy okazji).
            # Kanał Yahoo danej spółki zawiera też ogólne newsy — zostaną tylko, jeśli pasują do Twoich tematów.
            spolki_w_newsie = {t for t, wz in wz_spolek.items() if wz.search(tytul)}
            if not tematy and not spolki_w_newsie:
                continue   # nie dotyczy Twoich zainteresowań

            klucz = normalizuj(tytul)
            if klucz in newsy:   # ta sama wiadomość z innego źródła — łączymy etykiety
                stary = newsy[klucz]
                stary["tematy"] = sorted(set(stary["tematy"]) | set(tematy))
                stary["spolki"] = sorted(set(stary["spolki"]) | spolki_w_newsie)
                continue
            newsy[klucz] = {
                "tytul": tytul,
                "link": w["link"],
                "portal": portal,
                "jezyk": jezyk,
                "czas": w["czas"],
                "tematy": sorted(tematy),
                "spolki": sorted(spolki_w_newsie),
            }

    # Od najnowszych; każdy temat ma swój limit, newsy o Twoich spółkach zostają zawsze.
    lista, ile_tematu = [], {t: 0 for t in TEMATY}
    for n in sorted(newsy.values(), key=lambda n: n["czas"], reverse=True):
        if not n["spolki"] and all(ile_tematu[t] >= MAKS_NA_TEMAT for t in n["tematy"]):
            continue
        for t in n["tematy"]:
            ile_tematu[t] += 1
        lista.append(n)
    for n in lista:
        n["czas"] = n["czas"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return lista, spolki


def pokaz_w_terminalu(newsy):
    """Wypisuje najnowsze wiadomości w terminalu."""
    console.print(f"\n[bold]Newsy z ostatnich {NEWSY_Z_OSTATNICH_DNI} dni: {len(newsy)}[/bold]")
    for temat in TEMATY:
        console.print(f"  {temat}: {sum(temat in n['tematy'] for n in newsy)}")
    console.print(f"  Moje spółki: {sum(bool(n['spolki']) for n in newsy)}\n")
    for n in newsy[:15]:
        czas = datetime.strptime(n["czas"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        czas = czas.astimezone(ZoneInfo("Europe/Warsaw")).strftime("%d.%m %H:%M")
        etykiety = ", ".join(n["spolki"] + n["tematy"])
        console.print(f"[dim]{czas}[/dim] {n['tytul']} [cyan]({etykiety})[/cyan] [dim]— {n['portal']}[/dim]")


# ---------------------------------------------------------------
# Tłumaczenie tytułów na polski (DeepL)
# ---------------------------------------------------------------
def wczytaj_stare_tlumaczenia(sciezka):
    """Czyta poprzednio zapisaną stronę z newsami i zwraca {tytuł angielski: tytuł polski}.
    Dzięki temu tłumaczymy tylko NOWE tytuły i oszczędzamy darmowy limit DeepL."""
    try:
        tekst = Path(sciezka).read_text(encoding="utf-8")
        dane_json = tekst.split("const DANE = ", 1)[1].split(";\n", 1)[0].replace("<\\/", "</")
        newsy = json.loads(dane_json)["newsy"]
    except (OSError, IndexError, ValueError, KeyError):
        return {}
    return {n["tytul_en"]: n["tytul"] for n in newsy if n.get("tytul_en")}


def tlumacz_deepl(teksty):
    """Wysyła teksty do DeepL (po 50 naraz) i zwraca listę tłumaczeń w tej samej kolejności."""
    # Klucze darmowego planu kończą się na ":fx" i mają osobny adres.
    adres = "https://api-free.deepl.com/v2/translate" if DEEPL_KLUCZ.endswith(":fx") \
        else "https://api.deepl.com/v2/translate"
    wynik = []
    for i in range(0, len(teksty), 50):
        paczka = teksty[i:i + 50]
        cialo = json.dumps({"text": paczka, "source_lang": "EN", "target_lang": "PL"}).encode("utf-8")
        zapytanie = urllib.request.Request(adres, data=cialo, method="POST", headers={
            "Authorization": "DeepL-Auth-Key " + DEEPL_KLUCZ,
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(zapytanie, timeout=30) as odp:
            wynik += [t["text"] for t in json.loads(odp.read())["translations"]]
    return wynik


def przetlumacz_tytuly(newsy, poprzednia_strona):
    """Zamienia angielskie tytuły na polskie; oryginał zostaje w polu "tytul_en"."""
    global STATUS_TLUMACZENIA
    angielskie = [n for n in newsy if n["jezyk"] == "en"]
    stare = wczytaj_stare_tlumaczenia(poprzednia_strona) if poprzednia_strona else {}

    nowe = []
    for n in angielskie:
        if n["tytul"] in stare:
            n["tytul_en"], n["tytul"] = n["tytul"], stare[n["tytul"]]
        else:
            nowe.append(n)
    console.print(f"Tłumaczenia: {len(angielskie) - len(nowe)} z pamięci, {len(nowe)} nowych tytułów")

    STATUS_TLUMACZENIA = f"z pamięci {len(angielskie) - len(nowe)}, nowe {len(nowe)}"
    if not nowe:
        return
    if not DEEPL_KLUCZ:
        STATUS_TLUMACZENIA += " — brak klucza DEEPL_API_KEY"
        console.print("[yellow]⚠ Brak klucza DEEPL_API_KEY — nowe tytuły zostają po angielsku.[/yellow]")
        return
    try:
        tlumaczenia = tlumacz_deepl([n["tytul"] for n in nowe])
    except Exception as blad:
        # np. 403 = zły klucz, 456 = wyczerpany miesięczny limit
        STATUS_TLUMACZENIA += f" — błąd DeepL: {blad} (klucz kończy się na :fx? {DEEPL_KLUCZ.endswith(':fx')})"
        console.print(f"[yellow]⚠ DeepL: tłumaczenie nie powiodło się ({blad}) — tytuły po angielsku.[/yellow]")
        return
    znaki = sum(len(n["tytul"]) for n in nowe)
    for n, pl in zip(nowe, tlumaczenia):
        n["tytul_en"], n["tytul"] = n["tytul"], pl
    STATUS_TLUMACZENIA += f" — przetłumaczono ({znaki} znaków)"
    console.print(f"Przetłumaczono {len(nowe)} tytułów ({znaki} znaków z limitu DeepL)")


def zapisz_html(newsy, spolki, sciezka):
    """Wkłada dane do szablonu szablon_newsy.html i zapisuje gotową podstronę."""
    dane = {
        "aktualizacja": datetime.now(ZoneInfo("Europe/Warsaw")).strftime("%d.%m.%Y %H:%M"),
        "dni": NEWSY_Z_OSTATNICH_DNI,
        "tlumaczenie": STATUS_TLUMACZENIA,
        "tematy": list(TEMATY),
        "nazwy_spolek": {t: n for t, n in spolki},
        "newsy": newsy,
    }
    dane_json = json.dumps(dane, ensure_ascii=False).replace("</", "<\\/")
    strona = PLIK_SZABLONU.read_text(encoding="utf-8").replace("__DANE__", dane_json)
    sciezka = Path(sciezka)
    sciezka.parent.mkdir(parents=True, exist_ok=True)
    sciezka.write_text(strona, encoding="utf-8")
    console.print(f"Zapisano stronę: {sciezka}")


def main():
    parser = argparse.ArgumentParser(description="Newsy o spółkach z watchlisty")
    parser.add_argument("--html", metavar="PLIK", help="zapisz też stronę HTML do podanego pliku")
    argumenty = parser.parse_args()

    newsy, spolki = zbierz_newsy()
    # Poprzednia wersja strony (jeśli istnieje) służy jako pamięć gotowych tłumaczeń.
    przetlumacz_tytuly(newsy, argumenty.html)
    pokaz_w_terminalu(newsy)
    if argumenty.html:
        zapisz_html(newsy, spolki, argumenty.html)


if __name__ == "__main__":
    main()
