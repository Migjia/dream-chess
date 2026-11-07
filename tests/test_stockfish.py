"""Checks What, Where, and the full loop on real Stockfish.

These skip when Stockfish isn't installed. To run them, put `stockfish` on your PATH or set
STOCKFISH_PATH. On Debian and Ubuntu, apt may install it at /usr/games/stockfish.

Engine scores vary a little between runs, so these check outcomes that any sound search
must reach, rather than exact scores.
"""
import os
import shutil

import chess
import pytest

from dreamchess.core import occupancy
from dreamchess.engine import MATE_THRESHOLD, StockfishEngine
from dreamchess.mock import MockDream, MockHuman, MockPerception, RandomOpponent, SimWorld
from dreamchess.orchestrator import Orchestrator
from dreamchess.what import candidate_moves, choose_piece
from dreamchess.where import choose_destination

MATE_IN_ONE = "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"
MATE_IN_TWO = "7k/8/8/8/8/8/R7/1R4K1 w - - 0 1"
FREE_QUEEN_FOR_WHITE = "4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1"
FREE_QUEEN_FOR_BLACK = "3rk3/8/8/8/3Q4/8/8/4K3 b - - 0 1"
SEARCH_NOISE_CP = 100  # how far apart two short searches of one position may reasonably land


@pytest.fixture(scope="module")
def engine():
    path = os.environ.get("STOCKFISH_PATH") or shutil.which("stockfish")
    if not path:
        pytest.skip("Stockfish isn't installed")
    stockfish = StockfishEngine(path)
    yield stockfish
    stockfish.close()


def decide(board, engine, margin_cp=30):
    choice = choose_piece(board, engine, margin_cp)
    return choice, choose_destination(board, engine, choice, margin_cp)


def test_scores_every_legal_move_best_first(engine):
    board = chess.Board()
    ranked = engine.rank(board, candidate_moves(board))
    assert {s.move for s in ranked} == set(board.legal_moves)
    assert [s.cp for s in ranked] == sorted((s.cp for s in ranked), reverse=True)


def test_only_scores_the_moves_it_was_given(engine):
    board = chess.Board()
    knight_moves = [m for m in board.legal_moves if m.from_square == chess.G1]
    assert {s.move for s in engine.rank(board, knight_moves)} == set(knight_moves)


def test_scores_are_from_the_point_of_view_of_the_side_to_move(engine):
    board = chess.Board(FREE_QUEEN_FOR_BLACK)
    best = engine.rank(board, candidate_moves(board))[0]
    assert best.move == chess.Move.from_uci("d8d4")
    assert best.cp > 0


def test_what_and_where_find_mate_in_one(engine):
    choice, dest = decide(chess.Board(MATE_IN_ONE), engine)
    assert choice.square == chess.D1
    assert dest.move == chess.Move.from_uci("d1d8")
    assert dest.cp >= MATE_THRESHOLD


def test_easier_handling_never_costs_a_forced_mate(engine):
    board = chess.Board(MATE_IN_TWO)
    _, dest = decide(board, engine, margin_cp=99_999)
    board.push(dest.move)
    assert not board.is_game_over()
    for reply in list(board.legal_moves):  # whatever Black plays, White must have mate next
        board.push(reply)
        mates = []
        for move in list(board.legal_moves):
            board.push(move)
            mates.append(board.is_checkmate())
            board.pop()
        assert any(mates), f"no mate after {reply}"
        board.pop()


def test_takes_a_free_queen_rather_than_an_easier_move(engine):
    _, dest = decide(chess.Board(FREE_QUEEN_FOR_WHITE), engine)
    assert dest.move == chess.Move.from_uci("d1d5")


def test_handling_preference_stays_close_to_the_best_move(engine):
    choice, dest = decide(chess.Board(), engine)
    assert dest.cp >= choice.global_best_cp - 30 - SEARCH_NOISE_CP


def test_where_only_moves_the_piece_what_chose(engine):
    choice, dest = decide(chess.Board(), engine)
    assert dest.move.from_square == choice.square


@pytest.mark.parametrize("color", [chess.WHITE, chess.BLACK], ids=["white", "black"])
def test_full_loop_stays_in_sync_when_the_robot_fails(engine, color):
    board = chess.Board()
    world = SimWorld(board)
    agent = Orchestrator(
        board, color, engine, MockDream(world, seed=7, p_success=0.4),
        MockPerception(world, seed=8, noise=0.02), MockHuman(world),
        RandomOpponent(world, seed=9), log=lambda _: None,
    )
    agent.run(max_plies=10)
    assert world.occ == occupancy(board)
    assert agent.stats.moves >= 1
