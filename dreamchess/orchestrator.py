"""The agent loop: observe, decide, act, verify, recover.

The board only advances after the camera confirms the physical move, so the program
can never believe a move happened when it didn't. Every failure uses the same recovery
logic: compare the camera against the goal, then issue a move that closes the gap.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable

import chess

from .core import TRAY, Human, Mover, MoverError, Occupancy, OpponentSignal, Perception, Step, color_code, occupancy
from .engine import Engine
from .what import choose_piece
from .where import choose_destination, make_step, plan_move


class GameAborted(RuntimeError):
    pass


@dataclass
class Config:
    max_attempts: int = 6  # Dream-1 tries per goal before asking a person
    max_human_calls: int = 2  # per goal
    frames_per_observation: int = 3
    margin_cp: int = 30  # chess strength to trade for easier handling
    max_opponent_reads: int = 3
    # More wrong squares than this means a bumped board or an arm in view, so don't let the
    # robot "fix" it. Ordinary failures only touch a few squares.
    max_auto_fix_squares: int = 6


@dataclass
class Stats:
    moves: int = 0
    dream_attempts: int = 0
    corrections: int = 0
    human_calls: int = 0


def compare(goal: Occupancy, seen: Occupancy) -> tuple[Occupancy, Occupancy]:
    """Return (missing, extra): pieces the goal has but the camera doesn't, and vice versa."""
    missing = {sq: c for sq, c in goal.items() if seen.get(sq) != c}
    extra = {sq: c for sq, c in seen.items() if goal.get(sq) != c}
    return missing, extra


def infer_opponent_move(board: chess.Board, seen: Occupancy) -> chess.Move | None:
    """Find the one legal move that produces what the camera sees.

    The camera only needs colors, not piece types. Chess rules supply the rest.
    """
    matches = []
    for move in board.legal_moves:
        board.push(move)
        if occupancy(board) == seen:
            matches.append(move)
        board.pop()
    if len(matches) == 1:
        return matches[0]
    # The four promotion choices look identical from above, so assume a queen.
    queen = [m for m in matches if m.promotion == chess.QUEEN]
    return queen[0] if queen else None


class Orchestrator:
    def __init__(
        self,
        board: chess.Board,
        robot_color: chess.Color,
        engine: Engine,
        mover: Mover,
        perception: Perception,
        human: Human,
        wait_for_opponent: OpponentSignal,
        config: Config | None = None,
        log: Callable[[str], None] = print,
    ):
        self.board = board
        self.robot_color = robot_color
        self.engine = engine
        self.mover = mover
        self.perception = perception
        self.human = human
        self.wait_for_opponent = wait_for_opponent
        self.config = config or Config()
        self.log = log
        self.stats = Stats()

    def run(self, max_plies: int | None = None) -> str:
        plies = 0
        while not self.board.is_game_over(claim_draw=True):
            if max_plies is not None and plies >= max_plies:
                return "stopped"
            if self.board.turn == self.robot_color:
                self.play_robot_turn()
            else:
                self.read_opponent_turn()
            plies += 1
        return self.board.result(claim_draw=True)

    def play_robot_turn(self) -> chess.Move:
        # Catch anything bumped since the last move before planning on top of it.
        self._achieve(occupancy(self.board))

        choice = choose_piece(self.board, self.engine, self.config.margin_cp)
        self.log(
            f"WHAT  {chess.piece_name(choice.piece.piece_type)} on {chess.square_name(choice.square)} "
            f"(best {choice.piece_best_cp:+d} cp, {choice.crowding} neighbors, "
            f"{choice.alternatives} alternatives)"
        )
        dest = choose_destination(self.board, self.engine, choice, self.config.margin_cp)
        self.log(f"WHERE {self.board.san(dest.move)} ({dest.cp:+d} cp, risk {dest.risk})")

        for step in plan_move(self.board, dest.move):
            self._achieve(step.expected_after, step)

        self.board.push(dest.move)
        self.stats.moves += 1
        return dest.move

    def read_opponent_turn(self) -> chess.Move:
        self.wait_for_opponent(self.board)
        for _ in range(self.config.max_opponent_reads):
            move = infer_opponent_move(self.board, self._observe())
            if move is not None:
                self.log(f"SEEN  opponent played {self.board.san(move)}")
                self.board.push(move)
                return move
        raise GameAborted("camera doesn't match any legal opponent move")

    def _observe(self) -> Occupancy:
        """Vote across several frames so one bad frame can't trigger a false correction."""
        votes: dict[str, Counter] = {}
        frames = self.config.frames_per_observation
        for _ in range(frames):
            frame = self.perception.observe()
            for sq in chess.SQUARE_NAMES:
                votes.setdefault(sq, Counter())[frame.get(sq)] += 1
        result: Occupancy = {}
        for sq, counter in votes.items():
            value, _ = counter.most_common(1)[0]
            if value is not None:
                result[sq] = value
        return result

    def _achieve(self, goal: Occupancy, first: Step | None = None) -> None:
        """Keep acting until the camera shows `goal`, or escalate to a person."""
        step = first
        attempts = 0
        human_calls = 0
        while True:
            if step is not None:
                attempts += 1
                self.stats.dream_attempts += 1
                self.log(f"HOW   [{attempts}/{self.config.max_attempts}] {step.prompt}")
                try:
                    self.mover.execute(step)
                except MoverError as err:
                    self.log(f"      mover error: {err}")
                self.mover.go_home()  # the arms block the top camera

            missing, extra = compare(goal, self._observe())
            if not missing and not extra:
                return
            self.log(f"CHECK missing={sorted(missing)} extra={sorted(extra)}")

            can_retry = (
                attempts < self.config.max_attempts
                and len(missing) + len(extra) <= self.config.max_auto_fix_squares
            )
            step = self._corrective_step(missing, extra, goal, first) if can_retry else None
            if step is not None:
                self.stats.corrections += 1
                continue

            if human_calls >= self.config.max_human_calls:
                raise GameAborted(f"board still wrong after help: missing={missing} extra={extra}")
            human_calls += 1
            self.stats.human_calls += 1
            attempts = 0
            self.human.request_fix(f"Please fix the board. Missing: {missing}. Extra: {extra}.", goal)

    def _corrective_step(self, missing: Occupancy, extra: Occupancy, goal: Occupancy, first: Step | None) -> Step | None:
        """Pick the next physical action, or None if only a person can fix this."""
        for source, color in sorted(extra.items()):
            candidates = [sq for sq, c in missing.items() if c == color and sq != source]
            if candidates:
                target = min(
                    candidates,
                    key=lambda sq: (chess.square_distance(chess.parse_square(sq), chess.parse_square(source)), sq),
                )
                return make_step(color, "piece", source, target, self.robot_color, goal)
        if extra:  # a stray with nowhere to go, e.g. a capture that wasn't removed
            source, color = sorted(extra.items())[0]
            return make_step(color, "piece", source, TRAY, self.robot_color, goal)
        if first is not None and first.source == TRAY and first.target in missing:
            return first  # the spare queen didn't arrive, so try again
        return None  # a piece vanished from view, likely off the table
