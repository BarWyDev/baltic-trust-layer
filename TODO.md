# TODO — przygotowanie do hackatonu

Stan po sesji z 2026-09-12. Projekt uruchomiony i przetestowany end-to-end
(tryb demo, `uvicorn app:app --port 8010`).

## Zrobione

- [x] **`broadcast()` rzucał `UnboundLocalError` przy każdym wywołaniu** (`app.py:62`).
  `ws_clients -= dead` czyniło `ws_clients` zmienną lokalną, więc `if not ws_clients:`
  w linii 53 wywalało się natychmiast. Skutek: symulator umierał po cichu w momencie
  otwarcia dashboardu, przeglądarka dostawała tylko `init`. Naprawione przez
  `ws_clients.difference_update(dead)`.
- [x] **`speedup` stosowany dwukrotnie** (`demo_simulator.py:321`). 1 s realna = 1 h
  symulacji zamiast 60 s; okna 15-min zamykały się ~4×/s, mapa migotała
  (22 → 2 → 15 heksów), 12 h historii zużywało się w 13 s. Teraz `dt_sim = REPORT_INTERVAL_S`.
- [x] **Sprzężenie loiteringu z powyższym** (`detectors/geometry_detectors.py`).
  Historia przycinana do 20 raportów = 190 s, a loitering wymaga >300 s — po poprawce
  czasu scenariusz MV SUN przestałby się wyzwalać. Limit podniesiony do 60,
  progi wyciągnięte do `LOITER_MIN_DURATION_S` i `HISTORY_MAX_REPORTS`.

Po zmianach wszystkie 9 typów detekcji się wyzwala, liczba heksów rośnie płynnie,
okna zamykają się co ~15 s realnych.

## Zrobione — sesja 2

- [x] **`ShipStaticData` (AIS typ 5) parsowane zamiast wyrzucane.** `ais_client.py`
  subskrybowal ten typ, ale petla go pomijala. Nowy `StaticReport` w `models.py`,
  parser `_parse_static_data()`, osobny kanal `static_callback` w `stream_reports()`.
  Zweryfikowane na zywym feedzie AISStream (CAPELLA, IMO 9190171, callsign YLRB).
- [x] **`POSITION_LOSS` (FR-006) zaimplementowany.** `PositionLossDetector`
  w `detectors/geometry_detectors.py`: >5 min bez pozycji przy statycznych swiezszych
  niz ostatnia pozycja = wyciszony transponder. Cooldown 10 min, throttle ewaluacji 60 s.
  Byl to jedyny zadeklarowany, a niedzialajacy typ detekcji — teraz wyzwala sie 10 z 10.
- [x] **Symulator nadaje komunikaty statyczne** co 3 min symulacji, takze dla jednostek
  w trakcie AIS gap. Luka shadow fleet wydluzona z 30 s do 6 min (cykl 10 min,
  faza przesunieta per MMSI), inaczej nie przekroczylaby progu detektora.
- [x] **Rejestr tozsamosci** — `TrustEngine.get_static()` / `/api/static`, IMO i callsign
  w popupie jednostki na dashboardzie.
- [x] **Score saturowal sie na 100 — mapa byla binarna.** Detektory emituja detekcje
  per raport, wiec jedna anomalia liczyla sie setki razy (360 detekcji jednego klastra
  w oknie). Kazdy oceniony heks ladowal na 100.0, progi 15/40 nie mialy czego rozrozniac.
  Naprawione deduplikacja epizodow w `_calculate_score` + rozdzieleniem skladnika
  jednostkowego (dzielony przez liczbe jednostek) od obszarowego (juz zagregowany).
  Zmierzone przed: kazdy oceniony heks = 100.0. Po: 55 ocenionych heksow, zero
  nasyconych, score 0-91.2, wszystkie cztery poziomy w uzyciu (17 trusted /
  21 limited / 17 do_not_use). Dashboard pokazuje teraz epizody, nie surowe detekcje.
- [x] **MV SUN i inne samotne jednostki nie wplywaly na nic.** `MIN_VESSELS_FOR_SCORE`
  zerowal caly heks, wiec sztandarowy scenariusz z raportu ICEYE generowal ~200 detekcji
  na okno przy score 0.0 i poziomie NO_DATA — w kazdym oknie bez wyjatku. Prog wiaze sie
  teraz z rodzina dowodow: gatuje tylko `declared_integrity`, a `physical_geometry` liczy
  sie niezaleznie od liczby jednostek. Dodatkowo kazdy dowod geometryczny podnosi score
  do progu LIMITED, zeby heks z potwierdzona anomalia fizyczna nie wyszedl TRUSTED.
  Obie sciezki agregacji przepiete na wspolne `_evaluate_hex()`.
  Zmierzone: MV SUN = DO_NOT_USE, score 75.0, stabilnie w kazdym oknie. Heksow TRUSTED
  z detekcja geometryczna: 0. Rozklad 11 trusted / 45 limited / 25 do_not_use / 71 no_data,
  mediana score 37.5, zero nasyconych.
- [x] **Rzadkie detekcje byly niewidoczne na dashboardzie.** Lista trzymala 50 surowych
  detekcji, a te naplywaja ~86/s — cala lista wymieniala sie co ~0,6 s i `position_loss`
  czy `position_on_land` znikaly, zanim dalo sie je przeczytac (zmierzone w przegladarce:
  4 ramki WS z position_loss na 4488, na liscie widoczne 0). Lista agreguje teraz epizody
  tym samym kluczem co silnik, z licznikiem `xN`, wiekiem wpisu i renderem dlawionym
  do 4 Hz; eksmisja usuwa epizod najdluzej nieaktywny.
  Zmierzone po: wszystkie 9 typow przewija sie przez liste, `Utrata pozycji` utrzymuje
  sie na ekranie, dlugosc listy stabilna 24-27 zamiast ciaglego 50.
