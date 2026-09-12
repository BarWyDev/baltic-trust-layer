"""
Klient AISStream.io — WebSocket z pelnym zestawem pol integralnosciowych.
Wyciaga RAIM, PositionAccuracy, UTCSecond, NavigationalStatus z PositionReport.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import time
from typing import Any, AsyncIterator, Awaitable, Callable

import aiohttp

from models import AISReport, StaticReport
from data.gdansk_bay import GDANSK_BAY_BBOX

logger = logging.getLogger("ais_client")

# Waski bbox Zatoki czesto daje 0 ramek na darmowym AISStream
# (malo/brak stacji odbiorczych w tym prostokacie).
# Live slucha poludniowego Baltyku — detektory i tak filtrują akwen.
LIVE_BBOX = {
    "south": 53.80,
    "north": 56.20,
    "west": 14.20,
    "east": 20.80,
}
BBOX = [[
    [LIVE_BBOX["south"], LIVE_BBOX["west"]],
    [LIVE_BBOX["north"], LIVE_BBOX["east"]],
]]

AISSTREAM_WS_URL = "wss://stream.aisstream.io/v0/stream"


class AISStreamClient:
    """
    Asynchroniczny klient WebSocket dla AISStream.io.
    Filtruje do Zatoki Gdanskiej, wyciaga pola integralnosciowe.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("AISSTREAM_API_KEY", "")
        self._running = False
        self._reconnect_delay = 5
        self._max_reconnect_delay = 60
        self._session: aiohttp.ClientSession | None = None
        self.stats = {
            "ws_connected": False,
            "raw_messages": 0,
            "position_reports": 0,
            "static_reports": 0,
            "errors": 0,
            "last_error": "",
            "last_message_type": "",
        }

    async def _connect(self) -> aiohttp.ClientWebSocketResponse:
        """Polacz z AISStream i wyslij subskrypcje."""
        if self._session is None:
            self._session = aiohttp.ClientSession()

        ws = await self._session.ws_connect(
            AISSTREAM_WS_URL,
            heartbeat=20,
            compress=15,
        )

        subscribe_msg = {
            "APIKey": self.api_key,
            "BoundingBoxes": BBOX,
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
        }
        await ws.send_json(subscribe_msg)
        self.stats["ws_connected"] = True
        logger.info(
            "Polaczono z AISStream, bbox %s–%s N, %s–%s E",
            LIVE_BBOX["south"],
            LIVE_BBOX["north"],
            LIVE_BBOX["west"],
            LIVE_BBOX["east"],
        )
        return ws

    def _parse_position_report(self, msg: dict) -> AISReport | None:
        """
        Parsuj PositionReport z AISStream do AISReport.
        AISStream dostarcza pola integralnosciowe w MetaData i Message.PositionReport.
        """
        try:
            meta = msg.get("MetaData", {})
            pos = msg.get("Message", {}).get("PositionReport", {})

            if not pos:
                return None

            mmsi = meta.get("MMSI", 0)
            if not mmsi:
                return None

            # Pola integralnosciowe z PositionReport
            raim = pos.get("Raim", False)
            position_accuracy = pos.get("PositionAccuracy", False)
            # W AISStream: Timestamp to UTC second (0-63), nie unix timestamp
            utc_second = pos.get("Timestamp", 60)  # 60 = unavailable
            nav_status = pos.get("NavigationalStatus", 15)  # 15 = not defined

            return AISReport(
                mmsi=mmsi,
                name=meta.get("ShipName", f"MMSI-{mmsi}").strip(),
                lat=meta.get("latitude", pos.get("Latitude", 0.0)),
                lon=meta.get("longitude", pos.get("Longitude", 0.0)),
                sog=pos.get("Sog", 0.0),
                cog=pos.get("Cog", 0.0),
                heading=pos.get("TrueHeading", 0.0),
                nav_status=nav_status,
                position_accuracy=bool(position_accuracy),
                raim=bool(raim),
                utc_second=int(utc_second),
                ship_type=meta.get("ShipType", 0),
                timestamp=time.time(),  # czas odbioru
                msg_type=pos.get("MessageID", 1),
                flag=meta.get("Flag", ""),
                destination=meta.get("Destination", ""),
            )
        except Exception as e:
            logger.warning(f"Blad parsowania PositionReport: {e}")
            return None

    def _parse_static_data(self, msg: dict) -> StaticReport | None:
        """
        Parsuj ShipStaticData (AIS typ 5) do StaticReport.
        Komunikat nie zawiera pozycji — niesie tozsamosc jednostki:
        IMO, sygnal wywolawczy, wymiary, zanurzenie, port przeznaczenia.
        """
        try:
            meta = msg.get("MetaData", {})
            stat = msg.get("Message", {}).get("ShipStaticData", {})

            if not stat:
                return None

            mmsi = meta.get("MMSI") or stat.get("UserID") or 0
            if not mmsi:
                return None

            dim = stat.get("Dimension", {}) or {}
            eta = stat.get("Eta", {}) or {}
            eta_str = ""
            if eta.get("Month"):
                eta_str = (
                    f"{eta.get('Month', 0):02d}-{eta.get('Day', 0):02d} "
                    f"{eta.get('Hour', 0):02d}:{eta.get('Minute', 0):02d}"
                )

            name = (stat.get("Name") or meta.get("ShipName") or "").strip()

            return StaticReport(
                mmsi=int(mmsi),
                name=name or f"MMSI-{mmsi}",
                imo=int(stat.get("ImoNumber", 0) or 0),
                callsign=(stat.get("CallSign") or "").strip(),
                ship_type=int(stat.get("Type", 0) or 0),
                destination=(stat.get("Destination") or "").strip(),
                draught=float(stat.get("MaximumStaticDraught", 0.0) or 0.0),
                dim_bow=float(dim.get("A", 0.0) or 0.0),
                dim_stern=float(dim.get("B", 0.0) or 0.0),
                dim_port=float(dim.get("C", 0.0) or 0.0),
                dim_starboard=float(dim.get("D", 0.0) or 0.0),
                eta=eta_str,
                flag=meta.get("Flag", ""),
                timestamp=time.time(),  # czas odbioru
                msg_type=int(stat.get("MessageID", 5) or 5),
            )
        except Exception as e:
            logger.warning(f"Blad parsowania ShipStaticData: {e}")
            return None

    async def stream_reports(
        self,
        callback: Callable[[AISReport], None] | None = None,
        static_callback: Callable[[StaticReport], Awaitable[Any]] | None = None,
    ) -> AsyncIterator[AISReport]:
        """
        Generuje raporty AIS w petli z auto-reconnect.
        Mozna uzyc jako async iterator lub z callbackiem.

        Komunikaty statyczne (typ 5) nie sa yieldowane — ida osobnym
        kanalem przez static_callback, zeby nie mieszac typow w iteratorze.
        """
        self._running = True
        delay = self._reconnect_delay

        while self._running:
            try:
                ws = await self._connect()
                delay = self._reconnect_delay  # reset po udanym polaczeniu

                async for raw_msg in ws:
                    if not self._running:
                        break
                    if raw_msg.type in (
                        aiohttp.WSMsgType.TEXT,
                        aiohttp.WSMsgType.BINARY,
                    ):
                        payload = raw_msg.data
                        if isinstance(payload, (bytes, bytearray)):
                            payload = payload.decode("utf-8", errors="replace")
                        try:
                            data = json.loads(payload)
                        except json.JSONDecodeError:
                            continue

                        self.stats["raw_messages"] += 1

                        # AISStream przy zlym kluczu / throttle: {"error": "..."}
                        if "error" in data:
                            self.stats["errors"] += 1
                            self.stats["last_error"] = str(data.get("error", data))
                            logger.error("AISStream odrzucil subskrypcje: %s", data["error"])
                            break

                        msg_type = data.get("MessageType", "")
                        self.stats["last_message_type"] = msg_type or "(brak)"

                        if not msg_type:
                            logger.warning("AISStream wiadomosc bez typu: %s", list(data.keys()))
                            continue

                        if msg_type == "PositionReport":
                            report = self._parse_position_report(data)
                            if report:
                                self.stats["position_reports"] += 1
                                if callback:
                                    callback(report)
                                yield report
                        elif msg_type == "ShipStaticData":
                            static = self._parse_static_data(data)
                            if static:
                                self.stats["static_reports"] += 1
                                if static_callback:
                                    await static_callback(static)
                        elif self.stats["raw_messages"] <= 5:
                            logger.info("AISStream MessageType=%s (pomijam)", msg_type)

                    elif raw_msg.type in (
                        aiohttp.WSMsgType.ERROR,
                        aiohttp.WSMsgType.CLOSED,
                    ):
                        break

            except Exception as e:
                logger.error(f"AISStream error: {e}")

            if self._running:
                logger.info(f"Reconnect za {delay}s...")
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_delay)

    def stop(self):
        """Zatrzymaj klienta."""
        self._running = False

    async def close(self):
        """Zamknij sesje HTTP."""
        self.stop()
        if self._session:
            await self._session.close()
            self._session = None
