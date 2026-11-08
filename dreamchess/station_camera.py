"""A top-camera picture on request, from the station, kept in memory only.

The station holds its cameras, and saves frames only while it runs a move (to ~/.dreamlabs/last-run_inputs, which it
replaces on every run). Its first frame is saved within milliseconds of the start, while Dream-1's first motion takes
seconds to arrive (its first action chunk landed 2.8 s in on our runs, and the arms then ramp in over 2 s). So a
picture is a "hold still" run stopped as soon as that first frame is there: the arms never move. The station then
runs its home move (the arms are already home) and goes idle, about 4 s in all.

The picture is read into memory; this writes nothing to disk.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .vision import CalibrationError, Frame

HOLD_PROMPT = "Hold completely still. Do not move either arm."
STOP_BY_S = 1.2  # stop the run by now, picture or not: far ahead of the first motion
IDLE_WITHIN_S = 20.0


class StationSnapshot:
    """A FrameSource: each read() is one fresh top-camera picture, taken with the arms at home and still."""

    def __init__(self, client, folder: str = "~/.dreamlabs/last-run_inputs", role: str = "top",
                 log: Callable[[str], None] = lambda _: None, clock=time.time, sleep=time.sleep):
        self.client, self.folder, self.role = client, Path(folder).expanduser() / role, role
        self.log, self.clock, self.sleep = log, clock, sleep

    def _newest(self, since: float) -> Path | None:
        if not self.folder.is_dir():
            return None
        fresh = [p for p in self.folder.glob("*.jpg") if p.stat().st_mtime >= since]
        return max(fresh, key=lambda p: p.stat().st_mtime) if fresh else None

    def _wait_idle(self) -> dict:
        """Until the station is idle and stays idle: after a stop it's idle for a moment before its home move."""
        deadline = self.clock() + IDLE_WITHIN_S
        idle_polls = 0
        while True:
            status = self.client.status()
            idle_polls = idle_polls + 1 if status.get("state") == "idle" else 0
            if idle_polls >= 2 or self.clock() > deadline:
                return status
            self.sleep(0.25)

    def read(self) -> Frame:
        status = self.client.status()
        if status.get("state") != "idle":
            raise CalibrationError(f"the station is {status.get('state')}: a picture waits until it's idle")
        asked = self.clock() - 0.05
        self.client.start(HOLD_PROMPT, 1)
        picture, moved = None, False
        try:
            while self.clock() - asked < STOP_BY_S:
                picture = self._newest(asked)
                if picture is not None:
                    break
                status = self.client.status()
                if (status.get("chunks") or 0) > 0 and status.get("state") == "running":
                    moved = True  # Dream-1 answered unusually fast: stop now, before the arms can ramp in
                    break
                self.sleep(0.03)
        finally:
            self.client.stop()
        image = None
        for _ in range(5):  # the station may still be writing it
            if picture is None:
                break
            image = cv2.imdecode(np.frombuffer(picture.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is not None:
                break
            self.sleep(0.05)
        self._wait_idle()
        if moved:
            self.log("      the picture run got an action before its frame: stopped it at once")
        if image is None:
            raise CalibrationError("the station didn't save a top-camera frame in time")
        return Frame(color=image)
