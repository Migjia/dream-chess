"""WHAT: choose which piece to move.

A piece's value depends on where it could go, so every legal move gets scored and
each piece takes the score of its best move. By default it plays Stockfish's move. With a
`margin_cp` above 0, it may pick a piece with more room around it among those within that
margin of the top score, trading a little strength for easier handling: a slightly less sharp
move that the gripper can execute beats a perfect move that knocks over a neighbor.
"""
from __future__ import annotations

from dataclasses import dataclass

import chess

from .engine import MATE_THRESHOLD, Engine, ScoredMove


@dataclass(frozen=True)
class PieceChoice:
    square: chess.Square
    piece: chess.Piece
    piece_best_cp: int
    global_best_cp: int
    crowding: int
    alternatives: int  # how many other pieces were close enough to consider


def candidate_moves(board: chess.Board) -> list[chess.Move]:
    """Legal moves, promoting only to a queen so the spare-piece tray stays simple."""
    return [m for m in board.legal_moves if m.promotion in (None, chess.QUEEN)]


def crowding(board: chess.Board, square: chess.Square, ignore: chess.Square | None = None) -> int:
    """Count occupied neighboring squares, a proxy for how likely a collision is."""
    return sum(
        1
        for sq in chess.SquareSet(chess.BB_KING_ATTACKS[square])
        if sq != ignore and board.piece_at(sq) is not None
    )


def within_margin(score: int, best: int, margin_cp: int) -> bool:
    """Never give up a forced mate for an easier grip."""
    if best >= MATE_THRESHOLD:
        return score == best
    return score >= best - margin_cp


def choose_piece(board: chess.Board, engine: Engine, margin_cp: int = 0) -> PieceChoice:
    ranked: list[ScoredMove] = engine.rank(board, candidate_moves(board))
    if not ranked:
        raise ValueError("no legal moves")
    global_best = ranked[0].cp

    best_per_piece: dict[chess.Square, int] = {}
    for scored in ranked:  # best first, so the first hit per piece is its best move
        best_per_piece.setdefault(scored.move.from_square, scored.cp)

    eligible = [sq for sq, cp in best_per_piece.items() if within_margin(cp, global_best, margin_cp)]
    # Ties go to the higher engine score, then to the square index for repeatability.
    square = min(eligible, key=lambda sq: (crowding(board, sq), -best_per_piece[sq], sq))
    return PieceChoice(
        square=square,
        piece=board.piece_at(square),
        piece_best_cp=best_per_piece[square],
        global_best_cp=global_best,
        crowding=crowding(board, square),
        alternatives=len(eligible) - 1,
    )
