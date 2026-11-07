import threading
import time

import numpy as np
import pytest

from dreamchess.core import MoverError, Step
from dreamchess.dream_mover import DreamMover, dream_config

STEP = Step("w", "knight", "g1", "f3", "right", "pick up the knight", {})
HZ = 400  # fast, so these tests finish quickly


def chunk(values, length=48):
    """A chunk where both arms hold joints at `base`, with the given gripper per row."""
    rows = [[0.0] * 6 + [g] for g in values][:length]
    return {"q_r_chunk": rows, "q_l_chunk": [list(r) for r in rows]}


class FakeClient:
    def __init__(self, chunks, latency=0.0, error=None):
        self.chunks = list(chunks)
        self.latency, self.error = latency, error
        self.observations = []
        self.commanded = []
        self.resets = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.lock = threading.Lock()

    def reset_episode(self):
        self.resets += 1

    def set_observation(self, frames, observation):
        self.observations.append((frames, observation))

    def get_action(self, commanded=None):
        self.commanded.append(commanded)
        with self.lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        time.sleep(self.latency)
        with self.lock:
            self.in_flight -= 1
        if self.error:
            raise self.error
        return self.chunks.pop(0) if self.chunks else chunk([1.0] * 48)

    def refill_due(self, executed, remaining):
        return remaining == 0


class FakeStation:
    def __init__(self, camera_error=None):
        self.commands = []
        self.homes = 0
        self.camera_error = camera_error

    def frames(self):
        time.sleep(0.001)
        if self.camera_error:
            raise self.camera_error
        return {"video.overhead": "x", "video.wrist_l": "x", "video.wrist_r": "x"}

    def state(self):
        return {
            "state.right_arm": np.zeros(6, np.float32),
            "state.right_gripper": np.ones(1, np.float32),
            "state.left_arm": np.zeros(6, np.float32),
            "state.left_gripper": np.ones(1, np.float32),
        }

    def command(self, right, left):
        self.commands.append((right, left))

    def home(self):
        self.homes += 1


PICK_AND_RELEASE = [1.0] * 5 + [0.0] * 15 + [1.0] * 28


def mover(client, station=None, **args):
    return DreamMover(station or FakeStation(), client, action_hz=HZ, log=lambda _: None, **args)


def test_attempt_ends_when_gripper_closes_and_reopens():
    station = FakeStation()
    m = mover(FakeClient([chunk(PICK_AND_RELEASE)]), station, time_limit_s=5)
    start = time.monotonic()
    m.execute(STEP)
    assert time.monotonic() - start < 2
    assert len(station.commands) == 5 + 15 + 20


def test_gripper_that_starts_closed_and_opens_is_not_a_release():
    station = FakeStation()
    m = mover(FakeClient([chunk([0.0] * 20 + [1.0] * 28)]), station, time_limit_s=2)
    m.execute(STEP)
    assert m.chunks_received >= 2  # it kept going rather than stopping on the first opening


def test_stops_at_the_time_limit_without_a_release():
    client = FakeClient([])
    start = time.monotonic()
    mover(client, time_limit_s=0.2).execute(STEP)
    assert 0.15 < time.monotonic() - start < 1.5


def test_prompt_and_state_reach_the_model_and_episode_resets():
    client = FakeClient([chunk(PICK_AND_RELEASE)])
    mover(client, time_limit_s=5).execute(STEP)
    assert client.resets == 1
    frames, observation = client.observations[0]
    assert observation["prompt"] == "pick up the knight"
    assert "state.right_arm" in observation and "video.overhead" in frames


def test_later_model_calls_report_the_last_row_sent():
    client = FakeClient([], latency=0.005)
    mover(client, time_limit_s=2).execute(STEP)
    assert client.commanded[0] is None  # nothing has been sent before the first call
    later = client.commanded[1]
    assert len(later["q_r_chunk"]) == 7 and len(later["q_l_chunk"]) == 7


def test_never_runs_two_model_calls_at_once():
    client = FakeClient([], latency=0.02)
    mover(client, time_limit_s=0.3).execute(STEP)
    assert client.max_in_flight == 1


