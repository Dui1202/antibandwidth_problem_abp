import json

import run_with_figures


def test_wrapper_new_run_uses_five_minutes(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(run_with_figures, "run_stage", lambda command, monitor=None: calls.append(command))
    run_with_figures.main(["--output", str(tmp_path / "new")])
    assert calls[0][-2:] == ["--time-limit", "300"]


def test_wrapper_resume_uses_recorded_limit(monkeypatch, tmp_path):
    output = tmp_path / "old"
    output.mkdir()
    (output / "metadata.json").write_text(json.dumps({"config": {"time_limit": 600}}))
    calls = []
    monkeypatch.setattr(run_with_figures, "archive_interrupted", lambda output: 0)
    monkeypatch.setattr(run_with_figures, "run_stage", lambda command, monitor=None: calls.append(command))
    run_with_figures.main(["--output", str(output), "--resume"])
    assert calls[0][-2:] == ["--time-limit", "600"]
