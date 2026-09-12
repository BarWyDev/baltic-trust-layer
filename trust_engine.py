"""
Silnik oceny wiarygodnosci — Trust Scoring Engine (FR-010).
Agregacja detekcji w heksy H3, okna 15-minutowe, przypisanie trust level.
"""
from __future__ import annotations
import time
from collections import defaultdict
import h3
from models import (
    AISReport, StaticReport, Detection, DetectionType, DetectorFamily,
    Confidence, TrustLevel, HexCell, TimeWindow
)
from detectors.integrity_detectors import (
    run_integrity_checks, IntegrityDegradationDetector
)
from detectors.geometry_detectors import (
    run_geometry_checks, KinematicJumpDetector, ConvergentClusterDetector,
    InfraProximityDetector, PositionLossDetector,
)

# ── Stale konfiguracyjne ───────────────────────────────────────────────

H3_RESOLUTION = 7          # ~5.16 km² heksy — dobry balans dla Zatoki Gdanskiej
WINDOW_DURATION_S = 900    # 15 minut
MIN_VESSELS_FOR_SCORE = 2  # Minimum jednostek dla dowodow deklarowanej integralnosci
                           # (geometria fizyczna liczy sie niezaleznie od liczby jednostek)

# Wagi detekcji w scoring — geometria wazy wiecej bo jest bardziej jednoznaczna
DETECTION_WEIGHTS = {
    DetectionType.POSITION_ON_LAND: 30,
    DetectionType.KINEMATIC_JUMP: 25,
    DetectionType.CONVERGENT_CLUSTER: 35,
    DetectionType.RAIM_OFF: 10,
    DetectionType.LOW_ACCURACY: 5,
    DetectionType.TIMESTAMP_ANOMALY: 15,
    DetectionType.INTEGRITY_DEGRADATION: 20,
    DetectionType.POSITION_LOSS: 15,
    DetectionType.INFRA_PROXIMITY: 20,
    DetectionType.LOITERING: 30,
}

# Confidence multiplier
CONFIDENCE_MULTIPLIER = {
    Confidence.LOW: 0.5,
    Confidence.MEDIUM: 1.0,
    Confidence.HIGH: 1.5,
}

# Progi trust level (score 0 = idealne, im wyzsze tym gorzej)
TRUST_THRESHOLDS = {
    TrustLevel.TRUSTED: 15,        # score < 15 = zaufany
    TrustLevel.LIMITED: 40,         # 15 <= score < 40 = ograniczone zaufanie
    # score >= 40 = nie uzywaj GNSS
}


# ── Klasa silnika ──────────────────────────────────────────────────────

