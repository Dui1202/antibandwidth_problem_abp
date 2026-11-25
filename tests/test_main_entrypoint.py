from pathlib import Path

import main


def test_main_runs_benchmark_supplement_and_final_figures(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(main.run_with_figures, "main", lambda args: calls.append(("benchmark", args)))
    monkeypatch.setattr(main.supplement, "run", lambda *args: calls.append(("supplement", args)))
    monkeypatch.setattr(main, "generate", lambda path: calls.append(("figures", path)))
    output = tmp_path / "results"
    dataset = tmp_path / "dataset"

    main.main(["--output", str(output), "--dataset", str(dataset), "--resume",
               "--time-limit", "5", "--supplement-time-limit", "2", "--repetitions", "2"])

    assert [stage for stage, _ in calls] == ["benchmark", "supplement", "figures"]
    assert calls[0][1] == ["--output", str(output), "--dataset", str(dataset),
                           "--resume", "--time-limit", "5"]
    assert calls[1][1] == (output, dataset, 2, 2)
    assert calls[2][1] == output
