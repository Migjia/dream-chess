"""A webcam over the board, owned by the app, that reads the person's move once they say they've made it.

The station holds its three cameras the whole time it runs, so this is a camera of our own: any USB webcam that can
see all 64 squares. It's calibrated once from the page (the empty board, then the starting position) with the same
vision code the simulation uses, and the calibration is saved, so it survives a restart as long as the camera and
board don't move.

When the person presses "I've made my move", the app takes a few frames, reads which squares hold a white piece, a
brown piece, or nothing, and finds the one legal move that explains the change (`infer_opponent_move`). The camera
only tells colors apart; chess rules supply the rest. If no legal move explains it, it says what looks wrong, in
words a person can act on (and, later, that a voice can say): "Your pawn moved from g2 to g4, which isn't a legal
move. Please move it back from g4 to g2."
"""
from __future__ import annotations

import threading
import time
from collections import Counter
from pathlib import Path

import chess
import cv2

from .core import Occupancy, color_word, occupancy
from .orchestrator import compare, infer_opponent_move
from .vision import Calibration, CalibrationError, Frame, FrameSource, calibrate, classify, detect_corners, draw_debug

FRAMES_PER_READ = 5  # a person's hand or a flicker in one frame shouldn't decide a move
A1_CORNERS = ("bottom-left", "bottom-right", "top-right", "top-left")


class WebcamSource:
    """A USB webcam through OpenCV: `/dev/video4`, or an index like `0`."""

    def __init__(self, device: str, width: int = 1280, height: int = 720):
        target = int(device) if str(device).isdigit() else str(device)
        backend = cv2.CAP_V4L2 if isinstance(target, str) and target.startswith("/dev/") else cv2.CAP_ANY
        self.capture = cv2.VideoCapture(target, backend)
        if not self.capture.isOpened():
            raise CalibrationError(f"can't open the webcam {device}: is it plugged in, and is no other program using it?")
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        for _ in range(10):  # let auto exposure settle
            self.capture.read()

    def read(self) -> Frame:
        self.capture.grab()  # drop the frame queued from before, so this one is from now
        ok, image = self.capture.read()
        if not ok or image is None:
            raise CalibrationError("the webcam stopped sending frames")
        return Frame(color=image)

    def close(self) -> None:
        self.capture.release()


def _jpeg(image) -> bytes:
    ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return data.tobytes() if ok else b""


class BoardCamera:
    """The webcam, its calibration, and reading the board from it. Safe to call from any thread."""

    def __init__(self, open_source, calibration_path: str | Path):
        self._open_source = open_source  # opened on first use, so a missing webcam doesn't stop the app starting
        self.source: FrameSource | None = None
        self.path = Path(calibration_path).expanduser()
        self.lock = threading.RLock()
        self.calibration: Calibration | None = None
        self.empty: list[Frame] | None = None
        self.corners = None
        self.error = ""
        self.report: dict = {}
        if self.path.exists():
            try:
                self.calibration = Calibration.load(self.path)
            except (OSError, ValueError, KeyError) as err:
                self.error = f"couldn't load the saved calibration ({err}); calibrate again"

    def _frame(self) -> Frame:
        if self.source is None:
            self.source = self._open_source()
        return self.source.read()

    def _frames(self, count: int) -> list[Frame]:
        frames = []
        for _ in range(count):
            frames.append(self._frame())
            time.sleep(0.05)
        return frames

    def status(self) -> dict:
        with self.lock:
            step = "done" if self.calibration is not None else ("start" if self.empty is not None else "empty")
            return {"calibrated": self.calibration is not None, "step": step, "error": self.error, "report": self.report}

    def snapshot(self, grid: bool) -> bytes:
        """One frame as a JPEG, with the grid and what it reads drawn on it once calibrated."""
        with self.lock:
            frame = self._frame()
            if grid and self.calibration is not None:
                return _jpeg(draw_debug(frame, self.calibration, classify(frame, self.calibration)))
            return _jpeg(frame.color)

    # -- calibration: the empty board, then the starting position --------------------------------------------
    def capture_empty(self, a1: str = "bottom-left") -> dict:
        """Find the board on the empty board. `a1` is the image corner nearest a1."""
        with self.lock:
            if a1 not in A1_CORNERS:
                raise CalibrationError(f"a1 must be one of {', '.join(A1_CORNERS)}")
            frames = self._frames(3)
            self.corners = detect_corners(frames[-1].color, a1=a1)  # raises with a reason the page shows
            self.empty, self.calibration, self.error = frames, None, ""
            return self.status()

    def capture_start(self) -> dict:
        """Learn each piece color and what "occupied" looks like, from the standard starting position."""
        with self.lock:
            if self.empty is None:
                raise CalibrationError("capture the empty board first")
            calibration, report = calibrate(self.empty, self._frames(3), self.corners, use_depth=False)
            self.calibration, self.report, self.error = calibration, report, ""
            self.path.parent.mkdir(parents=True, exist_ok=True)
            calibration.save(self.path)
            return self.status()

    def reset(self) -> dict:
        with self.lock:
            self.calibration, self.empty, self.corners, self.report = None, None, None, {}
            return self.status()

    # -- reading the board ------------------------------------------------------------------------------------
    def read(self) -> Occupancy:
        """What stands on each square: a vote over a few frames."""
        with self.lock:
            if self.calibration is None:
                raise CalibrationError("the webcam isn't calibrated yet")
            votes: dict[str, Counter] = {}
            for frame in self._frames(FRAMES_PER_READ):
                seen = classify(frame, self.calibration)
                for square in chess.SQUARE_NAMES:
                    votes.setdefault(square, Counter())[seen.get(square)] += 1
            return {sq: value for sq, counter in votes.items() if (value := counter.most_common(1)[0][0])}


