import json
from pathlib import Path

import chess

from dreamchess.core import occupancy
from dreamchess.supervisor import Supervisor
from dreamchess.where import plan_move

DATA = Path(__file__).parent / "data"
ROOK_TEST = "1r4k1/8/8/8/8/8/r7/6K1 b - - 1 1"  # after Kg1: Brown mates with Rb1#


def supervisor(fen=ROOK_TEST, uci="b8b1"):
    board = chess.Board(fen)
    step = plan_move(board, chess.Move.from_uci(uci))[0]
    pieces = {chess.square_name(s): ("w" if p.color else "b", chess.piece_name(p.piece_type))
              for s, p in board.piece_map().items()}
    return Supervisor(step, pieces, chess.BLACK, step.expected_after), step


def hand(t, square, z, grip, arm="right"):
    return {"t": t, arm: {"square": square, "z": z, "grip": grip}}


def run(sup, samples):
    return [a for a in (sup.feed(s) for s in samples) if a is not None]


def test_a_clean_move_ends_the_run_once_the_piece_lands():
    sup, step = supervisor()
    actions = run(sup, [hand(0, None, 0.16, 1.0), hand(5, "b8", 0.06, 0.5), hand(6, "b8", 0.05, 0.1),
                        hand(9, "b4", 0.15, 0.1), hand(12, "b1", 0.06, 0.1), hand(13, "b1", 0.07, 0.8)])
    assert [a.kind for a in actions] == ["done"]
    assert sup.events[0] == "gripped on b8, the right square"


def test_letting_go_on_the_wrong_square_sends_the_correction_from_there():
    sup, _ = supervisor()
    actions = run(sup, [hand(5, "b8", 0.05, 0.1), hand(9, "b3", 0.06, 0.1), hand(10, "b3", 0.08, 0.9)])
    assert len(actions) == 1 and actions[0].kind == "prompt"
    assert "pick up the brown rook on square b3 and place it upright in the center of square b1" in actions[0].step.prompt
    # ...and once it's moved from there to the target, the run is done.
    more = run(sup, [hand(14, "b3", 0.05, 0.1), hand(18, "b1", 0.06, 0.1), hand(19, "b1", 0.06, 0.9)])
    assert [a.kind for a in more] == ["done"]


def test_grabbing_air_asks_for_the_same_step_again():
    sup, step = supervisor()
    actions = run(sup, [hand(5, "e4", 0.06, 0.1), hand(8, "e4", 0.06, 0.9)])
    assert len(actions) == 1 and actions[0].step.prompt == step.prompt
    assert "closed on e4, where there's no piece to take" in sup.events


def test_the_wrong_piece_is_put_back_before_trying_again():
    sup, step = supervisor()
    # It takes the rook on a2 instead, and drops it on a3.
    actions = run(sup, [hand(5, "a2", 0.05, 0.1), hand(9, "a3", 0.06, 0.1), hand(10, "a3", 0.07, 0.9)])
    assert "pick up the brown rook on square a3 and place it upright in the center of square a2" in actions[0].step.prompt
    # Once it's back, the original step again.
    more = run(sup, [hand(14, "a3", 0.05, 0.1), hand(18, "a2", 0.06, 0.1), hand(19, "a2", 0.06, 0.9)])
    assert more[0].step.prompt == step.prompt


def test_a_squeeze_in_the_air_isnt_a_grasp():
    sup, _ = supervisor()
    assert run(sup, [hand(5, "b8", 0.25, 0.1), hand(6, "b8", 0.25, 0.9)]) == []
    assert sup.phase == "reach"


def test_it_stops_asking_after_its_limit():
    sup, _ = supervisor()
    samples = []
    for i in range(10):  # grabbing air over and over
        samples += [hand(10 * i, "e4", 0.06, 0.1), hand(10 * i + 5, "e4", 0.06, 0.9)]
    assert len(run(sup, samples)) == sup.max_prompts


def replay(name):
    return [json.loads(line) for line in (DATA / name).read_text().splitlines()
            if line.strip() and "run_start" not in line]


def test_on_the_real_base_model_run_it_catches_the_grab_at_e4():
    # Run 10 (the base model, live): the hand went to e4 and d4 and closed there again and again.
    sup, _ = supervisor()
    actions = run(sup, replay("run10_base_hands.jsonl"))
    assert sup.events[0].startswith("closed on e4")
    assert actions and actions[0].kind == "prompt" and "square b8" in actions[0].step.prompt


def test_on_the_real_xiangwen_run_it_catches_the_grab_at_d3():
    sup, _ = supervisor()
    run(sup, replay("run7_xiangwen_hands.jsonl"))
    assert sup.events[0].startswith("closed on d3")
