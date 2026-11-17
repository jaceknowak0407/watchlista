"""Newsy: zbiera wiadomości z Yahoo Finance, Nasdaq i portali branżowych (EN i PL),
zostawia tylko te o Twoich spółkach i tematach (uran, krypto, złoto, ropa).

Uruchomienie:  .venv/bin/python newsy.py
Ze stroną WWW: .venv/bin/python newsy.py --html _site/newsy.html
"""

import argparse
import html
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
MAKS_DLUGOSC_SKROTU = 220     # skrót newsa (z opisu w RSS) — tyle znaków najwyżej
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
WYKLUCZ = ["Goldman", "Nuclear Sharing", "nuclear weapon", "nuclear deal", "broń jądrow", "broni jądrow"]

# Tytuły zawierające te frazy pomijamy całkiem (automatycznie generowany szum).
POMIJAJ_TYTULY = ["Prediction Market", "price prediction", "Price Prediction"]

# Portale z kanałami RSS: (nazwa, adres, język). Wszystkie podają lead artykułu,
# z którego robimy skrót. Dopisz własne, jeśli chcesz.
PORTALE = [
    # po angielsku
    ("Mining.com", "https://www.mining.com/feed/", "en"),
    ("OilPrice.com", "https://oilprice.com/rss/main", "en"),
    ("Rigzone", "https://www.rigzone.com/news/rss/rigzone_latest.aspx", "en"),
    ("World Nuclear News", "https://www.world-nuclear-news.org/rss", "en"),
    ("NucNet", "https://www.nucnet.org/feed.rss", "en"),
    ("FXStreet", "https://www.fxstreet.com/rss/news", "en"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss", "en"),
    ("Cointelegraph", "https://cointelegraph.com/rss", "en"),
    ("Decrypt", "https://decrypt.co/feed", "en"),
    ("Bitcoin Magazine", "https://bitcoinmagazine.com/.rss/full/", "en"),
    ("CryptoSlate", "https://cryptoslate.com/feed/", "en"),
    # po polsku
    ("Bankier.pl", "https://www.bankier.pl/rss/wiadomosci.xml", "pl"),
    ("WNP.pl", "https://www.wnp.pl/rss/serwis_rss.xml", "pl"),
    ("Business Insider PL", "https://businessinsider.com.pl/.feed", "pl"),
    ("Parkiet", "https://www.parkiet.com/rss_main", "pl"),
]

PLIK_SZABLONU = Path(__file__).parent / "szablon_newsy.html"

# Tłumaczenie tytułów EN -> PL przez DeepL API Free. Klucz NIE jest w kodzie: skrypt bierze go
# ze zmiennej środowiskowej DEEPL_API_KEY (na GitHubie: sekret repozytorium o tej nazwie).
# Bez klucza tytuły zostają po angielsku.
DEEPL_KLUCZ = os.environ.get("DEEPL_API_KEY", "").strip()
# Darmowy DeepL = 500 000 znaków/mies. Przy 12 odświeżeniach dziennie to ~1300 znaków na jedno uruchomienie.
DEEPL_ZNAKOW_NA_URUCHOMIENIE = 1300
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
        tytul = html.unescape(item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not tytul or not link.startswith("http"):
            continue
        try:
            czas = parsedate_to_datetime(item.findtext("pubDate") or "")
            if czas.tzinfo is None:
                czas = czas.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        opis = html.unescape(re.sub(r"<[^>]+>", " ", item.findtext("description") or ""))  # bez znaczników HTML
        zrodlo = item.find("source")   # Google News podaje tu nazwę portalu
        wpisy.append({
            "tytul": tytul,
            "link": link,
            "opis": " ".join(opis.split()),
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
    # Nasdaq: osobny kanał dla każdej spółki z USA (z leadami artykułów).
    for ticker, _ in spolki:
        if "-" in ticker or "." in ticker:   # BTC-USD, YCA.L — Nasdaq ich nie ma
            continue
        zrodla.append(("Nasdaq", "https://www.nasdaq.com/feed/rssoutbound?symbol=" + ticker, "en", ticker))
    for nazwa, url, jezyk in PORTALE:
        zrodla.append((nazwa, url, jezyk, None))
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


def zrob_skrot(opis, tytul):
    """Z opisu z RSS robi krótki skrót (do ~220 znaków). Pusty, jeśli opis nic nie wnosi."""
    # Usuwamy doklejone nagłówki sekcji, np. "Key TakeawaysCameco stock fell..." -> "Cameco stock fell..."
    opis = re.sub(r"^(Key Takeaways|Key Points|Highlights|Summary)\s*:?\s*", "", opis, flags=re.IGNORECASE)
    if len(opis) < 60 or normalizuj(opis)[:40] == normalizuj(tytul)[:40]:
        return ""   # brak opisu albo opis = powtórzony tytuł (tak robi np. Google News)
    if len(opis) <= MAKS_DLUGOSC_SKROTU:
        return opis
    # Tniemy na końcu zdania, a jeśli się nie da — na końcu wyrazu.
    ciecie = opis[:MAKS_DLUGOSC_SKROTU]
    kropka = max(ciecie.rfind(". "), ciecie.rfind("! "), ciecie.rfind("? "))
    if kropka > 80:
        return ciecie[:kropka + 1]
    return ciecie.rsplit(" ", 1)[0] + "…"


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
            skrot = zrob_skrot(w["opis"], tytul)
            if klucz in newsy:   # ta sama wiadomość z innego źródła — łączymy etykiety
                stary = newsy[klucz]
                stary["tematy"] = sorted(set(stary["tematy"]) | set(tematy))
                stary["spolki"] = sorted(set(stary["spolki"]) | spolki_w_newsie)
                if not stary["skrot"] and skrot:   # bierzemy skrót z tego źródła, które go ma
                    stary["skrot"] = skrot
                continue
            newsy[klucz] = {
                "tytul": tytul,
                "skrot": skrot,
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
    """Czyta poprzednio zapisaną stronę z newsami i zwraca {tekst angielski: tekst polski}
    (tytuły i skróty). Dzięki temu tłumaczymy tylko NOWE teksty i oszczędzamy limit DeepL."""
    try:
        tekst = Path(sciezka).read_text(encoding="utf-8")
        dane_json = tekst.split("const DANE = ", 1)[1].split(";\n", 1)[0].replace("<\\/", "</")
        newsy = json.loads(dane_json)["newsy"]
    except (OSError, IndexError, ValueError, KeyError):
        return {}
    pamiec = {}
    for n in newsy:
        if n.get("tytul_en"):
            pamiec[n["tytul_en"]] = n["tytul"]
        if n.get("skrot_en"):
            pamiec[n["skrot_en"]] = n["skrot"]
    return pamiec


def adres_deepl(sciezka):
    # Klucze darmowego planu kończą się na ":fx" i mają osobny adres.
    serwer = "https://api-free.deepl.com" if DEEPL_KLUCZ.endswith(":fx") else "https://api.deepl.com"
    return serwer + sciezka


def zuzycie_deepl():
    """Zwraca (zużyte znaki, miesięczny limit) dla klucza DeepL."""
    zapytanie = urllib.request.Request(adres_deepl("/v2/usage"),
                                       headers={"Authorization": "DeepL-Auth-Key " + DEEPL_KLUCZ})
    with urllib.request.urlopen(zapytanie, timeout=20) as odp:
        dane = json.loads(odp.read())
    return dane["character_count"], dane["character_limit"]


def tlumacz_deepl(teksty):
    """Wysyła teksty do DeepL (po 50 naraz) i zwraca listę tłumaczeń w tej samej kolejności."""
    wynik = []
    for i in range(0, len(teksty), 50):
        paczka = teksty[i:i + 50]
        cialo = json.dumps({"text": paczka, "source_lang": "EN", "target_lang": "PL"}).encode("utf-8")
        zapytanie = urllib.request.Request(adres_deepl("/v2/translate"), data=cialo, method="POST", headers={
            "Authorization": "DeepL-Auth-Key " + DEEPL_KLUCZ,
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(zapytanie, timeout=30) as odp:
            wynik += [t["text"] for t in json.loads(odp.read())["translations"]]
    return wynik


def przetlumacz_newsy(newsy, poprzednia_strona):
    """Tłumaczy angielskie tytuły i skróty na polski; oryginały zostają w polach *_en."""
    global STATUS_TLUMACZENIA
    pamiec = wczytaj_stare_tlumaczenia(poprzednia_strona) if poprzednia_strona else {}

    # Lista (news, pole) do przetłumaczenia: najpierw wszystkie tytuły, potem skróty
    # (gdy limit jest bliski wyczerpania, tłumaczymy tylko tytuły).
    angielskie = [n for n in newsy if n["jezyk"] == "en"]
    do_zrobienia = [(n, "tytul") for n in angielskie] + [(n, "skrot") for n in angielskie if n["skrot"]]
    nowe = []
    for n, pole in do_zrobienia:
        if n[pole] in pamiec:
            n[pole + "_en"], n[pole] = n[pole], pamiec[n[pole]]
        else:
            nowe.append((n, pole))
    # Kolejność: tytuły (najpierw o Twoich spółkach), potem skróty o Twoich spółkach, potem reszta skrótów.
    # W obrębie grupy najnowsze pierwsze (lista newsów jest już tak posortowana).
    nowe.sort(key=lambda np_: (np_[1] != "tytul", not np_[0]["spolki"]))
    STATUS_TLUMACZENIA = f"z pamięci {len(do_zrobienia) - len(nowe)}, nowe {len(nowe)}"
    console.print(f"Tłumaczenia: {STATUS_TLUMACZENIA} (tytuły + skróty)")
    if not nowe:
        return
    if not DEEPL_KLUCZ:
        STATUS_TLUMACZENIA += " — brak klucza DEEPL_API_KEY"
        console.print("[yellow]⚠ Brak klucza DEEPL_API_KEY — nowe teksty zostają po angielsku.[/yellow]")
        return

    try:
        # Pilnujemy darmowego limitu: zostawiamy 5% zapasu; w razie czego najpierw odpadają skróty.
        zuzyte, limit = zuzycie_deepl()
        wolne = min(int(limit * 0.95) - zuzyte, DEEPL_ZNAKOW_NA_URUCHOMIENIE)
        wybrane, znaki = [], 0
        for n, pole in nowe:
            if znaki + len(n[pole]) > wolne:
                continue   # nie mieści się w budżecie — przetłumaczy się przy następnym odświeżeniu
            wybrane.append((n, pole))
            znaki += len(n[pole])
        if not wybrane:
            STATUS_TLUMACZENIA += f" — limit DeepL wyczerpany ({zuzyte:,}/{limit:,} znaków)"
            console.print(f"[yellow]⚠ {STATUS_TLUMACZENIA}[/yellow]")
            return
        tlumaczenia = tlumacz_deepl([n[pole] for n, pole in wybrane])
    except Exception as blad:
        # np. 403 = zły klucz, 456 = wyczerpany miesięczny limit
        STATUS_TLUMACZENIA += f" — błąd DeepL: {blad} (klucz kończy się na :fx? {DEEPL_KLUCZ.endswith(':fx')})"
        console.print(f"[yellow]⚠ DeepL: tłumaczenie nie powiodło się ({blad}) — teksty po angielsku.[/yellow]")
        return

    for (n, pole), pl in zip(wybrane, tlumaczenia):
        n[pole + "_en"], n[pole] = n[pole], pl
    pominiete = len(nowe) - len(wybrane)
    STATUS_TLUMACZENIA += (f" — przetłumaczono {len(wybrane)} ({znaki:,} znaków), zużycie miesiąca "
                           f"{zuzyte + znaki:,}/{limit:,}" + (f", reszta ({pominiete}) w kolejnych odświeżeniach" if pominiete else ""))
    console.print(STATUS_TLUMACZENIA)


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
    przetlumacz_newsy(newsy, argumenty.html)
    pokaz_w_terminalu(newsy)
    if argumenty.html:
        zapisz_html(newsy, spolki, argumenty.html)


if __name__ == "__main__":
    main()
