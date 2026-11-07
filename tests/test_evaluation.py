import argparse
import json

import pytest

import eval_dream
from dreamchess.evaluation import TASKS, WORDINGS, load_results, prompt_for, relative_prompt, report, trial_plan
from dreamchess.where import write_prompt
from test_station_mover import FakeStation, station  # noqa: F401  (the fixture)


def task(task_id):
    return next(t for t in TASKS if t.id == task_id)


def test_named_wording_is_exactly_what_the_app_sends():
    t = task("t02")
    assert prompt_for(t, "named") == write_prompt("right", "w", "knight", "g1", "f3")


@pytest.mark.parametrize("task_id,expected", [
    ("t02", "move it 2 squares away from you and 1 square to your left"),
    ("t03", "move it 2 squares away from you."),
    ("t06", "move it 5 squares away from you and 5 squares to your right"),
    ("t08", "move it 1 square away from you."),
    ("t11", "put it in the tray"),
])
def test_relative_wording_describes_the_move_from_the_robots_side(task_id, expected):
    assert expected in relative_prompt(task(task_id))


def test_task_ids_are_unique_and_arms_match_the_app():
    assert len({t.id for t in TASKS}) == len(TASKS)
    assert "left arm" in prompt_for(task("t01"), "named") and "right arm" in prompt_for(task("t05"), "named")


def test_plan_alternates_which_wording_goes_first():
    plan = trial_plan(TASKS[:2], list(WORDINGS), repeat=2)
    assert len(plan) == 8
    assert [w for _, _, w in plan[:4]] == ["named", "relative", "relative", "named"]


def args(tmp_path, **extra):
    defaults = dict(label="baseline", checkpoint=None, manual=False, wording=list(WORDINGS), tasks=["t01"],
                    skip_tag=[], repeat=1, seconds=0.2, out=str(tmp_path))
    return argparse.Namespace(**{**defaults, **extra})


def scripted(*answers):
    queue = list(answers)
    return lambda prompt: queue.pop(0)


def fast_client(station):
    from dreamchess.station_mover import StationClient

    client = StationClient(station.url, timeout_s=5)
    return client


@pytest.fixture
def quick(monkeypatch):
    original = eval_dream.StationMover

    def make(client, **kwargs):
        return original(client, poll_s=0.02, grace_s=1.0, **kwargs)

    monkeypatch.setattr(eval_dream, "StationMover", make)


def test_run_needs_the_e_stop_confirmed(station, tmp_path, quick):  # noqa: F811
    with pytest.raises(SystemExit, match="e-stop"):
        eval_dream.cmd_run(args(tmp_path), ask=scripted("no"), say=lambda _: None, client=fast_client(station))
    assert station.run == 0


def test_run_refuses_when_the_station_is_busy(station, tmp_path, quick):  # noqa: F811
    station.state = "running"
    with pytest.raises(SystemExit, match="not idle"):
        eval_dream.cmd_run(args(tmp_path), ask=scripted("yes"), say=lambda _: None, client=fast_client(station))


def test_run_sends_each_prompt_and_logs_the_scores(station, tmp_path, quick):  # noqa: F811
    answers = scripted("yes", "", "s", "", "", "w", "landed on c4")
    out = eval_dream.cmd_run(args(tmp_path), ask=answers, say=lambda _: None, client=fast_client(station))
    results = load_results([out])
    assert [r["outcome"] for r in results] == ["success", "wrong_square"]
    assert {r["wording"] for r in results} == {"named", "relative"}
    assert results[1]["notes"] == "landed on c4"
    assert station.run == 2


def test_run_resumes_where_it_left_off(station, tmp_path, quick):  # noqa: F811
    eval_dream.cmd_run(args(tmp_path), ask=scripted("yes", "", "s", "", "q"), say=lambda _: None,
                       client=fast_client(station))
    lines = []
    out = eval_dream.cmd_run(args(tmp_path), ask=scripted("yes", "", "m", ""), say=lines.append,
                             client=fast_client(station))
    assert "1 of 2 trials to run" in lines[0]
    assert len(load_results([out])) == 2


def test_manual_mode_never_calls_the_station(station, tmp_path):  # noqa: F811
    out = eval_dream.cmd_run(args(tmp_path, manual=True), ask=scripted("", "", "s", "", "", "", "d", ""),
                             say=lambda _: None, client=fast_client(station))
    assert station.requests == []
    assert [r["outcome"] for r in load_results([out])] == ["success", "dropped"]


def test_ctrl_c_stops_the_arms(station, tmp_path, monkeypatch, quick):  # noqa: F811
    def interrupted(self, step):
        raise KeyboardInterrupt

    from dreamchess import station_mover

    monkeypatch.setattr(station_mover.StationMover, "execute", interrupted)
    out = eval_dream.cmd_run(args(tmp_path), ask=scripted("yes", "", "", "n"), say=lambda _: None,
                             client=fast_client(station))
    assert [body for m, p, body in station.requests if p == "/stop"]
    assert load_results([out])[0]["outcome"] == "stopped"


def test_checkpoint_is_sent_to_the_station(station, tmp_path, quick):  # noqa: F811
    eval_dream.cmd_run(args(tmp_path, checkpoint="dream-1-ft:abc12345-chess", wording=["named"]),
                       ask=scripted("yes", "", "s", ""), say=lambda _: None, client=fast_client(station))
    starts = [body for m, p, body in station.requests if p == "/start"]
    assert starts[0]["checkpoint"] == "dream-1-ft:abc12345-chess"


def test_report_compares_runs_and_points_at_weak_spots(tmp_path):
    rows = []
    for label, wins in (("baseline", 1), ("finetune-1", 2)):
        for i in range(4):
            rows.append({"label": label, "checkpoint": label, "task": f"t0{i}", "tags": ["far" if i < 2 else "near"],
                         "wording": "named", "repeat": 1, "outcome": "success" if i < wins else "missed"})
    path = tmp_path / "r.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    text = report(load_results([path]))
    assert "| baseline | baseline | 1/4 (25%)" in text
    assert "| finetune-1 | finetune-1 | 2/4 (50%)" in text
    assert "may be chance" in text
    assert "Where to focus data collection (finetune-1)" in text
    assert "under half the time: near" in text
    assert text.index("| baseline |") < text.index("| finetune-1 |")


def test_prompts_command_lists_every_task(tmp_path):
    lines = []
    eval_dream.cmd_prompts(None, say=lines.append)
    text = "\n".join(lines)
    assert all(t.id in text for t in TASKS)
