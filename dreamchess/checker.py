"""The checker agent: after each robot step, a top-camera picture, read into the board, and a verdict in words.

The orchestrator asks the checker what the board looks like (it's the orchestrator's Perception). The checker takes
a picture through the station (station_camera.py: the arms at home and still, kept in memory), reads which squares
hold a white piece, a brown piece, or nothing (webcam.py's BoardCamera, with the vision code), and returns that. The
orchestrator compares it with the board the move should have made, and on a mismatch writes the verdict in plain
words (describe_failure, e.g. "the brown queen went to b2 instead of c2") and sends Dream-1 the correction, until
the checker sees the board right, or six tries have failed and a person is asked to fix it.

Until the camera is calibrated, or if a picture fails, the person answers instead (human_eyes.py).
"""
from __future__ import annotations

from typing import Callable

from .core import TRAY, Occupancy, Step, color_word
from .vision import CalibrationError


class CameraChecker:
    def __init__(self, camera, fallback, log: Callable[[str], None] = lambda _: None):
        self.camera, self.fallback, self.log = camera, fallback, log

    def observe(self) -> Occupancy:
        if not self.camera.status()["calibrated"]:
            return self.fallback.observe()
        try:
            seen = self.camera.read()
        except CalibrationError as err:
            self.log(f"LOOK  couldn't take a picture ({err}): asking a person instead")
            return self.fallback.observe()
        self.log(f"LOOK  the top camera sees {sum(1 for c in seen.values() if c == 'w')} white and "
                 f"{sum(1 for c in seen.values() if c == 'b')} brown pieces")
        if hasattr(self.fallback, "belief"):
            self.fallback.belief = dict(seen)  # so a person asked later starts from what the camera saw
        return seen


def describe_failure(step: Step | None, missing: Occupancy, extra: Occupancy, names: dict[str, str]) -> str:
    """What went wrong, as a sentence the orchestrator logs and a person (or, later, a voice) can follow.

    `names` says which piece belongs on each square once the step is done, so the moved piece can be named."""
    if step is not None and step.target != TRAY and step.target in missing:
        piece = f"{color_word(step.color)} {step.piece_name}"
        landed = [sq for sq, c in extra.items() if c == step.color and sq != step.source]
        if step.source in extra:
            return f"the {piece} is still on {step.source}"
        if len(landed) == 1:
            return f"the {piece} went to {landed[0]} instead of {step.target}"
        return f"the {piece} didn't reach {step.target}, and the camera can't see where it went"
    if step is not None and step.target == TRAY and step.source in extra:
        return f"the {color_word(step.color)} {step.piece_name} is still on {step.source}, not in the tray"
    parts = []
    for square, color in sorted(missing.items()):
        parts.append(f"the {color_word(color)} {names.get(square, 'piece')} is missing from {square}")
    for square, color in sorted(extra.items()):
        parts.append(f"there's a {color_word(color)} piece on {square} that shouldn't be there")
    return "; ".join(parts) or "the board doesn't match"
