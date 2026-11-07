"""Record a game for the visual simulation.

This runs the real What, Where, and orchestrator code against the mock robot and captures
each decision, so the visual can't drift from what the app actually does. Only the robot and
camera are simulated.
"""
from __future__ import annotations

import re

import chess

from .core import TRAY, Occupancy, Step
from .engine import MATE_THRESHOLD, Engine, FallbackEngine
from .mock import MockDream, MockHuman, MockPerception, RandomOpponent, SimWorld
from .orchestrator import Orchestrator

# Mate in two. The script shows each kind of recovery: a missed grab, a wrong square, a bumped piece.
DEMO_FEN = "7k/8/8/8/8/8/R7/1R4K1 w - - 0 1"
DEMO_SCRIPT = ["miss", "off_by_one", "success", "knock"]

OUTCOMES = {
    "success": "The piece landed on the target square.",
    "miss": "The grab missed, so the piece stayed where it was.",
    "off_by_one": "The piece landed on the wrong square.",
    "knock": "The piece landed, but a neighboring piece got knocked out of place.",
    "lost": "The piece fell off the board.",
    "api_error": "The call to Dream-1 failed, so nothing moved.",
}


def _squares(text: str) -> list[str]:
    return re.findall(r"\b[a-h][1-8]\b", text)


def _score(cp: int) -> str:
    if abs(cp) >= MATE_THRESHOLD:
        return "forced mate" if cp > 0 else "getting mated"
    return f"{cp / 100:+.1f} pawns"


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" + ("" if number == 1 else "s")


class Recorder:
    def __init__(self, board: chess.Board, world: SimWorld):
        self.board, self.world = board, world
        self.frames: list[dict] = []
        self.pieces = {chess.square_name(s): p.symbol() for s, p in board.piece_map().items()}
        self.agent: Orchestrator | None = None

    def _sync(self) -> None:
        """Carry piece types through physical changes, since the camera only sees colors."""
        occ = self.world.occ
        color = lambda symbol: "w" if symbol.isupper() else "b"
        gone = [s for s, p in self.pieces.items() if occ.get(s) != color(p)]
        added = [s for s, c in occ.items() if s not in self.pieces or color(self.pieces[s]) != c]
        moved: dict[str, str] = {}
        for target in added:
            sources = [s for s in gone if color(self.pieces[s]) == occ[target] and s not in moved]
            if sources:
                nearest = min(
                    sources,
                    key=lambda s: chess.square_distance(chess.parse_square(s), chess.parse_square(target)),
                )
                moved[nearest] = target
        updated = {s: p for s, p in self.pieces.items() if s not in gone}
        for source, target in moved.items():
            updated[target] = self.pieces[source]
        for target in added:
            updated.setdefault(target, "Q" if occ[target] == "w" else "q")  # a spare queen
        self.pieces = updated

    def record(self, stage: str, text: str, highlight: list[str] | None = None, prompt: str = "", tone: str = "") -> None:
        self._sync()
        stats = self.agent.stats if self.agent else None
        self.frames.append({
            "stage": stage,
            "text": text,
            "prompt": prompt,
            "tone": tone,  # "good", "bad", or empty
            "highlight": highlight or [],
            "pieces": dict(self.pieces),
            "moves": stats.moves if stats else 0,
            "attempts": stats.dream_attempts if stats else 0,
            "corrections": stats.corrections if stats else 0,
            "rescues": stats.human_calls if stats else 0,
        })

    def log(self, line: str) -> None:
        """Turn the orchestrator's log lines into frames."""
        kind, _, rest = line.partition(" ")
        rest = rest.strip()
        if kind == "WHAT":
            found = re.match(r"(\w+) on (\w\d) \(best ([+-]\d+) cp, (\d+) neighbors, (\d+) alternatives\)", rest)
            piece, square, cp, neighbors, others = found.groups()
            self.record(
                "what",
                f"Chose the {piece} on {square}: {_score(int(cp))}, {_count(int(neighbors), 'neighboring piece')}, "
                f"{_count(int(others), 'other good option')}.",
                [square],
            )
        elif kind == "WHERE":
            found = re.match(r"(\S+) \(([+-]\d+) cp, risk (\d+)\)", rest)
            move, cp, risk = found.groups()
            self.record("where", f"Chose {move}: {_score(int(cp))}, handling risk {risk}.")
        elif kind == "CHECK":
            missing, extra = re.match(r"missing=(\[.*?\]) extra=(\[.*?\])", rest).groups()
            missing, extra = _squares(missing), _squares(extra)
            parts = []
            if missing:
                parts.append(f"expected a piece on {', '.join(missing)}")
            if extra:
                parts.append(f"found an unexpected piece on {', '.join(extra)}")
            self.record("check", "Board is wrong: " + " and ".join(parts) + ".", missing + extra, tone="bad")
        elif kind == "SEEN":
            self.record("opponent", f"The camera worked out that the opponent {rest.split(' ', 1)[1]}.")


