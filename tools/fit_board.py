"""Find where the board's squares are in each arm's own frame, from our recorded demos. The arms are never involved.

    ~/dream-env/bin/python tools/fit_board.py ~/hackathon_data/chess-all/chess-game2 ~/.dream-chess/board_fit.json

In every demo the operator's gripper closes over the piece's square and opens over its target square, and each demo's
task names both squares. So the hand's position at each squeeze and release (the arm's joints through the arm model's
forward kinematics, as the station computes them) pairs a spot in the arm's frame with a known square. A straight-line
fit per arm then turns any hand position into a square. Fit it on demos recorded with the board where it is now: the
fit only holds while the board and the arms stay put (game 2's demos read back 100% right, median error 0.1 square).

Runs with the Dream library's Python (~/dream-env), which has the arm model.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path

import numpy as np

FIRM_GRIP = 0.22  # below this the fingers are squeezed shut on a piece (fully open is 1.0)
REOPENED = 0.30   # above this again, after a squeeze, the piece has been let go
TASK = re.compile(r"(left|right) arm, pick up the \w+ \w+ on square ([a-h][1-8]) and "
                  r"(?:place it upright in the center of square ([a-h][1-8])|put it in the tray)")


def arm_models(station_yaml: str):
    from robots import config as rconfig
    from robots.kinematics import ArmKinematics

    cfg = rconfig.load(station_yaml)
    return {"right": ArmKinematics.from_config(cfg.follower_r), "left": ArmKinematics.from_config(cfg.follower_l)}


def events(dataset: Path, fk) -> list[tuple[str, np.ndarray, str]]:
    """(arm, hand position, square) at every squeeze and release in the dataset."""
    import pyarrow.parquet as pq

    tasks = {json.loads(line)["task_index"]: json.loads(line)["task"]
             for line in (dataset / "meta" / "tasks.jsonl").read_text().splitlines() if line.strip()}
    found = []
    for path in sorted(glob.glob(str(dataset / "data" / "*" / "*.parquet"))):
        table = pq.read_table(path).to_pydict()
        task = TASK.search(tasks[table["task_index"][0]])
        if not task:
            continue
        arm, source, target = task.groups()
        state = np.array(table["observation.state"], dtype=float)
        offset = 0 if arm == "right" else 7  # right joints, right gripper, left joints, left gripper
        joints, grip = state[:, offset:offset + 6], state[:, offset + 6]
        hands = np.array([fk[arm].ee_position(q) for q in joints])
        firm = np.where(grip < FIRM_GRIP)[0]
        if not len(firm):
            continue

        def lowest(i: int, back: int, ahead: int) -> int:  # the hand's lowest point near a moment: the table
            a, b = max(0, i - back), min(len(hands), i + ahead)
            return a + int(np.argmin(hands[a:b, 2]))

        squeeze = int(firm[0])
        found.append((arm, hands[lowest(squeeze, 45, 15)], source))
        reopen = np.where(grip[squeeze:] > REOPENED)[0]
        if target and len(reopen):
            found.append((arm, hands[lowest(squeeze + int(reopen[0]), 30, 15)], target))
    return found


def fit(found) -> dict:
    """Per arm: the 3x2 matrix taking (x, y, 1) of the hand to (file index, rank), and how well it reads back."""
    out = {}
    for arm in ("right", "left"):
        rows = [(hand, square) for a, hand, square in found if a == arm]
        if len(rows) < 4:
            continue
        X = np.array([[h[0], h[1], 1.0] for h, _ in rows])
        Y = np.array([["abcdefgh".index(s[0]), int(s[1])] for _, s in rows], dtype=float)
        coef, *_ = np.linalg.lstsq(X, Y, rcond=None)
        error = np.abs(X @ coef - Y).max(axis=1)
        out[arm] = {"coef": coef.tolist(), "events": len(rows), "median_error_squares": round(float(np.median(error)), 3),
                    "right_square": round(float((np.round(X @ coef) == Y).all(axis=1).mean()), 3),
                    "table_z": round(float(np.median([h[2] for h, _ in rows])), 3)}
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dataset", type=Path, help="a LeRobot dataset recorded with the board where it is now")
    parser.add_argument("out", type=Path)
    parser.add_argument("--station", default=str(Path("~/.dreamlabs/station.yaml").expanduser()))
    args = parser.parse_args()
    result = fit(events(args.dataset.expanduser(), arm_models(args.station)))
    result["dataset"] = str(args.dataset)
    args.out.expanduser().parent.mkdir(parents=True, exist_ok=True)
    args.out.expanduser().write_text(json.dumps(result, indent=2))
    for arm in ("right", "left"):
        if arm in result:
            r = result[arm]
            print(f"{arm} arm: {r['events']} squeezes and releases, {r['right_square']:.0%} read back on the right square, "
                  f"median error {r['median_error_squares']} of a square")


if __name__ == "__main__":
    main()
