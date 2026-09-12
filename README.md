# Baltic Trust Layer

**Warstwa wiarygodności GNSS dla Zatoki Gdańskiej.** Prototyp hackathonowy: zamienia
strumień raportów AIS w jedną odpowiedź na pytanie operatora — *„czy mogę w tym
kwadracie oprzeć manewr na GNSS?"* — aktualizowaną w oknach 15-minutowych.

---

## Problem

Na Bałtyku nakładają się dziś trzy zjawiska, które razem psują zaufanie do pozycji GNSS:

- **Zakłócanie i spoofing GNSS** — ~2500 zdarzeń jammingu odnotowanych przez EUROCONTROL
  w 2024, epicentrum Kaliningrad. Statek widzi pozycję, ale nie wie, czy jest prawdziwa.
- **Shadow fleet** — 150–170 sankcjonowanych tankowców miesięcznie, manipulacja AIS:
  wyłączanie transpondera, fałszywe MMSI/IMO, podmiana bandery.
- **Infrastruktura podmorska** — 35 kabli i rurociągów. Nord Stream (2022),
  Balticconnector (2023), Yi Peng 3 / C-Lion1 (XI 2024), Eagle S / 5 kabli (XII 2024),
  MV SUN przy SwePol Link (V 2025).

Luka, którą adresuje projekt, to **czas reakcji i brak zagregowanej oceny**. Przy MV SUN
od pierwszych obserwacji do formalnej reakcji minęło 6–8 dni. Operator dostaje surowe
pozycje AIS, a nie rekomendację manewrową dla akwenu. Baltic Trust Layer liczy tę
rekomendację na bieżąco z danych, które już płyną.

## Jak to działa

```
źródło AIS → AISReport → TrustEngine.process_report() → detektory
           → agregacja w heksy H3 (okna 15 min) → score 0-100 → TrustLevel
           → WebSocket /ws → dashboard
```

### 1. Wejście

Dwa strumienie komunikatów:

- **pozycyjne (typ 1/2/3)** → `AISReport`: pozycja, SOG/COG/heading, nav status oraz —
  kluczowe tutaj — pola integralnościowe `raim`, `position_accuracy`, `utc_second`.
- **statyczne (typ 5)** → `StaticReport`: IMO, sygnał wywoławczy, wymiary, zanurzenie,
  port przeznaczenia. Same w sobie nie generują detekcji, ale są dowodem, że transponder
  działa — bez nich nie da się odróżnić wyciszonej pozycji od jednostki, która po prostu
  wypłynęła z akwenu.

### 2. Dwie rodziny dowodów

Podział jest strukturalny: przechodzi przez scoring aż do dashboardu.

**Deklarowana integralność** (`detectors/integrity_detectors.py`) — to, co statek sam
o sobie mówi:

| Detekcja | Warunek | Waga |
|---|---|---|
| `RAIM_OFF` | RAIM wyłączony — brak kontroli integralności GNSS | 10 |
| `LOW_ACCURACY` | zadeklarowana dokładność pozycji >10 m | 5 |
| `TIMESTAMP_ANOMALY` | UTC second 61/62/63 = manual / dead reckoning / inoperative | 15 |
| `INTEGRITY_DEGRADATION` | >30% raportów w heksie ma flagi integralnościowe | 20 |

**Geometria fizyczna** (`detectors/geometry_detectors.py`) — czy taka pozycja jest
w ogóle możliwa:

| Detekcja | Warunek | Waga |
|---|---|---|
| `POSITION_ON_LAND` | pozycja na lądzie poza maskami portowymi | 30 |
| `KINEMATIC_JUMP` | implikowana prędkość >60 kn między raportami tego samego MMSI | 25 |
| `CONVERGENT_CLUSTER` | ≥3 różne MMSI w promieniu 50 m w ciągu 2 min — sygnatura spoofingu | 35 |
| `POSITION_LOSS` | >5 min bez pozycji przy nadal nadawanych komunikatach statycznych | 15 |
| `INFRA_PROXIMITY` | <2 km od kabla/rurociągu przy SOG <4 kn | 20 |
| `LOITERING` | >5 min w strefie, średnio <4 kn — wzorzec MV SUN | 30 |

Każda detekcja niesie pewność LOW / MEDIUM / HIGH (mnożnik 0.5 / 1.0 / 1.5) oraz surowe
dowody w polu `evidence` — dystans, implikowaną prędkość, listę MMSI w klastrze.

### 3. Agregacja

