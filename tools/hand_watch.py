"""Stream where each hand is during a station run: square, height and grip, about once a second.

    ~/dream-env/bin/python tools/hand_watch.py ~/.dream-chess/board_fit.json [--inputs FILE] [--from-start]

The station writes the arms' joints and grippers to ~/.dreamlabs/last-run_inputs/inputs.jsonl about once a second
while it runs a move (the same state it hands Dream-1). This follows that file, runs each arm's forward kinematics,
and prints one JSON line per sample:

    {"t": 12.0, "right": {"square": "b8", "x": .., "y": .., "z": 0.05, "grip": 0.08}, "left": {...}}

`t` is seconds since the run started; a line {"run_start": true} marks a new run. The app reads these to supervise a
move while it happens. Runs with the Dream library's Python (~/dream-env), which has the arm model.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

INPUTS = Path("~/.dreamlabs/last-run_inputs/inputs.jsonl").expanduser()
FILES = "abcdefgh"


def square_of(coef: np.ndarray, x: float, y: float) -> str | None:
    f, r = np.array([x, y, 1.0]) @ coef
    fi, ri = int(round(f)), int(round(r))
    return f"{FILES[fi]}{ri}" if 0 <= fi < 8 and 1 <= ri <= 8 else None  # None: off the board


def follow(path: Path, from_start: bool):
    """Yield each new line of a file the station rewrites for every run."""
    position = 0 if from_start else (path.stat().st_size if path.exists() else 0)
    inode = path.stat().st_ino if path.exists() else None
    while True:
        if not path.exists():
            time.sleep(0.3)
            continue
        stat = path.stat()
        if stat.st_ino != inode or stat.st_size < position:  # a new run replaced the file
            inode, position = stat.st_ino, 0
        if stat.st_size > position:
            with path.open() as f:
                f.seek(position)
                chunk = f.read()
            complete = chunk.rfind("\n") + 1  # leave a half-written last line for next time
            position += complete
            for line in chunk[:complete].splitlines():
                yield line
        else:
            time.sleep(0.3)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("fit", type=Path)
    parser.add_argument("--inputs", type=Path, default=INPUTS)
    parser.add_argument("--from-start", action="store_true", help="replay the file from its start (for checking)")
    parser.add_argument("--once", action="store_true", help="stop at the end of the file instead of following it")
    parser.add_argument("--station", default=str(Path("~/.dreamlabs/station.yaml").expanduser()))
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).parent))
    from fit_board import arm_models

    fit = json.loads(args.fit.expanduser().read_text())
    coef = {arm: np.array(fit[arm]["coef"]) for arm in ("right", "left") if arm in fit}
    fk = arm_models(args.station)
    started = None
    lines = args.inputs.read_text().splitlines() if args.once else follow(args.inputs, args.from_start)
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("kind") == "run_start":
            started = event.get("t_s")
            print(json.dumps({"run_start": True}), flush=True)
            continue
        if event.get("kind") != "inputs":
            continue
        state = event.get("state", {})
        out = {"t": round(event["t_s"] - (started or event["t_s"]), 2)}
        for arm in ("right", "left"):
            if arm not in coef or f"state.{arm}_arm" not in state:
                continue
            x, y, z = fk[arm].ee_position(np.array(state[f"state.{arm}_arm"], dtype=float))
            out[arm] = {"square": square_of(coef[arm], x, y), "x": round(float(x), 3), "y": round(float(y), 3),
                        "z": round(float(z), 3), "grip": round(float(state[f"state.{arm}_gripper"][0]), 3)}
        print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
