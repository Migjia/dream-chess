"""Chess evaluation. Uses Stockfish when available, otherwise a small built-in search."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Iterable, Protocol

import chess
import chess.engine

MATE_CP = 100_000
MATE_THRESHOLD = 90_000  # any score beyond this is a forced mate


@dataclass(frozen=True)
class ScoredMove:
    move: chess.Move
    cp: int  # centipawns from the point of view of the side to move


class Engine(Protocol):
    name: str

    def rank(self, board: chess.Board, moves: Iterable[chess.Move]) -> list[ScoredMove]:
        """Score the given moves, best first."""
        ...

    def close(self) -> None: ...


class StockfishEngine:
    name = "stockfish"

    def __init__(self, path: str, think_time: float = 0.3):
        self._engine = chess.engine.SimpleEngine.popen_uci(path)
        self._limit = chess.engine.Limit(time=think_time)

    def rank(self, board: chess.Board, moves: Iterable[chess.Move]) -> list[ScoredMove]:
        moves = list(moves)
        infos = self._engine.analyse(board, self._limit, multipv=len(moves), root_moves=moves)
        scored = [
            ScoredMove(info["pv"][0], info["score"].pov(board.turn).score(mate_score=MATE_CP))
            for info in infos
            if info.get("pv")
        ]
        return sorted(scored, key=lambda s: -s.cp)

    def close(self) -> None:
        self._engine.quit()


_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


def _evaluate(board: chess.Board) -> int:
    score = 0
    for sq, piece in board.piece_map().items():
        center = 3 - max(abs(chess.square_file(sq) - 3.5), abs(chess.square_rank(sq) - 3.5))
        value = _VALUES[piece.piece_type] + int(center * 5)
        score += value if piece.color == board.turn else -value
    return score


class FallbackEngine:
    """Weak but dependency-free, so the loop still runs without a Stockfish binary."""

    name = "fallback"

    def __init__(self, depth: int = 2):
        self.depth = depth

    def _search(self, board: chess.Board, depth: int, alpha: int, beta: int, ply: int) -> int:
        if board.is_checkmate():
            return -(MATE_CP - ply)
        if board.is_stalemate() or board.is_insufficient_material():
            return 0
        if depth == 0:
            return _evaluate(board)
        best = -MATE_CP * 2
        for move in board.legal_moves:
            board.push(move)
            best = max(best, -self._search(board, depth - 1, -beta, -alpha, ply + 1))
            board.pop()
            alpha = max(alpha, best)
            if alpha >= beta:
                break
        return best

    def rank(self, board: chess.Board, moves: Iterable[chess.Move]) -> list[ScoredMove]:
        board = board.copy(stack=False)
        scored = []
        for move in sorted(moves, key=lambda m: m.uci()):
            board.push(move)
            scored.append(ScoredMove(move, -self._search(board, self.depth, -MATE_CP * 2, MATE_CP * 2, 1)))
            board.pop()
        return sorted(scored, key=lambda s: -s.cp)

    def close(self) -> None:
        pass


def make_engine(path: str | None = None) -> Engine:
    path = path or os.environ.get("STOCKFISH_PATH") or shutil.which("stockfish")
    return StockfishEngine(path) if path else FallbackEngine()
