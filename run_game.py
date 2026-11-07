"""Play a full game against the mock robot. No hardware or API key needed.

    python run_game.py
    python run_game.py --color black --seed 7
    python run_game.py --p-success 1.0
    python run_game.py --fen "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"
"""
from __future__ import annotations

import argparse

import chess

from dreamchess.core import occupancy
from dreamchess.engine import make_engine
from dreamchess.mock import MockDream, MockHuman, MockPerception, RandomOpponent, SimWorld
from dreamchess.orchestrator import Orchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--color", choices=["white", "black"], default="white")
    parser.add_argument("--fen", default=chess.STARTING_FEN)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--p-success", type=float, default=0.4)
    parser.add_argument("--noise", type=float, default=0.05)
    parser.add_argument("--max-plies", type=int, default=80)
    parser.add_argument("--stockfish", help="path to a Stockfish binary (or set STOCKFISH_PATH)")
    args = parser.parse_args()

    board = chess.Board(args.fen)
    world = SimWorld(board)
    engine = make_engine(args.stockfish)
    agent = Orchestrator(
        board=board,
        robot_color=chess.WHITE if args.color == "white" else chess.BLACK,
        engine=engine,
        mover=MockDream(world, seed=args.seed, p_success=args.p_success),
        perception=MockPerception(world, seed=args.seed + 1, noise=args.noise),
        human=MockHuman(world),
        wait_for_opponent=RandomOpponent(world, seed=args.seed + 2),
    )

    print(f"engine: {engine.name}")
    try:
        result = agent.run(max_plies=args.max_plies)
    finally:
        engine.close()

    s = agent.stats
    print(f"\n{board}\n\nresult: {result}")
    print(f"robot moves: {s.moves}")
    print(f"Dream attempts: {s.dream_attempts} ({s.dream_attempts / max(s.moves, 1):.1f} per move)")
    print(f"corrections: {s.corrections}, human interventions: {s.human_calls}")
    print(f"table matches board: {world.occ == occupancy(board)}")


if __name__ == "__main__":
    main()
