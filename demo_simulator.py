"""
Symulator demo dla Zatoki Gdanskiej — Baltic Trust Layer.
Generuje realistyczne raporty AIS z wbudowanymi scenariuszami anomalii:
- Scenariusz 1: Jamming — wiele jednostek z RAIM off + low accuracy w jednym heksie
- Scenariusz 2: Spoofing — klaster zbiezny (wiele MMSI w jednym punkcie)
- Scenariusz 3: Pozycja na ladzie (nie w porcie)
- Scenariusz 4: Skok kinematyczny (teleportacja)
- Scenariusz 5: Normalne jednostki z dobrymi wskaznikami (kontrola)
- Scenariusz 6: Shadow fleet — AIS gap (pozycyjne milkna, statyczne nadal ida)

Symulator nadaje dwa strumienie: raporty pozycyjne (typ 1/2/3) oraz
komunikaty statyczne (typ 5). Ten drugi jest potrzebny, zeby FR-006
(utrata pozycji) mial jak odroznic wyciszony transponder od jednostki,
ktora po prostu wyplynela z akwenu.
"""
from __future__ import annotations
import asyncio
import math
import random
import time
from dataclasses import dataclass

from models import AISReport, StaticReport
from data.gdansk_bay import MAP_CENTER, GDANSK_BAY_BBOX


# ── Definicje tras ─────────────────────────────────────────────────────

@dataclass
class SimVessel:
    mmsi: int
    name: str
    ship_type: int
    flag: str
    # Trasa: lista (lat, lon) waypointow
    waypoints: list[tuple[float, float]]
    speed_kn: float = 12.0
    # Scenariusz anomalii
    anomaly: str = "none"
    # Stan biezacy
    wp_idx: int = 0
    lat: float = 0.0
    lon: float = 0.0
    cog: float = 0.0
    progress: float = 0.0  # 0-1 miedzy waypointami


# Trasy w Zatoce Gdanskiej
ROUTES = {
    "tor_podejsciowy_gdansk": [
        (54.55, 19.10), (54.50, 18.95), (54.45, 18.80),
        (54.42, 18.72), (54.40, 18.67),  # wejscie do portu Gdansk
    ],
    "tor_podejsciowy_gdynia": [
        (54.60, 19.00), (54.58, 18.80), (54.56, 18.65),
        (54.55, 18.55),  # wejscie do portu Gdynia
    ],
    "tranzyt_ns": [
        (54.95, 19.20), (54.80, 19.10), (54.65, 18.90),
        (54.50, 18.80), (54.35, 18.70),
    ],
    "tranzyt_ew": [
        (54.50, 19.60), (54.52, 19.30), (54.55, 19.00),
        (54.57, 18.70), (54.55, 18.40),
    ],
    "kotwicowisko_gdynia": [
        (54.56, 18.50), (54.555, 18.51), (54.56, 18.52),
        (54.555, 18.50),  # maly okrag — kotwicowisko
    ],
    "patrol_brzegowy": [
        (54.50, 18.60), (54.48, 18.70), (54.46, 18.75),
        (54.44, 18.70), (54.46, 18.65), (54.48, 18.60),
    ],
    # === Scenariusz MV SUN: manewry cykliczne przy SwePol Link ===
    # Zrekonstruowane z raportu ICEYE x Impulse Institute
    # Cykliczne manewry przy trasie SwePol Link, na morzu ~35 km na polnoc
    # od Jaroslawca. Poprzednie waypointy (lat 54.30-54.40, lon 16.90-17.15)
    # lezaly na ladzie pod Slupskiem — wybrzeze na tej dlugosci jest na ~54.58 N.
    "mv_sun_loiter": [
        (54.819, 16.578), (54.789, 16.587), (54.779, 16.628), (54.753, 16.632),
        (54.775, 16.633), (54.781, 16.597), (54.807, 16.593), (54.813, 16.557),
    ],
    # === Shadow fleet: tranzyt z wylaczaniem AIS ===
    "shadow_fleet_transit": [
        (54.95, 19.50),   # wejscie od polnocy
        (54.80, 19.20),
        (54.65, 18.90),
        (54.50, 18.70),
        (54.35, 18.50),   # tranzyt na poludnie
    ],
}


