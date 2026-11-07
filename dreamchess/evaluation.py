"""A repeatable test of Dream-1 on single chess moves, to compare models and prompt wordings.

Each trial is one pick-and-place, set up by hand and scored by the person watching. The named
wording comes straight from the app's own prompt writer (`where.write_prompt`), so the results
apply to the prompts the agent really sends.

Assumes the board sits with White's side nearest the robot, a1 at the robot's left.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import chess

from .core import TRAY, Step, color_word
from .where import arm_for, write_prompt


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    color: str  # "w" or "b"
    piece: str
    source: str
    target: str  # a square, or TRAY
    tags: tuple[str, ...]
    neighbors: tuple[tuple[str, str, str], ...] = ()  # (color, piece, square) placed around it


W, B = "w", "b"
TASKS = [
    Task("t01", "Short knight hop, left arm", W, "knight", "b1", "c3", ("near", "left-arm", "knight")),
    Task("t02", "Short knight hop, right arm", W, "knight", "g1", "f3", ("near", "right-arm", "knight")),
    Task("t03", "Pawn push", W, "pawn", "e2", "e4", ("near", "right-arm", "pawn")),
    Task("t04", "Long reach, left arm", W, "rook", "a1", "a6", ("far", "left-arm", "rook")),
    Task("t05", "Long reach, right arm", W, "rook", "h1", "h6", ("far", "right-arm", "rook")),
    Task("t06", "Long diagonal across the board", W, "bishop", "c1", "h6", ("far", "left-arm", "bishop", "cross-board")),
    Task("t07", "To the center", W, "queen", "d1", "d5", ("mid", "left-arm", "queen")),
    Task("t08", "Tallest piece, one square", W, "king", "e1", "e2", ("near", "right-arm", "king", "tall")),
    Task("t09", "Pick from between neighbors", W, "pawn", "e2", "e4", ("near", "right-arm", "pawn", "crowded"),
         ((W, "pawn", "d2"), (W, "pawn", "f2"))),
    Task("t10", "Place between neighbors", W, "bishop", "f1", "e3", ("near", "right-arm", "bishop", "crowded"),
         ((W, "pawn", "d3"), (W, "pawn", "f3"))),
    Task("t11", "Capture: remove a piece to the tray", B, "pawn", "d5", TRAY, ("mid", "left-arm", "pawn", "tray")),
    Task("t12", "Black piece on the far side", B, "queen", "d8", "d6", ("far", "left-arm", "queen", "black-piece")),
]
WORDINGS = ("named", "relative")

OUTCOMES = {
    "s": ("success", "Right square, upright, nothing else moved"),
    "w": ("wrong_square", "Put down on a different square"),
    "m": ("missed", "Never picked it up"),
    "d": ("dropped", "Dropped it, knocked it over, or it fell off the board"),
    "n": ("disturbed", "Moved the piece but bumped another piece out of place"),
    "x": ("no_motion", "The arms didn't really try, or the station reported an error"),
    "e": ("stopped", "A person stopped it for safety"),
}


def _arm(task: Task) -> str:
    return arm_for(task.target if task.source == TRAY else task.source, chess.WHITE)


def _squares(count: int) -> str:
    return f"{count} square" + ("" if count == 1 else "s")


def relative_prompt(task: Task) -> str:
    """The same move, described by direction and distance, for a camera that can't read square names."""
    item = f"the {color_word(task.color)} {task.piece}"
    if task.target == TRAY:
        return (f"Using your {_arm(task)} arm, pick up {item} and put it in the tray. "
                "Move slowly and do not touch any other piece.")
    forward = int(task.target[1]) - int(task.source[1])
    across = ord(task.target[0]) - ord(task.source[0])
    parts = []
    if forward:
        parts.append(f"{_squares(abs(forward))} {'away from you' if forward > 0 else 'toward you'}")
    if across:
        parts.append(f"{_squares(abs(across))} to your {'right' if across > 0 else 'left'}")
    return (f"Using your {_arm(task)} arm, pick up {item} and move it {' and '.join(parts)}. "
            "Set it down upright in the center of that square, moving slowly and touching no other piece.")


