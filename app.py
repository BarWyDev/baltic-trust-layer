"""
Baltic Trust Layer — glowna aplikacja FastAPI.
Tryby: demo (symulowane dane) | live (AISStream.io) | replay (CSV)
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# Dodaj katalog projektu do path
sys.path.insert(0, str(Path(__file__).parent))

from models import AISReport, StaticReport, TrustLevel
from trust_engine import TrustEngine
from demo_simulator import DemoSimulator
from data.iceye_context import serialize_infrastructure

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("btl")

# ── Stan globalny ──────────────────────────────────────────────────────

trust_engine = TrustEngine()
simulator: DemoSimulator | None = None
ais_client = None  # AISStreamClient — lazy import

ws_clients: set[WebSocket] = set()
last_vessels: dict[int, dict] = {}

# Statystyki
stats = {
    "reports_processed": 0,
    "static_processed": 0,
    "detections_total": 0,
    "processing_errors": 0,
    "start_time": 0.0,
    "mode": "unknown",
}


# ── WebSocket broadcast ───────────────────────────────────────────────

async def broadcast(data: dict):
    """Wyslij dane do wszystkich podlaczonych klientow WebSocket."""
    if not ws_clients:
        return
    msg = json.dumps(data)
    dead = set()
    for ws in ws_clients:
        try:
            # Timeout: martwy/zablokowany klient nie moze zatrzymac zrodla danych
            await asyncio.wait_for(ws.send_text(msg), timeout=1.0)
        except Exception:
            dead.add(ws)
    ws_clients.difference_update(dead)


# ── Obsluga bledow przetwarzania ───────────────────────────────────────

_MAX_LOGGED_ERRORS = 5


def log_processing_error(gdzie: str, exc: Exception) -> None:
    """
    Zaloguj blad przetwarzania, nie przerywajac strumienia danych.

    Bez tego pojedynczy zly raport zabijal caly task asyncio, a wyjatek
    nie trafial nigdzie — symulator umieral po cichu, dashboard dostawal
    tylko 'init'. Dokladnie tak ukryl sie kiedys blad w broadcast().

    Pierwsze bledy logujemy z pelnym tracebackiem, pozniej tylko zliczamy,
    zeby jedna powtarzalna usterka nie zalala logu w trakcie prezentacji.
    """
    stats["processing_errors"] += 1
    if stats["processing_errors"] <= _MAX_LOGGED_ERRORS:
        logger.exception("Blad przetwarzania (%s)", gdzie)
    elif stats["processing_errors"] % 100 == 0:
        logger.error(
            "Blad przetwarzania (%s): %s — lacznie %d bledow",
            gdzie, exc, stats["processing_errors"],
        )


# ── Callback przetwarzania raportu ─────────────────────────────────────

async def process_report(report: AISReport):
    """
    Przetworz raport AIS przez TrustEngine i broadcast wynikow.
    Nigdy nie propaguje wyjatku — zrodlo danych ma plynac dalej mimo
    pojedynczego zlego raportu.
    """
    try:
        await _process_report(report)
    except Exception as e:
        log_processing_error(f"raport MMSI {getattr(report, 'mmsi', '?')}", e)


async def _process_report(report: AISReport):
    stats["reports_processed"] += 1

    vessel = report.to_dict()
    # Dolacz tozsamosc z komunikatu statycznego (typ 5), jesli znana
    static = trust_engine.get_static(report.mmsi)
    if static is not None:
        vessel["imo"] = static.imo
        vessel["callsign"] = static.callsign
        vessel["draught"] = static.draught
    last_vessels[report.mmsi] = vessel

    detections = trust_engine.process_report(report)
    stats["detections_total"] += len(detections)

    # Wyslij raport + detekcje (nawet bez klientow — last_vessels juz zapisane)
    payload = {
        "type": "report",
        "vessel": vessel,
        "detections": [d.to_dict() for d in detections],
    }
    await broadcast(payload)

    # Co 20 raportow — wyslij hex snapshot
    if stats["reports_processed"] % 20 == 0:
        hex_data = trust_engine.get_current_hex_snapshot()
        brief = trust_engine.get_brief()
        await broadcast({
            "type": "hex_update",
            "hexes": hex_data,
            "brief": brief,
            "vessels": list(last_vessels.values()),
            "stats": {
                "reports": stats["reports_processed"],
                "static": stats["static_processed"],
                "detections": stats["detections_total"],
                "uptime_s": time.time() - stats["start_time"],
            },
        })


async def process_static(static: StaticReport):
    """
    Przetworz komunikat statyczny AIS (typ 5).
    Nie generuje detekcji sam z siebie i nie jest rozsylany osobno —
    zasila rejestr tozsamosci i PositionLossDetector (FR-006).
    """
    try:
        stats["static_processed"] += 1
        trust_engine.process_static(static)

        # Jednostka moze byc znana tylko ze statycznych (pozycji brak)
        known = last_vessels.get(static.mmsi)
        if known is not None:
            known["imo"] = static.imo
            known["callsign"] = static.callsign
            known["draught"] = static.draught
    except Exception as e:
        log_processing_error(f"komunikat statyczny MMSI {getattr(static, 'mmsi', '?')}", e)


# ── Lifespan ───────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uruchom zrodlo danych w tle."""
    global simulator, ais_client
    stats["start_time"] = time.time()

    mode = os.getenv("MODE", "demo")
    stats["mode"] = mode
    logger.info(f"Baltic Trust Layer — tryb: {mode}")

    task = None

    def start_simulator(powod: str = "") -> asyncio.Task:
        """Uruchom symulator w tle. Uzywane takze jako fallback z live/replay."""
        global simulator
        simulator = DemoSimulator(speedup=60)
        logger.info(
            "Symulator: %d jednostek w Zatoce Gdanskiej%s",
            simulator.vessel_count, f" ({powod})" if powod else "",
        )

        async def demo_loop():
            try:
                await simulator.run(process_report, process_static)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Bez tego wyjatek w tasku asyncio nie trafia nigdzie
                # i symulator umiera po cichu
                logger.exception("Symulator zatrzymal sie z bledem")

        return asyncio.create_task(demo_loop())

    if mode == "demo":
        task = start_simulator()

    elif mode == "live":
        from ais_client import AISStreamClient
        api_key = os.getenv("AISSTREAM_API_KEY", "")
        if not api_key or api_key == "your_api_key_here":
            logger.error("Brak AISSTREAM_API_KEY! Uzyj MODE=demo lub ustaw klucz.")
            task = start_simulator("fallback z trybu live")
        else:
            ais_client = AISStreamClient(api_key)

            async def live_loop():
                try:
                    async for report in ais_client.stream_reports(
                        static_callback=process_static
                    ):
                        await process_report(report)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Strumien AISStream zatrzymal sie")

            task = asyncio.create_task(live_loop())

    elif mode == "replay":
        replay_file = os.getenv("REPLAY_FILE", "")
        if replay_file and Path(replay_file).exists():
            task = asyncio.create_task(replay_csv(replay_file))
        else:
            logger.error(f"Brak pliku replay: {replay_file}. Fallback do demo.")
            task = start_simulator("fallback z trybu replay")

    yield

    # Cleanup
    if simulator:
        simulator.stop()
    if ais_client:
        await ais_client.close()
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def replay_csv(filepath: str):
    """Odtwarzanie z pliku CSV — placeholder, do rozbudowy."""
    import csv
    logger.info(f"Replay z pliku: {filepath}")
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                report = AISReport(
                    mmsi=int(row.get("MMSI", 0)),
                    name=row.get("ShipName", f"MMSI-{row.get('MMSI', '?')}"),
                    lat=float(row.get("Latitude", 0)),
                    lon=float(row.get("Longitude", 0)),
                    sog=float(row.get("SOG", 0)),
                    cog=float(row.get("COG", 0)),
                    heading=float(row.get("Heading", 0)),
                    nav_status=int(row.get("NavigationalStatus", 15)),
                    position_accuracy=bool(int(row.get("PositionAccuracy", 0))),
                    raim=bool(int(row.get("RAIM", 0))),
                    utc_second=int(row.get("UTCSecond", 60)),
                    ship_type=int(row.get("ShipType", 0)),
                    timestamp=float(row.get("Timestamp", time.time())),
                    msg_type=int(row.get("MessageType", 1)),
                )
                await process_report(report)
                await asyncio.sleep(0.05)  # throttle
            except Exception as e:
                logger.warning(f"Blad parsowania CSV row: {e}")
                continue


