"""WHERE: choose the destination square, then expand the move into physical steps.

One chess move is not always one pick-and-place. Captures, castling, en passant, and
promotion all need several, and each step gets verified separately.
"""
from __future__ import annotations

from dataclasses import dataclass

import chess

from .core import TRAY, Occupancy, Step, color_code, color_word, occupancy
from .engine import Engine
from .what import PieceChoice, candidate_moves, crowding, within_margin

CAPTURE_RISK = 3  # a capture adds a whole extra pick-and-place


@dataclass(frozen=True)
class Destination:
    move: chess.Move
    cp: int
    risk: int


def choose_destination(
    board: chess.Board, engine: Engine, choice: PieceChoice, margin_cp: int = 30
) -> Destination:
    moves = [m for m in candidate_moves(board) if m.from_square == choice.square]
    ranked = engine.rank(board, moves)

    def risk(move: chess.Move) -> int:
        return crowding(board, move.to_square, ignore=move.from_square) + (
            CAPTURE_RISK if board.is_capture(move) else 0
        )

    # Compare against the best move overall, so WHAT and WHERE can't each spend the
    # margin and add up to twice the allowed loss.
    eligible = [s for s in ranked if within_margin(s.cp, choice.global_best_cp, margin_cp)]
    eligible = eligible or ranked[:1]  # engine scores vary a little between searches
    best = min(eligible, key=lambda s: (risk(s.move), -s.cp, s.move.uci()))
    return Destination(best.move, best.cp, risk(best.move))


def arm_for(square: str, robot_color: chess.Color) -> str:
    """Seated behind its own pieces, White has the a-file on its left; Black the h-file."""
    queenside = square[0] in "abcd"
    return "left" if queenside == (robot_color == chess.WHITE) else "right"


def write_prompt(arm: str, color: str, piece_name: str, source: str, target: str) -> str:
    """The text Dream-1 receives. Tune this wording on the real robot first."""
    item = f"{color_word(color)} {piece_name}".strip()
    if source == TRAY:
        pick = f"pick up the spare {item} from the tray"
    else:
        pick = f"pick up the {item} on square {source}"
    place = "put it in the tray" if target == TRAY else f"place it upright in the center of square {target}"
    return f"Using your {arm} arm, {pick} and {place}. Move slowly and do not touch any other piece."


def make_step(
    color: str, piece_name: str, source: str, target: str, robot_color: chess.Color, expected_after: Occupancy
) -> Step:
    arm = arm_for(target if source == TRAY else source, robot_color)
    return Step(
        color=color,
        piece_name=piece_name,
        source=source,
        target=target,
        arm=arm,
        prompt=write_prompt(arm, color, piece_name, source, target),
        expected_after=expected_after,
    )


def plan_move(board: chess.Board, move: chess.Move) -> list[Step]:
    """Expand a legal move into ordered steps. Doesn't modify the board."""
    robot_color = board.turn
    us = color_code(robot_color)
    them = color_code(not robot_color)
    src = chess.square_name(move.from_square)
    dst = chess.square_name(move.to_square)
    name = chess.piece_name(board.piece_type_at(move.from_square))

    occ = occupancy(board)
    steps: list[Step] = []

    def add(color: str, piece_name: str, source: str, target: str) -> None:
        if source != TRAY:
            del occ[source]
        if target != TRAY:
            occ[target] = color
        steps.append(make_step(color, piece_name, source, target, robot_color, dict(occ)))

    if board.is_en_passant(move):
        captured = chess.square_name(chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square)))
        add(them, "pawn", captured, TRAY)
    elif board.is_capture(move):
        add(them, chess.piece_name(board.piece_type_at(move.to_square)), dst, TRAY)

    if move.promotion:
        add(us, "pawn", src, TRAY)
        add(us, "queen", TRAY, dst)
    else:
        add(us, name, src, dst)

    if board.is_castling(move):
        rank = src[1]
        kingside = chess.square_file(move.to_square) > chess.square_file(move.from_square)
        add(us, "rook", ("h" if kingside else "a") + rank, ("f" if kingside else "d") + rank)

    return steps
