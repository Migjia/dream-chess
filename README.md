# Dream Chess

YAM bimanual arms play chess using DreamAPI. Dream-1 misses too often to trust blindly, so a
top camera checks every move and the app retries until the board is right.

- [docs/MISSION.md](docs/MISSION.md): the mission, decisions, where it runs, and how we'll know it works.
- [docs/GAME_PLAN.md](docs/GAME_PLAN.md): who does what and the order to test in.

## Run it without a robot

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

pytest                               # takes about 3 minutes
python run_game.py                   # full game on the mock robot
python run_game.py --fen "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"
python vision_tool.py calibrate --synthetic --yes
python vision_tool.py check --synthetic
```

Games use a weak built-in engine unless you install Stockfish and pass `--stockfish <path>`
or set `STOCKFISH_PATH`.

## How it fits together

| Part | File | Job |
| --- | --- | --- |
| What | `dreamchess/what.py` | Scores every legal move and picks the piece |
| Where | `dreamchess/where.py` | Picks the square, splits the move into steps, and writes the prompts |
| How | `dreamchess/dream_mover.py` | Plays Dream-1's actions on the arms |
| Check | `dreamchess/vision.py` | Reads the board from the top camera |
| Orchestrator | `dreamchess/orchestrator.py` | Runs the loop, retries, and asks a person for help |
| Simulation | `dreamchess/mock.py`, `dreamchess/synth.py` | A failing robot and a simulated camera |

## Status

Tested in simulation only. `dream_mover.py` has only run against a fake client, the camera code
has only seen simulated images, and the Stockfish path has never run.

## Safety

- A person stays at the e-stop whenever the arms can move.
- A person, not a coding agent, runs `python -m dream.check_loop`, `python -m dream.input_check`,
  and `dreamcli tcp`. The Dream docs require this.
- Start new code with `dry_run=True`, which calls the model but never moves the arms.
- Never commit API keys. They belong in `~/.dreamlabs/credentials` on the station.
