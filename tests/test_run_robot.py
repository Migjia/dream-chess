import argparse
import json

import chess
import pytest

import run_robot
from dreamchess.core import Step, occupancy
from dreamchess.human_eyes import GameQuit, HumanEyes, TerminalOpponent
from dreamchess.station_mover import StationMover as RealStationMover
from test_station_mover import FakeStation, station  # noqa: F401  (the fixture)

# White to move, and its only move is Kg1; then Brown mates in one with Rb1#.
BROWN_MATES = "1r4k1/8/8/8/8/8/r7/7K w - - 0 1"


def scripted(*answers):
    queue = list(answers)

    def ask(prompt):
        assert queue, f"ran out of answers at: {prompt}"
        return queue.pop(0)

    ask.queue = queue
    return ask


def args(tmp_path, **extra):
    defaults = dict(fen=BROWN_MATES, label="test", seconds=0.2, checkpoint=None, stockfish=None, max_plies=4,
                    station=None, log_dir=str(tmp_path), sim=False, sim_success=1.0, seed=1)
    return argparse.Namespace(**{**defaults, **extra})


def events(tmp_path):
    return [json.loads(line) for line in (tmp_path / "test.jsonl").read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def quick(monkeypatch):
    from dreamchess import station_mover

    original = station_mover.StationMover
    monkeypatch.setattr(station_mover, "StationMover",
                        lambda client, **kw: original(client, poll_s=0.02, grace_s=1.0, **kw))


def client_for(station):  # noqa: F811
    from dreamchess.station_mover import StationClient

    return StationClient(station.url, timeout_s=5)


# --- The person as the camera ---

STEP = Step("b", "rook", "b8", "b1", "right", "pick up the brown rook on square b8 ...", {})


def eyes_after(*answers):
    eyes = HumanEyes(chess.Board(BROWN_MATES), ask=scripted(*answers), say=lambda _: None)
    eyes.attempted(STEP)
    return eyes.observe()


def test_landed_moves_the_piece():
    seen = eyes_after("y", "")
    assert seen.get("b1") == "b" and "b8" not in seen


def test_landed_somewhere_else():
    seen = eyes_after("n", "c1", "")
    assert seen.get("c1") == "b" and "b1" not in seen and "b8" not in seen


def test_did_not_move_at_all():
    seen = eyes_after("n", "same", "")
    assert seen.get("b8") == "b" and "b1" not in seen


def test_fell_off_the_board():
    seen = eyes_after("n", "gone", "")
    assert "b8" not in seen and "b1" not in seen


def test_records_a_bumped_neighbor():
    seen = eyes_after("y", "a2 a3", "")
    assert seen.get("a3") == "b" and "a2" not in seen


def test_bad_answers_are_asked_again():
    seen = eyes_after("maybe", "n", "h9", "c1", "zz", "e4 e3", "")  # e4 is empty, so that bump is refused
    assert seen.get("c1") == "b" and "e3" not in seen


def test_opponent_move_must_be_legal_and_accepts_both_notations():
    board = chess.Board()
    seen = []
    TerminalOpponent(scripted("e5", "e2e4"), say=lambda _: None, on_move=seen.append)(board)
    assert seen[0].peek() == chess.Move.from_uci("e2e4")
    TerminalOpponent(scripted("Nf3"), say=lambda _: None, on_move=seen.append)(board)
    assert seen[1].peek() == chess.Move.from_uci("g1f3")
    with pytest.raises(GameQuit):
        TerminalOpponent(scripted("quit"), say=lambda _: None)(board)


# --- Whole games against the fake station ---

def test_full_game_robot_mates_and_logs_it(station, tmp_path, quick):  # noqa: F811
    ask = scripted("", "yes", "Kg1", "y", "")
    summary = run_robot.play(args(tmp_path), ask=ask, say=lambda _: None, client=client_for(station))
    assert summary["result"] == "0-1"
    assert summary["robot_moves"] == 1 and summary["dream_attempts"] == 1
    starts = [body for m, p, body in station.requests if p == "/start"]
    assert len(starts) == 1 and "brown rook" in starts[0]["prompt"]
    kinds = [e["type"] for e in events(tmp_path)]
    assert kinds[0] == "game_start" and kinds[-1] == "game_end"
    assert "opponent_move" in kinds and "attempt" in kinds and "attempt_result" in kinds


def test_a_miss_is_retried_with_a_fix_prompt(station, tmp_path, quick):  # noqa: F811
    ask = scripted("", "yes", "Kg1", "n", "b2", "", "y", "")
    summary = run_robot.play(args(tmp_path), ask=ask, say=lambda _: None, client=client_for(station))
    assert summary["result"] == "0-1"
    assert summary["dream_attempts"] == 2 and summary["corrections"] == 1
    prompts = [body["prompt"] for m, p, body in station.requests if p == "/start"]
    assert "Column (b), Row (2)" in prompts[1] and "Column (b), Row (1)" in prompts[1]


def test_a_lost_piece_asks_a_person_to_fix_the_board(station, tmp_path, quick):  # noqa: F811
    ask = scripted("", "yes", "Kg1", "n", "gone", "", "")
    summary = run_robot.play(args(tmp_path), ask=ask, say=lambda _: None, client=client_for(station))
    assert summary["human_rescues"] == 1 and summary["result"] == "0-1"
    assert any(e["type"] == "help" and "put a brown piece on b1" in e["changes"] for e in events(tmp_path))


def test_needs_the_e_stop_confirmed(station, tmp_path, quick):  # noqa: F811
    with pytest.raises(SystemExit, match="e-stop"):
        run_robot.play(args(tmp_path), ask=scripted("", "no"), say=lambda _: None, client=client_for(station))
    assert station.run == 0


def test_refuses_when_the_station_is_busy(station, tmp_path, quick):  # noqa: F811
    station.state = "running"
    with pytest.raises(SystemExit, match="not idle"):
        run_robot.play(args(tmp_path), ask=scripted(), say=lambda _: None, client=client_for(station))


def test_quitting_still_saves_a_summary(station, tmp_path, quick):  # noqa: F811
    summary = run_robot.play(args(tmp_path), ask=scripted("", "yes", "quit"), say=lambda _: None,
                             client=client_for(station))
    assert summary["ending"] == "quit"
    assert events(tmp_path)[-1]["type"] == "game_end"


def test_ctrl_c_stops_the_arms(station, tmp_path, quick, monkeypatch):  # noqa: F811
    def interrupted(self, step):
        raise KeyboardInterrupt

    monkeypatch.setattr(RealStationMover, "execute", interrupted)
    summary = run_robot.play(args(tmp_path), ask=scripted("", "yes", "Kg1"), say=lambda _: None,
                             client=client_for(station))
    assert summary["ending"] == "stopped with Ctrl-C"
    assert [body for m, p, body in station.requests if p == "/stop"]


def test_sim_mode_plays_without_a_station(tmp_path):
    summary = run_robot.play(args(tmp_path, sim=True), ask=scripted("Kg1"), say=lambda _: None)
    assert summary["result"] == "0-1"


def test_setup_lists_every_piece_in_plain_words():
    text = run_robot.describe_position(chess.Board(BROWN_MATES))
    assert "brown rook: a2, b8" in text and "white king: h1" in text and "brown king: g8" in text


@pytest.mark.parametrize("line,expected", [
    ("WHAT  knight on g8 (best +9 cp, 5 neighbors, 0 alternatives)", "I'll move my knight on g8."),
    ("WHERE Nf6 (+9 cp, risk 3)", "My move: Nf6."),
    ("HOW   [2/6] Using your left arm, pick up", "Robot, attempt 2 of 6: Using your left arm, pick up"),
    ("CHECK missing=['c6'] extra=['b8']", "That didn't work: expected a piece on c6 and found an unexpected piece on b8. Fixing it."),
    ("SEEN  opponent played e4", "You played e4."),
])
def test_agent_lines_are_shown_in_plain_words(line, expected):
    assert run_robot.plain(line) == expected


class TrackedEngine:
    """Stands in for Stockfish, recording whether it was closed."""

    name = "stockfish"
    started = []

    def __init__(self, *args):
        from dreamchess.engine import FallbackEngine

        self.inner, self.closed = FallbackEngine(), False
        TrackedEngine.started.append(self)

    def rank(self, board, moves):
        return self.inner.rank(board, moves)

    def close(self):
        self.closed = True


@pytest.fixture
def tracked(monkeypatch):
    TrackedEngine.started = []
    monkeypatch.setattr(run_robot, "make_engine", TrackedEngine)
    return TrackedEngine.started


def test_refusing_to_start_leaves_no_engine_running(station, tmp_path, quick, tracked):  # noqa: F811
    with pytest.raises(SystemExit):
        run_robot.play(args(tmp_path), ask=scripted("", "no"), say=lambda _: None, client=client_for(station))
    station.state = "running"
    with pytest.raises(SystemExit):
        run_robot.play(args(tmp_path), ask=scripted(), say=lambda _: None, client=client_for(station))
    assert all(engine.closed for engine in tracked)


@pytest.mark.parametrize("answers", [("", "yes", "Kg1", "y", ""), ("", "yes", "quit")], ids=["mate", "quit"])
def test_every_finished_game_closes_the_engine(station, tmp_path, quick, tracked, answers):  # noqa: F811
    run_robot.play(args(tmp_path), ask=scripted(*answers), say=lambda _: None, client=client_for(station))
    assert tracked and all(engine.closed for engine in tracked)
