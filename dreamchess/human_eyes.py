"""A person stands in for the top camera, until the station shares it.

After each robot step, the person answers whether the piece landed, where it ended up if not,
and whether anything else got bumped. That keeps an up-to-date picture of the board in the same
form the camera code produces, so the orchestrator's checks, retries, and fixes work unchanged.
"""
from __future__ import annotations

from typing import Callable

import chess

from .core import TRAY, Mover, Occupancy, Step, color_word, occupancy

Ask = Callable[[str], str]
Say = Callable[[str], None]
Record = Callable[[dict], None]


class GameQuit(Exception):
    """The person asked to stop the game."""


def _square(text: str) -> str | None:
    text = text.strip().lower()
    try:
        chess.parse_square(text)
        return text
    except ValueError:
        return None


def _place(step: Step) -> str:
    return f"the tray on the robot's {step.arm}" if step.target == TRAY else step.target


class HumanEyes:
    """A Perception backed by a person's answers."""

    def __init__(self, board: chess.Board, ask: Ask = input, say: Say = print, record: Record = lambda _: None):
        self.belief: Occupancy = occupancy(board)
        self.pending: Step | None = None
        self.ask, self.say, self.record = ask, say, record

    def attempted(self, step: Step) -> None:
        self.pending = step

    def observe(self) -> Occupancy:
        if self.pending is not None:
            step, self.pending = self.pending, None
            self._ask_about(step)
        return dict(self.belief)

    def opponent_moved(self, board_after: chess.Board) -> None:
        self.belief = occupancy(board_after)

    def fixed_by_person(self, expected: Occupancy) -> None:
        self.belief = dict(expected)

    def _move(self, source: str, target: str, color: str) -> None:
        if source != TRAY:
            self.belief.pop(source, None)
        if target not in (TRAY, "gone"):
            self.belief[target] = color

    def _ask_about(self, step: Step) -> None:
        name = f"{color_word(step.color)} {step.piece_name}"
        start = "the tray" if step.source == TRAY else step.source
        while True:
            answer = self.ask(f"  Did the {name} from {start} end up on {_place(step)}? y/n: ").strip().lower()
            if answer in ("y", "n"):
                break
        result = {"type": "attempt_result", "prompt": step.prompt, "landed": answer == "y"}
        if answer == "y":
            self._move(step.source, step.target, step.color)
        else:
            while True:
                where = self.ask("  Where is it now? A square, 'same' if it didn't move, 'tray', or 'gone' if it "
                                 "left the board: ").strip().lower()
                if where in ("same", "tray", "gone") or _square(where):
                    break
            result["ended_on"] = where
            if where != "same":
                self._move(step.source, TRAY if where == "tray" else where, step.color)

        bumps = []
        while True:
            answer = self.ask("  Anything else knocked out of place? Type 'from to', like e4 e3, or press Enter "
                              "for no: ").strip().lower()
            if not answer:
                break
            parts = answer.split()
            if len(parts) != 2 or not _square(parts[0]) or not (_square(parts[1]) or parts[1] == "gone"):
                self.say("  Type two squares, like e4 e3, or e4 gone if it left the board.")
                continue
            if parts[0] not in self.belief:
                self.say(f"  There shouldn't be a piece on {parts[0]}; check the square and try again.")
                continue
            self._move(parts[0], parts[1], self.belief[parts[0]])
            bumps.append(answer)
        result["bumped"] = bumps
        self.record(result)


class AttemptMover:
    """Wraps the real mover to tell the eyes what was tried and to time each attempt."""

    def __init__(self, inner: Mover, eyes: HumanEyes | None, record: Record, clock: Callable[[], float]):
        self.inner, self.eyes, self.record, self.clock = inner, eyes, record, clock

    def execute(self, step: Step) -> None:
        if self.eyes is not None:
            self.eyes.attempted(step)
        started = self.clock()
        try:
            self.inner.execute(step)
        finally:
            self.record({"type": "attempt", "prompt": step.prompt, "arm": step.arm,
                         "source": step.source, "target": step.target,
                         "seconds": round(self.clock() - started, 1)})

    def go_home(self) -> None:
        self.inner.go_home()


class TerminalOpponent:
    """Asks the person for their move and checks it's legal."""

    def __init__(self, ask: Ask = input, say: Say = print, on_move: Callable[[chess.Board], None] = lambda _: None,
                 record: Record = lambda _: None, script: tuple[str, ...] = ()):
        self.ask, self.say, self.on_move, self.record = ask, say, on_move, record
        self.script = script  # White's moves in a scripted game, to suggest one at a time

    def _hint(self, board: chess.Board) -> str:
        index = len(board.move_stack) // 2 if board.turn == chess.WHITE else None
        if index is None or index >= len(self.script):
            return ""
        try:
            move = board.parse_san(self.script[index])
        except ValueError:
            return ""  # off the script: no suggestion
        return f" [script: play {self.script[index]}, {chess.square_name(move.from_square)} to "                f"{chess.square_name(move.to_square)}]"

    def __call__(self, board: chess.Board) -> None:
        while True:
            text = self.ask(f"Your move{self._hint(board)}, such as e4, Nf3, or e2e4 (or 'quit'): ").strip()
            if text.lower() in ("quit", "q"):
                raise GameQuit()
            move = None
            try:
                move = board.parse_san(text)
            except ValueError:
                try:
                    move = chess.Move.from_uci(text.lower())
                except ValueError:
                    pass
            if move is not None and move in board.legal_moves:
                break
            self.say("  That isn't a legal move here. Try again.")
        after = board.copy(stack=False)
        after.push(move)
        self.record({"type": "opponent_move", "san": board.san(move)})
        self.on_move(after)


class TerminalHuman:
    """Asks a person to fix the board when the robot can't."""

    def __init__(self, eyes: HumanEyes | None, ask: Ask = input, say: Say = print, record: Record = lambda _: None):
        self.eyes, self.ask, self.say, self.record = eyes, ask, say, record

    def request_fix(self, message: str, expected: Occupancy) -> None:
        seen = self.eyes.belief if self.eyes is not None else {}
        changes = []
        for square in sorted(set(seen) | set(expected)):
            if seen.get(square) == expected.get(square):
                continue
            if square in expected:
                changes.append(f"put a {color_word(expected[square])} piece on {square}")
            else:
                changes.append(f"clear {square}")
        self.say("\nThe robot needs a hand. Please " + ("; ".join(changes) if changes else "check the board") + ".")
        self.record({"type": "help", "changes": changes})
        answer = self.ask("Press Enter once the board is fixed (or 'quit'): ").strip().lower()
        if answer in ("quit", "q"):
            raise GameQuit()
        if self.eyes is not None:
            self.eyes.fixed_by_person(expected)
