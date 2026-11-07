"""Test Dream-1 on single chess moves, then compare runs. Runs on the NUC, at the station.

    python eval_dream.py prompts                    # list every prompt, nothing moves
    python eval_dream.py run --label baseline       # moves the arms: a person must be at the e-stop
    python eval_dream.py run --label baseline --manual   # you send prompts yourself; this only logs scores
    python eval_dream.py report evals/results/*.jsonl

`run` sends each prompt through the station's local API. Ctrl-C stops the arms at once.
"""
from __future__ import annotations

import argparse
import datetime
import json
import time
from pathlib import Path

from dreamchess.core import MoverError
from dreamchess.evaluation import (
    OUTCOMES, TASKS, WORDINGS, load_results, prompt_for, report, setup_text, step_for, trial_key, trial_plan,
)
from dreamchess.station_mover import StationClient, StationMover

RESULTS = Path(__file__).parent / "evals" / "results"


def cmd_prompts(args, say=print) -> None:
    for task in TASKS:
        say(f"\n{task.id}  {task.title}  [{', '.join(task.tags)}]")
        say(f"  Setup:    {setup_text(task)}")
        for wording in WORDINGS:
            say(f"  {wording:9} {prompt_for(task, wording)}")


def ask_outcome(ask) -> str:
    choices = "  ".join(f"{key}={name}" for key, (name, _) in OUTCOMES.items())
    while True:
        answer = ask(f"  Result? {choices}: ").strip().lower()
        if answer in OUTCOMES:
            return OUTCOMES[answer][0]


def cmd_run(args, ask=input, say=print, client: StationClient | None = None) -> Path:
    tasks = [t for t in TASKS if (not args.tasks or t.id in args.tasks) and not set(t.tags) & set(args.skip_tag)]
    plan = trial_plan(tasks, args.wording, args.repeat)
    out = Path(args.out) / f"{args.label}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {trial_key(e) for e in load_results([out])} if out.exists() else set()
    remaining = [p for p in plan if (args.label, p[1].id, p[2], p[0]) not in done]
    say(f"{len(remaining)} of {len(plan)} trials to run for '{args.label}'; results go to {out}")
    if not args.setup:
        say('Tip: describe the setup with --setup, such as "edge labels: yes", so runs compare fairly.')

    mover = None
    if not args.manual:
        client = client or StationClient()
        status = client.status()
        if status.get("state") != "idle":
            raise SystemExit(f"The station is {status.get('state')}, not idle. Wait for it, then run this again.")
        mover = StationMover(client, attempt_s=args.seconds, checkpoint=args.checkpoint, log=say)
        say("This moves the arms. Keep the board clear of hands while a trial runs.")
        if ask("Type yes when a person has a hand on the e-stop: ").strip().lower() != "yes":
            raise SystemExit("Stopped: nobody confirmed the e-stop.")

    for number, (rep, task, wording) in enumerate(remaining, 1):
        step = step_for(task, wording)
        say(f"\n[{number}/{len(remaining)}] {task.id} {task.title} ({wording}, round {rep})")
        say(f"  {setup_text(task)}")
        say(f"  Prompt: {step.prompt}")
        answer = ask("  Press Enter to run, s to skip, q to quit: ").strip().lower()
        if answer == "q":
            break
        if answer == "s":
            continue

        error, checkpoint, started = "", args.checkpoint, time.monotonic()
        if mover is not None:
            try:
                mover.execute(step)
                checkpoint = client.status().get("checkpoint") or checkpoint
                mover.go_home()
            except KeyboardInterrupt:
                client.stop()
                say("  Stopped the arms.")
                error = "stopped with Ctrl-C"
            except MoverError as err:
                error = str(err)
                say(f"  Station problem: {error}")
        else:
            ask("  Send the prompt yourself, then press Enter once the arm has finished: ")
        seconds = round(time.monotonic() - started, 1)

        outcome = "stopped" if error == "stopped with Ctrl-C" else ask_outcome(ask)
        entry = {
            "label": args.label, "checkpoint": checkpoint, "task": task.id, "title": task.title,
            "tags": list(task.tags), "wording": wording, "repeat": rep, "prompt": step.prompt,
            "outcome": outcome, "seconds": seconds, "error": error, "manual": bool(args.manual), "setup": args.setup,
            "notes": ask("  Notes (optional): ").strip(),
            "time": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        if error == "stopped with Ctrl-C" and ask("  Keep going? y/n: ").strip().lower() != "y":
            break
    say(f"\nSaved to {out}. See the results with: python eval_dream.py report {out}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prompts").set_defaults(func=cmd_prompts)

    run = sub.add_parser("run")
    run.set_defaults(func=cmd_run)
    run.add_argument("--label", required=True, help="a name for this run, such as baseline or finetune-1")
    run.add_argument("--checkpoint", help="the model to run, such as a fine-tuned ID; default keeps the station's")
    run.add_argument("--manual", action="store_true", help="don't call the station: you send each prompt yourself")
    run.add_argument("--wording", nargs="+", default=list(WORDINGS), choices=WORDINGS)
    run.add_argument("--tasks", nargs="+", default=[], help="only these task IDs, such as t01 t03")
    run.add_argument("--skip-tag", nargs="+", default=[], help="leave out tasks with these tags, such as tray")
    run.add_argument("--repeat", type=int, default=2, help="rounds of every task")
    run.add_argument("--setup", default="", help='what this run used, such as "edge labels: yes"')
    run.add_argument("--seconds", type=float, default=30.0, help="time limit per attempt")
    run.add_argument("--out", default=str(RESULTS))

    rep = sub.add_parser("report")
    rep.set_defaults(func=lambda args: print(report(load_results(args.files))))
    rep.add_argument("files", nargs="+")

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
