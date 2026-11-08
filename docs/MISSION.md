# Mission and decisions

**Mission:** a robot that plays chess delicately, confidently, and accurately, using Dream-1 for
motion and an agent that catches and fixes its mistakes.

**The demo:** YAM arms playing Brown finish a short mate-in-2 or mate-in-3 against a person, and
recover from at least one failed move along the way.

The [README](../README.md) explains how the system works. This page records why it's built this
way, and how we'll know it works.

## Decisions and why

| Decision | Why | Revisit if |
| --- | --- | --- |
| **The app is the brain; Dream-1 is the hands** | Dream-1 doesn't know chess, can't see the board as a grid, and never reports success | Never: it follows from what Dream-1 is |
| **Always play Stockfish's move** | The robot should play like a strong bot. The rest of the app exists to carry the move out | Never for the demo. A margin setting can trade strength for easier moves, but it's off |
| **Stockfish for chess decisions** | It's free, strong, runs on a normal computer, and needs no training | The NUC can't run it |
| **No LLM in the decisions** | Plain code is fast, testable, and can't invent an illegal move | Optional later, for commentary |
| **The robot plays Brown** | Our board's dark pieces are brown, and that word matches what the camera sees | The board changes |
| **Square names are how we point** | Describing moves by direction, or marking squares, isn't practical here | The eval shows Dream-1 can't find named squares even after fine-tuning |
| **One pick-and-place per instruction** | Dream-1 starts fresh each time, and short tasks are what it does best | Never |
| **Check every step, and fix or retry** | Dream Labs reports about 40% full success on pick-and-place, so misses are normal | Never: this is the core of the project |
| **Record a move only after it's confirmed** | The app can never believe a move happened when it didn't | Never |
| **Send steps through the station's API** | The station already runs Dream-1 with safety limits, and drives the arms and cameras | The station is unavailable; the direct connection is a fallback |
| **A person stands in for the camera, for now** | The station keeps the top camera to itself | Approval to add a camera plug-in to the station |
| **Ask a person when stuck** | A short rescue beats a robot making things worse | Never for lost pieces or a badly disturbed board |
| **Demo a short mate** | Each robot move could take minutes with retries | Testing shows full games are practical |

## How we'll know it's working

Passing tests only prove the logic. Each row needs real evidence, from the robot itself:

| Question | Evidence | Status |
| --- | --- | --- |
| Are the game and retry logic right? | Tests pass | ✅ Passing |
| Do What and Where work on real Stockfish? | `tests/test_stockfish.py` shows 10 passed, not skipped | ✅ Passed on GitHub; Stockfish not yet on the NUC |
| **Can Dream-1 follow our instructions?** | The baseline eval: 28 trials on the base model | ▶️ Ready to run: **the biggest unknown** |
| Which moves does it struggle with? | The eval report, by kind of move | ▶️ Comes with the baseline |
| Does a fine-tuned model do better? | The same eval, compared with the baseline | Waiting on the baseline |
| Does the whole game work? | `run_robot.py` game logs: finished, moves per hour, rescues | Not run on the real robot yet |
| Can the camera read the real board? | `vision_tool.py check` gets all 64 squares right | Waiting for station approval |

## How we'll know we're on the right path

Everything depends on one thing we haven't measured: whether Dream-1 can find the squares we name.
The baseline eval answers that.

- **Most trials succeed:** build on the base model, and go straight to full games.
- **Some kinds of move fail:** record fine-tuning demos of exactly those, in this scene, with our
  exact sentences, then re-run the eval.
- **Almost nothing succeeds:** fine-tuning is the main option. Meanwhile, shrink the demo to the
  moves that do work.

A robot that visibly notices its own mistake and fixes it is still a strong demo, because that
recovery is what this project adds to Dream-1.
