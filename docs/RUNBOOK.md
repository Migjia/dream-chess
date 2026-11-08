# Runbook: the robot and the app, at the station

From arriving at the station to a game on screen. Nothing here has been run on the real arms yet, so the
first real game is also the first test of the base model through our pipeline.

## 1. Connect and update

On your laptop (Git Bash), log in to the NUC with the app's page forwarded:

```bash
ssh -L 8800:127.0.0.1:8800 dream-nuc
```

Then, on the NUC:

```bash
cd ~/dream-chess
git pull
```

## 2. Check nothing else holds the arms

Only one program can drive the arms at a time. Stop `dhk-collect` if it's running (Ctrl+C in its
window). The Dream station must be **running and idle**, because the app sends each move through it:

```bash
curl -s http://127.0.0.1:8091/status | python3 -m json.tool | head -5
```

You want `"state": "idle"`. If nothing answers, the station isn't running. Ask whoever runs it to start it.

## 3. Rehearse first: nothing moves

```bash
.venv/bin/python app.py --sim
```

Open http://localhost:8800 on your laptop. You play White from the page, and a simulated robot plays
Brown. Press Ctrl+C on the NUC to stop it.

## 4. Play the real robot

Set up the board with brown nearest the robot (rank 8 closest, the h-file at the robot's left), a tray
spot beside each arm, and **a person with a hand on the e-stop**. Then:

```bash
.venv/bin/python app.py                                    # the base model (dreamlabs/dream-1-beta)
.venv/bin/python app.py --checkpoint "dream-1-ft:..."      # or a fine-tuned model
```

The station keeps whichever model it ran last, so the app always names the one it wants: with no
`--checkpoint`, that's the base model.

**A model nobody has run lately takes a while to start on DreamAPI, up to 15 minutes for a fine-tune.** The app
starts it as soon as it launches (`tools/warm_dream.py`, from a client of its own that never touches the arms), and
"The robot's brain" shows it warming up with a timer. Set up the board meanwhile. If the robot's move begins before
the model is ready, the arms wait without a time limit, and once Dream-1 answers the app starts the step again by
itself, so nobody has to say whether a piece landed when nothing moved.

The page asks for everything the terminal used to: confirm the board is set up, confirm the e-stop,
make your move (type it, or click a piece and then its square), and, after each robot step, whether
the piece landed. **Stop the arms** on the page, or Ctrl+C on the NUC, stops the arms at once.

"The robot's eyes" shows the frames the station hands Dream-1 (from `~/.dreamlabs/last-run_inputs`; change it
with `--frames`), and "The robot's brain" shows the station's status. If the brain says *Station offline*, the
station isn't running. The board itself still comes from your answers until the station shares its camera.

**To test what the model learned, replay a collection game** (`--script 1`, `2` or `3`). You play White's moves
from the script, which the page suggests and fills in. The robot plays that game's brown moves, so every prompt is
one Dream-1 was fine-tuned on, with the pieces where they were in its demos. Stockfish's own picks, like a mate in one
that slides a rook the length of the board, can be far from anything in the training data.

```bash
.venv/bin/python app.py --script 1 --checkpoint "dream-1-ft:..."   # game 1: 20 robot moves, starting 1.e4 Nf6
```

**The checker agent: a top-camera picture after every step.** Calibrate it once, from the page's "Calibrate the top
camera" card: clear the board and capture it (if the board isn't found by itself, click its four corners on the
picture: a1, h1, h8, a8), then set up the starting position and capture that. From then on, after each step Dream-1
runs, the checker takes a picture and reads the board. If the move didn't happen (say, *the brown queen went to b2
instead of c2*), the orchestrator sends Dream-1 the correction, and the checker looks again, until the board is right
or six tries have failed and a person is asked. Your moves are read the same way: make the move, then press **I've
made my move**.

A picture is a "hold still" run that the app stops as soon as the station saves its first frame, well before Dream-1's
first motion, so the arms stay at home. It takes about 4 s, and the picture stays in memory: the app writes nothing.
The calibration is saved to `~/.dream-chess/top-calibration.npz`; calibrate again if the camera or the board moves.
Without a calibration, a person checks each step, as before (`--no-top-camera` turns pictures off).

**The supervisor watches every move as it happens** (on by default; `--no-supervise` turns it off). It follows the
hand from the arms' joint angles, through the board calibration in `~/.dream-chess/board_fit.json`, and re-prompts
Dream-1 mid-run when it grips an empty square or the wrong piece, or lets go on the wrong square. Once the piece lands
on its target, it ends the run. The page shows the hand's square and grip live in the brain card. If the board moves,
fit it again on demos recorded in the new spot:

```bash
~/dream-env/bin/python tools/fit_board.py ~/hackathon_data/<dataset> ~/.dream-chess/board_fit.json
```

To set up from the robot's side, switch the page's board to **From the robot's side**, so each piece lands on the
right file. A rook on b2 instead of a2 puts two rooks on the b-file, and the model may reach for the wrong one.

## 5. Notes

- Stockfish isn't installed on the NUC, so the robot plays the weaker built-in engine until someone
  with the admin password runs `sudo apt install stockfish`. The page shows which engine is in use.
- Every game is logged to `games/`, ending with a summary of moves, Dream-1 attempts, fixes, and
  rescues.
- A fine-tuned model's first run can take up to an hour to start on Dream's side. Start it early.
