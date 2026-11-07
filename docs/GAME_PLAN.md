# Game plan

**Goal:** the robot plays a short mate-in-2 or mate-in-3 from a sparse position, and recovers
on camera from at least one failed grab. A sparse board gives the gripper room, and a short
game fits the time: one benchmark suggests each move could take several minutes.

## The agents

Only How uses a learned model. Chess and safety decisions stay in plain code, which is faster,
testable, and can't hallucinate an illegal move.

| Agent | Decides | Tool | Status |
| --- | --- | --- | --- |
| What | Which piece to move | Stockfish scores every legal move, with a penalty for crowded pieces | Built |
| Where | Which square, and the physical steps | Stockfish, chess rules, and a prompt template | Built |
| How | How the arms move | Dream-1 through DreamAPI | Written, not run on hardware |
| Check | Whether the move happened | RealSense depth and color | Written, not run on hardware |
| Orchestrator | What happens next | A plain Python loop | Built |

An LLM is optional and comes last. The best places for one are commentary for the demo and
choosing how to recover from unusual failures.

## Who does what

Assign names at the first team check-in.

| Person | Owns | First task | Done when |
| --- | --- | --- | --- |
| A: Station and How | `dream_mover.py`, the `Station` adapter, API key and credits | Run `tools/inspect_station.sh` | One real pick-and-place runs through `DreamMover` |
| B: Check | `vision.py`, `camera.py`, calibration | Find the top camera and save a snapshot | `vision_tool.py check` reads all 64 squares on the real board |
| C: What, Where, and integration | `what.py`, `where.py`, `orchestrator.py`, `run_robot.py` | Install Stockfish and run a game with it | The full loop runs with a terminal-driven opponent |
| D: Physical setup, prompts, and demo | Board, pieces, prompt log, video, pitch | Tape down the board and measure the gripper against the piece gaps | A rehearsed demo and a backup video exist |

Everyone can stop the arms. Whoever runs a motion test stands at the e-stop.

## Test order

Each stage has to pass before the next, and nothing moves until stage 5.

| Stage | Test | Arms move? | Who runs it | Pass means |
| --- | --- | --- | --- | --- |
| 1 | Run `tools/inspect_station.sh` | No | Anyone | We know the Python version, cameras, and what holds them |
| 2 | Install, then run `pytest` on the NUC | No | A | All tests pass on the station |
| 3 | Calibrate and check the top camera | No | B | All 64 squares read correctly |
| 4 | `DreamMover` with `dry_run=True`, with `dream.DebugView` open | No | A | The page shows the right cameras, state, and prompt |
| 5 | `python -m dream.check_loop` | **Yes** | **A person at the e-stop** | Every line prints PASS |
| 6 | One piece on an empty board, trying prompt wordings | **Yes** | A and D | Dream-1 reaches the right square |
| 7 | A pawn with neighbors on both sides | **Yes** | A and D | We know how crowded the demo can be |
| 8 | Full loop on the demo position | **Yes** | Everyone | The game finishes with the board correct |
| 9 | Record a backup video | **Yes** | D | Saved somewhere safe |

To view the debug page over SSH, forward its port: `ssh -L <port>:localhost:<port> user@nuc`.

## Reading the first results

- **If Dream-1 doesn't understand square names:** try "the pawn nearest your left hand", or put
  large labels on the demo squares. This is the biggest open question, so test it early.
- **If a crowded pawn keeps failing:** build the demo so no piece has close neighbors.
- **If depth is too noisy for pawns:** use `--no-depth`, and mount or angle the camera to look
  as straight down as possible.

## Still to write

- `Station`, the small adapter for the NUC's arms and cameras, once stage 1 shows how they work.
- `run_robot.py`, which connects the real pieces, a terminal prompt for human help, and an
  "opponent has moved" prompt.
- A safe `home()`: lift straight up, then clear the camera, and never carry off a gripped piece.
- Try the `region` setting to keep the arms above the table, and check that it applies with
  `head: "joint"`.

## Repo rules

- Keep `main` working. Use a short branch per task, and merge once tests pass.
- Don't commit keys, `calibration.npz`, or camera images. `.gitignore` covers the usual ones.
