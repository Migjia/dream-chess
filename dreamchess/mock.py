"""Simulated robot, camera, and helper, built to fail so recovery gets exercised.

The 40% success default is Dream Labs' reported pick-and-place rate on the YAM. The
split between failure types is an invented placeholder: replace it with real data.
"""
from __future__ import annotations

import random

import chess

from .core import TRAY, MoverError, Occupancy, Step, occupancy

DEFAULT_FAILURES = {"miss": 0.30, "off_by_one": 0.15, "knock": 0.10, "lost": 0.05}


class SimWorld:
    """The true physical state of the table, which the orchestrator can't see directly."""

    def __init__(self, board: chess.Board):
        self.occ: Occupancy = occupancy(board)
        self.arms_home = True


def _neighbors(square: str) -> list[str]:
    return [chess.square_name(s) for s in chess.SquareSet(chess.BB_KING_ATTACKS[chess.parse_square(square)])]


class MockDream:
    """Stands in for Dream-1. `script` forces specific outcomes for tests."""

    def __init__(self, world: SimWorld, seed: int = 0, p_success: float = 0.4, script: list[str] | None = None):
        self.world = world
        self.rng = random.Random(seed)
        self.p_success = p_success
        self.script = list(script or [])
        self.prompts: list[str] = []

    def _roll(self) -> str:
        if self.script:
            return self.script.pop(0)
        if self.rng.random() < self.p_success:
            return "success"
        names = list(DEFAULT_FAILURES)
        return self.rng.choices(names, weights=[DEFAULT_FAILURES[n] for n in names])[0]

    def execute(self, step: Step) -> None:
        self.world.arms_home = False
        self.prompts.append(step.prompt)
        outcome = self._roll()
        if outcome == "api_error":
            raise MoverError("simulated timeout")
        if outcome == "miss":
            return

        occ = self.world.occ
        if step.source != TRAY:
            if step.source not in occ:
                return  # nothing there to grab
        if step.target != TRAY and step.target in occ:
            return  # target occupied, so nothing can be placed

        if outcome == "lost":
            if step.source != TRAY:
                del occ[step.source]
            return

        if outcome == "off_by_one":
            anchor = step.source if step.target == TRAY else step.target
            spots = [sq for sq in _neighbors(anchor) if sq not in occ]
            if spots:
                if step.source != TRAY:
                    del occ[step.source]
                occ[self.rng.choice(spots)] = step.color
            return

        # "success" and "knock" both complete the move.
        if step.source != TRAY:
            del occ[step.source]
        if step.target != TRAY:
            occ[step.target] = step.color

        if outcome == "knock" and step.target != TRAY:
            hit = [sq for sq in _neighbors(step.target) if sq in occ]
            if hit:
                victim = self.rng.choice(hit)
                spots = [sq for sq in _neighbors(victim) if sq not in occ]
                if spots:
                    occ[self.rng.choice(spots)] = occ.pop(victim)

    def go_home(self) -> None:
        self.world.arms_home = True


class MockPerception:
    def __init__(self, world: SimWorld, seed: int = 0, noise: float = 0.05):
        self.world = world
        self.rng = random.Random(seed)
        self.noise = noise  # chance that a frame misreads one square

    def observe(self) -> Occupancy:
        if not self.world.arms_home:
            raise RuntimeError("observed while the arms were blocking the camera")
        frame = dict(self.world.occ)
        if self.rng.random() < self.noise:
            square = self.rng.choice(chess.SQUARE_NAMES)
            if square in frame:
                del frame[square]
            else:
                frame[square] = "w"
        return frame


class MockHuman:
    def __init__(self, world: SimWorld, fixes: bool = True):
        self.world = world
        self.fixes = fixes
        self.calls: list[str] = []

    def request_fix(self, message: str, expected: Occupancy) -> None:
        self.calls.append(message)
        if self.fixes:
            self.world.occ = dict(expected)


class RandomOpponent:
    """Plays a random legal move directly on the simulated table."""

    def __init__(self, world: SimWorld, seed: int = 0):
        self.world = world
        self.rng = random.Random(seed)

    def __call__(self, board: chess.Board) -> None:
        after = board.copy(stack=False)
        after.push(self.rng.choice(list(board.legal_moves)))
        self.world.occ = occupancy(after)
