#!/usr/bin/env python3
"""Create a compact, machine-readable baseline/experiment comparison."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


METRICS = ["octave_down_duration_sec", "octave_up_duration_sec", "median_absolute_cents_error", "p90_absolute_cents_error", "within_25_cents", "within_50_cents", "dropout_frames", "pitch_jump_count", "pitch_coverage", "longest_stable_correct_sec"]


def concise(summary):
    return {metric: summary.get(metric) for metric in METRICS}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("baseline", type=Path)
    p.add_argument("best", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    baseline = json.loads(args.baseline.read_text())
    best = json.loads(args.best.read_text())
    report = {
        "baseline": concise(baseline),
        "best": concise(best),
        "delta_best_minus_baseline": {key: best.get(key, 0) - baseline.get(key, 0) for key in METRICS if isinstance(best.get(key), (int, float)) and isinstance(baseline.get(key), (int, float))},
        "frequency_bands": {"best": best.get("frequency_band_metrics", {})},
        "holdout": {"best": best.get("holdout_metrics", {})},
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