`TrustEngine` (`trust_engine.py`) przypisuje raporty i detekcje do heksów H3
rozdzielczości 7 (~5,16 km²) w oknach 15-minutowych.

```
score = suma_jednostkowa / liczba_jednostek + suma_obszarowa    (obcięte do 100)
```

Score liczy się na **unikalnych epizodach**, nie na surowych detekcjach. Detektory
pracują per raport, więc jedna anomalia potrafi wygenerować setki detekcji w oknie
(4 statki × 90 raportów = 360 detekcji tego samego klastra). Epizod to typ detekcji
plus dotknięta jednostka; detekcje obszarowe (klaster zbieżny, degradacja
integralności) zbierane są po samym typie, bo ich skład potrafi fluktuować między
raportami. Z duplikatów zostaje ten o najwyższej pewności.

Podział na dwa składniki jest celowy:

- **jednostkowe** (RAIM off, skok, loitering, utrata pozycji) dzielą się przez liczbę
  jednostek w heksie — to udział dotkniętej floty. Jeden pechowy statek to nie to samo,
  co pięć statków z tym samym objawem.
- **obszarowe** (klaster zbieżny, degradacja integralności) już agregują wiele MMSI,
  więc dzielenie ich drugi raz przez liczbę jednostek zaniżałoby je bez powodu.

Próg `MIN_VESSELS_FOR_SCORE = 2` obowiązuje **tylko rodzinę deklarowanej
integralności** — pojedynczy statek z wyłączonym RAIM nie mówi nic o akwenie, dopiero
kilka jednostek z tym samym objawem to sygnał. Dowody z rodziny geometrii fizycznej
(pozycja na lądzie, skok, loitering przy infrastrukturze, utrata pozycji) liczą się
niezależnie od liczby jednostek: jeden tankowiec krążący nad kablem to fakt, nie
statystyka. Każdy taki dowód podnosi score co najmniej do progu `LIMITED` — heks
z potwierdzoną anomalią fizyczną nie może zostać opisany jako „brak istotnych
anomalii". `NO_DATA` oznacza więc brak podstaw do oceny: za mało jednostek na wnioski
statystyczne i żadnego twardego dowodu.

### 4. Wyjście

Zamknięty zbiór czterech wartości:

| Score | Poziom | Rekomendacja |
|---|---|---|
| <15 | `TRUSTED` | pozycja GNSS wiarygodna |
| 15–40 | `LIMITED` | ograniczone zaufanie, weryfikuj radarem |
| ≥40 | `DO_NOT_USE` | nie opieraj manewru na GNSS |
| — | `NO_DATA` | za mało jednostek **i** brak dowodu geometrycznego |

`get_brief()` skleja to w jedną rekomendację dla całego akwenu — **wygrywa najgorszy
heks**: pojedynczy `DO_NOT_USE` przestawia cały brief.

## Uruchomienie

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # następnie ustaw MODE / AISSTREAM_API_KEY
python app.py               # http://0.0.0.0:8000
```

Dashboard pod `/`. W repo nie ma testów, lintera ani build stepu — jedyne, co się
uruchamia, to serwer.

## Źródła danych

### Pozycje AIS — trzy tryby (`MODE` w `.env`)

**`demo`** (domyślny) — `DemoSimulator` prowadzi ~20 jednostek po trasach w Zatoce
Gdańskiej, raport co 10 s czasu symulacji, speedup 60× (1 s realna = 60 s symulacji).
Każdy scenariusz anomalii istnieje po to, żeby wyzwolić konkretny detektor:

| Scenariusz | Jednostki | Wyzwala |
|---|---|---|
| `jamming` | 3 na torze podejściowym Gdańsk | RAIM off, low accuracy, timestamp anomaly, degradacja heksa |
| `spoofing_cluster` | 4 na tranzycie E–W | klaster zbieżny |
| `on_land` | 1 | pozycja na lądzie |
| `kinematic_jump` | 1 | skok kinematyczny |
| `mv_sun` | 1 przy SwePol Link | bliskość infrastruktury + loitering |
| `shadow_fleet` | 2 | utrata pozycji (6 min ciszy pozycyjnej, statyczne nadal idą) |

To podstawowy sposób na przećwiczenie wszystkich detektorów bez żywego feedu.

**`live`** — AISStream.io przez WebSocket (`wss://stream.aisstream.io/v0/stream`),
subskrypcja `PositionReport` + `ShipStaticData` ograniczona bounding boxem akwenu,
auto-reconnect z wykładniczym backoffem.
Wymaga darmowego klucza (`AISSTREAM_API_KEY`, rejestracja przez GitHub). Bez klucza
aplikacja cicho spada do trybu demo.

