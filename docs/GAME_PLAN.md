# Game plan

**Goal:** the robot, playing Brown, finishes a short mate-in-2 or mate-in-3 against a person, and
recovers from at least one failed move along the way. A short game fits the time: with retries,
each robot move could take a few minutes.

See the [README](../README.md) for how the system works.

## Who does what

Assign names at the next team check-in.

| Person | Owns | Next task | Done when |
| --- | --- | --- | --- |
| A: Station and How | `station_mover.py`, station access, API key and credits | Get approval to add the camera plug-in to the station | The station shares its top camera with our app |
| B: Check | `vision.py`, `camera.py`, calibration | Calibrate the top camera once the station shares it | `vision_tool.py check` reads all 64 squares on the real board |
| C: What, Where, and integration | `what.py`, `where.py`, `orchestrator.py`, `run_robot.py` | Get Stockfish installed on the NUC, then choose the demo position | A full game finishes with `run_robot.py` |
| D: Physical setup, eval, and demo | Board, trays, the eval, video, pitch | Set up the board and run the baseline eval with Xiangwen | Baseline results are committed, and a backup video exists |
| Xiangwen: Dream-1 | The eval runs and fine-tuning | Run the baseline eval, then plan data collection from its report | A fine-tune beats the baseline, or we know it doesn't |

Everyone can stop the arms. Whoever runs a test that moves the arms keeps a hand on the e-stop.

## Test order

Each stage has to pass before the next.

| Stage | Test | Arms move? | Pass means | Status |
| --- | --- | --- | --- | --- |
| 1 | Survey the NUC with `tools/inspect_station.sh` | No | We know what runs the arms and cameras | ✅ Done |
| 2 | Install our app on the NUC and run the tests | No | Tests pass there | ✅ Done |
| 3 | Dream-1 baseline eval: `eval_dream.py` | **Yes** | 28 trials scored, with notes on every failure | ▶️ Next |
| 4 | First real game with a person as the camera: `run_robot.py` on a short mate | **Yes** | The game finishes, and the log shows where time went | After stage 3 |
| 5 | Camera check on the real board | No | All 64 squares read correctly | Needs station approval |
| 6 | Full games with the camera, on the demo position | **Yes** | The demo game finishes correctly 3 times | After stages 4 and 5 |
| 7 | Record a backup video | **Yes** | Saved somewhere safe | As soon as one game works |

If Xiangwen fine-tunes a model, re-run stage 3 with it before using it in stage 6.

## Reading the first results

- **Dream-1 often goes to the wrong square:** fine-tune on demos spread across many squares, using
  our exact sentences.
- **One arm or one area keeps failing:** focus the demos there, and choose a demo position that
  avoids it.
- **Crowded pieces keep getting knocked over:** pick a demo position with space around the pieces.
- **Many attempts time out:** raise the limit with `--seconds 45`.

## Still to do

- Install Stockfish on the NUC (`sudo apt install stockfish` needs the admin password).
- Add the camera plug-in to the station's configuration, once approved, then calibrate.
- A piece tracker, so fix prompts and help requests name the piece ("the brown knight"), not
  just its color.

## Repo rules

- Keep `main` working. Use a short branch per task, and merge once tests pass.
- Don't commit keys, `calibration.npz`, or camera images. `.gitignore` covers the usual ones.
