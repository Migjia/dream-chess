"""Set up and check the top camera. Runs over SSH: it opens no windows and saves images instead.

    python vision_tool.py list
    python vision_tool.py snapshot --serial <top camera serial>
    python vision_tool.py calibrate --serial <top camera serial> --a1 bottom-left
    python vision_tool.py check --serial <top camera serial>

Rehearse without hardware by adding --synthetic to calibrate and check.
"""
from __future__ import annotations

import argparse

import chess
import cv2
import numpy as np

from dreamchess.core import occupancy
from dreamchess.synth import SynthCamera, pieces_from_board
from dreamchess.vision import CalibrationError, Calibration, calibrate, classify, detect_corners, draw_debug

FRAMES_PER_CAPTURE = 10


def open_source(args):
    if args.synthetic:
        return SynthCamera(tilt_deg=25, seed=1)
    from dreamchess.camera import RealSenseSource

    return RealSenseSource(serial=args.serial, use_depth=not args.no_depth)


def capture(source) -> list:
    return [source.read() for _ in range(FRAMES_PER_CAPTURE)]


def wait(args, message: str) -> None:
    print(message)
    if not args.yes:
        input("Press Enter when ready... ")


def set_scene(source, args, board: chess.Board | None) -> None:
    if args.synthetic:
        source.pieces = pieces_from_board(board) if board else {}


def parse_corners(text: str) -> np.ndarray:
    return np.array([[float(v) for v in pair.split(",")] for pair in text.split(";")], dtype=np.float32)


def board_text(seen: dict[str, str]) -> str:
    rows = []
    for rank in range(8, 0, -1):
        cells = [seen.get(f"{file}{rank}", ".") for file in "abcdefgh"]
        rows.append(f"{rank}  " + " ".join(cells))
    return "\n".join(rows) + "\n   a b c d e f g h"


def cmd_list(args) -> None:
    from dreamchess.camera import list_realsense

    for camera in list_realsense():
        print(f"{camera['serial']}  {camera['name']}")


def cmd_snapshot(args) -> None:
    source = open_source(args)
    frame = source.read()
    cv2.imwrite(args.out, frame.color)
    height, width = frame.color.shape[:2]
    depth = "yes" if frame.depth is not None else "no"
    print(f"saved {args.out} ({width} x {height}, depth: {depth})")


def cmd_calibrate(args) -> None:
    source = open_source(args)
    wait(args, "Step 1 of 2: clear the board completely and move the arms out of view.")
    set_scene(source, args, None)
    empty = capture(source)
    corners = parse_corners(args.corners) if args.corners else detect_corners(empty[0].color, args.a1)
    print("corners (a1, h1, h8, a8):", np.round(corners, 1).tolist())

    wait(args, "Step 2 of 2: set up the normal starting position, with White on the a1 side.")
    set_scene(source, args, chess.Board())
    start = capture(source)
    calib, report = calibrate(empty, start, corners, use_depth=not args.no_depth)
    calib.save(args.calibration)

    print(f"saved {args.calibration}")
    for key, value in report.items():
        print(f"  {key}: {value:.3f}" if isinstance(value, float) else f"  {key}: {value}")
    if report["lowest_piece_score"] < 2 * report["highest_empty_score"]:
        print("  WARNING: pieces and empty squares score too close, so expect misreads.")
        print("  Check the lighting and camera angle, then calibrate again.")


def cmd_check(args) -> None:
    source = open_source(args)
    board = chess.Board(args.fen) if args.fen else None
    set_scene(source, args, board or chess.Board())
    frame = source.read()
    calib = Calibration.load(args.calibration)
    seen = classify(frame, calib)
    print(board_text(seen))
    cv2.imwrite(args.out, draw_debug(frame, calib, seen))
    print(f"saved {args.out}: green dots are read as white, red dots as black")
    if board:
        expected = occupancy(board)
        wrong = sorted(sq for sq in chess.SQUARE_NAMES if seen.get(sq) != expected.get(sq))
        print("all 64 squares correct" if not wrong else f"wrong squares: {wrong}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, func, out=None):
        command = sub.add_parser(name)
        command.set_defaults(func=func)
        command.add_argument("--serial", help="which RealSense, from the list command")
        command.add_argument("--no-depth", action="store_true", help="use color only")
        command.add_argument("--synthetic", action="store_true", help="use the simulated camera")
        command.add_argument("--calibration", default="calibration.npz")
        if out:
            command.add_argument("--out", default=out)
        return command

    add("list", cmd_list)
    add("snapshot", cmd_snapshot, "snapshot.png")
    calibrate_parser = add("calibrate", cmd_calibrate)
    calibrate_parser.add_argument("--a1", default="bottom-left", help="where a1 appears in the image, e.g. top-right")
    calibrate_parser.add_argument("--corners", help="by hand, from a snapshot: 'x,y;x,y;x,y;x,y' for a1;h1;h8;a8")
    calibrate_parser.add_argument("--yes", action="store_true", help="don't wait for Enter")
    check_parser = add("check", cmd_check, "check.png")
    check_parser.add_argument("--fen", help="compare against this position")

    args = parser.parse_args()
    try:
        args.func(args)
    except CalibrationError as err:
        raise SystemExit(f"calibration failed: {err}")


if __name__ == "__main__":
    main()
