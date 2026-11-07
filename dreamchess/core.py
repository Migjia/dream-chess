"""Shared types and the three interfaces the real hardware has to implement."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

import chess

# What a camera can reliably see: square name -> "w" or "b". Empty squares are absent.
Occupancy = dict[str, str]

TRAY = "tray"  # off-board area for captured pieces and the spare queens


@dataclass(frozen=True)
class Step:
    """One physical pick-and-place: a single instruction to Dream-1."""

    color: str
    piece_name: str
    source: str  # square name or TRAY
    target: str  # square name or TRAY
    arm: str  # "left" or "right"
    prompt: str
    expected_after: Occupancy  # what the top camera should see once this succeeds


class MoverError(RuntimeError):
    """The move attempt failed outright, e.g. a Dream API timeout."""


class Mover(Protocol):
    """HOW: the Dream-1 slot. Swap MockDream for a real adapter here."""

    def execute(self, step: Step) -> None: ...

    def go_home(self) -> None:
        """Move the arms out of the top camera's view."""
        ...


class Perception(Protocol):
    def observe(self) -> Occupancy: ...


class Human(Protocol):
    def request_fix(self, message: str, expected: Occupancy) -> None: ...


# Blocks until the opponent has finished moving.
OpponentSignal = Callable[[chess.Board], None]


def occupancy(board: chess.Board) -> Occupancy:
    return {
        chess.square_name(sq): "w" if piece.color == chess.WHITE else "b"
        for sq, piece in board.piece_map().items()
    }


def color_code(color: chess.Color) -> str:
    return "w" if color == chess.WHITE else "b"


def color_word(code: str) -> str:
    return "white" if code == "w" else "black"
