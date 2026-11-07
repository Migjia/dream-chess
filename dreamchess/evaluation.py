"""A repeatable test of Dream-1 on single chess moves, to compare models and setups.

Each trial is one pick-and-place, set up by hand and scored by the person watching. Every
prompt comes straight from the app's own prompt writer (`where.write_prompt`), so the results
apply to the prompts the agent really sends, including its fix prompts after a failure.

The robot plays Brown (Black), so it sits behind the 8th rank, with the h-file at its left.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import chess

from .core import TRAY, Step, color_word
from .where import arm_for, write_prompt

ROBOT = chess.BLACK
WORDINGS = ("named",)  # square names, exactly as the app sends them


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    color: str  # "b" for the robot's brown pieces, "w" for the opponent's
    piece: str  # the word the prompt uses; "piece" for the app's fix prompts
    source: str
    target: str  # a square, or TRAY
    tags: tuple[str, ...]
    neighbors: tuple[tuple[str, str, str], ...] = ()  # (color, piece, square) placed around it
    setup_piece: str = ""  # the real piece to place, when the prompt only says "piece"


B, W = "b", "w"
TASKS = [
    Task("t01", "Short knight hop, left arm", B, "knight", "g8", "f6", ("near", "left-arm", "knight")),
    Task("t02", "Short knight hop, right arm", B, "knight", "b8", "c6", ("near", "right-arm", "knight")),
    Task("t03", "Pawn push", B, "pawn", "e7", "e5", ("near", "left-arm", "pawn")),
    Task("t04", "Long reach, left arm", B, "rook", "h8", "h3", ("far", "left-arm", "rook")),
    Task("t05", "Long reach, right arm", B, "rook", "a8", "a3", ("far", "right-arm", "rook")),
    Task("t06", "Long diagonal across the board", B, "bishop", "f8", "a3", ("far", "left-arm", "bishop", "cross-board")),
    Task("t07", "To the center", B, "queen", "d8", "d4", ("mid", "right-arm", "queen")),
    Task("t08", "Tallest piece, one square", B, "king", "e8", "e7", ("near", "left-arm", "king", "tall")),
    Task("t09", "Pick from between neighbors", B, "pawn", "d7", "d5", ("near", "right-arm", "pawn", "crowded"),
         ((B, "pawn", "c7"), (B, "pawn", "e7"))),
    Task("t10", "Place between neighbors", B, "bishop", "c8", "d6", ("near", "right-arm", "bishop", "crowded"),
         ((B, "pawn", "c6"), (B, "pawn", "e6"))),
    Task("t11", "Capture: opponent piece to the left tray", W, "pawn", "e5", TRAY,
         ("mid", "left-arm", "pawn", "tray", "opponent-piece")),
    Task("t12", "Capture: opponent piece to the right tray", W, "knight", "c4", TRAY,
         ("mid", "right-arm", "knight", "tray", "opponent-piece")),
    Task("t13", "Fix: own piece on the wrong square", B, "piece", "g6", "f6", ("near", "left-arm", "recovery"),
         setup_piece="knight"),
    Task("t14", "Fix: put back a bumped opponent piece", W, "piece", "e3", "e4",
         ("mid", "left-arm", "recovery", "opponent-piece"), ((B, "knight", "f5"),), setup_piece="pawn"),
]

OUTCOMES = {
    "s": ("success", "Right square, upright, nothing else moved"),
    "w": ("wrong_square", "Put down on a different square"),
    "m": ("missed", "Never picked it up"),
    "d": ("dropped", "Dropped it, knocked it over, or it fell off the board"),
    "n": ("disturbed", "Moved the piece but bumped another piece out of place"),
    "t": ("timed_out", "Was still moving when the time limit ended"),
    "x": ("no_motion", "The arms didn't really try, or the station reported an error"),
    "e": ("stopped", "A person stopped it for safety"),
}


def _arm(task: Task) -> str:
    return arm_for(task.target if task.source == TRAY else task.source, ROBOT)


def prompt_for(task: Task, wording: str = "named") -> str:
    if wording != "named":
        raise ValueError(f"unknown wording {wording!r}; choose from {WORDINGS}")
    return write_prompt(_arm(task), task.color, task.piece, task.source, task.target)


def step_for(task: Task, wording: str = "named") -> Step:
    return Step(task.color, task.piece, task.source, task.target, _arm(task), prompt_for(task, wording), {})


def setup_text(task: Task) -> str:
    placed = [(task.color, task.setup_piece or task.piece, task.source)] + list(task.neighbors)
    pieces = ", ".join(f"{color_word(c)} {p} on {sq}" for c, p, sq in placed)
    tray = f" Check the tray on the robot's {_arm(task)} is empty." if task.target == TRAY else ""
    return f"Clear the board, then place: {pieces}.{tray}"


def trial_plan(tasks: list[Task], wordings: list[str], repeat: int) -> list[tuple[int, Task, str]]:
    """Every task once per round, with the order reversed on alternate rounds."""
    plan = []
    for rep in range(repeat):
        ordered = tasks if rep % 2 == 0 else list(reversed(tasks))
        for task in ordered:
            plan.extend((rep + 1, task, wording) for wording in wordings)
    return plan


def trial_key(entry: dict) -> tuple:
    return entry["label"], entry["task"], entry["wording"], entry["repeat"]


def load_results(paths: list[str | Path]) -> list[dict]:
    results = []
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                results.append(json.loads(line))
    return results


def _rate(entries: list[dict]) -> str:
    if not entries:
        return "-"
    wins = sum(e["outcome"] == "success" for e in entries)
    return f"{wins}/{len(entries)} ({100 * wins / len(entries):.0f}%)"


def report(results: list[dict]) -> str:
    """Markdown tables comparing each run, by kind of move and by what went wrong."""
    if not results:
        return "No results yet."
    by_label: dict[str, list[dict]] = defaultdict(list)
    for entry in results:
        by_label[entry["label"]].append(entry)
    labels = list(by_label)  # in the order they were run, so the last is the newest

    lines = ["## Success rate", "", "| Run | Checkpoint | Setup | Success |", "| --- | --- | --- | --- |"]
    for label in labels:
        entries = by_label[label]
        checkpoints = ", ".join(sorted({e.get("checkpoint") or "unknown" for e in entries}))
        setups = "; ".join(sorted({e.get("setup") or "not recorded" for e in entries}))
        lines.append(f"| {label} | {checkpoints} | {setups} | {_rate(entries)} |")

    tags = sorted({tag for e in results for tag in e["tags"]})
    lines += ["", "## By kind of move", "", "| Kind | " + " | ".join(labels) + " |",
              "| --- | " + " | ".join("---" for _ in labels) + " |"]
    for tag in tags:
        lines.append(f"| {tag} | " + " | ".join(_rate([e for e in by_label[l] if tag in e["tags"]]) for l in labels) + " |")

    lines += ["", "## What went wrong", "", "| Outcome | " + " | ".join(labels) + " |",
              "| --- | " + " | ".join("---" for _ in labels) + " |"]
    for name, _ in OUTCOMES.values():
        counts = [str(Counter(e["outcome"] for e in by_label[l])[name]) for l in labels]
        lines.append(f"| {name} | " + " | ".join(counts) + " |")

    latest = by_label[labels[-1]]

    def weak(tag: str) -> bool:
        entries = [e for e in latest if tag in e["tags"]]
        return bool(entries) and sum(e["outcome"] == "success" for e in entries) / len(entries) < 0.5

    lines += ["", f"## Where to focus data collection ({labels[-1]})", ""]
    lines.append("Kinds of move succeeding under half the time: " + (", ".join(t for t in tags if weak(t)) or "none") + ".")
    smallest = min(len(by_label[l]) for l in labels)
    if smallest < 30:
        lines.append(f"\nWith only {smallest} trials in a run, a difference of a few successes may be chance.")
    return "\n".join(lines)
