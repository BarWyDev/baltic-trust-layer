"""
Modele danych Baltic Trust Layer.
Dwie rodziny dowodow: deklarowana integralnosc + geometria fizyczna.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
import time


# ===== AIS integrity fields (z komunikatow typu 1/2/3) =====

class NavStatus(int, Enum):
    """Navigation Status z AIS msg 1/2/3, bity 38-41."""
    UNDERWAY_ENGINE = 0
    AT_ANCHOR = 1
    NOT_UNDER_COMMAND = 2
    RESTRICTED_MANEUVERABILITY = 3
    CONSTRAINED_DRAUGHT = 4
    MOORED = 5
    AGROUND = 6
    FISHING = 7
    UNDERWAY_SAILING = 8
    # 9-13 reserved
    AIS_SART = 14
    NOT_DEFINED = 15


class UTCSecond(int, Enum):
    """Specjalne wartosci UTC Second (bity 137-142)."""
    UNAVAILABLE = 60
    MANUAL_MODE = 61
    DEAD_RECKONING = 62
    INOPERATIVE = 63


# ===== Typy detekcji =====

class DetectorFamily(str, Enum):
    """Dwie rodziny dowodow z PRD."""
    DECLARED_INTEGRITY = "declared_integrity"  # FR-002, FR-008: RAIM, accuracy, timestamp
    PHYSICAL_GEOMETRY = "physical_geometry"     # FR-004..FR-007: pozycja, skoki, klastry


class DetectionType(str, Enum):
    # Rodzina: deklarowana integralnosc
    RAIM_OFF = "raim_off"                    # RAIM wylaczony
    LOW_ACCURACY = "low_accuracy"            # Position accuracy = 0 (>10m)
    TIMESTAMP_ANOMALY = "timestamp_anomaly"  # UTC second = 61/62/63
    INTEGRITY_DEGRADATION = "integrity_deg"  # FR-008: zbyt duzy udzial zlych wskaznikow w heksie

    # Rodzina: geometria fizyczna
    POSITION_ON_LAND = "position_on_land"    # FR-004: pozycja na ladzie (poza maska portowa)
    KINEMATIC_JUMP = "kinematic_jump"        # FR-005: skok kinematyczny > 60 kn
    POSITION_LOSS = "position_loss"          # FR-006: komunikaty statyczne sa, pozycyjnych brak
    CONVERGENT_CLUSTER = "convergent_cluster" # FR-007: wiele MMSI w jednym punkcie
    INFRA_PROXIMITY = "infra_proximity"      # Bliskosc infrastruktury krytycznej + anomalia
    LOITERING = "loitering"                  # Loitering/dryf przy infrastrukturze


class Confidence(str, Enum):
    """Trzystopniowa skala pewnosci (FR-009) zamiast 0-1."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TrustLevel(str, Enum):
    """Rekomendacja manewrowa — zamkniety zbior 3 wartosci."""
    TRUSTED = "trusted"                  # Pozycja wiarygodna
    LIMITED = "limited"                  # Ograniczone zaufanie, weryfikuj radarem
    DO_NOT_USE = "do_not_use"            # Nie opieraj manewru na GNSS
    NO_DATA = "no_data"                  # Za malo jednostek do oceny


# ===== Struktury danych =====

