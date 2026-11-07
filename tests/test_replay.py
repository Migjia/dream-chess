import json

import chess
import pytest

from dreamchess.engine import FallbackEngine
from dreamchess.replay import DEMO_FEN, DEMO_SCRIPT, record_game


def color(symbol):
    return "w" if symbol.isupper() else "b"


@pytest.fixture(scope="module")
def frames():
    return record_game(DEMO_FEN, script=list(DEMO_SCRIPT))


def test_demo_ends_in_a_real_checkmate(frames):
    assert frames[-1]["text"] == "Checkmate. White wins."
    assert frames[-1]["moves"] == 2


def test_demo_final_position_is_mate_on_the_real_rules(frames):
    pieces = frames[-1]["pieces"]
    board = chess.Board(None)
    for square, symbol in pieces.items():
        board.set_piece_at(chess.parse_square(square), chess.Piece.from_symbol(symbol))
    board.turn = chess.BLACK
    assert board.is_checkmate()


def test_demo_shows_every_part_of_the_loop(frames):
    stages = {frame["stage"] for frame in frames}
    assert {"what", "where", "how", "check", "update", "opponent", "end"} <= stages


def test_demo_shows_each_failure_and_its_recovery(frames):
    texts = " ".join(frame["text"] for frame in frames)
    assert "grab missed" in texts and "wrong square" in texts and "knocked out of place" in texts
    assert frames[-1]["corrections"] >= 3
    assert frames[-1]["rescues"] == 0


def test_a_failed_step_never_updates_the_board_right_after(frames):
    for before, after in zip(frames, frames[1:]):
        if before["tone"] == "bad":
            assert after["stage"] != "update"


def test_piece_count_never_grows_without_a_promotion(frames):
    start = len(frames[0]["pieces"])
    assert all(len(frame["pieces"]) <= start for frame in frames)


def test_no_jargon_in_the_captions(frames):
    assert not any(" cp" in frame["text"] for frame in frames)


def test_a_knock_with_nothing_nearby_is_shown_as_a_clean_move():
    frames = record_game("7k/8/8/8/8/8/8/R5K1 w - - 0 1", script=["knock"], max_plies=1, engine=FallbackEngine(1))
    assert not any("knocked" in frame["text"] for frame in frames)


def test_captures_and_lost_pieces_are_recorded_correctly():
    frames = record_game(
        "r5k1/5ppp/8/8/8/5Q2/5PPP/3R2K1 w - - 0 1", script=["lost", "success"], engine=FallbackEngine(),
    )
    assert any(frame["stage"] == "person" or "Camera confirms" in frame["text"] for frame in frames)
    assert "a8" in frames[-1]["pieces"] and frames[-1]["pieces"]["a8"] == "Q"


@pytest.mark.parametrize("robot", [chess.WHITE, chess.BLACK], ids=["white", "black"])
def test_every_frame_can_be_sent_to_the_page(robot):
    frames = record_game(robot_color=robot, p_success=1.0, max_plies=4, engine=FallbackEngine(1))
    assert json.loads(json.dumps(frames)) == frames