# ── Flota symulowana ───────────────────────────────────────────────────

FLEET: list[dict] = [
    # === Normalne jednostki (kontrola) ===
    {"mmsi": 261001001, "name": "GDANSK PILOT", "type": 50, "flag": "PL",
     "route": "tor_podejsciowy_gdansk", "speed": 8.0, "anomaly": "none"},
    {"mmsi": 261001002, "name": "ZAWISZA CZARNY", "type": 36, "flag": "PL",
     "route": "patrol_brzegowy", "speed": 10.0, "anomaly": "none"},
    {"mmsi": 261001003, "name": "KAPITAN POINC", "type": 52, "flag": "PL",
     "route": "tor_podejsciowy_gdynia", "speed": 6.0, "anomaly": "none"},
    {"mmsi": 305001001, "name": "BALTIC CARRIER", "type": 70, "flag": "AG",
     "route": "tranzyt_ns", "speed": 14.0, "anomaly": "none"},
    {"mmsi": 636001001, "name": "OCEAN PEARL", "type": 70, "flag": "LR",
     "route": "tranzyt_ew", "speed": 16.0, "anomaly": "none"},
    {"mmsi": 211001001, "name": "HAMBURG EXPRESS", "type": 71, "flag": "DE",
     "route": "tranzyt_ns", "speed": 18.0, "anomaly": "none"},
    {"mmsi": 220001001, "name": "MAERSK GDYNIA", "type": 71, "flag": "DK",
     "route": "tor_podejsciowy_gdynia", "speed": 12.0, "anomaly": "none"},
    {"mmsi": 261001004, "name": "JANTAR", "type": 31, "flag": "PL",
     "route": "kotwicowisko_gdynia", "speed": 3.0, "anomaly": "none"},

    # === Scenariusz 1: Jamming — RAIM off w grupie ===
    {"mmsi": 261002001, "name": "KRAB", "type": 30, "flag": "PL",
     "route": "tor_podejsciowy_gdansk", "speed": 7.0, "anomaly": "jamming"},
    {"mmsi": 261002002, "name": "REKIN", "type": 30, "flag": "PL",
     "route": "tor_podejsciowy_gdansk", "speed": 9.0, "anomaly": "jamming"},
    {"mmsi": 261002003, "name": "DORSZ", "type": 30, "flag": "PL",
     "route": "tor_podejsciowy_gdansk", "speed": 6.5, "anomaly": "jamming"},

    # === Scenariusz 2: Spoofing — klaster zbiezny ===
    {"mmsi": 273001001, "name": "VOLGA-1", "type": 70, "flag": "RU",
     "route": "tranzyt_ew", "speed": 11.0, "anomaly": "spoofing_cluster"},
    {"mmsi": 273001002, "name": "VOLGA-2", "type": 70, "flag": "RU",
     "route": "tranzyt_ew", "speed": 13.0, "anomaly": "spoofing_cluster"},
    {"mmsi": 273001003, "name": "VOLGA-3", "type": 70, "flag": "RU",
     "route": "tranzyt_ew", "speed": 10.0, "anomaly": "spoofing_cluster"},
    {"mmsi": 273001004, "name": "NEVA STAR", "type": 70, "flag": "RU",
     "route": "tranzyt_ew", "speed": 12.0, "anomaly": "spoofing_cluster"},

    # === Scenariusz 3: Pozycja na ladzie (nie w porcie) ===
    {"mmsi": 273002001, "name": "PHANTOM SHIP", "type": 70, "flag": "RU",
     "route": "tranzyt_ns", "speed": 10.0, "anomaly": "on_land"},

    # === Scenariusz 4: Skok kinematyczny ===
    {"mmsi": 374001001, "name": "SANTA ELENA", "type": 70, "flag": "PA",
     "route": "tranzyt_ew", "speed": 13.0, "anomaly": "kinematic_jump"},

    # === Scenariusz 5: MV SUN — loitering przy SwePol Link ===
    # Zrekonstruowany z raportu ICEYE x Impulse: tankowiec shadow fleet
    # manewrujacy cyklicznie przy kablu podmorskim, predkosc 2-3 kn
    {"mmsi": 304001001, "name": "MV SUN", "type": 80, "flag": "AG",
     "route": "mv_sun_loiter", "speed": 2.5, "anomaly": "mv_sun"},

    # === Scenariusz 6: Shadow fleet — tranzyt z AIS gaps ===
    # 150-170 sankcjonowanych tankow miesiecznie na Baltyku (raport ICEYE)
    {"mmsi": 273003001, "name": "TAGANROG", "type": 80, "flag": "RU",
     "route": "shadow_fleet_transit", "speed": 11.0, "anomaly": "shadow_fleet"},
    {"mmsi": 273003002, "name": "NOVOROSSIYSK-7", "type": 80, "flag": "RU",
     "route": "shadow_fleet_transit", "speed": 9.5, "anomaly": "shadow_fleet"},
]


