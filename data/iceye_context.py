"""
Dane referencyjne z raportu ICEYE × Impulse Institute
'Bezpieczenstwo Baltyku' (2026).

Realne incydenty, statystyki shadow fleet, infrastruktura krytyczna.
Uzywane w dashboardzie do kontekstu i w prezentacji hackathonowej.
"""
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════
# Infrastruktura krytyczna podmorska — kable i rurociagi
# Zrodlo: raport ICEYE × Impulse, str. 18-24
# ═══════════════════════════════════════════════════════════════════════

# Trasy sa przyblizone (hackathon) — nie zastępują map hydrograficznych.
SUBSEA_INFRASTRUCTURE = [
    {
        "name": "SwePol Link",
        "type": "power_cable",
        "capacity": "600 MW",
        "status": "operational",
        # Trasa poprawiona: poprzednia wersja schodzila na lad — punkt
        # opisany jako "podejscie Ustka" (53.93, 18.22) lezal ~70 km w glebi
        # kraju pod Starogardem Gdanskim, a cztery ostatnie waypointy biegly
        # przez Pomorze. Kabel idzie Karlshamn -> Wierzbiecino k. Ustki.
        "route": [
            (56.10, 14.90),   # Karlshamn, SE — wyjscie na morze
            (55.85, 15.15),
            (55.55, 15.60),   # na polnoc/wschod od Bornholmu
            (55.25, 16.05),
            (54.95, 16.40),
            (54.75, 16.65),
            (54.62, 16.85),   # podejscie Ustka (Wierzbiecino)
        ],
        "incident_proximity": True,  # MV SUN incident maj 2025
        "note": "Kabel energetyczny Szwecja-Polska, 245 km",
    },
    {
        "name": "Baltic Pipe",
        "type": "gas_pipeline",
        "capacity": "10 mld m3/rok",
        "status": "operational",
        "route": [
            (55.70, 10.80),   # Dania
            (55.50, 12.00),
            (55.40, 13.50),
            (55.20, 14.50),
            (55.10, 15.50),
            (54.90, 16.50),
            (54.80, 17.50),
            (54.60, 18.00),
            (54.50, 18.30),   # podejscie polskie
        ],
        "note": "Gazociag Norwegia-Dania-Polska, operacyjny od 2022",
    },
    {
        "name": "C-Lion1",
        "type": "telecom_cable",
        "capacity": "144 Tbps",
        "status": "damaged",
        "route": [
            (60.10, 24.90),   # Helsinki
            (59.80, 23.50),
            (59.20, 21.00),
            (58.50, 19.50),
            (57.50, 18.50),   # okolice Gotlandii
            (56.50, 16.00),
            (55.50, 13.00),
            (54.50, 11.50),
            (54.20, 10.50),   # Rostock, DE
        ],
        "incident": "Uszkodzony 17-18 XI 2024, Yi Peng 3",
        "note": "Kabel swiatlowodowy Finlandia-Niemcy, 1172 km",
    },
    {
        "name": "EstLink 1",
        "type": "power_cable",
        "capacity": "350 MW",
        "status": "operational",
        "route": [
            (60.17, 24.65),   # Espoo, FI
            (59.85, 24.60),
            (59.42, 24.55),   # Harku, EE
        ],
        "note": "Kabel energetyczny Finlandia-Estonia (2006)",
    },
    {
        "name": "EstLink 2",
        "type": "power_cable",
        "capacity": "650 MW",
        "status": "damaged",
        "route": [
            (60.40, 25.62),   # Anttila / Porvoo, FI
            (59.95, 26.10),
            (59.50, 26.55),   # Pussi, EE
        ],
        "incident": "Uszkodzony 25 XII 2024, naprawa ~60M EUR, 6 mies. przerwy",
        "note": "Kabel energetyczny Estonia-Finlandia",
    },
    {
        "name": "Balticconnector",
        "type": "gas_pipeline",
        "capacity": "2.6 mld m3/rok",
        "status": "damaged",
        "route": [
            (60.05, 23.95),   # Inkoo, FI
            (59.75, 23.70),
            (59.45, 23.90),
            (59.35, 24.05),   # Paldiski, EE
        ],
        "incident": "Uszkodzony X 2023, przerwanie dostaw",
        "note": "Gazociag Estonia-Finlandia",
    },
    {
        "name": "NordBalt",
        "type": "power_cable",
        "capacity": "700 MW",
        "status": "operational",
        "route": [
            (56.38, 16.08),   # ladowanie SE (Bergkvara)
            (56.20, 17.40),
            (56.00, 18.80),
            (55.85, 20.10),
            (55.72, 21.12),   # Klaipeda, LT
        ],
        "note": "Kabel energetyczny Szwecja-Litwa, 450 km",
    },
    {
        "name": "Harmony Link",
        "type": "power_cable",
        "capacity": "700 MW",
        "status": "planned",
        "route": [
            (54.75, 18.08),   # Zarnowiec / polskie podejscie
            (54.92, 18.35),
            (55.12, 18.90),
            (55.32, 19.60),
            (55.52, 20.40),
            (55.70, 21.10),   # Klaipeda, LT
        ],
        "note": "Planowany kabel PL-LT — odcinek widoczny z Zatoki Gdanskiej",
    },
    {
        "name": "Nord Stream 1",
        "type": "gas_pipeline",
        "capacity": "55 mld m3/rok",
        "status": "damaged",
        "route": [
            (60.50, 28.60),   # Wyborg, RU
            (59.60, 24.20),
            (58.40, 20.40),
            (56.80, 18.20),
            (55.55, 15.70),   # okolice Bornholmu — eksplozje IX 2022
            (54.80, 13.90),
            (54.15, 13.65),   # Lubmin, DE
        ],
        "incident": "Eksplozje 26 IX 2022, okolice Bornholmu",
        "note": "Gazociag Rosja-Niemcy, nieczynny po sabotażu",
    },
    {
        "name": "Nord Stream 2",
        "type": "gas_pipeline",
        "capacity": "55 mld m3/rok",
        "status": "damaged",
        "route": [
            (59.67, 28.32),   # Ust-Luga, RU
            (59.10, 22.40),
            (57.60, 19.20),
            (55.90, 16.20),
            (55.53, 15.70),
            (54.60, 14.00),
            (54.15, 13.65),   # Lubmin, DE
        ],
        "incident": "Eksplozje 26 IX 2022, okolice Bornholmu",
        "note": "Gazociag Rosja-Niemcy, nieczynny po sabotażu",
    },
    {
        "name": "BCS East (Litwa–Gotlandia)",
        "type": "telecom_cable",
        "capacity": "",
        "status": "damaged",
        "route": [
            (55.90, 21.05),   # Litwa
            (56.40, 20.10),
            (56.90, 19.20),
            (57.40, 18.70),   # Gotlandia
        ],
        "incident": "Uszkodzony 17-18 XI 2024, Yi Peng 3",
        "note": "Kabel swiatlowodowy Litwa-Szwecja (Gotlandia)",
    },
    {
        "name": "EE-S1 (Estonia–Szwecja)",
        "type": "telecom_cable",
        "capacity": "",
        "status": "operational",
        "route": [
            (59.00, 23.40),   # zachodnia Estonia
            (58.50, 21.40),
            (58.10, 19.60),
            (57.65, 18.40),   # Gotlandia
        ],
        "note": "Kabel swiatlowodowy Estonia-Szwecja",
    },
    {
        "name": "Poland–Sweden fiber (BCS)",
        "type": "telecom_cable",
        "capacity": "",
        "status": "operational",
        "route": [
            (54.18, 15.58),   # Kolobrzeg
            (54.70, 15.10),
            (55.30, 14.50),
            (56.00, 14.85),   # poludniowa Szwecja
        ],
        "note": "Lacze swiatlowodowe Polska-Szwecja",
    },
    {
        "name": "Baltic Power — kabel wyprowadzajacy",
        "type": "wind_export",
        "capacity": "1.2 GW",
        "status": "planned",
        "route": [
            (55.06, 17.22),   # farma ~20 km od Ustki
            (54.95, 17.35),
            (54.82, 17.48),   # ladowanie Lubiatowo
        ],
        "note": "Eksport z MFW Baltic Power do sieci krajowej",
    },
    {
        "name": "Baltica 2 — kabel wyprowadzajacy",
        "type": "wind_export",
        "capacity": "1.5 GW",
        "status": "planned",
        "route": [
            (55.18, 17.85),
            (54.95, 17.95),
            (54.76, 18.08),   # podejscie Zarnowiec — widoczne z Zatoki
        ],
        "note": "Eksport z MFW Baltica 2, polska EEZ na N od Leby",
    },
]

