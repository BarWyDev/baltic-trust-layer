"""
Detektory rodziny "geometria fizyczna" (physical geometry).
FR-004: Pozycja na ladzie (z wylaczeniem masek portowych)
FR-005: Skok kinematyczny > 60 kn miedzy kolejnymi raportami
FR-006: Utrata pozycji (komunikaty statyczne sa, pozycyjnych brak)
FR-007: Klaster zbiezny (wiele MMSI w jednym punkcie)
"""
from __future__ import annotations
import time
from models import (
    AISReport, StaticReport, Detection, DetectionType, DetectorFamily, Confidence
)
from data.gdansk_bay import (
    is_likely_on_land, is_in_port_mask, is_in_operational_area,
    haversine_km, min_distance_to_route_km,
)
from data.iceye_context import SUBSEA_INFRASTRUCTURE


# ── FR-004: Pozycja na ladzie ──────────────────────────────────────────

def detect_position_on_land(report: AISReport) -> Detection | None:
    """
    Pozycja na ladzie poza maska portowa.
    Maski portowe wykluczaja doki, nabrzeza, kanaly — tam 'na ladzie' jest ok.
    """
    if not is_in_operational_area(report.lat, report.lon):
        return None

    if not is_likely_on_land(report.lat, report.lon):
        return None

    # is_likely_on_land juz wyklucza port masks, ale dla jasnosci:
    return Detection(
        id=f"land-{report.mmsi}-{int(report.timestamp)}",
        detection_type=DetectionType.POSITION_ON_LAND,
        family=DetectorFamily.PHYSICAL_GEOMETRY,
        confidence=Confidence.HIGH,
        mmsi_list=[report.mmsi],
        vessel_names=[report.name],
        lat=report.lat,
        lon=report.lon,
        time_start=report.timestamp,
        time_end=report.timestamp,
        description=(
            f"{report.name} (MMSI {report.mmsi}): "
            f"pozycja na ladzie ({report.lat:.4f}, {report.lon:.4f})"
        ),
        evidence={
            "lat": report.lat,
            "lon": report.lon,
            "in_port_mask": False,
        },
    )


# ── FR-005: Skok kinematyczny ──────────────────────────────────────────

class KinematicJumpDetector:
    """
    Wykrywa skoki kinematyczne: jesli odleglosc miedzy kolejnymi raportami
    implikuje predkosc > 60 kn (ok. 111 km/h), to jest anomalia.
    Na hackatonie: proste porownanie dwoch kolejnych raportow per MMSI.
    """

    JUMP_THRESHOLD_KN = 60.0  # prędkość w węzłach
    KN_TO_KMH = 1.852         # 1 knot = 1.852 km/h

    def __init__(self):
        # mmsi -> ostatni AISReport
        self._last_report: dict[int, AISReport] = {}

    def reset(self):
        self._last_report.clear()

    def check(self, report: AISReport) -> Detection | None:
        """Sprawdz czy nastapil skok kinematyczny od ostatniego raportu."""
        prev = self._last_report.get(report.mmsi)
        self._last_report[report.mmsi] = report

        if prev is None:
            return None

        dt = report.timestamp - prev.timestamp
        if dt <= 0:
            return None

        dist_km = haversine_km(prev.lat, prev.lon, report.lat, report.lon)
        dt_hours = dt / 3600.0
        if dt_hours < 0.0001:  # zbyt krotki interwał
            return None

        implied_speed_kn = (dist_km / dt_hours) / self.KN_TO_KMH

        if implied_speed_kn <= self.JUMP_THRESHOLD_KN:
            return None

        # Confidence rośnie z prędkością
        if implied_speed_kn > 200:
            conf = Confidence.HIGH
        elif implied_speed_kn > 100:
            conf = Confidence.MEDIUM
        else:
            conf = Confidence.LOW

        return Detection(
            id=f"jump-{report.mmsi}-{int(report.timestamp)}",
            detection_type=DetectionType.KINEMATIC_JUMP,
            family=DetectorFamily.PHYSICAL_GEOMETRY,
            confidence=conf,
            mmsi_list=[report.mmsi],
            vessel_names=[report.name],
            lat=report.lat,
            lon=report.lon,
            time_start=prev.timestamp,
            time_end=report.timestamp,
            description=(
                f"{report.name} (MMSI {report.mmsi}): skok kinematyczny "
                f"{dist_km:.1f} km w {dt:.0f}s "
                f"(implikowana predkosc {implied_speed_kn:.0f} kn)"
            ),
            evidence={
                "prev_lat": prev.lat,
                "prev_lon": prev.lon,
                "curr_lat": report.lat,
                "curr_lon": report.lon,
                "distance_km": round(dist_km, 2),
                "time_delta_s": round(dt, 1),
                "implied_speed_kn": round(implied_speed_kn, 1),
            },
        )


