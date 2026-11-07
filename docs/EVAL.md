# Dream-1 eval

This tests Dream-1 on 12 single chess moves, each in two wordings, so we can:

1. **Measure the base model** before anyone fine-tunes.
2. **Choose the prompt wording** the app should send.
3. **See which kinds of move fail**, so data collection targets them.
4. **Compare a fine-tuned model** against the baseline on exactly the same trials.

The "named" wording is exactly what the app sends today. The "relative" wording describes the
same move by direction and distance ("2 squares away from you and 1 square to your left"), in
case Dream-1 can't read square names on a board this small. The full list is in
[EVAL_PROMPTS.md](EVAL_PROMPTS.md).

## Set up the board first, and then don't change it

Results only compare fairly if the setup stays the same, so settle these before the baseline:

- **White's side nearest the robot**, with a1, a dark square, at the robot's left.
- **Closer to the arms and fully in the top camera's view.** In the last saved top-camera frame,
  the board was small at the back of the table.
- **Taped down**, with the same lighting and the same piece set throughout.
- **A tray on the left side of the board**, within the left arm's reach, for the capture task
  (t11). With no tray, leave that task out with `--skip-tag tray`.

If the setup changes, run the baseline again.

## Run it on the NUC

The station must be up and idle. **A person keeps a hand on the e-stop for the whole run.**

```bash
cd ~/dream-chess
git pull
.venv/bin/python eval_dream.py run --label baseline
```

For each trial, it shows the setup and the prompt. Set the pieces, press Enter, and watch. When
the arm finishes, type the result and any notes. **Ctrl-C stops the arms at once.** You can quit
at any time: running the same command again picks up where you left off.

There are 24 trials. At roughly a minute and a half each, plan on about 40 minutes.

**To send the prompts yourself**, for example from Live View, add `--manual`. The tool then only
shows each prompt and records your scores.

**To test a fine-tuned model**, run the same trials under a new label:

```bash
.venv/bin/python eval_dream.py run --label finetune-1 --checkpoint "dream-1-ft:<your model ID>"
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
| `x` | no_motion | The arms didn't really try, or the station reported an error |
| `e` | stopped | A person stopped it for safety |

Only `s` counts as a success. Put the details in the notes, such as "landed on c4" or "grabbed
the neighbor".

## Read the results

```bash
.venv/bin/python eval_dream.py report evals/results/*.jsonl
```

This shows each run's success rate for each wording, kind of move, and failure. Commit the
`.jsonl` files so the team can see them.

With 24 trials, a difference of one or two successes may just be chance. Trust large gaps, or
repeat the runs with `--repeat 2`.

## Use the baseline to plan data collection

The app needs demos that look like what it will actually ask for:

1. **Use the same scene.** Record on this station with the board, camera, lighting, and pieces
   exactly as they'll be for the demo, with the robot on White's side.
2. **Use the app's exact wording.** Each demo's task text should be the prompt the app would send
   for that move, in whichever wording wins the baseline. `eval_dream.py prompts` prints examples.
3. **Focus on the weak spots.** The report names the kinds of move succeeding under half the
   time, so record more of those.
4. **Cover what the app really sends:** both arms, near and far squares, captures to the tray,
   the rook's move when castling, and pieces with close neighbors.
5. **Record only clean demos.** Move slowly, set the piece down upright in the middle of the
   square, and lift straight up. Throw out any demo that bumps another piece.
6. **Keep the eval out of the training data.** Don't record demos of the 12 eval moves from the
   same starting squares, or the comparison will flatter the fine-tune.

How many demos a fine-tune needs isn't something we've measured. Check Dream's fine-tuning docs.

## Decide whether to use a fine-tuned model

Run the same eval with the same setup. Switch only if it clearly beats the baseline, especially
on the kinds of move the demo game needs. Otherwise, keep the base model and put the time into
prompts and setup.
