import random

import chess
import numpy as np
import pytest

from dreamchess.camera import SharedFrameSource
from dreamchess.core import occupancy
from dreamchess.engine import FallbackEngine
from dreamchess.mock import MockDream, MockHuman, RandomOpponent, SimWorld
from dreamchess.orchestrator import Config, Orchestrator
from dreamchess.synth import SynthCamera, pieces_from_board, pieces_from_occupancy
from dreamchess.vision import (
    Calibration,
    CalibrationError,
    CameraPerception,
    Frame,
    calibrate,
    classify,
    detect_corners,
)


def capture(cam, board, count=3):
    cam.pieces = pieces_from_board(board) if board else {}
    return [cam.read() for _ in range(count)]


def setup(click_error=2.0, **camera_args):
    cam = SynthCamera(**camera_args)
    calib, report = calibrate(capture(cam, None), capture(cam, chess.Board()), cam.corners(click_error))
    return cam, calib, report


def random_position(seed, plies=30):
    rng = random.Random(seed)
    board = chess.Board()
    for _ in range(plies):
        moves = list(board.legal_moves)
        if not moves:
            break
        board.push(rng.choice(moves))
    return board


def wrong_squares(cam, calib, board):
    cam.pieces = pieces_from_board(board)
    seen = classify(cam.read(), calib)
    expected = occupancy(board)
    return sorted(sq for sq in chess.SQUARE_NAMES if seen.get(sq) != expected.get(sq))


@pytest.mark.parametrize("tilt", [0, 25, 40])
@pytest.mark.parametrize("seed", range(2))
def test_depth_reads_midgame_positions_at_any_tilt(tilt, seed):
    cam, calib, _ = setup(tilt_deg=tilt, seed=seed)
    assert wrong_squares(cam, calib, random_position(seed)) == []


def test_depth_handles_tall_pieces_next_to_empty_squares():
    # A king on d4 with empty squares around it, tilted hard: its top leans over d5 in the image.
    cam, calib, _ = setup(tilt_deg=40)
    board = chess.Board("8/8/8/8/3K4/8/8/k7 w - - 0 1")
    assert wrong_squares(cam, calib, board) == []


@pytest.mark.parametrize("seed", range(2))
def test_color_only_mode_reads_positions_from_directly_above(seed):
    cam = SynthCamera(tilt_deg=0, with_depth=False, seed=seed)
    calib, report = calibrate(capture(cam, None), capture(cam, chess.Board()), cam.corners(2.0))
    assert report["mode"] == "color only"
    assert wrong_squares(cam, calib, random_position(seed)) == []


def test_detects_corners_on_empty_board_without_clicks():
    cam = SynthCamera(tilt_deg=25, seed=1, width=1280, height=720)
    found = detect_corners(cam.read().color, "bottom-left")
    assert np.abs(found - cam.corners()).max() < 3.0


def test_detected_corners_calibrate_successfully():
    cam = SynthCamera(tilt_deg=25, seed=1, width=1280, height=720)
    empty = capture(cam, None, 3)
    calib, _ = calibrate(empty, capture(cam, chess.Board(), 3), detect_corners(empty[0].color))
    assert wrong_squares(cam, calib, random_position(5)) == []


def test_rejects_a1_on_a_light_square():
    cam = SynthCamera(tilt_deg=25, seed=1, width=1280, height=720)
    with pytest.raises(CalibrationError, match="dark square"):
        detect_corners(cam.read().color, "bottom-right")


def test_rejects_corners_in_the_wrong_order():
    cam = SynthCamera(seed=1)
    reversed_corners = cam.corners()[::-1]
    with pytest.raises(CalibrationError, match="out of order"):
        calibrate(capture(cam, None), capture(cam, chess.Board()), reversed_corners)