# ── FR-007: Klaster zbiezny ───────────────────────────────────────────

class ConvergentClusterDetector:
    """
    Wykrywa sytuacje gdy wiele roznych MMSI raportuje dokladnie ta sama
    (lub bardzo bliska) pozycje — sygnatura spoofingu broadcast.
    Prog: >= 3 MMSI w promieniu 50m w ciagu 2 minut.
    """

    CLUSTER_RADIUS_KM = 0.05   # 50 metrow
    CLUSTER_WINDOW_S = 120.0    # 2 minuty
    MIN_VESSELS = 3             # minimum 3 rozne MMSI

    def __init__(self):
        # Lista aktywnych raportow w oknie
        self._recent_reports: list[AISReport] = []

    def reset(self):
        self._recent_reports.clear()

    def check(self, report: AISReport) -> Detection | None:
        """Dodaj raport i sprawdz czy tworzy klaster zbiezny."""
        now = report.timestamp

        # Usun raporty spoza okna
        self._recent_reports = [
            r for r in self._recent_reports
            if now - r.timestamp <= self.CLUSTER_WINDOW_S
        ]
        self._recent_reports.append(report)

        # Znajdz raporty blisko biezacego
        nearby: list[AISReport] = []
        for r in self._recent_reports:
            if r.mmsi == report.mmsi:
                continue
            dist = haversine_km(report.lat, report.lon, r.lat, r.lon)
            if dist <= self.CLUSTER_RADIUS_KM:
                nearby.append(r)

        # Unikalne MMSI w klastrze (wliczajac biezacy)
        cluster_mmsis = {report.mmsi}
        cluster_names = {report.name}
        for r in nearby:
            cluster_mmsis.add(r.mmsi)
            cluster_names.add(r.name)

        if len(cluster_mmsis) < self.MIN_VESSELS:
            return None

        # Confidence rośnie z liczba jednostek w klastrze
        if len(cluster_mmsis) >= 5:
            conf = Confidence.HIGH
        elif len(cluster_mmsis) >= 4:
            conf = Confidence.MEDIUM
        else:
            conf = Confidence.LOW

        return Detection(
            id=f"cluster-{int(report.lat*1000)}-{int(report.lon*1000)}-{int(now)}",
            detection_type=DetectionType.CONVERGENT_CLUSTER,
            family=DetectorFamily.PHYSICAL_GEOMETRY,
            confidence=conf,
            mmsi_list=sorted(cluster_mmsis),
            vessel_names=sorted(cluster_names),
            lat=report.lat,
            lon=report.lon,
            time_start=now - self.CLUSTER_WINDOW_S,
            time_end=now,
            description=(
                f"Klaster zbiezny: {len(cluster_mmsis)} jednostek w promieniu "
                f"{self.CLUSTER_RADIUS_KM*1000:.0f}m "
                f"({report.lat:.4f}, {report.lon:.4f})"
            ),
            evidence={
                "cluster_center": [report.lat, report.lon],
                "vessel_count": len(cluster_mmsis),
                "mmsis": sorted(cluster_mmsis),
                "radius_m": self.CLUSTER_RADIUS_KM * 1000,
            },
        )


# ── Bliskosc infrastruktury krytycznej ─────────────────────────────────

