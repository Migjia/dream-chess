import chess

from dreamchess.engine import FallbackEngine
from dreamchess.mock import MockDream, MockHuman, MockPerception, SimWorld
from dreamchess.orchestrator import Config, Orchestrator
from dreamchess.scripts import load_games


def test_the_three_collection_games_parse_and_play_legally():
    games = load_games()
    assert {n: len(moves) for n, moves in games.items()} == {1: 20, 2: 13, 3: 8}
    for moves in games.values():
        board = chess.Board()
        for white, brown in moves:
            board.push_san(white)
            board.push_san(brown)
    assert games[1][:2] == [("e4", "Nf6"), ("Nf3", "Nxe4")]


class ScriptedWhite:
    """Plays White's moves from the script, like the person following the page's hints."""

    def __init__(self, world, moves):
        self.world, self.moves, self.played = world, list(moves), 0

    def __call__(self, board):
        board.push_san(self.moves[self.played])
        self.world.occ = {chess.square_name(s): ("w" if p.color else "b") for s, p in board.piece_map().items()}
        board.pop()
        self.played += 1


def play(white_moves, forced):
    board = chess.Board()
    world = SimWorld(board)
    lines = []
    agent = Orchestrator(board, chess.BLACK, FallbackEngine(depth=1), MockDream(world, p_success=1.0),
                         MockPerception(world), MockHuman(world), ScriptedWhite(world, white_moves),
                         config=Config(forced_moves=tuple(forced)), log=lines.append)
    agent.run(max_plies=2 * len(white_moves))
    return board, lines


def test_the_robot_plays_the_scripts_moves_with_the_trained_prompts():
    game = load_games()[1][:4]
    board, lines = play([w for w, _ in game], [b for _, b in game])
    assert [m.uci() for m in board.move_stack][:2] == ["e2e4", "g8f6"]
    assert any("WHERE Nf6 (from the script)" in line for line in lines)
    assert any("pick up the brown knight on square g8 and place it upright in the center of square f6" in line
               for line in lines)


def test_leaving_the_script_hands_the_choice_back_to_stockfish():
    # White plays d4 instead of the script's e4, so the script's Nxe4 later can't happen.
    board, lines = play(["d4", "Nf3"], ["Nf6", "Nxe4"])
    assert any("left the script" in line for line in lines)
    assert len(board.move_stack) == 4
