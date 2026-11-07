import argparse
import json

import chess
import pytest

import eval_dream
from dreamchess.evaluation import ROBOT, TASKS, load_results, prompt_for, report, setup_text, trial_plan
from dreamchess.where import arm_for, write_prompt
from test_station_mover import FakeStation, station  # noqa: F401  (the fixture)


def task(task_id):
    return next(t for t in TASKS if t.id == task_id)


def test_robot_plays_brown_and_pieces_are_named_brown():
    assert ROBOT == chess.BLACK
    assert "brown knight on square g8" in prompt_for(task("t01"))


def test_every_prompt_is_exactly_what_the_app_sends():
    for t in TASKS:
        arm = arm_for(t.target if t.source == "tray" else t.source, chess.BLACK)
        assert prompt_for(t) == write_prompt(arm, t.color, t.piece, t.source, t.target)


def test_arms_follow_the_robots_seat_on_browns_side():
    # Seated behind the 8th rank, the robot has the h-file at its left.
    assert "left arm" in prompt_for(task("t01"))   # g8
    assert "right arm" in prompt_for(task("t02"))  # b8


def test_captures_use_the_tray_on_the_same_side_as_the_arm():
    assert "left arm" in prompt_for(task("t11")) and "tray on your left" in prompt_for(task("t11"))
    assert "right arm" in prompt_for(task("t12")) and "tray on your right" in prompt_for(task("t12"))


def test_recovery_trials_use_the_apps_fix_wording_but_set_up_a_real_piece():
    assert "pick up the brown piece on square g6" in prompt_for(task("t13"))
    assert "brown knight on g6" in setup_text(task("t13"))
    assert "pick up the white piece on square e3" in prompt_for(task("t14"))


def test_task_ids_are_unique_and_targets_spread_across_the_board():
    assert len({t.id for t in TASKS}) == len(TASKS)
    tags = {tag for t in TASKS for tag in t.tags}
    assert {"near", "mid", "far", "left-arm", "right-arm", "crowded", "tray", "recovery"} <= tags


def test_two_rounds_reverse_the_order():
    plan = trial_plan(TASKS[:3], ["named"], repeat=2)
    assert [t.id for _, t, _ in plan] == ["t01", "t02", "t03", "t03", "t02", "t01"]


def args(tmp_path, **extra):
    defaults = dict(label="baseline", checkpoint=None, manual=False, wording=["named"], tasks=["t01", "t02"],
                    skip_tag=[], repeat=1, seconds=0.2, out=str(tmp_path), setup="edge labels: yes")
    return argparse.Namespace(**{**defaults, **extra})


def scripted(*answers):
    queue = list(answers)
    return lambda prompt: queue.pop(0)


def client_for(station):  # noqa: F811
    from dreamchess.station_mover import StationClient

    return StationClient(station.url, timeout_s=5)


@pytest.fixture
def quick(monkeypatch):
    original = eval_dream.StationMover
    monkeypatch.setattr(eval_dream, "StationMover", lambda client, **kw: original(client, poll_s=0.02, grace_s=1.0, **kw))


def test_run_needs_the_e_stop_confirmed(station, tmp_path, quick):  # noqa: F811
    with pytest.raises(SystemExit, match="e-stop"):
        eval_dream.cmd_run(args(tmp_path), ask=scripted("no"), say=lambda _: None, client=client_for(station))
    assert station.run == 0


def test_run_refuses_when_the_station_is_busy(station, tmp_path, quick):  # noqa: F811
    station.state = "running"
    with pytest.raises(SystemExit, match="not idle"):
        eval_dream.cmd_run(args(tmp_path), ask=scripted("yes"), say=lambda _: None, client=client_for(station))


def test_run_sends_each_prompt_and_logs_scores_and_setup(station, tmp_path, quick):  # noqa: F811
    answers = scripted("yes", "", "s", "", "", "t", "still reaching at the end")
    out = eval_dream.cmd_run(args(tmp_path), ask=answers, say=lambda _: None, client=client_for(station))
    results = load_results([out])
    assert [r["outcome"] for r in results] == ["success", "timed_out"]
    assert results[1]["notes"] == "still reaching at the end"
    assert all(r["setup"] == "edge labels: yes" for r in results)
    starts = [body["prompt"] for m, p, body in station.requests if p == "/start"]
    assert starts == [prompt_for(task("t01")), prompt_for(task("t02"))]


def test_run_resumes_where_it_left_off(station, tmp_path, quick):  # noqa: F811
    eval_dream.cmd_run(args(tmp_path), ask=scripted("yes", "", "s", "", "q"), say=lambda _: None,
                       client=client_for(station))
    lines = []
    out = eval_dream.cmd_run(args(tmp_path), ask=scripted("yes", "", "m", ""), say=lines.append,
                             client=client_for(station))
    assert "1 of 2 trials to run" in lines[0]
    assert len(load_results([out])) == 2


def test_manual_mode_never_calls_the_station(station, tmp_path):  # noqa: F811
    out = eval_dream.cmd_run(args(tmp_path, manual=True), ask=scripted("", "", "s", "", "", "", "d", ""),
                             say=lambda _: None, client=client_for(station))
    assert station.requests == []
    assert [r["outcome"] for r in load_results([out])] == ["success", "dropped"]


def test_ctrl_c_stops_the_arms(station, tmp_path, monkeypatch, quick):  # noqa: F811
    from dreamchess import station_mover

    def interrupted(self, step):
        raise KeyboardInterrupt

    monkeypatch.setattr(station_mover.StationMover, "execute", interrupted)
    out = eval_dream.cmd_run(args(tmp_path, tasks=["t01"]), ask=scripted("yes", "", "", "n"), say=lambda _: None,
                             client=client_for(station))
    assert [body for m, p, body in station.requests if p == "/stop"]
    assert load_results([out])[0]["outcome"] == "stopped"


def test_checkpoint_is_sent_to_the_station(station, tmp_path, quick):  # noqa: F811
    eval_dream.cmd_run(args(tmp_path, checkpoint="dream-1-ft:abc12345-chess", tasks=["t01"]),
                       ask=scripted("yes", "", "s", ""), say=lambda _: None, client=client_for(station))
    starts = [body for m, p, body in station.requests if p == "/start"]
    assert starts[0]["checkpoint"] == "dream-1-ft:abc12345-chess"


def test_report_compares_runs_and_points_at_weak_spots(tmp_path):
    rows = []
    for label, wins in (("baseline", 1), ("finetune-1", 2)):
        for i in range(4):
            rows.append({"label": label, "checkpoint": label, "setup": "edge labels: yes", "task": f"t0{i}",
                         "tags": ["far" if i < 2 else "near"], "wording": "named", "repeat": 1,
                         "outcome": "success" if i < wins else "missed"})
    path = tmp_path / "r.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    text = report(load_results([path]))
    assert "| baseline | baseline | edge labels: yes | 1/4 (25%) |" in text
    assert "| finetune-1 | finetune-1 | edge labels: yes | 2/4 (50%) |" in text
    assert "Where to focus data collection (finetune-1)" in text
    assert "under half the time: near" in text
    assert "may be chance" in text


def test_prompts_command_lists_every_task():
    lines = []
    eval_dream.cmd_prompts(None, say=lines.append)
    text = "\n".join(lines)
    assert all(t.id in text for t in TASKS)