class InfraProximityDetector:
    """
    Wykrywa jednostki w poblizu infrastruktury krytycznej podmorskiej
    (kable, rurociagi) z anomalnym zachowaniem.
    Inspirowane incydentem MV SUN (maj 2025) — loitering przy SwePol Link.
    """

    PROXIMITY_THRESHOLD_KM = 5.0    # alert < 5 km od infrastruktury
    LOITER_THRESHOLD_KM = 2.0       # loitering < 2 km
    SLOW_SPEED_KN = 4.0             # ponizej = podejrzana niska predkosc
    LOITER_MIN_REPORTS = 3          # minimum raportow w strefie
    LOITER_MIN_DURATION_S = 300     # minimum czasu w strefie zeby uznac loitering
    # Historia musi obejmowac wiecej niz LOITER_MIN_DURATION_S przy typowym
    # interwale AIS (~10 s), inaczej loitering nigdy sie nie wyzwoli.
    HISTORY_MAX_REPORTS = 60

    def __init__(self):
        # mmsi -> lista raportow w poblizu infrastruktury
        self._vessel_near_infra: dict[int, list[dict]] = {}

    def reset(self):
        self._vessel_near_infra.clear()

    def check(self, report: AISReport) -> list[Detection]:
        """Sprawdz bliskosc infrastruktury i zachowanie."""
        detections = []

        for infra in SUBSEA_INFRASTRUCTURE:
            route = infra.get("route", [])
            if not route or len(route) < 2:
                continue

            dist_km = min_distance_to_route_km(report.lat, report.lon, route)

            if dist_km > self.PROXIMITY_THRESHOLD_KM:
                continue

            # Blisko infrastruktury — sprawdz zachowanie
            key = (report.mmsi, infra["name"])
            if key not in self._vessel_near_infra:
                self._vessel_near_infra[key] = []

            self._vessel_near_infra[key].append({
                "lat": report.lat, "lon": report.lon,
                "sog": report.sog, "ts": report.timestamp,
                "dist_km": dist_km,
            })

            self._vessel_near_infra[key] = (
                self._vessel_near_infra[key][-self.HISTORY_MAX_REPORTS:]
            )
            history = self._vessel_near_infra[key]

            # Detekcja 1: Niska predkosc przy infrastrukturze
            if report.sog < self.SLOW_SPEED_KN and dist_km < self.LOITER_THRESHOLD_KM:
                conf = Confidence.HIGH if dist_km < 1.0 else Confidence.MEDIUM
                detections.append(Detection(
                    id=f"infra-{report.mmsi}-{infra['name'][:10]}-{int(report.timestamp)}",
                    detection_type=DetectionType.INFRA_PROXIMITY,
                    family=DetectorFamily.PHYSICAL_GEOMETRY,
                    confidence=conf,
                    mmsi_list=[report.mmsi],
                    vessel_names=[report.name],
                    lat=report.lat, lon=report.lon,
                    time_start=report.timestamp,
                    time_end=report.timestamp,
                    description=(
                        f"{report.name}: {report.sog:.1f} kn w odl. "
                        f"{dist_km:.1f} km od {infra['name']}"
                    ),
                    evidence={
                        "infrastructure": infra["name"],
                        "distance_km": round(dist_km, 2),
                        "sog": report.sog,
                        "infra_type": infra.get("type", "unknown"),
                    },
                ))

            # Detekcja 2: Loitering — wiele raportow w strefie
            if len(history) >= self.LOITER_MIN_REPORTS:
                close_reports = [r for r in history if r["dist_km"] < self.LOITER_THRESHOLD_KM]
                if len(close_reports) >= self.LOITER_MIN_REPORTS:
                    duration_s = history[-1]["ts"] - history[0]["ts"]
                    avg_sog = sum(r["sog"] for r in close_reports) / len(close_reports)
                    if avg_sog < self.SLOW_SPEED_KN and duration_s > self.LOITER_MIN_DURATION_S:
                        detections.append(Detection(
                            id=f"loiter-{report.mmsi}-{infra['name'][:10]}-{int(report.timestamp)}",
                            detection_type=DetectionType.LOITERING,
                            family=DetectorFamily.PHYSICAL_GEOMETRY,
                            confidence=Confidence.HIGH,
                            mmsi_list=[report.mmsi],
                            vessel_names=[report.name],
                            lat=report.lat, lon=report.lon,
                            time_start=history[0]["ts"],
                            time_end=report.timestamp,
                            description=(
                                f"{report.name}: loitering {duration_s/60:.0f} min "
                                f"przy {infra['name']} (sr. {avg_sog:.1f} kn, "
                                f"odl. {dist_km:.1f} km) — wzorzec MV SUN"
                            ),
                            evidence={
                                "infrastructure": infra["name"],
                                "duration_min": round(duration_s / 60, 1),
                                "avg_speed_kn": round(avg_sog, 1),
                                "reports_in_zone": len(close_reports),
                                "min_distance_km": round(
                                    min(r["dist_km"] for r in close_reports), 2
                                ),
                                "pattern": "mv_sun_like",
                            },
                        ))

        return detections