# Segmenty SwePol Link w Zatoce Gdanskiej / polskich wodach
# (do detekcji bliskosci w symulatorze)
SWEPOL_LINK_POLISH_SEGMENT = [
    (54.60, 16.40),
    (54.40, 17.00),
    (54.20, 17.50),
    (54.05, 18.00),
    (53.93, 18.22),
]


# ═══════════════════════════════════════════════════════════════════════
# Terminale energetyczne (polskie)
# ═══════════════════════════════════════════════════════════════════════

ENERGY_TERMINALS = [
    {
        "name": "Terminal LNG Swinoujscie",
        "type": "lng",
        "lat": 53.93, "lon": 14.27,
        "capacity": "8.3 mld m3/rok",
        "status": "operational",
    },
    {
        "name": "Naftoport Gdansk",
        "type": "oil",
        "lat": 54.40, "lon": 18.68,
        "capacity": "37.4 mln ton/rok (2025)",
        "status": "operational",
    },
    {
        "name": "FSRU Gdansk (planowany)",
        "type": "lng",
        "lat": 54.392, "lon": 18.725,
        "capacity": "6.1 mld m3/rok",
        "status": "planned",
    },
    {
        "name": "DCT Gdansk",
        "type": "container",
        "lat": 54.383, "lon": 18.717,
        "capacity": "",
        "status": "operational",
    },
    {
        "name": "Port Gdynia — basen wewnetrzny",
        "type": "port",
        "lat": 54.534, "lon": 18.548,
        "capacity": "",
        "status": "operational",
    },
]