class RecordingDream(MockDream):
    def __init__(self, recorder: Recorder, *args, **kwargs):
        super().__init__(recorder.world, *args, **kwargs)
        self.recorder = recorder
        self.last = "success"

    def _roll(self) -> str:
        self.last = super()._roll()
        return self.last

    def execute(self, step: Step) -> None:
        squares = [s for s in (step.source, step.target) if s != TRAY]
        self.recorder.record("how", "Dream-1 gets this prompt:", squares, prompt=step.prompt)
        try:
            super().execute(step)
        finally:
            landed = self.world.occ == step.expected_after
            # A "knock" with no piece close enough to hit is just a clean move.
            outcome = "success" if landed else self.last
            self.recorder.record(
                "how", f"Simulated result: {OUTCOMES[outcome]}", squares, tone="good" if landed else "bad"
            )
            if landed:
                self.recorder.record("check", "Camera confirms this step matches the expected board.", squares, tone="good")


class RecordingHuman(MockHuman):
    def __init__(self, recorder: Recorder):
        super().__init__(recorder.world)
        self.recorder = recorder

    def request_fix(self, message: str, expected: Occupancy) -> None:
        super().request_fix(message, expected)
        self.recorder.record("person", "The robot can't fix this alone, so a person restores the board.")


def record_game(
    fen: str = DEMO_FEN,
    robot_color: chess.Color = chess.WHITE,
    script: list[str] | None = None,
    seed: int = 1,
    p_success: float = 1.0,
    max_plies: int = 12,
    engine: Engine | None = None,
) -> list[dict]:
    board = chess.Board(fen)
    world = SimWorld(board)
    recorder = Recorder(board, world)
    agent = Orchestrator(
        board, robot_color, engine or FallbackEngine(),
        RecordingDream(recorder, seed=seed, p_success=p_success, script=script),
        MockPerception(world, noise=0), RecordingHuman(recorder),
        RandomOpponent(world, seed=seed + 2), log=recorder.log,
    )
    recorder.agent = agent
    recorder.record("start", "The robot plays " + ("White." if robot_color == chess.WHITE else "Black."))

    plies = 0
    while not board.is_game_over(claim_draw=True) and plies < max_plies:
        if board.turn == robot_color:
            before = board.copy(stack=False)
            move = agent.play_robot_turn()
            recorder.record(
                "update", f"Every step is confirmed, so the board now records {before.san(move)}.",
                [chess.square_name(move.to_square)], tone="good",
            )
        else:
            agent.read_opponent_turn()
        plies += 1

    if board.is_checkmate():
        winner = "White" if board.turn == chess.BLACK else "Black"
        recorder.record("end", f"Checkmate. {winner} wins.", tone="good")
    else:
        recorder.record("end", f"Stopped with result {board.result(claim_draw=True)}.")
    return recorder.frames
