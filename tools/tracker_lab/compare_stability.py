#!/usr/bin/env python3
"""Compare baseline, octave-family, and stability experiment reports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


SUMMARY_KEYS = [
    "octave_down_duration_sec", "octave_up_duration_sec",
    "median_absolute_cents_error", "p90_absolute_cents_error",
    "within_25_cents", "within_50_cents", "pitch_jump_count",
    "pitch_coverage", "dropout_frames",
]


def read_run(path: Path):
    summary = json.loads((path / "summary.json").read_text())
    stability = json.loads((path / "stability_metrics.json").read_text())
    return {
        "summary": {key: summary[key] for key in SUMMARY_KEYS},
        "frequency_band_metrics": summary["frequency_band_metrics"],
        "holdout_metrics": summary["holdout_metrics"],
        "stability": stability,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--octave-v1", type=Path, required=True)
    p.add_argument("--best", type=Path, required=True)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    report = {
        "metric_notes": {
            "stability_conditioning": "reference voiced, tracker valid, <=100-cent error, and five-frame reference motion <=10 cents",
            "important_caveat": "baseline stability statistics cover fewer correctly tracked frames because octave-wrong frames are excluded",
        },
        "baseline": read_run(args.baseline),
        "octave_v1": read_run(args.octave_v1),
        "stability_best": read_run(args.best),
    }
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