# ═══════════════════════════════════════════════════════════════════════
# Realne incydenty z raportu
# ═══════════════════════════════════════════════════════════════════════

INCIDENTS = [
    {
        "id": "mv_sun_2025",
        "name": "MV SUN — manewry przy SwePol Link",
        "vessel": {
            "name": "MV SUN",
            "imo": 9293117,
            "type": "Suezmax tanker",
            "flag": "AG",  # Antigua & Barbuda
            "built": 2005,
            "shadow_fleet": True,
        },
        "date_start": "2025-05-12",
        "date_end": "2025-05-22",
        "timeline": [
            {"date": "2025-05-12", "event": "Tranzyt przez ciesn. dunskie (Kattegat, Great Belt)"},
            {"date": "2025-05-15", "event": "Redukcja predkosci przy Olandii, opuszczenie TSS na poludnie"},
            {"date": "2025-05-16", "event": "Cykliczne manewry w poblizu trasy SwePol Link"},
            {"date": "2025-05-17", "event": "Pierwsze wejscie na kontr-kurs w polskiej EEZ"},
            {"date": "2025-05-18", "event": "Identyfikacja: lot rozp. M28B Bryza, NATO wykrywa anomalie"},
            {"date": "2025-05-20", "event": "ORP Heweliusz skierowany do ochrony; PSE potwierdza normalnosc kabla"},
            {"date": "2025-05-21", "event": "Sankcje UE nalozone na MV SUN"},
            {"date": "2025-05-22", "event": "Jednostka opuszcza polska EEZ"},
        ],
        "behavior": {
            "min_speed_kn": 2.5,
            "maneuver_type": "cykliczne zwroty w poblizu infrastruktury",
            "detection_delay_days": 6,
            "note": "Nie mozna rozstrzygnac zamiaru jednostki",
        },
        "location": {
            # Na morzu ~20 km na polnoc od Ustki, przy trasie SwePol Link
            # i >8 km od pozostalej infrastruktury, zeby incydent jednoznacznie
            # dotyczyl tego kabla. Poprzednie (54.30, 17.00) wypadalo na ladzie
            # pod Slupskiem.
            "lat": 54.786,
            "lon": 16.605,
            "area": "Okolice trasy SwePol Link, polska EEZ",
        },
        "lesson": (
            "6-8 dni od pierwszych obserwacji do formalnej reakcji. "
            "System Baltic Trust Layer z oknami 15-min wykrylby anomalie "
            "w zachowaniu (loitering, niska predkosc, bliskosc infrastruktury) "
            "w ciagu minut."
        ),
    },
    {
        "id": "eagle_s_2024",
        "name": "Eagle S — uszkodzenie 5 kabli",
        "vessel": {
            "name": "EAGLE S",
            "type": "tankowiec shadow fleet",
            "flag": "CK",  # Cook Islands
            "shadow_fleet": True,
        },
        "date_start": "2024-12-25",
        "date_end": "2024-12-26",
        "location": {
            "lat": 59.72,
            "lon": 24.55,
            "area": "Zatoka Finska, 90 km odcinek",
        },
        "damage": "5 kabli podmorskich uszkodzonych na odcinku 90 km",
        "legal_note": (
            "Sad Regionalnyw Helsinkach oddalil zarzuty wobec kapitana "
            "i 2 oficerow, powolujac sie na ograniczenia UNCLOS ws. "
            "jurysdykcji karnej poza wodami terytorialnymi."
        ),
    },
    {
        "id": "yi_peng_3_2024",
        "name": "Yi Peng 3 — zerwanie kabli Litwa-Gotlandia + C-Lion1",
        "vessel": {
            "name": "YI PENG 3",
            "type": "bulk carrier",
            "flag": "CN",
        },
        "date_start": "2024-11-17",
        "date_end": "2024-11-18",
        "location": {
            "lat": 57.35,
            "lon": 18.75,
            "area": "Odcinek Litwa-Gotlandia / C-Lion1",
        },
        "damage": "Kable Litwa-Gotlandia + C-Lion1 uszkodzone",
    },
    {
        "id": "balticconnector_2023",
        "name": "Balticconnector — uszkodzenie gazociagu",
        "date_start": "2023-10-01",
        "location": {
            "lat": 59.62,
            "lon": 23.75,
            "area": "Zatoka Finska",
        },
        "damage": "Przerwanie dostaw gazu Estonia-Finlandia",
    },
    {
        "id": "nord_stream_2022",
        "name": "Nord Stream 1/2 — eksplozje",
        "date_start": "2022-09-26",
        "location": {
            "lat": 55.54,
            "lon": 15.70,
            "area": "Poludniowy Baltyk, okolice Bornholmu",
        },
        "damage": "Cztery nitki gazociagu uszkodzone",
    },
]