# ── FR-006: Utrata pozycji ─────────────────────────────────────────────

class PositionLossDetector:
    """
    FR-006: komunikaty statyczne (typ 5) przychodza, pozycyjnych brak.

    Sygnatura selektywnego wyciszenia pozycji przy zywym transponderze AIS:
    jednostka nadal deklaruje tozsamosc, ale przestaje podawac gdzie jest.
    Typowy wzorzec shadow fleet (raport ICEYE: wylaczanie transpondera,
    150-170 sankcjonowanych tankowcow miesiecznie na Baltyku).

    Detektor jest bezstanowy wobec okna czasowego — sledzi pojedyncze MMSI
    i emituje alert dopiero gdy luka przekroczy prog, z cooldownem zeby
    nie zalewac dashboardu przy dlugiej ciszy.
    """

    GAP_THRESHOLD_S = 300.0       # 5 min bez pozycji = luka
    STATIC_FRESHNESS_S = 900.0    # statyczny starszy niz 15 min = caly transponder zamilkl
    REEMIT_COOLDOWN_S = 600.0     # nie powtarzaj alertu dla tego samego MMSI czesciej
    EVAL_INTERVAL_S = 60.0        # nie przemiataj listy przy kazdym raporcie
    TRACK_TTL_S = 7200.0          # porzuc slad po 2 h calkowitej ciszy

    def __init__(self):
        # mmsi -> slad jednostki
        self._tracks: dict[int, dict] = {}
        self._last_eval_ts: float = 0.0

    def reset(self):
        self._tracks.clear()
        self._last_eval_ts = 0.0

    def _track(self, mmsi: int) -> dict:
        if mmsi not in self._tracks:
            self._tracks[mmsi] = {
                "name": "", "imo": 0,
                "last_pos_ts": 0.0, "lat": 0.0, "lon": 0.0,
                "last_static_ts": 0.0,
                "statics_in_gap": 0,
                "last_alert_ts": 0.0,
            }
        return self._tracks[mmsi]

    def add_position(self, report: AISReport):
        """Zarejestruj raport pozycyjny — zamyka ewentualna luke."""
        tr = self._track(report.mmsi)
        tr["name"] = report.name or tr["name"]
        tr["last_pos_ts"] = report.timestamp
        tr["lat"] = report.lat
        tr["lon"] = report.lon
        tr["statics_in_gap"] = 0

    def add_static(self, static: StaticReport):
        """Zarejestruj komunikat statyczny — dowod ze transponder zyje."""
        tr = self._track(static.mmsi)
        if static.name:
            tr["name"] = static.name
        if static.imo:
            tr["imo"] = static.imo
        tr["last_static_ts"] = static.timestamp
        # Statyczny po ostatniej pozycji = nadaje tozsamosc bez pozycji
        if tr["last_pos_ts"] > 0 and static.timestamp > tr["last_pos_ts"]:
            tr["statics_in_gap"] += 1

    def evaluate(self, now: float) -> list[Detection]:
        """
        Sprawdz wszystkie slady i wygeneruj detekcje dla jednostek,
        ktore milcza pozycyjnie mimo swiezych komunikatow statycznych.
        """
        if now - self._last_eval_ts < self.EVAL_INTERVAL_S:
            return []
        self._last_eval_ts = now

        detections = []
        stale = []

        for mmsi, tr in self._tracks.items():
            last_pos = tr["last_pos_ts"]
            last_static = tr["last_static_ts"]

            # Porzuc slady po dlugiej calkowitej ciszy
            if now - max(last_pos, last_static) > self.TRACK_TTL_S:
                stale.append(mmsi)
                continue

            # Potrzebujemy ostatniej znanej pozycji (zeby przypisac heks)
            # oraz swiezego statycznego (inaczej jednostka po prostu odplynela)
            if last_pos <= 0 or last_static <= 0:
                continue

            gap_s = now - last_pos
            if gap_s < self.GAP_THRESHOLD_S:
                continue
            if last_static <= last_pos:
                continue
            if now - last_static > self.STATIC_FRESHNESS_S:
                continue
            if now - tr["last_alert_ts"] < self.REEMIT_COOLDOWN_S:
                continue

            tr["last_alert_ts"] = now

            # Im dluzsza cisza pozycyjna, tym mocniejszy dowod
            if gap_s > 1800:
                conf = Confidence.HIGH
            elif gap_s > 900:
                conf = Confidence.MEDIUM
            else:
                conf = Confidence.LOW

            name = tr["name"] or f"MMSI-{mmsi}"
            detections.append(Detection(
                id=f"posloss-{mmsi}-{int(now)}",
                detection_type=DetectionType.POSITION_LOSS,
                family=DetectorFamily.PHYSICAL_GEOMETRY,
                confidence=conf,
                mmsi_list=[mmsi],
                vessel_names=[name],
                lat=tr["lat"],
                lon=tr["lon"],
                time_start=last_pos,
                time_end=now,
                description=(
                    f"{name} (MMSI {mmsi}): brak pozycji od {gap_s/60:.0f} min, "
                    f"komunikaty statyczne nadal nadawane "
                    f"({tr['statics_in_gap']}x) — transponder zyje"
                ),
                evidence={
                    "gap_min": round(gap_s / 60, 1),
                    "last_position": [tr["lat"], tr["lon"]],
                    "last_position_ts": last_pos,
                    "last_static_ts": last_static,
                    "static_age_s": round(now - last_static, 1),
                    "statics_in_gap": tr["statics_in_gap"],
                    "imo": tr["imo"],
                    "pattern": "selective_ais_silence",
                },
            ))

        for mmsi in stale:
            self._tracks.pop(mmsi, None)

        return detections


