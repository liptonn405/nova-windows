"""Background battery/media/audio metering; no blocking calls in paint events."""

import asyncio
import sys
import threading
import time
import psutil
from .windows import com


class Monitor:
    def __init__(self):
        self.stop_event = threading.Event()
        self.energy = 0.0
        self.playing = False
        self.battery = None
        self.plugged = False
        self.warning = ""
        self._thread = None

    def start(self):
        if sys.platform != "win32":
            return
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def stop(self):
        self.stop_event.set()

    def run(self):
        with com():
            self._run()

    def _run(self):
        meter = None
        manager = None
        last_device = 0.0
        last_status = 0.0

        async def connect():
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager,
            )

            return await Manager.request_async()

        try:
            manager = asyncio.run(connect())
        except Exception as e:
            self.warning = "Медиасессия недоступна: " + str(e)[:100]
        while not self.stop_event.is_set():
            now = time.monotonic()
            if now - last_device > 10:
                last_device = now
                try:
                    from ctypes import cast, POINTER
                    from comtypes import CLSCTX_ALL
                    from pycaw.pycaw import AudioUtilities
                    from pycaw.api.endpointvolume import IAudioMeterInformation

                    device = AudioUtilities.GetSpeakers()
                    meter = cast(
                        device._dev.Activate(IAudioMeterInformation._iid_, CLSCTX_ALL, None),
                        POINTER(IAudioMeterInformation),
                    )
                except Exception:
                    meter = None
            try:
                self.energy = float(meter.GetPeakValue()) if meter else 0.0
            except Exception:
                meter = None
                self.energy = 0.0
            if now - last_status > 2:
                last_status = now
                battery = psutil.sensors_battery()
                self.battery = battery.percent if battery else None
                self.plugged = bool(battery and battery.power_plugged)
                try:
                    session = manager.get_current_session() if manager else None
                    self.playing = bool(session and int(session.get_playback_info().playback_status) == 4)
                except Exception:
                    self.playing = False
            self.stop_event.wait(0.033 if self.playing else 0.3)