# ═══════════════════════════════════════════════════════════════════════
# Statystyki z raportu
# ═══════════════════════════════════════════════════════════════════════

REPORT_STATS = {
    "gnss_jamming": {
        "eurocontrol_events_2024": 2500,
        "tdoa_detection_time_s": 300,
        "polska_tarcza_sensors_planned": 100,
        "epicenter": "Kaliningrad",
    },
    "shadow_fleet": {
        "monthly_sanctioned_tankers_baltic": "150-170",
        "danish_waters_transits_2025": 292,
        "ais_manipulation": [
            "Wylaczanie transpondera AIS",
            "Spoofing z fikcyjnymi numerami IMO",
            "Fałszowanie tożsamości (zmiana MMSI/IMO)",
            "Manipulacja flagą bandery",
        ],
    },
    "maritime_traffic": {
        "vessels_on_baltic_at_any_time": 1500,
        "global_trade_share_pct": "8-15",
        "cargo_share_pct": 47,
        "tanker_share_pct": 23,
        "passenger_share_pct": 4,
        "polish_ports_2025_mln_tons": 128,
        "gdansk_port_ships_2025": 3650,
        "gdansk_port_tons_2025_mln": 80.4,
    },
    "response_times": {
        "pre_2024_hours": 17,
        "nato_baltic_sentry_hours": 1,
        "mv_sun_detection_delay_days": "6-8",
        "transit_polish_waters_hours": "6-8",
    },
    "infrastructure": {
        "subsea_cables_count": 35,
        "baltic_avg_depth_m": 50,
        "polish_max_depth_m": 118,
        "wind_power_operational_gw": 3.1,
        "wind_power_target_2030_gw": 19.6,
    },
    "polish_monitoring": {
        "ksbm_radars": 27,
        "ksbm_coastal": 6,
        "ksbm_gdansk_bay": 3,
        "vhf_stations": 12,
        "cctv_cameras": 26,
        "rdf_units": 5,
        "dgps_stations": 2,
        "hel_camera_range_nm": 7,
    },
}


