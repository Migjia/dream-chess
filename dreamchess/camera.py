"""Frame sources: a real RealSense camera, or frames handed over by another program."""
from __future__ import annotations

import threading
import time

import numpy as np

from .vision import Frame, Intrinsics


def list_realsense() -> list[dict[str, str]]:
    import pyrealsense2 as rs

    return [
        {"name": d.get_info(rs.camera_info.name), "serial": d.get_info(rs.camera_info.serial_number)}
        for d in rs.context().query_devices()
    ]


class RealSenseSource:
    """Reads color and aligned depth. Only one program can open a RealSense at a time."""

    def __init__(self, serial: str | None = None, width: int = 1280, height: int = 720, fps: int = 30, use_depth: bool = True):
        import pyrealsense2 as rs  # imported here so the mock works without the camera SDK

        self.use_depth = use_depth
        self.pipeline = rs.pipeline()
        config = rs.config()
        if serial:
            config.enable_device(serial)
        config.enable_stream(rs.stream.color, width, height, rs.format.bgr8, fps)
        if use_depth:
            config.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
        profile = self.pipeline.start(config)
        self.align = rs.align(rs.stream.color) if use_depth else None
        self.depth_scale = profile.get_device().first_depth_sensor().get_depth_scale() if use_depth else 0.0
        for _ in range(30):  # auto-exposure needs a moment to settle after starting
            self.pipeline.wait_for_frames(5000)

    def read(self) -> Frame:
        frames = self.pipeline.wait_for_frames(5000)
        if not self.use_depth:
            return Frame(np.asanyarray(frames.get_color_frame().get_data()).copy())
        frames = self.align.process(frames)
        color = frames.get_color_frame()
        k = color.profile.as_video_stream_profile().intrinsics
        depth = np.asanyarray(frames.get_depth_frame().get_data()).astype(np.float32) * self.depth_scale
        return Frame(np.asanyarray(color.get_data()).copy(), depth, Intrinsics(k.fx, k.fy, k.ppx, k.ppy))

    def close(self) -> None:
        self.pipeline.stop()


class SharedFrameSource:
    """For when another program owns the camera: it calls update(), and read() returns new frames."""

    def __init__(self, max_age_s: float = 2.0):
        self.max_age_s = max_age_s
        self._frame: Frame | None = None
        self._stamp = 0.0
        self._last_read_stamp = 0.0
        self._changed = threading.Condition()

    def update(self, frame: Frame) -> None:
        with self._changed:
            self._frame = frame
            self._stamp = time.monotonic()
            self._changed.notify_all()

    def read(self) -> Frame:
        with self._changed:
            fresh = self._changed.wait_for(lambda: self._stamp > self._last_read_stamp, timeout=self.max_age_s)
            if not fresh:
                raise TimeoutError(f"no new camera frame in {self.max_age_s} s")
            self._last_read_stamp = self._stamp
            return self._frame