# ── Dane statyczne (komunikat AIS typ 5) ───────────────────────────────

# Realne numery IMO tam, gdzie je znamy z raportu ICEYE x Impulse.
# Reszta floty dostaje deterministyczny numer syntetyczny.
IMO_OVERRIDES = {
    304001001: 9293117,  # MV SUN — IMO z raportu (incydent przy SwePol Link)
}

# ship_type -> (zanurzenie m, dlugosc m, szerokosc m)
STATIC_BY_SHIP_TYPE = {
    30: (4.0, 28.0, 8.0),    # kuter rybacki
    31: (5.5, 35.0, 10.0),   # holownik
    36: (4.2, 45.0, 9.0),    # jacht/zaglowiec
    50: (3.8, 22.0, 7.0),    # pilotowa
    52: (5.0, 38.0, 11.0),   # holownik portowy
    70: (9.8, 180.0, 26.0),  # drobnicowiec
    71: (14.0, 330.0, 43.0), # kontenerowiec
    80: (12.5, 250.0, 44.0), # tankowiec
}
DEFAULT_STATIC = (6.0, 90.0, 15.0)


def synthetic_imo(mmsi: int) -> int:
    """Deterministyczny numer IMO dla jednostek bez realnego odpowiednika."""
    if mmsi in IMO_OVERRIDES:
        return IMO_OVERRIDES[mmsi]
    return 9000000 + (mmsi % 900000)


# ── Symulator ──────────────────────────────────────────────────────────

