"""The scripted collection games (docs/COLLECTION_GAMES.md), to replay on the robot.

Every brown move in those games is a demo Dream-1 was fine-tuned on, with exactly the prompt the app sends. So a game
replayed from the script tests the model on what it learned, instead of on whatever Stockfish happens to pick: the
person plays the script's white moves, and the robot plays the script's brown ones.
"""
from __future__ import annotations

import re
from pathlib import Path

GAMES = Path(__file__).resolve().parent.parent / "docs" / "COLLECTION_GAMES.md"


def load_games(path: str | Path = GAMES) -> dict[int, list[tuple[str, str]]]:
    """{game number: [(white move, brown reply), ...]}, each move in SAN, in the order played."""
    games: dict[int, list[tuple[str, str]]] = {}
    current: list[tuple[str, str]] | None = None
    white: str | None = None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if found := re.match(r"## Game (\d+)", line):
            current = games.setdefault(int(found.group(1)), [])
            white = None
        elif current is not None and (found := re.match(r"WHITE: play (\S+)", line.strip())):
            white = found.group(1)
        elif current is not None and white and (found := re.match(r"DEMO \d+\s+\[\w+ arm\]\s+Brown (\S+?),?(\s|$)",
                                                                  line.strip(), re.I)):
            current.append((white, found.group(1)))  # a capture's second step and fix demos name no new move
            white = None
    return games