def test_rejects_starting_position_missing_a_piece():
    cam = SynthCamera(seed=1)
    empty = capture(cam, None)
    board = chess.Board()
    board.remove_piece_at(chess.E2)
    with pytest.raises(CalibrationError, match="separate pieces"):
        calibrate(empty, capture(cam, board), cam.corners())


def test_rejects_pieces_that_look_the_same(monkeypatch):
    cam = SynthCamera(seed=1)
    empty = capture(cam, None)
    start = capture(cam, chess.Board())
    cam.pieces = {sq: ("w", h, r) for sq, (_, h, r) in cam.pieces.items()}
    start = [cam.read() for _ in range(5)]
    with pytest.raises(CalibrationError, match="too alike"):
        calibrate(empty, start, cam.corners())


def test_calibration_survives_save_and_load(tmp_path):
    cam, calib, _ = setup(seed=2)
    path = tmp_path / "calibration.npz"
    calib.save(path)
    loaded = Calibration.load(path)
    assert loaded.use_depth
    assert wrong_squares(cam, loaded, random_position(3)) == []


def test_arm_hovering_over_the_board_is_not_read_as_a_piece():
    cam, calib, _ = setup(seed=2)
    board = chess.Board()
    cam.pieces = pieces_from_board(board)
    frame = cam.read()
    # An arm 30 cm above the board's middle: a patch of the image much nearer the camera.
    u, v = (int(p) for p in cam.project(4 * cam.square, 4 * cam.square))
    depth = frame.depth.copy()
    depth[v - 25 : v + 25, u - 25 : u + 25] = frame.depth[v, u] - 0.30
    assert classify(Frame(frame.color, depth, frame.intrinsics), calib) == occupancy(board)


def test_shared_source_returns_each_frame_once():
    source = SharedFrameSource(max_age_s=0.05)
    frame = object()
    source.update(frame)
    assert source.read() is frame
    with pytest.raises(TimeoutError):
        source.read()


class WorldCamera(SynthCamera):
    """A camera aimed at the simulated table, so the robot's mistakes show up in its frames."""

    def __init__(self, world, **args):
        super().__init__(**args)
        self.world = world

    def read(self):
        if not self.world.arms_home:
            raise RuntimeError("observed while the arms were blocking the camera")
        self.pieces = pieces_from_occupancy(self.world.occ)
        return super().read()


def test_full_game_runs_through_the_real_vision_code():
    board = chess.Board()
    world = SimWorld(board)
    cam = WorldCamera(world, tilt_deg=25, seed=4)
    world.occ = {}
    empty = [cam.read() for _ in range(5)]
    world.occ = occupancy(board)
    calib, _ = calibrate(empty, [cam.read() for _ in range(5)], cam.corners(2.0))

    # Every failure here has to be noticed by the camera code and fixed by a new prompt.
    mover = MockDream(world, seed=4, p_success=1.0, script=["miss", "off_by_one", "success", "miss"])
    agent = Orchestrator(
        board, chess.WHITE, FallbackEngine(depth=1), mover,
        CameraPerception(cam, calib), MockHuman(world), RandomOpponent(world, seed=5),
        config=Config(), log=lambda _: None,
    )
    agent.run(max_plies=6)
    assert world.occ == occupancy(board)
    assert agent.stats.corrections >= 2


def test_large_mismatch_goes_to_a_person_not_the_robot():
    board = chess.Board()
    world = SimWorld(board)
    mover = MockDream(world, p_success=1.0)
    human = MockHuman(world)
    from dreamchess.mock import MockPerception

    agent = Orchestrator(
        board, chess.WHITE, FallbackEngine(depth=1), mover, MockPerception(world, noise=0), human,
        RandomOpponent(world), log=lambda _: None,
    )
    for sq in ["a2", "b2", "c2", "d2"]:
        world.occ[sq.replace("2", "4")] = world.occ.pop(sq)
    agent._achieve(occupancy(board))
    assert mover.prompts == []
    assert len(human.calls) == 1