# ── FastAPI app ────────────────────────────────────────────────────────

app = FastAPI(
    title="Baltic Trust Layer",
    description="Warstwa wiarygodnosci GNSS dla Zatoki Gdanskiej",
    version="0.1.0",
    lifespan=lifespan,
)

# Serwuj pliki statyczne
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── Endpointy ──────────────────────────────────────────────────────────

@app.get("/")
async def index():
    """Serwuj dashboard."""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse("<h1>Baltic Trust Layer</h1><p>Brak pliku dashboard.</p>")


@app.get("/prezentacja")
async def prezentacja():
    """Pitch 3 min — slajdy HTML."""
    return RedirectResponse("/static/prezentacja/index.html")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket do real-time updates."""
    await ws.accept()
    ws_clients.add(ws)
    logger.info(f"WebSocket connected ({len(ws_clients)} total)")

    # Wyslij stan poczatkowy
    try:
        hex_data = trust_engine.get_current_hex_snapshot()
        brief = trust_engine.get_brief()
        await ws.send_text(json.dumps({
            "type": "init",
            "hexes": hex_data,
            "brief": brief,
            "vessels": list(last_vessels.values()),
            "stats": {
                "reports": stats["reports_processed"],
                "static": stats["static_processed"],
                "detections": stats["detections_total"],
                "mode": stats["mode"],
            },
        }))

        # Utrzymuj polaczenie
        while True:
            data = await ws.receive_text()
            # Klient moze wyslac ping lub zadanie brief
            if data == "brief":
                brief = trust_engine.get_brief()
                await ws.send_text(json.dumps({
                    "type": "brief",
                    "brief": brief,
                }))
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)
        logger.info(f"WebSocket disconnected ({len(ws_clients)} total)")


@app.get("/api/infrastructure")
async def get_infrastructure():
    """Kable, rurociagi, terminale i incydenty (ICEYE × Impulse)."""
    return JSONResponse(serialize_infrastructure())


@app.get("/api/hexes")
async def get_hexes():
    """Biezacy snapshot heksow H3."""
    return JSONResponse(trust_engine.get_current_hex_snapshot())


@app.get("/api/brief")
async def get_brief():
    """FR-014: Brief z rekomendacjami."""
    return JSONResponse(trust_engine.get_brief())


@app.get("/api/detections")
async def get_detections():
    """Lista wszystkich detekcji z biezacego okna."""
    dets = trust_engine.all_detections
    return JSONResponse([d.to_dict() for d in dets[-100:]])  # ostatnie 100


@app.get("/api/static")
async def get_static_data():
    """Rejestr danych statycznych AIS (typ 5) — tozsamosc jednostek."""
    return JSONResponse([
        s.to_dict() for s in trust_engine.static_registry.values()
    ])


@app.get("/api/stats")
async def get_stats():
    """Statystyki systemu."""
    payload = {
        **stats,
        "uptime_s": time.time() - stats["start_time"],
        "ws_clients": len(ws_clients),
        "history_windows": len(trust_engine.history),
        "vessels_tracked": len(last_vessels),
    }
    if ais_client is not None:
        payload["aisstream"] = ais_client.stats
    return JSONResponse(payload)


@app.get("/api/history")
async def get_history():
    """Historia okien czasowych z trust levels."""
    return JSONResponse([
        {
            "label": tw.label,
            "start": tw.start,
            "end": tw.end,
            "hex_count": len(tw.hex_cells),
            "hexes": {
                h3_idx: cell.to_dict()
                for h3_idx, cell in tw.hex_cells.items()
            },
        }
        for tw in trust_engine.history
    ])


# ── Main ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
