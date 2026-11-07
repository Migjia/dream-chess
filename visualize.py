"""Build the visual simulation from a real run of the agent code.

    python visualize.py

Writes docs/simulation.gif for the README, and docs/simulation.html, an interactive version
you can open in a browser.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from dreamchess.replay import DEMO_FEN, DEMO_SCRIPT, record_game

ROOT = Path(__file__).parent
SIZE = (960, 540)
SQUARE = 58
BOARD_LEFT, BOARD_TOP = 46, 34
PANEL_LEFT = BOARD_LEFT + SQUARE * 8 + 36
PANEL_WIDTH_CHARS = 44

GROUND, INK, QUIET, RULE = "#eef1ea", "#1c2a24", "#55655c", "#cdd6cc"
LIGHT, DARK = "#efe9d2", "#6f9a78"
ACCENT, BAD = "#1f6b4c", "#a83a26"
LOOP = [("what", "What"), ("where", "Where"), ("how", "How"), ("check", "Check"), ("update", "Update")]
TITLES = {
    "start": "Starting position", "what": "What: pick the piece", "where": "Where: pick the square",
    "how": "How: move the piece", "check": "Check: read the board", "update": "Update the board",
    "opponent": "Opponent moves", "person": "Ask a person", "end": "Game over",
}


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size)


def square_box(square: str) -> tuple[int, int, int, int]:
    x = BOARD_LEFT + "abcdefgh".index(square[0]) * SQUARE
    y = BOARD_TOP + (8 - int(square[1])) * SQUARE
    return x, y, x + SQUARE, y + SQUARE


def draw_board(draw: ImageDraw.ImageDraw, frame: dict) -> None:
    for file_index, file in enumerate("abcdefgh"):
        for rank in range(1, 9):
            draw.rectangle(square_box(f"{file}{rank}"), fill=DARK if (file_index + rank) % 2 == 1 else LIGHT)
        x = BOARD_LEFT + file_index * SQUARE + SQUARE / 2
        draw.text((x, BOARD_TOP + SQUARE * 8 + 13), file, fill=QUIET, font=font(15), anchor="mm")
    for rank in range(1, 9):
        y = BOARD_TOP + (8 - rank) * SQUARE + SQUARE / 2
        draw.text((BOARD_LEFT - 15, y), str(rank), fill=QUIET, font=font(15), anchor="mm")

    mark = BAD if frame["tone"] == "bad" else ACCENT
    for square in frame["highlight"]:
        x0, y0, x1, y1 = square_box(square)
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), outline=mark, width=5)

    for square, symbol in frame["pieces"].items():
        x0, y0, x1, y1 = square_box(square)
        inset = 9
        white = symbol.isupper()
        draw.ellipse(
            (x0 + inset, y0 + inset, x1 - inset, y1 - inset),
            fill="#fbf8ee" if white else "#23302a", outline="#23302a" if white else "#fbf8ee", width=2,
        )
        draw.text(
            ((x0 + x1) / 2, (y0 + y1) / 2), symbol.upper(),
            fill="#23302a" if white else "#fbf8ee", font=font(22), anchor="mm",
        )


def draw_panel(draw: ImageDraw.ImageDraw, frame: dict) -> None:
    x = PANEL_LEFT
    for stage, label in LOOP:
        width = draw.textlength(label, font=font(15)) + 18
        active = frame["stage"] == stage
        color = (BAD if frame["tone"] == "bad" else ACCENT) if active else None
        draw.rounded_rectangle((x, BOARD_TOP, x + width, BOARD_TOP + 28), 4, fill=color, outline=color or RULE)
        draw.text((x + width / 2, BOARD_TOP + 14), label, fill=GROUND if active else QUIET, font=font(15), anchor="mm")
        x += width + 6

    y = BOARD_TOP + 52
    draw.text((PANEL_LEFT, y), TITLES[frame["stage"]], fill=INK, font=font(24))
    y += 38
    text_color = {"bad": BAD, "good": ACCENT}.get(frame["tone"], INK)
    for line in textwrap.wrap(frame["text"], PANEL_WIDTH_CHARS):
        draw.text((PANEL_LEFT, y), line, fill=text_color, font=font(17))
        y += 24
    if frame["prompt"]:
        lines = textwrap.wrap(frame["prompt"], PANEL_WIDTH_CHARS + 4)
        y += 6
        draw.rectangle((PANEL_LEFT, y, SIZE[0] - 24, y + 22 * len(lines) + 18), fill="#fbfcf8", outline=RULE)
        y += 9
        for line in lines:
            draw.text((PANEL_LEFT + 11, y), line, fill=INK, font=font(15))
            y += 22

    counts = [("moves", "Moves"), ("attempts", "Attempts"), ("corrections", "Fixes"), ("rescues", "Rescues")]
    for index, (key, label) in enumerate(counts):
        cx = PANEL_LEFT + index * 106
        draw.text((cx, 438), str(frame[key]), fill=INK, font=font(28))
        draw.text((cx, 474), label, fill=QUIET, font=font(14))
    draw.text((PANEL_LEFT, 504), "Simulated robot, scripted failures, real agent code.", fill=QUIET, font=font(13))


def render_frame(frame: dict) -> Image.Image:
    image = Image.new("RGB", SIZE, GROUND)
    draw = ImageDraw.Draw(image)
    draw_board(draw, frame)
    draw_panel(draw, frame)
    return image


def write_gif(frames: list[dict], path: Path) -> None:
    images = [render_frame(frame).quantize(colors=64, dither=Image.Dither.NONE) for frame in frames]
    durations = [3400 if frame["prompt"] else 2200 for frame in frames]
    durations[-1] = 5000
    images[0].save(path, save_all=True, append_images=images[1:], duration=durations, loop=0, optimize=True)


def page_fragment(frames: list[dict]) -> str:
    """The page without a document wrapper. '</' is escaped so the data can't close the script."""
    template = (ROOT / "dreamchess" / "simulation_template.html").read_text(encoding="utf-8")
    return template.replace("/*FRAMES*/[]", json.dumps(frames).replace("</", "<\\/"))


def main() -> None:
    frames = record_game(DEMO_FEN, script=list(DEMO_SCRIPT))
    docs = ROOT / "docs"
    write_gif(frames, docs / "simulation.gif")
    head = '<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n'
    head += '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    (docs / "simulation.html").write_text(head + page_fragment(frames), encoding="utf-8")
    print(f"wrote {len(frames)} steps to docs/simulation.gif and docs/simulation.html")


if __name__ == "__main__":
    main()