def prompt_for(task: Task, wording: str) -> str:
    if wording == "named":
        return write_prompt(_arm(task), task.color, task.piece, task.source, task.target)
    if wording == "relative":
        return relative_prompt(task)
    raise ValueError(f"unknown wording {wording!r}; choose from {WORDINGS}")


def step_for(task: Task, wording: str) -> Step:
    return Step(task.color, task.piece, task.source, task.target, _arm(task), prompt_for(task, wording), {})


def setup_text(task: Task) -> str:
    placed = [(task.color, task.piece, task.source)] + list(task.neighbors)
    pieces = ", ".join(f"{color_word(c)} {p} on {sq}" for c, p, sq in placed)
    tray = " Put an empty tray where the robot can reach it." if task.target == TRAY else ""
    return f"Clear the board, then place: {pieces}.{tray}"


def trial_plan(tasks: list[Task], wordings: list[str], repeat: int) -> list[tuple[int, Task, str]]:
    """Alternate wordings within each task, so neither always goes first."""
    plan = []
    for rep in range(repeat):
        for index, task in enumerate(tasks):
            order = wordings if (index + rep) % 2 == 0 else list(reversed(wordings))
            plan.extend((rep + 1, task, wording) for wording in order)
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
    """Markdown tables comparing each label, by wording, by kind of move, and by failure."""
    if not results:
        return "No results yet."
    by_label: dict[str, list[dict]] = defaultdict(list)
    for entry in results:
        by_label[entry["label"]].append(entry)
    labels = list(by_label)  # in the order they were run, so the last is the newest
    lines = ["## Success rate", "", "| Run | Checkpoint | All | " + " | ".join(w.title() for w in WORDINGS) + " |",
             "| --- | --- | --- | " + " | ".join("---" for _ in WORDINGS) + " |"]
    for label in labels:
        entries = by_label[label]
        checkpoints = sorted({e.get("checkpoint") or "unknown" for e in entries})
        cells = [_rate([e for e in entries if e["wording"] == w]) for w in WORDINGS]
        lines.append(f"| {label} | {', '.join(checkpoints)} | {_rate(entries)} | " + " | ".join(cells) + " |")

    tags = sorted({tag for e in results for tag in e["tags"]})
    lines += ["", "## By kind of move", "", "| Kind | " + " | ".join(labels) + " |",
              "| --- | " + " | ".join("---" for _ in labels) + " |"]
    for tag in tags:
        lines.append(f"| {tag} | " + " | ".join(_rate([e for e in by_label[l] if tag in e["tags"]]) for l in labels) + " |")

    names = [name for name, _ in OUTCOMES.values()]
    lines += ["", "## What went wrong", "", "| Outcome | " + " | ".join(labels) + " |",
              "| --- | " + " | ".join("---" for _ in labels) + " |"]
    for name in names:
        counts = [str(Counter(e["outcome"] for e in by_label[l])[name]) for l in labels]
        lines.append(f"| {name} | " + " | ".join(counts) + " |")

    latest = by_label[labels[-1]]
    weak = [t for t in tags if (lambda es: es and sum(e["outcome"] == "success" for e in es) / len(es) < 0.5)(
        [e for e in latest if t in e["tags"]])]
    lines += ["", f"## Where to focus data collection ({labels[-1]})", ""]
    lines.append("Kinds of move succeeding under half the time: " + (", ".join(weak) if weak else "none") + ".")
    smallest = min(len(by_label[l]) for l in labels)
    if smallest < 20:
        lines.append(f"\nWith only {smallest} trials in a run, a difference of one or two successes may be chance.")
    return "\n".join(lines)
