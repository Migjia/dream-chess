# Dream-1 eval

This tests Dream-1 on 14 single chess moves, each run twice, so we can:

1. **Measure the base model** before anyone fine-tunes.
2. **See which kinds of move fail**, so data collection targets them.
3. **Compare a fine-tuned model** against the baseline on exactly the same trials.

Every prompt comes from the app's own prompt writer, so the eval measures exactly what the agent
sends. That includes its fix prompts after a failure, such as "pick up the brown piece on square
g6", which name only the color because the camera can't tell piece types apart. The full list is
in [EVAL_PROMPTS.md](EVAL_PROMPTS.md).

## What Dream-1 has to figure out

Dream-1 doesn't know chess or the board's grid. It gets camera images and one sentence naming
two squares, such as g8 and f6, and has to work out where those are from what it sees. Our app
knows every square's position from the camera calibration, but Dream-1 never gets that map. That's
why edge labels and fine-tuning matter, and why this baseline is worth measuring first.

## Set up the board first, and then don't change it

Results only compare fairly if the setup stays the same, so settle these before the baseline:

- **The robot plays Brown.** Its side of the board, rank 8, is nearest the robot, with the h-file
  at the robot's left. The opponent plays White.
- **Edge labels:** write a–h and 1–8 large along the board's edges, on tape if needed.
- **Closer to the arms and fully in the top camera's view.** In the last saved top-camera frame,
  the board was small at the back of the table.
- **Taped down**, with the same lighting and the same piece set throughout.
- **A tray beside each arm:** one on the robot's left and one on its right, each within reach.
  With no trays, leave the capture tasks out with `--skip-tag tray`.

If the setup changes, run the baseline again under a new label.

## Run it on the NUC

The station must be up and idle. **A person keeps a hand on the e-stop for the whole run.**

```bash
cd ~/dream-chess
git pull
.venv/bin/python eval_dream.py run --label baseline --setup "edge labels: yes"
```

For each trial, it shows the setup and the prompt. Set the pieces, press Enter, and watch. When
the arm finishes, type the result and any notes. **Ctrl-C stops the arms at once.** You can quit
at any time: running the same command again picks up where you left off.

There are 28 trials, which at roughly a minute and a half each is about 40 minutes. For a quicker
first look, use `--repeat 1`.

**To send the prompts yourself**, for example from Live View, add `--manual`. The tool then only
shows each prompt and records your scores.

**To test a fine-tuned model**, run the same trials under a new label:

```bash
.venv/bin/python eval_dream.py run --label finetune-1 --setup "edge labels: yes" --checkpoint "dream-1-ft:<your model ID>"
```

That model then stays in use on the station for later runs until another start names a
different one.

## Scoring

| Key | Result | Use it when |
| --- | --- | --- |
| `s` | success | It landed on the right square, upright, and nothing else moved |
| `w` | wrong_square | It put the piece down on a different square |
| `m` | missed | It never picked the piece up |
| `d` | dropped | It dropped the piece, knocked it over, or it fell off the board |
| `n` | disturbed | It moved the piece but bumped another out of place |
| `t` | timed_out | It was still moving when the 30-second limit ended |
| `x` | no_motion | The arms didn't really try, or the station reported an error |
| `e` | stopped | A person stopped it for safety |

Only `s` counts as a success. Put the details in the notes, such as "landed on f5" or "grabbed
the neighbor". If many trials time out, try `--seconds 45`.

## Read the results

```bash
.venv/bin/python eval_dream.py report evals/results/*.jsonl
```

This shows each run's success rate by kind of move and by failure. Commit the `.jsonl` files so
the team can see them.

With 28 trials, a difference of a few successes may just be chance. Trust large gaps.

## Use the baseline to plan data collection

The app needs demos that look like what it will actually ask for:

1. **Use the same scene.** Record on this station with the board, labels, camera, lighting, and
   pieces exactly as they'll be for the demo, with the robot on Brown's side.
2. **Use the app's exact wording.** Each demo's task text should be the prompt the app would send
   for that move. `eval_dream.py prompts` prints examples.
3. **Focus on the weak spots.** The report names the kinds of move succeeding under half the
   time, so record more of those.
4. **Cover the whole board.** Since Dream-1 must learn where each named square is, spread demos
   across many different squares, with both arms.
5. **Include what the app really sends:** captures to the tray on each side, fix prompts that
   say "the brown piece" or "the white piece", and pieces with close neighbors.
6. **Record only clean demos.** Move slowly, set the piece down upright in the middle of the
   square, and lift straight up. Throw out any demo that bumps another piece.
7. **Keep the eval out of the training data.** Don't record demos of the 14 eval moves from the
   same starting squares, or the comparison will flatter the fine-tune.

How many demos a fine-tune needs isn't something we've measured. Check Dream's fine-tuning docs.

## Decide whether to use a fine-tuned model

Run the same eval with the same setup. Switch only if it clearly beats the baseline. Otherwise,
keep the base model.