**`replay`** — odtwarzanie z CSV wskazanego przez `REPLAY_FILE`. Parser jest, ale nie ma
przykładowego pliku — tryb pozostaje szkieletem.

### Dane referencyjne (statyczne, w repo)

- **`data/iceye_context.py`** — z raportu ICEYE × Impulse Institute „Bezpieczeństwo
  Bałtyku": 15 tras infrastruktury podmorskiej (SwePol Link, Baltic Pipe, C-Lion1,
  EstLink 1/2, Balticconnector, NordBalt, Harmony Link, Nord Stream 1/2, kable
  wyprowadzające farm wiatrowych), terminale (Naftoport, DCT Gdańsk, LNG Świnoujście),
  5 opisanych incydentów z timeline'ami oraz statystyki bałtyckie. Trasy zasilają
  `InfraProximityDetector`; reszta idzie do kontekstu na dashboardzie.
- **`data/gdansk_bay.py`** — bounding box akwenu (54.30–55.00 N, 18.30–19.70 E),
  6 masek portowych (żeby dok nie liczył się jako „pozycja na lądzie"), uproszczona
  heurystyka linii brzegowej, `haversine_km` i odległość punkt–trasa.

## Architektura

| Plik | Rola |
|---|---|
| `app.py` | FastAPI, wybór źródła danych w `lifespan()`, broadcast po WebSocket, jedyny stan globalny |
| `models.py` | wspólne dataclassy i enumy: `AISReport`, `Detection`, `HexCell`, `TimeWindow` |
| `trust_engine.py` | agregacja w heksy i okna, scoring, brief |
| `detectors/integrity_detectors.py` | rodzina „deklarowana integralność" |
| `detectors/geometry_detectors.py` | rodzina „geometria fizyczna" |
| `data/gdansk_bay.py` | geometria akwenu i helpery odległości |
| `data/iceye_context.py` | dane referencyjne z raportu ICEYE × Impulse |
| `demo_simulator.py` | symulowana flota i scenariusze anomalii |
| `ais_client.py` | klient AISStream.io z auto-reconnectem |
| `static/index.html` | dashboard jednoplikowy (HTML/CSS/JS, bez build stepu) |

## Interfejs

**WebSocket `/ws`** — podstawowy kontrakt danych. Typy wiadomości: `init` (stan
początkowy), `report` (pojedynczy raport + jego detekcje), `hex_update` (snapshot
heksów co 20 raportów, z briefem i statystykami), `brief` (na żądanie klienta).

**REST `/api/*`** — dostęp pomocniczy/debugowy do tego samego stanu:
`/api/hexes`, `/api/brief`, `/api/detections`, `/api/infrastructure`, `/api/static`
(rejestr tożsamości z komunikatów typu 5), `/api/stats`, `/api/history`.

## Ograniczenia

Rzeczy, o których warto wiedzieć przed oceną prototypu:

- **Brak niezależnej weryfikacji.** Wszystkie dowody pochodzą z samego AIS — nie ma
  radaru, SAR ani TDoA. System wykrywa *niespójność*, nie *prawdę*.
- **`POSITION_LOSS` wymaga komunikatów statycznych.** Jednostka, która wyłącza cały
  transponder (a nie tylko pozycję), przestaje istnieć dla systemu — to dziura, którą
  zamknąć może dopiero niezależna obserwacja, np. SAR.
- **Geometria jest przybliżona.** Linia brzegowa, maski portowe i trasy kabli są rysowane
  ręcznie na potrzeby hackatonu — nie zastępują map hydrograficznych ani danych EMODnet.
  Trasa SwePol Link została skorygowana (poprzednia wersja schodziła na ląd), ale
  pozostałe trasy w `data/iceye_context.py` nie były audytowane pod tym kątem —
  Baltic Pipe w obecnej postaci biegnie przez Zatokę Gdańską, choć realnie wychodzi
  na brzeg w Niechorzu.
- **Scoring nie zna korelacji.** Trzy detekcje od jednego statku sumują się tak samo jak
  od trzech różnych; jedyną korektą jest dzielenie przez liczbę jednostek.
- **Tryb `replay` bez danych** i tryb `live` bez klucza cicho spadają do demo.

## Kontekst

Projekt powstał na polski hackathon bezpieczeństwa morskiego; komentarze i identyfikatory
w kodzie są w większości po polsku. Odniesienia do incydentów i statystyk pochodzą
z raportu ICEYE × Impulse Institute o bezpieczeństwie Bałtyku.