# ═══════════════════════════════════════════════════════════════════════
# Rekomendacje CBM (Centrum Bezpieczenstwa Morskiego)
# 12 priorytetow architektonicznych
# ═══════════════════════════════════════════════════════════════════════

def serialize_infrastructure() -> dict:
    """Snapshot dla dashboardu i /api/infrastructure."""
    cables = []
    for item in SUBSEA_INFRASTRUCTURE:
        cables.append({
            "name": item["name"],
            "type": item["type"],
            "capacity": item.get("capacity", ""),
            "status": item.get("status", "operational"),
            "route": [list(p) for p in item.get("route", [])],
            "incident": bool(item.get("incident") or item.get("incident_proximity")),
            "incident_note": item.get("incident", ""),
            "note": item.get("note", ""),
        })

    terminals = []
    for item in ENERGY_TERMINALS:
        terminals.append({
            "name": item["name"],
            "type": item["type"],
            "lat": item["lat"],
            "lon": item["lon"],
            "capacity": item.get("capacity", ""),
            "status": item.get("status", "operational"),
        })

    incidents = []
    for item in INCIDENTS:
        loc = item.get("location") or {}
        if "lat" not in loc or "lon" not in loc:
            continue
        incidents.append({
            "id": item["id"],
            "name": item["name"],
            "lat": loc["lat"],
            "lon": loc["lon"],
            "area": loc.get("area", ""),
        })

    return {
        "cables": cables,
        "terminals": terminals,
        "incidents": incidents,
        "stats": {
            "subsea_cables_count_report": REPORT_STATS["infrastructure"]["subsea_cables_count"],
            "shown": len(cables),
        },
    }


CBM_PRIORITIES = [
    "Calodobowa wymiana informacji z progami eskalacji",
    "Fuzja danych wielozrodlowych (integracja, nie zastapienie)",
    "Klasyfikacja anomalii i gradacja ryzyka",
    "Tworzenie obrazu sytuacyjnego z roznych domen",
    "Kontrola dostepu oparta na rolach (RBAC)",
    "Identyfikacja jurysdykcji — routing do wlasciwego organu",
    "Wsparcie przekazywania — ciaglosc swiadomosci",
    "Koordynacja miedzynarodowa — wymiana danych z partnerami",
    "Koordynacja kryzysowa — eskalacja miedzyagencyjna",
    "Inzynieria odpornosci — redundantne czujniki i sciezki",
    "Otwarta architektura — integracja nowych zdolnosci bez przebudowy",
    "Szkolenie/symulacja — generowanie scenariuszy",
]