@dataclass
class AISReport:
    """Pojedynczy raport AIS z pelnym zestawem pol integralnosciowych."""
    mmsi: int
    name: str
    lat: float
    lon: float
    sog: float              # speed over ground (knots)
    cog: float              # course over ground (degrees)
    heading: float
    nav_status: int          # 0-15
    position_accuracy: bool  # True = high (<=10m), False = low (>10m)
    raim: bool               # True = RAIM in use
    utc_second: int          # 0-63
    ship_type: int
    timestamp: float         # unix epoch
    msg_type: int            # 1, 2, or 3
    flag: str = ""
    destination: str = ""

    @property
    def has_integrity_issue(self) -> bool:
        """Czy wskazniki integralnosciowe sygnalizuja problem?"""
        return (
            not self.raim
            or not self.position_accuracy
            or self.utc_second in (61, 62, 63)
        )

    @property
    def utc_second_label(self) -> str:
        if self.utc_second <= 59:
            return f"{self.utc_second}s"
        return {60: "unavail", 61: "MANUAL", 62: "DEAD_RECK", 63: "INOP"}.get(
            self.utc_second, f"?{self.utc_second}"
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["has_integrity_issue"] = self.has_integrity_issue
        d["utc_second_label"] = self.utc_second_label
        return d


@dataclass
class StaticReport:
    """
    Komunikat statyczny AIS (typ 5 / AISStream ShipStaticData).
    Nie zawiera pozycji — niesie tozsamosc jednostki i parametry kadluba.
    Uzywany przez PositionLossDetector (FR-006): transponder zyje,
    ale pozycyjnych brak.
    """
    mmsi: int
    name: str = ""
    imo: int = 0
    callsign: str = ""
    ship_type: int = 0
    destination: str = ""
    draught: float = 0.0          # maksymalne zanurzenie statyczne (m)
    dim_bow: float = 0.0          # A — dziob do anteny (m)
    dim_stern: float = 0.0        # B — antena do rufy (m)
    dim_port: float = 0.0         # C — antena do lewej burty (m)
    dim_starboard: float = 0.0    # D — antena do prawej burty (m)
    eta: str = ""
    flag: str = ""
    timestamp: float = 0.0        # unix epoch (czas odbioru)
    msg_type: int = 5

    @property
    def length_m(self) -> float:
        return self.dim_bow + self.dim_stern

    @property
    def beam_m(self) -> float:
        return self.dim_port + self.dim_starboard

    def to_dict(self) -> dict:
        d = asdict(self)
        d["length_m"] = self.length_m
        d["beam_m"] = self.beam_m
        return d


@dataclass
class Detection:
    """Pojedyncza detekcja — wynik jednego detektora."""
    id: str
    detection_type: DetectionType
    family: DetectorFamily
    confidence: Confidence
    mmsi_list: list[int]         # dotknięte jednostki
    vessel_names: list[str]
    lat: float
    lon: float
    time_start: float
    time_end: float
    description: str
    evidence: dict = field(default_factory=dict)  # surowe dowody

    def to_dict(self) -> dict:
        d = asdict(self)
        d["detection_type"] = self.detection_type.value
        d["family"] = self.family.value
        d["confidence"] = self.confidence.value
        return d


@dataclass
class HexCell:
    """Pojedynczy heks H3 z ocena wiarygodnosci."""
    h3_index: str
    center_lat: float
    center_lon: float
    trust_score: float          # 0-100
    trust_level: TrustLevel
    vessel_count: int
    detection_count: int        # surowe detekcje (jedna anomalia = wiele detekcji)
    episode_count: int = 0      # unikalne epizody — to wchodzi do score
    detections: list[Detection] = field(default_factory=list)
    # Rozdzielenie dowodow per rodzina
    integrity_detections: int = 0    # rodzina "deklarowana integralnosc"
    geometry_detections: int = 0     # rodzina "geometria fizyczna"

    def to_dict(self) -> dict:
        d = {
            "h3_index": self.h3_index,
            "center": [self.center_lat, self.center_lon],
            "trust_score": round(self.trust_score, 1),
            "trust_level": self.trust_level.value,
            "vessel_count": self.vessel_count,
            "detection_count": self.detection_count,
            "episode_count": self.episode_count,
            "integrity_detections": self.integrity_detections,
            "geometry_detections": self.geometry_detections,
            "detections": [d.to_dict() for d in self.detections],
        }
        return d


@dataclass
class TimeWindow:
    """15-minutowe okno czasowe z heksami."""
    start: float
    end: float
    hex_cells: dict[str, HexCell] = field(default_factory=dict)  # h3_index -> HexCell

    @property
    def label(self) -> str:
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(self.start, tz=timezone.utc)
        return dt.strftime("%H:%M")
