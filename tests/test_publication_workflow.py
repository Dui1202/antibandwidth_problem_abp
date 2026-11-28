"""End-to-end check of publication exports without touching collected data."""

import hashlib
from pathlib import Path
import shutil

from visualization.publication import generate_all


RESULTS = Path(__file__).resolve().parents[1] / "results/benchmark_20261125T084243Z"
INPUTS = ("metadata.json", "manifest.csv", "thresholds.csv", "fixed.csv", "optimization.csv")


def test_publication_workflow_exports_complete_pdf_svg_pairs(tmp_path):
    for name in INPUTS:
        shutil.copy2(RESULTS / name, tmp_path / name)
    before = {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in INPUTS}

    output = generate_all(tmp_path)
    pdfs = {path.stem for path in output.glob("*.pdf")}
    svgs = {path.stem for path in output.glob("*.svg")}
    assert pdfs == svgs
    assert len(pdfs) == 20
    for name in pdfs:
        assert (output / f"{name}.pdf").read_bytes().startswith(b"%PDF-")
        assert b"<svg" in (output / f"{name}.svg").read_bytes()[:2000]
    assert before == {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
                      for name in INPUTS}
