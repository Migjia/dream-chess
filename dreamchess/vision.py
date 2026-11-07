"""The top-camera check: turn a camera frame into {square: "w" or "b"}.

Calibration has two captures, and needs no hand-tuned thresholds:
  1. The empty board finds the board's position, automatically or from given corners.
  2. The starting position has known piece locations, so it teaches the occupancy
     threshold and piece colors from your actual pieces and lighting.

With depth, each pixel becomes a 3D point measured against the board plane. A tall piece
at an angle then counts over its own square rather than leaning onto its neighbor.
Without depth, this falls back to comparing colors against the empty board.

Nothing here opens a window, so it all works over SSH.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import chess
import cv2
import numpy as np

from .core import Occupancy, occupancy

WARP_SQUARE_PX = 100
MIN_PIECE_HEIGHT_M = 0.012  # lower than this is depth noise on the board surface
MAX_PIECE_HEIGHT_M = 0.16  # higher than this is an arm or a hand, not a chess piece
SQUARE_INNER_FRACTION = 0.8  # ignore the square's edges, where neighbors can spill over
MIN_COLOR_DISTANCE = 15.0  # below this, white and black pieces look too alike
ORDER_ERROR = "corners are out of order: give a1, h1, h8, a8, going around the board"


class CalibrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Intrinsics:
    fx: float
    fy: float
    cx: float
    cy: float


@dataclass(frozen=True)
class Frame:
    color: np.ndarray  # H x W x 3, BGR, uint8
    depth: np.ndarray | None = None  # H x W, float32 meters aligned to color; 0 means no reading
    intrinsics: Intrinsics | None = None


class FrameSource(Protocol):
    def read(self) -> Frame: ...


@dataclass
class Calibration:
    corners: np.ndarray  # a1, h1, h8, a8 in image pixels
    homography: np.ndarray
    empty_warp: np.ndarray  # Lab image of the empty board, top-down
    threshold: float
    white_lab: np.ndarray
    black_lab: np.ndarray
    # Depth mode only; all None when calibrated from color alone.
    board_origin: np.ndarray | None = None
    board_axes: np.ndarray | None = None  # columns: toward h1, toward a8, up from the board
    square_size: np.ndarray | None = None  # meters along each axis
    reference_counts: np.ndarray | None = None  # pixels each empty square covers

    @property
    def use_depth(self) -> bool:
        return self.board_origin is not None

    def save(self, path: str | Path) -> None:
        fields = {k: v for k, v in vars(self).items() if v is not None}
        with open(path, "wb") as f:
            np.savez_compressed(f, **fields)

    @classmethod
    def load(cls, path: str | Path) -> "Calibration":
        with np.load(path, allow_pickle=False) as data:
            fields = {k: data[k] for k in data.files}
        fields["threshold"] = float(fields["threshold"])
        return cls(**fields)


def _to_lab(bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)


def _points_in_camera(depth: np.ndarray, k: Intrinsics) -> np.ndarray:
    v, u = np.indices(depth.shape, dtype=np.float32)
    return np.dstack(((u - k.cx) / k.fx * depth, (v - k.cy) / k.fy * depth, depth))


def _median_frame(frames: list[Frame]) -> Frame:
    color = np.median([f.color for f in frames], axis=0).astype(np.uint8)
    depth = None
    if frames[0].depth is not None:
        stack = np.array([f.depth for f in frames], dtype=np.float32)
        stack[stack <= 0] = np.nan
        all_invalid = np.isnan(stack).all(axis=0)
        stack[:, all_invalid] = 0
        depth = np.nanmedian(stack, axis=0).astype(np.float32)
    return Frame(color, depth, frames[0].intrinsics)


def _cross_2d(a: np.ndarray, b: np.ndarray) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def detect_corners(color: np.ndarray, a1: str = "bottom-left") -> np.ndarray:
    """Find an empty board's outer corners. `a1` says where a1 appears in the image.

    A printed chessboard has no way to mark its own rotation, so `a1` settles it, and the
    square colors confirm it: a1 must be a dark square.
    """
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    flags = cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY
    found, inner = cv2.findChessboardCornersSB(gray, (7, 7), flags=flags)
    if not found:
        raise CalibrationError(
            "couldn't find the board. Clear it completely, check that all 64 squares are in view, "
            "or pass the corners by hand with --corners"
        )
    grid = np.array([[c, r] for r in range(7) for c in range(7)], dtype=np.float32)
    to_image, _ = cv2.findHomography(grid, inner.reshape(-1, 2))
    outer = cv2.perspectiveTransform(
        np.array([[[-1, -1], [7, -1], [7, 7], [-1, 7]]], dtype=np.float32), to_image
    )[0]

    # Going a1, h1, h8, a8 runs counterclockwise on screen, where y points down.
    middle = outer.mean(axis=0)
    outer = outer[np.argsort(-np.arctan2(outer[:, 1] - middle[1], outer[:, 0] - middle[0]))]

    height, width = gray.shape
    targets = {
        "bottom-left": (0, height),
        "bottom-right": (width, height),
        "top-right": (width, 0),
        "top-left": (0, 0),
    }
    if a1 not in targets:
        raise CalibrationError(f"a1 must be one of {sorted(targets)}")
    start = int(np.argmin(np.linalg.norm(outer - np.array(targets[a1]), axis=1)))
    corners = np.roll(outer, -start, axis=0).astype(np.float32)

    size = WARP_SQUARE_PX * 8
    target = np.array([[0, size], [size, size], [size, 0], [0, 0]], dtype=np.float32)
    warp = cv2.warpPerspective(gray, cv2.getPerspectiveTransform(corners, target), (size, size))
    q = WARP_SQUARE_PX // 4
    a1_patch = warp[size - 3 * q : size - q, q : 3 * q]
    h1_patch = warp[size - 3 * q : size - q, size - 3 * q : size - q]
    if a1_patch.mean() >= h1_patch.mean():
        raise CalibrationError(
            f"a1 isn't a dark square with a1={a1}. Pick the corner where the dark square is on "
            "White's left, or check that the board isn't rotated 90 degrees"
        )
    return corners


def _fit_board_plane(frame: Frame, corners: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Least-squares plane through the board, dropping outliers. Returns (point, unit normal)."""
    mask = np.zeros(frame.depth.shape, np.uint8)
    cv2.fillConvexPoly(mask, corners.astype(np.int32), 1)
    points = _points_in_camera(frame.depth, frame.intrinsics)[(mask == 1) & (frame.depth > 0)]
    if len(points) < 100:
        raise CalibrationError("not enough depth readings on the board; is it in the camera's depth range?")
    for _ in range(4):
        center = points.mean(axis=0)
        normal = np.linalg.svd(points - center, full_matrices=False)[2][2]
        distance = np.abs((points - center) @ normal)
        points = points[distance < max(0.004, 2.5 * np.median(distance))]
    return center, normal if normal @ -center > 0 else -normal  # normal faces the camera


