"""
Detektory rodziny "deklarowana integralnosc" (declared integrity).
FR-002: RAIM off, low accuracy, timestamp anomaly
FR-008: Integrity degradation per hex (zbyt duzy udzial zlych wskaznikow)
"""
from __future__ import annotations
import time
import uuid
from models import (
    AISReport, Detection, DetectionType, DetectorFamily, Confidence
)


# ── FR-002: Pojedyncze flagi integralnosciowe ──────────────────────────

def detect_raim_off(report: AISReport) -> Detection | None:
    """RAIM wylaczony — sygnalizuje brak kontroli integralnosci GNSS."""
    if report.raim:
        return None
    return Detection(
        id=f"raim-{report.mmsi}-{int(report.timestamp)}",
        detection_type=DetectionType.RAIM_OFF,
        family=DetectorFamily.DECLARED_INTEGRITY,
        confidence=Confidence.MEDIUM,
        mmsi_list=[report.mmsi],
        vessel_names=[report.name],
        lat=report.lat,
        lon=report.lon,
        time_start=report.timestamp,
        time_end=report.timestamp,
        description=f"{report.name} (MMSI {report.mmsi}): RAIM wylaczony",
        evidence={"raim": False, "msg_type": report.msg_type},
    )


def detect_low_accuracy(report: AISReport) -> Detection | None:
    """Position accuracy = 0 (>10m) — zadeklarowana niska dokladnosc."""
    if report.position_accuracy:
        return None
    return Detection(
        id=f"acc-{report.mmsi}-{int(report.timestamp)}",
        detection_type=DetectionType.LOW_ACCURACY,
        family=DetectorFamily.DECLARED_INTEGRITY,
        confidence=Confidence.LOW,
        mmsi_list=[report.mmsi],
        vessel_names=[report.name],
        lat=report.lat,
        lon=report.lon,
        time_start=report.timestamp,
        time_end=report.timestamp,
        description=(
            f"{report.name} (MMSI {report.mmsi}): "
            f"niska dokladnosc pozycji (>10m)"
        ),
        evidence={"position_accuracy": False},
    )


def detect_timestamp_anomaly(report: AISReport) -> Detection | None:
    """UTC second = 61 (manual), 62 (dead reckoning), 63 (inoperative)."""
    if report.utc_second <= 60:
        return None

    label = {61: "manual mode", 62: "dead reckoning", 63: "inoperative"}.get(
        report.utc_second, f"unknown({report.utc_second})"
    )
    # Dead reckoning / inoperative = wiekszy problem niz manual
    conf = Confidence.HIGH if report.utc_second >= 62 else Confidence.MEDIUM

    return Detection(
        id=f"utc-{report.mmsi}-{int(report.timestamp)}",
        detection_type=DetectionType.TIMESTAMP_ANOMALY,
        family=DetectorFamily.DECLARED_INTEGRITY,
        confidence=conf,
        mmsi_list=[report.mmsi],
        vessel_names=[report.name],
        lat=report.lat,
        lon=report.lon,
        time_start=report.timestamp,
        time_end=report.timestamp,
        description=(
            f"{report.name} (MMSI {report.mmsi}): "
            f"UTC second = {report.utc_second} ({label})"
        ),
        evidence={
            "utc_second": report.utc_second,
            "utc_second_label": label,
        },
    )


# ── FR-008: Degradacja integralnosciowa per heks ───────────────────────

class IntegrityDegradationDetector:
    """
    Sledzi udzial raportow z problemami integralnosciowymi w danym heksie.
    Jezeli >30% raportow w oknie czasowym ma flagi integralnosciowe,
    generuje detekcje dla calego heksa.
    """

    DEGRADATION_THRESHOLD = 0.30  # 30% raportow z problemami

    def __init__(self):
        # h3_index -> {"total": int, "flagged": int, "mmsis": set, "names": set}
        self._hex_stats: dict[str, dict] = {}

    def reset(self):
        self._hex_stats.clear()

    def add_report(self, report: AISReport, h3_index: str):
        """Dodaj raport do statystyk heksa."""
        if h3_index not in self._hex_stats:
            self._hex_stats[h3_index] = {
                "total": 0, "flagged": 0,
                "mmsis": set(), "names": set(),
                "lat": 0.0, "lon": 0.0,
            }
        stats = self._hex_stats[h3_index]
        stats["total"] += 1
        stats["mmsis"].add(report.mmsi)
        stats["names"].add(report.name)
        stats["lat"] = report.lat  # ostatnia pozycja jako reprezentacyjna
        stats["lon"] = report.lon

        if report.has_integrity_issue:
            stats["flagged"] += 1

    def evaluate(self, window_start: float, window_end: float) -> list[Detection]:
        """Wygeneruj detekcje degradacji dla heksow przekraczajacych prog."""
        detections = []
        for h3_idx, stats in self._hex_stats.items():
            if stats["total"] < 3:  # minimum 3 raporty zeby oceniac
                continue
            ratio = stats["flagged"] / stats["total"]
            if ratio < self.DEGRADATION_THRESHOLD:
                continue

            # Confidence zalezna od proporcji
            if ratio > 0.6:
                conf = Confidence.HIGH
            elif ratio > 0.4:
                conf = Confidence.MEDIUM
            else:
                conf = Confidence.LOW

            det = Detection(
                id=f"intdeg-{h3_idx}-{int(window_start)}",
                detection_type=DetectionType.INTEGRITY_DEGRADATION,
                family=DetectorFamily.DECLARED_INTEGRITY,
                confidence=conf,
                mmsi_list=sorted(stats["mmsis"]),
                vessel_names=sorted(stats["names"]),
                lat=stats["lat"],
                lon=stats["lon"],
                time_start=window_start,
                time_end=window_end,
                description=(
                    f"Heks {h3_idx}: {ratio:.0%} raportow z problemami "
                    f"integralnosciowymi ({stats['flagged']}/{stats['total']})"
                ),
                evidence={
                    "h3_index": h3_idx,
                    "total_reports": stats["total"],
                    "flagged_reports": stats["flagged"],
                    "ratio": round(ratio, 3),
                    "unique_vessels": len(stats["mmsis"]),
                },
            )
            detections.append(det)
        return detections


# ── Interfejs glowny ───────────────────────────────────────────────────

def run_integrity_checks(report: AISReport) -> list[Detection]:
    """Uruchom wszystkie detektory per-raport z rodziny declared_integrity."""
    detections = []
    for detector_fn in (detect_raim_off, detect_low_accuracy, detect_timestamp_anomaly):
        det = detector_fn(report)
        if det is not None:
            detections.append(det)
    return detections