def _piece(board: chess.Board, square: str) -> str:
    piece = board.piece_at(chess.parse_square(square))
    return chess.piece_name(piece.piece_type) if piece else "piece"


def read_move(board: chess.Board, seen: Occupancy) -> dict:
    """The person's move, from what the camera sees after it: {"move", "san"}, or {"problem", "fix"} in plain words.

    `board` is the game before the move. Every message is a whole sentence, so a voice can say it as it is."""
    before = occupancy(board)
    if seen == before:
        return {"problem": "The camera doesn't see any change on the board yet.",
                "fix": "Make your move on the board, then press the button again."}
    work = board.copy()
    move = infer_opponent_move(work, seen)
    if move is not None:
        return {"move": move.uci(), "san": board.san(move)}

    missing, extra = compare(before, seen)
    mover = "w" if board.turn == chess.WHITE else "b"
    # The other side's pieces first: they shouldn't have moved at all, and a bumped one can make a good move look bad.
    others = []
    for sq, c in sorted(missing.items()):
        if c != mover and seen.get(sq) != c:
            others.append(f"the {color_word(c)} {_piece(board, sq)} on {sq} is missing")
    for sq, c in sorted(extra.items()):
        if c != mover and before.get(sq) is None:
            others.append(f"there's a {color_word(c)} piece on {sq} that shouldn't be there")
    if others:
        # Would the person's own part be a legal move, if the robot's pieces were back?
        own = {sq: c for sq, c in seen.items() if c == mover}
        own.update({sq: c for sq, c in before.items() if c != mover and seen.get(sq) != mover})
        guess = infer_opponent_move(board.copy(), own)
        lead = f"Your move, {board.san(guess)}, looks right, but the robot's pieces have moved: " if guess             else "The robot's pieces have moved: "
        return {"problem": lead + "; ".join(others) + ".",
                "fix": "Please put them back where the board on the page shows them, then press the button again.",
                "missing": missing, "extra": extra}
    gone = [sq for sq, c in missing.items() if c == mover and seen.get(sq) is None]
    landed = [sq for sq, c in extra.items() if c == mover]
    if len(gone) == 1 and len(landed) == 1:
        start, end = gone[0], landed[0]
        name = _piece(board, start)
        return {"problem": f"Your {name} moved from {start} to {end}, which isn't a legal move.",
                "fix": f"Please move your {name} back from {end} to {start}, then make a legal move.",
                "missing": missing, "extra": extra}
    squares = ", ".join(sorted(set(missing) | set(extra)))
    return {"problem": f"The camera can't match what it sees to a legal move. The squares that changed: {squares}.",
            "fix": "Please check those squares against the board on the page, or type your move instead.",
            "missing": missing, "extra": extra}
