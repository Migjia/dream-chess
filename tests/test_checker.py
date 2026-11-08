"""The chain of command: Dream-1 runs a step, the checker takes a picture and reads the board, and on a mismatch
the orchestrator gets the verdict in words and sends Dream-1 the correction, until the checker confirms."""
import threading
import time

import chess

from dreamchess.checker import CameraChecker, describe_failure
from dreamchess.core import occupancy
from dreamchess.engine import FallbackEngine
from dreamchess.mock import MockDream, MockHuman, SimWorld
from dreamchess.orchestrator import Orchestrator
from dreamchess.station_camera import StationSnapshot
from dreamchess.vision import CalibrationError
from dreamchess.where import plan_move
from test_station_mover import FakeStation, posts, station  # noqa: F401


def step_for(fen, uci):
    return plan_move(chess.Board(fen), chess.Move.from_uci(uci))[0]


QUEEN = "4k3/2q5/8/8/8/8/8/4K3 b - - 0 1"


def test_the_verdict_names_the_piece_and_both_squares():
    step = step_for(QUEEN, "c7c2")
    assert describe_failure(step, {"c2": "b"}, {"b2": "b"}, {}) == "the brown queen went to b2 instead of c2"
    assert describe_failure(step, {"c2": "b"}, {"c7": "b"}, {}) == "the brown queen is still on c7"
    assert "can't see where it went" in describe_failure(step, {"c2": "b"}, {}, {})
    assert describe_failure(None, {"e4": "w"}, {}, {"e4": "pawn"}) == "the white pawn is missing from e4"


class TableCamera:
    """A calibrated camera that sees the simulated table exactly."""

    def __init__(self, world):
        self.world, self.last_seen, self.reads = world, None, 0

    def status(self):
        return {"calibrated": True}

    def read(self):
        self.reads += 1
        self.last_seen = dict(self.world.occ)
        return dict(self.world.occ)


def test_a_failed_move_goes_back_down_the_chain_until_the_checker_confirms_it():
    board = chess.Board(QUEEN)
    world = SimWorld(board)
    lines = []
    dream = MockDream(world, script=["off_by_one", "success"])  # the first try lands a square off
    camera = TableCamera(world)
    agent = Orchestrator(board, chess.BLACK, FallbackEngine(depth=1), dream, CameraChecker(camera, None, lines.append),
                         MockHuman(world), lambda b: None, log=lines.append)
    move = agent.play_robot_turn()
    checks = [line for line in lines if line.startswith("CHECK")]
    assert len(checks) == 1 and "instead of" in checks[0], checks  # the verdict, in words, to the orchestrator
    hows = [line for line in lines if line.startswith("HOW")]
    assert len(hows) == 2 and f"square {chess.square_name(move.to_square)}" in hows[1]  # the correction, back down
    assert world.occ == occupancy(board) and camera.reads >= 2  # ...until the checker saw it right


class Fallback:
    def __init__(self):
        self.asked, self.belief = 0, {}

    def observe(self):
        self.asked += 1
        return {"e1": "w"}


def test_without_a_calibrated_camera_a_person_checks():
    class Uncalibrated:
        def status(self):
            return {"calibrated": False}

    person = Fallback()
    assert CameraChecker(Uncalibrated(), person).observe() == {"e1": "w"} and person.asked == 1


def test_a_failed_picture_falls_back_to_a_person():
    class Broken(TableCamera):
        def read(self):
            raise CalibrationError("the station didn't save a top-camera frame in time")

    person, lines = Fallback(), []
    CameraChecker(Broken(None), person, lines.append).observe()
    assert person.asked == 1 and "asking a person instead" in lines[0]


# --- The picture itself: a hold-still run, stopped before the arms can move ---

def test_a_picture_is_a_run_stopped_as_soon_as_its_first_frame_is_saved(station, tmp_path):  # noqa: F811
    import cv2
    import numpy as np

    from dreamchess.station_mover import StationClient

    top = tmp_path / "top"
    top.mkdir()

    def save_frame_when_running():  # what the station does: its first frame within moments of the start
        while station.status()["state"] != "running":
            time.sleep(0.005)
        cv2.imwrite(str(top / "1.jpg"), np.full((36, 64, 3), 200, np.uint8))

    station.run_s = 10.0  # left alone, it would run on
    station.warm_s, station.move_after_s = 2.8, 30.0  # like the real station: the first action comes ~2.8 s in
    threading.Thread(target=save_frame_when_running, daemon=True).start()
    started = time.time()
    frame = StationSnapshot(StationClient(station.url, timeout_s=5), str(tmp_path)).read()
    assert frame.color.shape == (36, 64, 3)
    assert time.time() - started < 3.0
    assert posts(station, "/start")[0]["prompt"].startswith("Hold completely still")
    assert len(posts(station, "/stop")) == 1 and station.chunks == 0  # stopped before any action
    assert list(top.iterdir()) == [top / "1.jpg"]  # nothing of ours written


def test_no_picture_while_the_station_is_busy(station, tmp_path):  # noqa: F811
    import pytest

    from dreamchess.station_mover import StationClient

    station.state = "running"
    with pytest.raises(CalibrationError, match="a picture waits until it's idle"):
        StationSnapshot(StationClient(station.url, timeout_s=5), str(tmp_path)).read()
    assert posts(station, "/start") == []