class TrustEngine:
    """
    Glowny silnik Baltic Trust Layer.
    Przetwarza raporty AIS, uruchamia detektory, agreguje w heksy H3.
    """

    def __init__(self, h3_resolution: int = H3_RESOLUTION):
        self.h3_resolution = h3_resolution
        self.jump_detector = KinematicJumpDetector()
        self.cluster_detector = ConvergentClusterDetector()
        self.infra_detector = InfraProximityDetector()
        self.position_loss_detector = PositionLossDetector()
        self.integrity_degradation = IntegrityDegradationDetector()

        # Rejestr danych statycznych (typ 5) — mmsi -> ostatni StaticReport
        self._static_registry: dict[int, StaticReport] = {}

        # Biezace okno czasowe
        self._current_window: TimeWindow | None = None
        self._window_detections: list[Detection] = []
        self._window_reports_per_hex: dict[str, list[AISReport]] = defaultdict(list)

        # Historia okien (ostatnie N)
        self._history: list[TimeWindow] = []
        self._max_history = 48  # 48 * 15min = 12h

        # Bufor ostatnich detekcji (dla /api/detections i debugowania).
        # Musi byc ograniczony: przy ~336 tys. detekcji/h i ~1.4 kB na sztuke
        # nieprzycinana lista rosla o ~0.5 GB na godzine demo. Historia okien
        # ma wlasny limit (_max_history), wiec stabilizuje sie sama.
        self._all_detections: list[Detection] = []
        self._max_all_detections = 1000

        # Licznik wszystkich detekcji od startu — potrzebny osobno, bo
        # len(_all_detections) po przycieciu nie jest juz suma calkowita
        self._detections_seen = 0

    @property
    def current_window(self) -> TimeWindow | None:
        return self._current_window

    @property
    def history(self) -> list[TimeWindow]:
        return list(self._history)

    @property
    def all_detections(self) -> list[Detection]:
        return list(self._all_detections)

    @property
    def detections_seen(self) -> int:
        """Liczba wszystkich detekcji od startu (bufor jest przycinany)."""
        return self._detections_seen

    def _record_detections(self, detections: list[Detection]) -> None:
        """Dopisz do bufora ostatnich detekcji, przycinajac do limitu."""
        if not detections:
            return
        self._detections_seen += len(detections)
        self._all_detections.extend(detections)
        overflow = len(self._all_detections) - self._max_all_detections
        if overflow > 0:
            del self._all_detections[:overflow]

    def _get_h3_index(self, lat: float, lon: float) -> str:
        """Oblicz H3 index dla pozycji."""
        return h3.latlng_to_cell(lat, lon, self.h3_resolution)

    def _ensure_window(self, timestamp: float) -> bool:
        """
        Upewnij sie ze mamy aktywne okno czasowe.
        Zwraca True jesli utworzono nowe okno (poprzednie zamknieto).
        """
        if self._current_window is None:
            # Zaokraglij do 15 minut
            window_start = (timestamp // WINDOW_DURATION_S) * WINDOW_DURATION_S
            self._current_window = TimeWindow(
                start=window_start,
                end=window_start + WINDOW_DURATION_S,
            )
            return False

        if timestamp >= self._current_window.end:
            # Zamknij biezace okno, otworz nowe
            self._finalize_window()
            window_start = (timestamp // WINDOW_DURATION_S) * WINDOW_DURATION_S
            self._current_window = TimeWindow(
                start=window_start,
                end=window_start + WINDOW_DURATION_S,
            )
            return True

        return False

    def _finalize_window(self):
        """Zamknij biezace okno: oblicz trust scores, zapisz do historii."""
        if self._current_window is None:
            return

        # FR-008: Integrity degradation per hex
        deg_detections = self.integrity_degradation.evaluate(
            self._current_window.start, self._current_window.end
        )
        self._window_detections.extend(deg_detections)
        self._record_detections(deg_detections)

        # Agreguj detekcje do heksow
        hex_detections: dict[str, list[Detection]] = defaultdict(list)
        for det in self._window_detections:
            h3_idx = self._get_h3_index(det.lat, det.lon)
            hex_detections[h3_idx].append(det)

        # Zbuduj HexCells
        all_hex_indices = set(self._window_reports_per_hex.keys()) | set(hex_detections.keys())

        for h3_idx in all_hex_indices:
            reports = self._window_reports_per_hex.get(h3_idx, [])
            dets = hex_detections.get(h3_idx, [])

            vessel_count = len({r.mmsi for r in reports})
            center = h3.cell_to_latlng(h3_idx)

            # Policz detekcje per rodzina
            integrity_count = sum(
                1 for d in dets if d.family == DetectorFamily.DECLARED_INTEGRITY
            )
            geometry_count = sum(
                1 for d in dets if d.family == DetectorFamily.PHYSICAL_GEOMETRY
            )

            # Oblicz trust score
            trust_score, trust_level = self._evaluate_hex(dets, vessel_count)

            cell = HexCell(
                h3_index=h3_idx,
                center_lat=center[0],
                center_lon=center[1],
                trust_score=trust_score,
                trust_level=trust_level,
                vessel_count=vessel_count,
                detection_count=len(dets),
                episode_count=self._count_episodes(dets),
                detections=dets,
                integrity_detections=integrity_count,
                geometry_detections=geometry_count,
            )
            self._current_window.hex_cells[h3_idx] = cell

        # Zapisz do historii
        self._history.append(self._current_window)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        # Reset na nowe okno
        self._window_detections.clear()
        self._window_reports_per_hex.clear()
        self.integrity_degradation.reset()

    @staticmethod
    def _dedupe_episodes(detections: list[Detection]) -> list[Detection]:
        """
        Sprowadz detekcje do unikalnych epizodow.

        Detektory pracuja per raport, wiec ta sama anomalia potrafi wygenerowac
        setki detekcji w jednym oknie (4 statki x 90 raportow = 360 detekcji
        jednego klastra zbieznego). Bez deduplikacji score mierzy czestotliwosc
        raportowania, nie powage zjawiska, i saturuje sie na 100 dla kazdego
        heksa z jakakolwiek anomalia.

        Klucz epizodu zalezy od zasiegu detekcji:
        - jednostkowa (1 MMSI) -> typ + MMSI, bo kazdy statek to osobny epizod
        - obszarowa (wiele MMSI) -> sam typ, bo sklad potrafi fluktuowac miedzy
          raportami (raz 3 statki w klastrze, raz 4) i ten sam fizyczny klaster
          liczylby sie kilka razy

        Z duplikatow zostaje ten o najwyzszej pewnosci.
        """
        best: dict[tuple, Detection] = {}
        for det in detections:
            if len(det.mmsi_list) > 1:
                key = (det.detection_type, ())
            else:
                key = (det.detection_type, tuple(det.mmsi_list))
            current = best.get(key)
            if current is None or (
                CONFIDENCE_MULTIPLIER.get(det.confidence, 1.0)
                > CONFIDENCE_MULTIPLIER.get(current.confidence, 1.0)
            ):
                best[key] = det
        return list(best.values())

    @classmethod
    def _count_episodes(cls, detections: list[Detection]) -> int:
        """Liczba unikalnych epizodow (a nie surowych detekcji) w heksie."""
        return len(cls._dedupe_episodes(detections))

    @classmethod
    def _scorable_episodes(
        cls, detections: list[Detection], vessel_count: int
    ) -> list[Detection]:
        """
        Epizody, ktore wolno wliczyc do score przy tej liczbie jednostek.

        Prog MIN_VESSELS_FOR_SCORE dotyczy wylacznie rodziny "deklarowana
        integralnosc": pojedynczy statek z RAIM off nie mowi nic o akwenie,
        dopiero kilka jednostek z tym samym objawem to sygnal o obszarze.

        Rodzina "geometria fizyczna" (pozycja na ladzie, skok kinematyczny,
        loitering przy infrastrukturze, utrata pozycji) to twardy dowod
        niezalezny od liczby jednostek — jeden tankowiec krazacy nad kablem
        jest faktem, nie statystyka. Bez tego rozroznienia sztandarowy
        scenariusz MV SUN (samotna jednostka we wlasnym heksie) generowal
        ~200 detekcji na okno i nie wplywal na nic.
        """
        episodes = cls._dedupe_episodes(detections)
        if vessel_count >= MIN_VESSELS_FOR_SCORE:
            return episodes
        return [
            det for det in episodes
            if det.family == DetectorFamily.PHYSICAL_GEOMETRY
        ]

    @staticmethod
    def _score_episodes(episodes: list[Detection], vessel_count: int) -> float:
        """
        Score = suma_jednostkowa / vessel_count + suma_obszarowa

        Detekcje dotyczace jednej jednostki (RAIM off, skok, loitering) dziela
        sie przez liczbe jednostek w heksie — to udzial dotknietej floty.
        Detekcje obszarowe (klaster zbiezny, degradacja integralnosci) juz
        agreguja wiele MMSI, wiec dzielenie ich drugi raz przez liczbe
        jednostek zaniza je bez powodu.

        Znormalizowane do 0-100.
        """
        if not episodes:
            return 0.0

        per_vessel = 0.0
        area = 0.0

        for det in episodes:
            weight = DETECTION_WEIGHTS.get(det.detection_type, 10)
            multiplier = CONFIDENCE_MULTIPLIER.get(det.confidence, 1.0)
            contribution = weight * multiplier

            if len(det.mmsi_list) > 1:
                area += contribution
            else:
                per_vessel += contribution

        score = per_vessel / max(vessel_count, 1) + area

        return min(score, 100.0)

    def _evaluate_hex(
        self, detections: list[Detection], vessel_count: int
    ) -> tuple[float, TrustLevel]:
        """
        Policz (score, poziom zaufania) dla heksa.

        Wspolne dla obu sciezek agregacji — zamkniecia okna i snapshotu
        biezacego okna — zeby nie rozjechaly sie przy zmianie scoringu.

        NO_DATA oznacza brak podstaw do oceny: za malo jednostek na wnioski
        statystyczne I zadnego twardego dowodu geometrycznego.
        """
        episodes = self._scorable_episodes(detections, vessel_count)

        if not episodes and vessel_count < MIN_VESSELS_FOR_SCORE:
            return 0.0, TrustLevel.NO_DATA

        score = self._score_episodes(episodes, vessel_count)

        # Potwierdzony dowod geometryczny wyklucza TRUSTED. Rekomendacja dla
        # tego poziomu brzmi "brak istotnych anomalii w akwenie" — a to nie jest
        # prawda w heksie, w ktorym statek zniknal z pozycji albo stoi na ladzie,
        # nawet jesli pojedynczy epizod o niskiej pewnosci wyszedl arytmetycznie
        # ponizej progu. Podnosimy score do progu, a nie sam poziom, zeby liczba
        # na dashboardzie zgadzala sie z etykieta.
        if any(d.family == DetectorFamily.PHYSICAL_GEOMETRY for d in episodes):
            score = max(score, TRUST_THRESHOLDS[TrustLevel.TRUSTED])

        return score, self._score_to_level(score)

    def _score_to_level(self, score: float) -> TrustLevel:
        """Przypisz trust level na podstawie score."""
        if score < TRUST_THRESHOLDS[TrustLevel.TRUSTED]:
            return TrustLevel.TRUSTED
        elif score < TRUST_THRESHOLDS[TrustLevel.LIMITED]:
            return TrustLevel.LIMITED
        else:
            return TrustLevel.DO_NOT_USE

    # ── Interfejs publiczny ─────────────────────────────────────────────

    def process_report(self, report: AISReport) -> list[Detection]:
        """
        Przetworz pojedynczy raport AIS przez wszystkie detektory.
        Zwraca liste detekcji wygenerowanych dla tego raportu.
        """
        window_changed = self._ensure_window(report.timestamp)

        # Przypisz do heksa
        h3_idx = self._get_h3_index(report.lat, report.lon)
        self._window_reports_per_hex[h3_idx].append(report)

        # FR-008: dodaj do statystyk degradacji
        self.integrity_degradation.add_report(report, h3_idx)

        # Detektory per-raport
        detections = []

        # Rodzina: deklarowana integralnosc
        detections.extend(run_integrity_checks(report))

        # Rodzina: geometria fizyczna
        detections.extend(run_geometry_checks(
            report,
            jump_det=self.jump_detector,
            cluster_det=self.cluster_detector,
            infra_det=self.infra_detector,
            loss_det=self.position_loss_detector,
        ))

        # Zapisz detekcje do okna
        self._window_detections.extend(detections)
        self._record_detections(detections)

        return detections

    def process_static(self, static: StaticReport) -> None:
        """
        Zarejestruj komunikat statyczny AIS (typ 5).
        Sam z siebie nie generuje detekcji — jest dowodem, ze transponder
        dziala, co pozwala PositionLossDetector odroznic wyciszenie pozycji
        (FR-006) od zwyklego wyjscia jednostki z akwenu.
        """
        self._static_registry[static.mmsi] = static
        self.position_loss_detector.add_static(static)

    def get_static(self, mmsi: int) -> StaticReport | None:
        """Ostatnie dane statyczne dla MMSI (tozsamosc, IMO, wymiary)."""
        return self._static_registry.get(mmsi)

    @property
    def static_registry(self) -> dict[int, StaticReport]:
        return dict(self._static_registry)

    def get_current_hex_snapshot(self) -> dict[str, dict]:
        """
        Zwroc aktualny stan heksow (dla dashboardu).
        Laczy dane z biezacego (niezamknietego) okna.
        """
        snapshot = {}

        # Dane z biezacego okna — oblicz na biezaco
        hex_detections: dict[str, list[Detection]] = defaultdict(list)
        for det in self._window_detections:
            h3_idx = self._get_h3_index(det.lat, det.lon)
            hex_detections[h3_idx].append(det)

        all_indices = set(self._window_reports_per_hex.keys()) | set(hex_detections.keys())

        for h3_idx in all_indices:
            reports = self._window_reports_per_hex.get(h3_idx, [])
            dets = hex_detections.get(h3_idx, [])
            vessel_count = len({r.mmsi for r in reports})
            center = h3.cell_to_latlng(h3_idx)

            integrity_count = sum(
                1 for d in dets if d.family == DetectorFamily.DECLARED_INTEGRITY
            )
            geometry_count = sum(
                1 for d in dets if d.family == DetectorFamily.PHYSICAL_GEOMETRY
            )

            score, level = self._evaluate_hex(dets, vessel_count)

            snapshot[h3_idx] = {
                "h3_index": h3_idx,
                "center": [center[0], center[1]],
                "trust_score": round(score, 1),
                "trust_level": level.value,
                "vessel_count": vessel_count,
                "detection_count": len(dets),
                "episode_count": self._count_episodes(dets),
                "integrity_detections": integrity_count,
                "geometry_detections": geometry_count,
                "boundary": [list(c) for c in h3.cell_to_boundary(h3_idx)],
            }

        return snapshot

    def get_brief(self) -> dict:
        """
        FR-014: Generuj brief z rekomendacjami.
        Zamkniety zbior: TRUSTED / LIMITED / DO_NOT_USE / NO_DATA.
        """
        snapshot = self.get_current_hex_snapshot()

        # Policz heksy per trust level
        level_counts = {tl.value: 0 for tl in TrustLevel}
        worst_hexes = []

        for h3_idx, data in snapshot.items():
            level_counts[data["trust_level"]] += 1
            if data["trust_level"] in ("limited", "do_not_use"):
                worst_hexes.append(data)

        # Sortuj worst hexes po score malejaco
        worst_hexes.sort(key=lambda x: x["trust_score"], reverse=True)

        # Ogolna rekomendacja — najgorszy hex determinuje
        if any(d["trust_level"] == "do_not_use" for d in worst_hexes):
            overall = TrustLevel.DO_NOT_USE.value
            recommendation = (
                "NIE OPIERAJ MANEWRU NA GNSS. "
                "Wykryto silne sygnaly zaklocen/spoofingu w czesci akwenu. "
                "Weryfikuj pozycje radarem i wizualnie."
            )
        elif any(d["trust_level"] == "limited" for d in worst_hexes):
            overall = TrustLevel.LIMITED.value
            recommendation = (
                "OGRANICZONE ZAUFANIE DO GNSS. "
                "Wykryto anomalie integralnosciowe w czesci akwenu. "
                "Zalecana weryfikacja radarem."
            )
        elif level_counts.get("trusted", 0) > 0:
            overall = TrustLevel.TRUSTED.value
            recommendation = (
                "POZYCJA GNSS WIARYGODNA. "
                "Brak istotnych anomalii w akwenie operacyjnym."
            )
        else:
            overall = TrustLevel.NO_DATA.value
            recommendation = (
                "BRAK DANYCH. "
                "Za malo jednostek w akwenie do oceny wiarygodnosci GNSS."
            )

        return {
            "timestamp": time.time(),
            "overall_trust": overall,
            "recommendation": recommendation,
            "hex_summary": level_counts,
            "total_hexes": len(snapshot),
            "total_detections": self._detections_seen,
            "worst_areas": worst_hexes[:5],  # top 5 najgorszych
            "window": {
                "start": self._current_window.start if self._current_window else 0,
                "end": self._current_window.end if self._current_window else 0,
            },
        }

    def force_finalize(self):
        """Wymus zamkniecie biezacego okna (np. do testow)."""
        self._finalize_window()
