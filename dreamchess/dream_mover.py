"""HOW: run one pick-and-place on real arms with Dream-1.

Based on the dreamlabs-client 1.1.3 docs. Not yet run against the real service or arms.

The client needs three things running at once: camera ticks feeding set_observation, one
get_action on its own thread, and a loop playing one chunk row per tick. Dream-1 never says
it has finished, so an attempt ends when the gripper closes and reopens, or at a time limit.
Whether it worked is then up to the top camera, not this file.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Protocol

from .core import MoverError, Step

CLOSED_BELOW, OPEN_ABOVE = 0.4, 0.7  # gripper runs from 0 closed to 1 open
MIN_CLOSED_ROWS = 10  # a real grasp, not a flicker
RELEASED_ROWS = 20  # about a second of staying open at 20 Hz


class Station(Protocol):
    """What the YAM station has to provide. Written once the NUC has been inspected."""

    def frames(self) -> dict[str, str]:
        """Block for the next camera tick. Return video.overhead, video.wrist_l and video.wrist_r,
        each a base64 JPEG with no data: prefix, resized to 320x176 at quality 85."""
        ...

    def state(self) -> dict:
        """Return state.right_arm, state.left_arm (6 joints, radians) and state.right_gripper,
        state.left_gripper (1 value, 0 closed to 1 open), as float32 arrays."""
        ...

    def command(self, right: list[float], left: list[float]) -> None:
        """Send one row to each arm: six joint targets, then the gripper."""
        ...

    def home(self) -> None:
        """Clear the top camera's view. Must lift straight up first, so the arm doesn't sweep
        through the pieces, and must not carry off or drop a piece that's still gripped."""
        ...


def dream_config(checkpoint: str = "dreamlabs/dream-1-beta", action_hz: int = 20) -> dict:
    return {
        "timeout_ms": 15000,
        "strict": True,  # the docs say to leave this on
        "checkpoint": checkpoint,
        "action_hz": action_hz,
        "ik": {"arm": "yam", "head": "joint"},
        "embodiment": {
            "state": {"right_arm": [0, 6], "right_gripper": [6, 7], "left_arm": [7, 13], "left_gripper": [13, 14]},
            "action": {"right_arm": [0, 6], "right_gripper": [6, 7], "left_arm": [7, 13], "left_gripper": [13, 14]},
            "video": {role: f"observation.images.{role}" for role in ("overhead", "wrist_l", "wrist_r")},
        },
    }


def connect(checkpoint: str = "dreamlabs/dream-1-beta", action_hz: int = 20):
    """Open a client. Reads the API key from ~/.dreamlabs/credentials or DREAM_API_KEY."""
    import dream

    client = dream.DreamClient()
    client.policy(dream_config(checkpoint, action_hz))
    return client


class _ReleaseDetector:
    """Spots an arm going open, closed, then open again: the piece has been put down."""

    def __init__(self):
        self.phase = "waiting_for_open"
        self.count = 0

    def update(self, gripper: float) -> bool:
        if self.phase == "waiting_for_open":
            if gripper > OPEN_ABOVE:
                self.phase, self.count = "open", 0
        elif self.phase == "open":
            self.count = self.count + 1 if gripper < CLOSED_BELOW else 0
            if self.count >= MIN_CLOSED_ROWS:
                self.phase, self.count = "gripping", 0
        else:
            self.count = self.count + 1 if gripper > OPEN_ABOVE else 0
        return self.phase == "gripping" and self.count >= RELEASED_ROWS