# ── Interfejs glowny ───────────────────────────────────────────────────

# Stateful detektory — inicjalizowane raz, utrzymuja stan miedzy raportami
_jump_detector = KinematicJumpDetector()
_cluster_detector = ConvergentClusterDetector()
_infra_detector = InfraProximityDetector()
_position_loss_detector = PositionLossDetector()


def get_jump_detector() -> KinematicJumpDetector:
    return _jump_detector


def get_cluster_detector() -> ConvergentClusterDetector:
    return _cluster_detector


def get_infra_detector() -> InfraProximityDetector:
    return _infra_detector


def get_position_loss_detector() -> PositionLossDetector:
    return _position_loss_detector


def run_geometry_checks(
    report: AISReport,
    jump_det: KinematicJumpDetector | None = None,
    cluster_det: ConvergentClusterDetector | None = None,
    infra_det: InfraProximityDetector | None = None,
    loss_det: PositionLossDetector | None = None,
) -> list[Detection]:
    """Uruchom wszystkie detektory per-raport z rodziny physical_geometry."""
    jd = jump_det or _jump_detector
    cd = cluster_det or _cluster_detector
    ip = infra_det or _infra_detector
    ld = loss_det or _position_loss_detector

    detections = []

    # FR-004: pozycja na ladzie
    det = detect_position_on_land(report)
    if det:
        detections.append(det)

    # FR-005: skok kinematyczny
    det = jd.check(report)
    if det:
        detections.append(det)

    # FR-007: klaster zbiezny
    det = cd.check(report)
    if det:
        detections.append(det)

    # Bliskosc infrastruktury krytycznej (ICEYE report)
    infra_dets = ip.check(report)
    detections.extend(infra_dets)

    # FR-006: utrata pozycji — dotyczy jednostek MILCZACYCH, wiec biezacy
    # raport sluzy tu tylko jako zegar (evaluate ma wlasny throttle)
    ld.add_position(report)
    detections.extend(ld.evaluate(report.timestamp))

    return detections