- [x] **MV SUN byl poza kadrem mapy — i krazyl nad polem pod Slupskiem.**
  Widoku startowego nie da sie rozszerzyc na oba rejony: objecie korytarza SwePol Link
  (lon ~17.0) razem z Zatoka wymaga ~3 stopni dlugosci, co schodzi do zoomu 8 —
  heksy nieczytelne, pol kadru to lad. Zamiast tego: ostrzezenie `updateOffscreenAlert()`
  o krytycznych heksach poza kadrem (z przyciskiem "Pokaz", ktory rozszerza widok)
  plus przycisk szybkiego skoku "MV SUN — SwePol Link". Rozwiazuje problem ogolnie,
  nie tylko dla tego jednego scenariusza.
- [x] **Trasa SwePol Link schodzila na lad** (`data/iceye_context.py`). Cztery ostatnie
  waypointy bieglly przez Pomorze, a punkt opisany jako "podejscie Ustka" (53.93, 18.22)
  lezal ~70 km w glebi kraju pod Starogardem Gdanskim; start (55.38, 14.30) byl ~90 km
  od Karlshamn. Scenariusz `mv_sun_loiter` dziedziczyl ten blad i renderowal sie nad
  polem pod Slupskiem. Trasa poprawiona na przebieg morski Karlshamn -> Wierzbiecino
  k. Ustki; MV SUN przeniesiony na (54.75-54.82 N, 16.56-16.63 E) — ~20 km od brzegu,
  <1 km od kabla i >8 km od Baltic Pipe, zeby detekcja jednoznacznie wskazywala
  SwePol Link (wczesniej opis brzmial "loitering przy Baltic Pipe").
  Zmierzone: loitering i infra_proximity nadal sie wyzwalaja, opis "loitering 10 min
  przy SwePol Link (sr. 2.4 kn, odl. 0.6 km) — wzorzec MV SUN".
- [ ] **Pozostale trasy infrastruktury nieaudytowane.** Poprawiony zostal tylko
  SwePol Link. Baltic Pipe w repo biegnie przez (54.90, 16.50) i (54.50, 18.30),
  czyli przez Zatoke Gdanska — prawdziwy gazociag wychodzi na lad w Niechorzu
  (~54.1 N, 15.0 E). Reszta tras (C-Lion1, NordBalt, Harmony Link, kable MFW)
  tez wymaga sprawdzenia, czy nie przecina ladu.
- [x] **`_all_detections` roslo bez ograniczen.** Bufor przyciety do 1000 ostatnich
  detekcji; skumulowana suma przeniesiona do osobnego licznika `_detections_seen`,
  zeby `brief.total_detections` nadal pokazywal wszystko od startu, a nie dlugosc bufora.
  Zmierzone: RSS stabilizuje sie na 102 MB od ticku ~5000 (gdy `_history` nasyca sie
  na 48 oknach) i nie rosnie przez kolejne 2000 tickow, mimo licznika detekcji
  rosnacego z 77 tys. do 108 tys. Wczesniej ~0,5 GB/h bez konca.
- [x] **Wyjatek w przetwarzaniu zabijal strumien po cichu.** `process_report`
  i `process_static` maja teraz `try/except` z `log_processing_error()`: pierwsze
  5 bledow z pelnym tracebackiem, potem co setny, plus licznik `processing_errors`
  w `/api/stats`. Trzy miejsca startu symulatora (demo + fallbacki z live i replay)
  ujednolicone w `start_simulator()` — dwa z nich nie mialy zadnego logowania wyjatkow.
  `CancelledError` przepuszczany, zeby zamykanie aplikacji dzialalo normalnie.
  Zmierzone: po wstrzyknieciu raportu z `lat=None` strumien plynie dalej
  (9 raportow przetworzonych, 1 blad zalogowany).

## Priorytet wysoki

- [ ] **Port 8000 zajęty na maszynie dev** przez inny proces — sprawdzić przed prezentacją
  (`lsof -ti :8000`) albo zmienić port w `app.py`.

## Priorytet średni

- [x] **README** — napisany (`README.md`): problem, przepływ danych, tabele detektorów
  z wagami, tryby i źródła danych, architektura, kontrakt WS/REST, sekcja ograniczeń.
- [ ] **`.env` ma `AISSTREAM_API_KEY=your_api_key_here`** → tryb `live` cicho spada
  do demo. Jeśli ma być pokaz na żywych danych, potrzebny klucz z aisstream.io.
- [ ] **Tryb `replay` to szkielet** — brak przykładowego CSV, więc nie da się go pokazać.

## Priorytet niski

- [x] `DemoSimulator._generate_report` deklaruje `-> AISReport`, a zwraca `None`
  dla scenariusza `shadow_fleet` — adnotacja poprawiona na `AISReport | None`.
- [ ] `InfraProximityDetector._vessel_near_infra` ma adnotację `dict[int, list[dict]]`,
  a kluczem jest krotka `(mmsi, nazwa_infrastruktury)`.
- [ ] Brak testów — żadnego `test_*.py` w repo.