class DemoSimulator:
    """
    Generuje raporty AIS co ~10 sekund z wbudowanymi anomaliami.
    Jednostki poruszaja sie wzdluz zdefiniowanych tras.
    """

    REPORT_INTERVAL_S = 10  # co ile sekund nowy raport
    SPEEDUP = 60            # 1s realnego czasu = 60s symulacji

    # Komunikat statyczny (typ 5) co 18 tickow = 3 min symulacji.
    # W rzeczywistosci AIS nadaje go co 6 min; skrocone, zeby scenariusz
    # shadow fleet zdazyl wygenerowac statyczny wewnatrz kazdej luki.
    STATIC_INTERVAL_TICKS = 18

    # Scenariusz shadow fleet: cykl 60 tickow (10 min symulacji),
    # z czego ostatnie 36 tickow (6 min) transponder nie nadaje pozycji.
    # Luka musi przekroczyc PositionLossDetector.GAP_THRESHOLD_S (300 s).
    SHADOW_CYCLE_TICKS = 60
    SHADOW_DARK_FROM_TICK = 24

    def __init__(self, speedup: float = SPEEDUP):
        self.speedup = speedup
        self._running = False
        self._vessels: list[SimVessel] = []
        self._sim_time = time.time()
        self._tick_count = 0
        self._spoof_center = (54.52, 19.00)  # punkt spoofingu
        self._init_fleet()

    def _init_fleet(self):
        """Zainicjalizuj flote z definicji."""
        for v in FLEET:
            route = ROUTES[v["route"]]
            vessel = SimVessel(
                mmsi=v["mmsi"],
                name=v["name"],
                ship_type=v["type"],
                flag=v["flag"],
                waypoints=list(route),
                speed_kn=v["speed"],
                anomaly=v["anomaly"],
                lat=route[0][0],
                lon=route[0][1],
            )
            self._vessels.append(vessel)

    def _move_vessel(self, v: SimVessel, dt_s: float):
        """Przesun jednostke wzdluz trasy."""
        if len(v.waypoints) < 2:
            return

        # Cel biezacego odcinka
        target_idx = (v.wp_idx + 1) % len(v.waypoints)
        target = v.waypoints[target_idx]

        # Odleglosc do celu
        dlat = target[0] - v.lat
        dlon = target[1] - v.lon
        dist_deg = math.sqrt(dlat**2 + dlon**2)

        if dist_deg < 0.001:
            # Dotarl do waypoint — nastepny
            v.wp_idx = target_idx
            v.lat = target[0]
            v.lon = target[1]
            return

        # Predkosc w stopniach/s (przyblizone)
        speed_deg_s = (v.speed_kn * 1.852 / 3600.0) / 111.0  # km/s -> deg/s
        move = speed_deg_s * dt_s

        # Ogranicz do odleglosci do celu
        if move > dist_deg:
            move = dist_deg

        # Przesun
        ratio = move / dist_deg
        v.lat += dlat * ratio
        v.lon += dlon * ratio

        # COG
        v.cog = math.degrees(math.atan2(dlon, dlat)) % 360

    def _generate_report(self, v: SimVessel) -> AISReport | None:
        """Generuj raport AIS dla jednostki, z anomaliami wg scenariusza."""
        lat = v.lat
        lon = v.lon
        raim = True
        accuracy = True
        utc_second = int(self._sim_time) % 60
        nav_status = 0  # underway engine

        # Jitter GPS (realistyczny)
        lat += random.gauss(0, 0.0001)
        lon += random.gauss(0, 0.0001)

        if v.anomaly == "jamming":
            # Scenariusz 1: RAIM off, niska accuracy, czasem zly timestamp
            raim = False
            accuracy = random.random() < 0.3  # 70% szans na low accuracy
            if random.random() < 0.2:
                utc_second = random.choice([61, 62, 63])

        elif v.anomaly == "spoofing_cluster":
            # Scenariusz 2: Wszystkie jednostki raportuja te sama pozycje
            lat = self._spoof_center[0] + random.gauss(0, 0.00005)
            lon = self._spoof_center[1] + random.gauss(0, 0.00005)
            # Spoofing moze miec "dobre" wskazniki — to podstep!
            raim = random.random() < 0.7
            accuracy = True

        elif v.anomaly == "on_land":
            # Scenariusz 3: Pozycja na ladzie (Polwysep Helski, nie w porcie)
            if self._tick_count % 5 == 0:  # co 5 tick
                lat = 54.70  # Polwysep Helski
                lon = 18.42  # na ladzie

        elif v.anomaly == "kinematic_jump":
            # Scenariusz 4: Co 10 tick — skok na drugi koniec Zatoki
            if self._tick_count % 10 == 0:
                lat = 54.90  # polnoc Zatoki
                lon = 19.40  # daleki wschod
            elif self._tick_count % 10 == 1:
                # Powrot — powoduje kolejny skok
                pass  # normalna pozycja

        elif v.anomaly == "mv_sun":
            # Scenariusz 5: MV SUN — loitering przy infrastrukturze
            # Niska predkosc (2-3 kn), cykliczne manewry, RAIM czasem off
            # Zrekonstruowane z raportu ICEYE x Impulse (maj 2025)
            v.speed_kn = 2.0 + random.gauss(0.5, 0.3)
            nav_status = 0  # underway engine — ale ledwo sie rusza
            raim = random.random() < 0.6  # czasem RAIM off
            accuracy = random.random() < 0.5

        elif v.anomaly == "shadow_fleet":
            # Scenariusz 6: Shadow fleet — periodyczne AIS gaps.
            # Cykl 10 min symulacji, z czego 6 min bez pozycji. Komunikaty
            # statyczne ida dalej (patrz run()) — to wlasnie sygnatura FR-006:
            # transponder zyje, pozycji brak.
            # Faza przesunieta per MMSI, zeby obie jednostki nie milkly naraz.
            cycle = (self._tick_count + v.mmsi) % self.SHADOW_CYCLE_TICKS
            if cycle >= self.SHADOW_DARK_FROM_TICK:
                # AIS pozycyjny wylaczony — pomijamy raport
                return None
            # Gdy nadaje: czasem falszywe dane
            if random.random() < 0.3:
                raim = False
                accuracy = False

        return AISReport(
            mmsi=v.mmsi,
            name=v.name,
            lat=lat,
            lon=lon,
            sog=v.speed_kn + random.gauss(0, 0.5),
            cog=v.cog + random.gauss(0, 2.0),
            heading=v.cog + random.gauss(0, 3.0),
            nav_status=nav_status,
            position_accuracy=accuracy,
            raim=raim,
            utc_second=utc_second,
            ship_type=v.ship_type,
            timestamp=self._sim_time,
            msg_type=random.choice([1, 2, 3]),
            flag=v.flag,
            destination="GDANSK" if "gdansk" in str(v.waypoints) else "GDYNIA",
        )

    def _generate_static(self, v: SimVessel) -> StaticReport:
        """
        Komunikat statyczny AIS (typ 5) — tozsamosc jednostki.
        Nadawany takze wtedy, gdy jednostka nie raportuje pozycji.
        """
        draught, length, beam = STATIC_BY_SHIP_TYPE.get(v.ship_type, DEFAULT_STATIC)
        return StaticReport(
            mmsi=v.mmsi,
            name=v.name,
            imo=synthetic_imo(v.mmsi),
            callsign=f"S{v.mmsi % 100000:05d}",
            ship_type=v.ship_type,
            destination="GDANSK" if "gdansk" in str(v.waypoints) else "GDYNIA",
            draught=draught,
            dim_bow=round(length * 0.6, 1),
            dim_stern=round(length * 0.4, 1),
            dim_port=round(beam / 2, 1),
            dim_starboard=round(beam / 2, 1),
            eta="",
            flag=v.flag,
            timestamp=self._sim_time,
        )

    async def run(self, report_callback, static_callback=None) -> None:
        """
        Glowna petla symulatora.
        report_callback(report: AISReport) — wywolywane dla kazdego raportu.
        static_callback(static: StaticReport) — opcjonalne, komunikaty typu 5.
        """
        self._running = True
        self._sim_time = time.time()

        while self._running:
            # speedup skraca tylko realne czekanie miedzy tickami; krok zegara
            # symulacji to zwykly interwal AIS, inaczej przyspieszenie liczy sie
            # dwa razy i okna 15-min zamykaja sie kilka razy na sekunde
            dt_sim = self.REPORT_INTERVAL_S
            self._sim_time += dt_sim
            self._tick_count += 1

            # Przesun wszystkie jednostki
            for v in self._vessels:
                self._move_vessel(v, dt_sim)

            # Komunikaty statyczne (typ 5) — takze dla jednostek, ktore
            # akurat nie nadaja pozycji. Faza przesunieta per MMSI, zeby
            # nie szly wszystkie w tym samym ticku.
            if static_callback is not None:
                for v in self._vessels:
                    if (self._tick_count + v.mmsi) % self.STATIC_INTERVAL_TICKS == 0:
                        await static_callback(self._generate_static(v))

            # Generuj raporty (losowa kolejnosc jak w prawdziwym AIS)
            shuffled = list(self._vessels)
            random.shuffle(shuffled)

            for v in shuffled:
                report = self._generate_report(v)
                if report is not None:
                    await report_callback(report)

            # Czekaj miedzy raporty (realny czas)
            await asyncio.sleep(self.REPORT_INTERVAL_S / self.speedup)

    def stop(self):
        self._running = False

    @property
    def vessel_count(self) -> int:
        return len(self._vessels)
