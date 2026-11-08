# Audit: the agentic system after the first live runs (Nov 8)

What the app does, what today's runs on the real arms showed, and what it will take for the robot to make the
right moves. Numbers come from the station's own logs (`~/.dreamlabs/station.log`, `~/robots-inference.jsonl`) and
from the joint states it saves during each run.

## How the app works

One loop per robot move. The **agent** (`dreamchess/orchestrator.py`) keeps the game and calls its tools in order:

| Step | Tool | What it does |
|---|---|---|
| Your move | You, on the page (later: the top camera) | The agent checks it's legal and records it |
| What | Stockfish (`what.py`) | Picks the piece, from a full search of the position |
| Where | Stockfish (`where.py`) | Picks the square, and splits the move into physical steps (a capture is two: the taken piece to the tray, then the move) |
| How | **Dream-1 via DreamAPI**, through the station (`station_mover.py`) | One plain sentence per step, worded exactly like our training demos, sent to the station, which runs Dream-1's control loop on the arms |
| Watch | **The supervisor** (`supervisor.py`, new) | During the run, follows the hand from its joint angles and re-prompts Dream-1 the moment it grips or lets go in the wrong place |
| Check | You, on the page (later: the top camera) | After the run: did the piece land? If not, the agent sends a fix and tries again (up to 6 times), then asks a person |

Around the loop: the model is started on DreamAPI when the app launches (`tools/warm_dream.py`), so the first move
doesn't wait out a cold start; time the arms spend held while DreamAPI is slow doesn't count against an attempt;
and the page shows each part as it works.

**Dream-1 knows nothing about chess.** It gets three camera views, the arms' joints, and one sentence, and streams
motion at 20 Hz. Everything chess-related, and every judgment about whether a move worked, is the agent's.

## What today's live runs showed

| Run | Model | Move asked | What happened |
|---|---|---|---|
| 1-2 | Xiangwen's fine-tune | Rb1# (b8 to b1) | Never moved: the model was still starting on DreamAPI, and our 30 s limit cut the runs off (fixed: #14) |
| 3 | Base | Rb1# | Moved 9 s, held 18 s while DreamAPI's gateway stalled, moved 23 s, then our limit stopped it (fixed: #17) |
| 4-5 | Base, from Dream's live view | Rb1# | Moved; took the wrong rook |
| 6 | Xiangwen's | Rb1# | Stopped at 80 s while still starting: the station reports the last run's action count while a new run starts (fixed: #18) |
| 7 | Xiangwen's | Rb1# | 82 s of motion, no stalls. **Closed the gripper on d3, an empty square** |
| 8 | Base | Rb1# | Picked up the right rook on b8, then set it down on several wrong squares (from Ahmed's notes) |
| 9-10 | Base | Rb1# | **Closed the gripper on e4, d4 and f3, all empty**, over and over |

Where the hand went comes from the joint states the station saves each second, through the arm model, and a board
calibration fitted to our game 2 demos (100% of their grasps and releases read back on the right square).

## Findings, most important first

1. **The test move was nothing like the training data.** Rb1# slides a rook 7 squares, the full length of the board,
   to the far rank. Our 57 demos are almost all 1-2 square moves (36 of 42 placements; the longest is 5), mostly
   knights, pawns, queens and bishops, near the robot; there is one rook demo, to the tray; and only 7 moves end on
   rank 1 or 2. Both models were asked for something they had never seen.
2. **Both models grab empty squares.** Neither went for a wrong piece: they closed on d3, e4, d4 and f3, where
   nothing stood. Tying square names to places on the board is the skill that's weakest, and it's exactly what
   fine-tuning on our data is for.
3. **No evidence yet that fine-tuning made things worse.** One out-of-distribution move, one to three tries per
   model, is too little to compare. Xiangwen's model was trained on 20 episodes of game 1 for 1,000 steps. Ours,
   `chess-1k` and `chess-2k`, use all 58 cleaned episodes from both games, and are still training. The fair
   comparison is the same in-distribution moves, several tries each (see below).
4. **Only a person checks the board.** The station holds all three cameras and shares frames only during runs, so
   nothing reads the board between moves. The supervisor now watches the hand during a move, but whether the board is
   right afterwards is still your answer on the page.
5. **The board has to stay where it was calibrated.** The hand tracker's square map (`~/.dream-chess/board_fit.json`)
   was fitted on game 2's demos. Today's top camera shows the board within about 1.5 cm of where it was then. If it
   moves, the map is wrong until it's fitted again on demos recorded in the new spot.
6. **Setup mistakes are invisible to the agent.** A rook placed on b2 instead of a2 put two rooks on the b-file. The
   page can now show the board from the robot's side, for setting up from there.
7. **The models ask the gripper to snap shut faster than allowed** (up to 170 clamped commands a run). The station
   limits it safely, but it's a sign the model is unsure.
8. **Pipeline bugs found and fixed today**: the model starting up mid-move (#14), DreamAPI stalls eating the
   attempt (#17), the last run's actions miscounted (#18), corrections saying "piece" instead of the piece (#15).

## How to get the robot to make the right moves

In order:

1. **Test on moves the model learned.** Replay a collection game (`app.py --script 2 --checkpoint ...`): the robot
   plays the game's brown moves, so every prompt is a trained one, from the position it was recorded in. Game 2
   matches the board calibration. Try each model on the same moves, three tries each, and count successes.
2. **Switch to `chess-1k` or `chess-2k` when they finish.** They're trained on all our cleaned data.
3. **Keep the supervisor on** (the default). It re-prompts mid-run on a missed grasp or a wrong drop, worded like
   the training demos, and ends the run once the piece lands.
4. **Favor easy moves in demos**, if a perfect engine move isn't required: `margin_cp` above 0 lets the agent trade a
   little strength for moves that are short and uncrowded. It's 0 now, by choice.
5. **Collect more of what fails**: longer moves, the far ranks, rooks, and squeezes over the right square. Even 10-20
   more demos aimed at these would help the most.
6. **Get the station's top camera shared between moves.** Then the check becomes automatic, and your moves are read
   from the board (the work is ready on the `board-camera-wip` branch).