def test_skips_rows_already_past_when_a_new_chunk_lands():
    class EarlyRefill(FakeClient):
        def refill_due(self, executed, remaining):
            return executed >= 5

    numbered = [{"q_r_chunk": [[float(i) * 0.001] * 6 + [1.0] for i in range(48)],
                 "q_l_chunk": [[0.0] * 6 + [1.0] for _ in range(48)]} for _ in range(50)]
    station = FakeStation()
    mover(EarlyRefill(numbered, latency=0.02), station, time_limit_s=1).execute(STEP)
    firsts = [c[0][0] for c in station.commands]
    # After a refill the plan resumes partway through the new chunk, never back at row 0.
    resumes = [b for a, b in zip(firsts, firsts[1:]) if b < a]
    assert resumes and all(value > 0 for value in resumes)


def test_a_stalled_loop_does_not_play_rows_in_a_burst():
    class StallingStation(FakeStation):
        def __init__(self):
            super().__init__()
            self.times = []

        def command(self, right, left):
            super().command(right, left)
            self.times.append(time.perf_counter())
            if len(self.times) == 3:
                time.sleep(0.3)  # the loop falls well behind here
                self.resumed = time.perf_counter()

    station = StallingStation()
    rate = 50
    m = DreamMover(station, FakeClient([]), action_hz=rate, time_limit_s=1.0, log=lambda _: None)
    m.execute(STEP)
    # Catching up would add about 15 extra rows, so allow only slight timing slack.
    after_stall = [t for t in station.times if t >= station.resumed]
    elapsed = after_stall[-1] - station.resumed
    assert len(after_stall) <= elapsed * rate + 3


def test_large_jump_stops_and_sends_nothing_further():
    rows = [[0.0] * 6 + [1.0]] * 3 + [[1.0] * 6 + [1.0]] * 45
    station = FakeStation()
    client = FakeClient([{"q_r_chunk": rows, "q_l_chunk": [[0.0] * 6 + [1.0]] * 48}])
    with pytest.raises(MoverError, match="jump"):
        mover(client, station, time_limit_s=5).execute(STEP)
    assert len(station.commands) == 3


def test_first_row_far_from_where_the_arm_is_stops():
    station = FakeStation()
    far = [[1.0] * 6 + [1.0]] * 48
    with pytest.raises(MoverError, match="jump"):
        mover(FakeClient([{"q_r_chunk": far, "q_l_chunk": far}]), station, time_limit_s=5).execute(STEP)
    assert station.commands == []


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_invalid_numbers_stop_the_arm(bad):
    rows = [[0.0] * 5 + [bad, 1.0]] * 48
    station = FakeStation()
    with pytest.raises(MoverError, match="bad"):
        mover(FakeClient([{"q_r_chunk": rows, "q_l_chunk": rows}]), station, time_limit_s=5).execute(STEP)
    assert station.commands == []


def test_model_error_becomes_a_mover_error():
    with pytest.raises(MoverError, match="Dream-1 call failed"):
        mover(FakeClient([], error=RuntimeError("timeout")), time_limit_s=5).execute(STEP)


def test_camera_failure_stops_the_attempt():
    station = FakeStation()
    client = FakeClient([], latency=0.01)
    m = mover(client, station, time_limit_s=5)
    original = station.frames
    calls = []

    def fail_after_first():
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("camera unplugged")
        return original()

    station.frames = fail_after_first
    with pytest.raises(MoverError, match="camera stopped"):
        m.execute(STEP)


def test_dry_run_calls_the_model_but_never_moves():
    station = FakeStation()
    client = FakeClient([chunk(PICK_AND_RELEASE)])
    m = mover(client, station, time_limit_s=5, dry_run=True)
    m.execute(STEP)
    m.go_home()
    assert m.chunks_received == 1
    assert station.commands == [] and station.homes == 0


def test_config_matches_the_documented_yam_setup():
    config = dream_config()
    assert config["strict"] is True
    assert config["checkpoint"] == "dreamlabs/dream-1-beta"
    assert config["ik"] == {"arm": "yam", "head": "joint"}
    assert set(config["embodiment"]["video"]) == {"overhead", "wrist_l", "wrist_r"}