def _board_pose(frame: Frame, corners: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    plane_point, normal = _fit_board_plane(frame, corners)
    k = frame.intrinsics
    rays = np.column_stack(((corners[:, 0] - k.cx) / k.fx, (corners[:, 1] - k.cy) / k.fy, np.ones(4)))
    a1, h1, _, a8 = rays * ((plane_point @ normal) / (rays @ normal))[:, None]

    x_axis = (h1 - a1) / np.linalg.norm(h1 - a1)
    y_axis = np.cross(normal, x_axis)
    if (a8 - a1) @ y_axis <= 0:
        raise CalibrationError(ORDER_ERROR)
    size = np.array([np.linalg.norm(h1 - a1) / 8, ((a8 - a1) @ y_axis) / 8])
    return a1, np.column_stack((x_axis, y_axis, normal)), size


def _board_coords(frame: Frame, origin: np.ndarray, axes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (H x W x 3 of [x, y, height] in board meters, mask of valid depth)."""
    depth = cv2.medianBlur(frame.depth.astype(np.float32), 5)  # removes stray edge pixels
    return (_points_in_camera(depth, frame.intrinsics) - origin) @ axes, depth > 0


def _inner_square_index(coords: np.ndarray, size: np.ndarray) -> np.ndarray:
    """Square index (0 to 63) for each pixel, or -1 if off the board or near an edge."""
    fx, fy = coords[..., 0] / size[0], coords[..., 1] / size[1]
    margin = (1 - SQUARE_INNER_FRACTION) / 2
    inner = (
        (fx >= 0) & (fx < 8) & (fy >= 0) & (fy < 8)
        & (fx % 1 >= margin) & (fx % 1 <= 1 - margin)
        & (fy % 1 >= margin) & (fy % 1 <= 1 - margin)
    )
    index = np.full(fx.shape, -1, dtype=np.int32)
    index[inner] = fy[inner].astype(np.int32) * 8 + fx[inner].astype(np.int32)
    return index


def _measure_depth(frame: Frame, c: Calibration) -> tuple[np.ndarray, np.ndarray]:
    """Per square: share of the square covered by raised points, and those points' mean Lab."""
    coords, valid = _board_coords(frame, c.board_origin, c.board_axes)
    index = _inner_square_index(coords, c.square_size)
    height = coords[..., 2]
    raised = valid & (index >= 0) & (height > MIN_PIECE_HEIGHT_M) & (height < MAX_PIECE_HEIGHT_M)

    squares = index[raised]
    counts = np.bincount(squares, minlength=64).astype(np.float64)
    lab_points = _to_lab(frame.color)[raised]
    lab = np.column_stack([np.bincount(squares, lab_points[:, i], 64) for i in range(3)])
    lab = lab / np.maximum(counts, 1)[:, None]
    return counts / np.maximum(c.reference_counts, 1), lab


def _measure_color(frame: Frame, c: Calibration) -> tuple[np.ndarray, np.ndarray]:
    """Per square: how much the middle changed since the empty board, and the changed color."""
    size = WARP_SQUARE_PX * 8
    lab = _to_lab(cv2.warpPerspective(frame.color, c.homography, (size, size)))
    scores, colors = np.zeros(64), np.zeros((64, 3))
    q = WARP_SQUARE_PX // 4
    for sq in chess.SQUARES:
        x = chess.square_file(sq) * WARP_SQUARE_PX
        y = (7 - chess.square_rank(sq)) * WARP_SQUARE_PX
        roi = lab[y + q : y + 3 * q, x + q : x + 3 * q].reshape(-1, 3)
        reference = c.empty_warp[y + q : y + 3 * q, x + q : x + 3 * q].reshape(-1, 3)
        difference = np.linalg.norm((roi - reference) * [0.5, 1, 1], axis=1)
        scores[sq] = difference.mean()
        colors[sq] = roi[difference >= np.percentile(difference, 70)].mean(axis=0)
    return scores, colors


def measure(frame: Frame, c: Calibration) -> tuple[np.ndarray, np.ndarray]:
    return _measure_depth(frame, c) if c.use_depth else _measure_color(frame, c)


def classify(frame: Frame, c: Calibration) -> Occupancy:
    scores, labs = measure(frame, c)
    result: Occupancy = {}
    for sq in chess.SQUARES:
        if scores[sq] > c.threshold:
            is_white = np.linalg.norm(labs[sq] - c.white_lab) <= np.linalg.norm(labs[sq] - c.black_lab)
            result[chess.square_name(sq)] = "w" if is_white else "b"
    return result


def calibrate(
    empty_frames: list[Frame], start_frames: list[Frame], corners, use_depth: bool = True
) -> tuple[Calibration, dict]:
    """Build a calibration from captures of the empty board and the starting position."""
    corners = np.asarray(corners, dtype=np.float32)
    if corners.shape != (4, 2):
        raise CalibrationError("need exactly four corners: a1, h1, h8, a8")
    if cv2.contourArea(corners) < 100:
        raise CalibrationError("the corners don't enclose an area")
    # Listing the corners in the wrong direction mirrors the board, so check it here.
    if _cross_2d(corners[1] - corners[0], corners[3] - corners[0]) >= 0:
        raise CalibrationError(ORDER_ERROR)
    empty, start = _median_frame(empty_frames), _median_frame(start_frames)

    size = WARP_SQUARE_PX * 8
    target = np.array([[0, size], [size, size], [size, 0], [0, 0]], dtype=np.float32)
    homography = cv2.getPerspectiveTransform(corners, target)
    calib = Calibration(
        corners=corners,
        homography=homography,
        empty_warp=_to_lab(cv2.warpPerspective(empty.color, homography, (size, size))),
        threshold=0.0,
        white_lab=np.zeros(3),
        black_lab=np.zeros(3),
    )

    if use_depth and empty.depth is not None and empty.intrinsics is not None:
        calib.board_origin, calib.board_axes, calib.square_size = _board_pose(empty, corners)
        coords, valid = _board_coords(empty, calib.board_origin, calib.board_axes)
        index = _inner_square_index(coords, calib.square_size)
        calib.reference_counts = np.bincount(index[valid & (index >= 0)], minlength=64).astype(np.float64)
        if calib.reference_counts.min() < 10:
            raise CalibrationError("some squares have almost no depth readings; check the corners and depth range")

    # Learn the threshold and colors from the starting position, where every piece is known.
    board = chess.Board()
    occupied = [sq for sq in chess.SQUARES if board.piece_at(sq)]
    vacant = [sq for sq in chess.SQUARES if not board.piece_at(sq)]
    scores, labs = measure(start, calib)
    lowest_piece, highest_empty = scores[occupied].min(), scores[vacant].max()
    if lowest_piece <= highest_empty:
        weak = chess.square_name(occupied[int(np.argmin(scores[occupied]))])
        ghost = chess.square_name(vacant[int(np.argmax(scores[vacant]))])
        raise CalibrationError(
            f"can't separate pieces from empty squares: {weak} scored {lowest_piece:.3f} "
            f"but empty {ghost} scored {highest_empty:.3f}. Is the starting position set up with "
            "White on the a1 side? Does the camera see every square?"
        )
    calib.threshold = float((lowest_piece + highest_empty) / 2)
    calib.white_lab = labs[[sq for sq in occupied if board.color_at(sq) == chess.WHITE]].mean(axis=0)
    calib.black_lab = labs[[sq for sq in occupied if board.color_at(sq) == chess.BLACK]].mean(axis=0)

    color_distance = float(np.linalg.norm(calib.white_lab - calib.black_lab))
    if color_distance < MIN_COLOR_DISTANCE:
        raise CalibrationError(
            f"white and black pieces look too alike ({color_distance:.0f}, need {MIN_COLOR_DISTANCE:.0f}). "
            "Put colored dots on the piece tops and recalibrate."
        )

    seen = classify(start, calib)
    wrong = sorted(sq for sq in chess.SQUARE_NAMES if seen.get(sq) != occupancy(board).get(sq))
    if wrong:
        raise CalibrationError(f"couldn't read the starting position back; wrong squares: {wrong}")

    report = {
        "mode": "depth" if calib.use_depth else "color only",
        "lowest_piece_score": float(lowest_piece),
        "highest_empty_score": float(highest_empty),
        "threshold": calib.threshold,
        "color_distance": color_distance,
    }
    return calib, report


class CameraPerception:
    """The Perception the orchestrator uses on real hardware."""

    def __init__(self, source: FrameSource, calibration: Calibration):
        self.source = source
        self.calibration = calibration

    def observe(self) -> Occupancy:
        return classify(self.source.read(), self.calibration)


def draw_debug(frame: Frame, calib: Calibration, seen: Occupancy) -> np.ndarray:
    """Draw the board grid and what was read on each square, to compare by eye."""
    image = frame.color.copy()
    to_image = np.linalg.inv(calib.homography)

    def project(x: float, y: float) -> tuple[int, int]:
        p = to_image @ np.array([x, y, 1.0])
        return int(p[0] / p[2]), int(p[1] / p[2])

    for i in range(9):
        line = i * WARP_SQUARE_PX
        cv2.line(image, project(line, 0), project(line, 800), (0, 255, 255), 1)
        cv2.line(image, project(0, line), project(800, line), (0, 255, 255), 1)
    for name, code in seen.items():
        sq = chess.parse_square(name)
        x = (chess.square_file(sq) + 0.5) * WARP_SQUARE_PX
        y = (7.5 - chess.square_rank(sq)) * WARP_SQUARE_PX
        ink = (0, 200, 0) if code == "w" else (0, 0, 255)
        cv2.circle(image, project(x, y), 7, ink, -1)
    return image