class DreamMover:
    def __init__(
        self,
        station: Station,
        client,
        action_hz: int = 20,
        time_limit_s: float = 90.0,
        max_joint_step_rad: float = 0.2,
        dry_run: bool = False,
        log=print,
    ):
        self.station = station
        self.client = client
        self.period = 1.0 / action_hz
        self.time_limit_s = time_limit_s
        self.max_joint_step_rad = max_joint_step_rad
        self.dry_run = dry_run  # call the model and check its answers, but never move
        self.log = log
        self.rows_played = 0
        self.chunks_received = 0

    def go_home(self) -> None:
        if not self.dry_run:
            self.station.home()

    def _send_observation(self, prompt: str) -> None:
        frames = self.station.frames()
        self.client.set_observation(frames, {**self.station.state(), "prompt": prompt})

    def execute(self, step: Step) -> None:
        self.client.reset_episode()
        self._send_observation(step.prompt)  # the docs require one tick before the first get_action

        stop = threading.Event()
        camera_error: list[BaseException] = []

        def camera_loop() -> None:
            try:
                while not stop.is_set():
                    self._send_observation(step.prompt)
            except Exception as err:
                camera_error.append(err)

        camera = threading.Thread(target=camera_loop, daemon=True)
        camera.start()
        try:
            self._play(camera_error)
        finally:
            stop.set()
            camera.join(timeout=2.0)

    def _measured(self) -> tuple[list[float], list[float]]:
        state = self.station.state()
        return (
            [float(v) for v in state["state.right_arm"]],
            [float(v) for v in state["state.left_arm"]],
        )

    def _check_row(self, row: list[float], previous: list[float] | None, side: str) -> None:
        """Refuse bad targets. Stopping is always safer than a sudden move near chess pieces."""
        if len(row) != 7 or not all(math.isfinite(v) for v in row):
            raise MoverError(f"bad {side} row from the model: {row}")
        if previous is None:
            return
        jump = max(abs(a - b) for a, b in zip(row[:6], previous[:6]))
        if jump > self.max_joint_step_rad:
            raise MoverError(f"{side} arm would jump {jump:.2f} rad in one row; stopping")

    def _play(self, camera_error: list[BaseException]) -> None:
        rows: list[tuple[list[float], list[float]]] = []
        index = executed = played_during_request = 0
        request: threading.Thread | None = None
        reply: dict = {}
        previous: tuple[list[float] | None, list[float] | None] = (None, None)
        detectors = (_ReleaseDetector(), _ReleaseDetector())
        last_sent: tuple[list[float], list[float]] | None = None

        def ask() -> None:
            try:
                # Real arms trail their commands, so the client joins chunks best from the last
                # row actually sent.
                if last_sent is None:
                    reply["action"] = self.client.get_action()
                else:
                    commanded = {"q_r_chunk": last_sent[0], "q_l_chunk": last_sent[1]}
                    reply["action"] = self.client.get_action(commanded=commanded)
            except Exception as err:
                reply["error"] = err

        start = next_tick = time.perf_counter()
        try:
            while time.perf_counter() - start < self.time_limit_s:
                if camera_error:
                    raise MoverError(f"camera stopped: {camera_error[0]}") from camera_error[0]

                if request is not None and not request.is_alive():
                    request = None
                    if "error" in reply:
                        raise MoverError(f"Dream-1 call failed: {reply['error']}") from reply["error"]
                    action = reply["action"]
                    rows = list(zip(action["q_r_chunk"], action["q_l_chunk"]))
                    self.chunks_received += 1
                    # The arms kept moving during the round trip, so those rows are already past.
                    index = min(played_during_request, len(rows))
                    executed = 0
                    if not self.dry_run and index < len(rows):
                        right, left = self._measured()
                        previous = (right, left)
                    else:
                        previous = (None, None)
                    reply.clear()

                remaining = len(rows) - index
                if request is None and (not rows or self.client.refill_due(executed, remaining)):
                    played_during_request = 0
                    request = threading.Thread(target=ask, daemon=True)
                    request.start()

                if index < len(rows):  # with no rows left, the arms hold until the next chunk lands
                    right, left = (list(map(float, r)) for r in rows[index])
                    self._check_row(right, previous[0], "right")
                    self._check_row(left, previous[1], "left")
                    if not self.dry_run:
                        self.station.command(right, left)
                        last_sent = (right, left)
                    previous = (right, left)
                    index += 1
                    executed += 1
                    played_during_request += 1
                    self.rows_played += 1
                    released = [d.update(row[6]) for d, row in zip(detectors, (right, left))]
                    if any(released):
                        self.log("      gripper released: ending this attempt")
                        return

                # Never play late rows in a burst to catch up: after a stall, just carry on from
                # now, because a sudden speed-up near the pieces is worse than running late.
                now = time.perf_counter()
                next_tick = max(next_tick + self.period, now)
                time.sleep(next_tick - now)
            self.log(f"      reached the {self.time_limit_s:.0f} s limit: ending this attempt")
        finally:
            if request is not None:
                request.join(timeout=self.period)
