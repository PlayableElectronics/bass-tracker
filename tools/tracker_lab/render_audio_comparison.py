#!/usr/bin/env python3
"""Render local-only baseline/best full and failure-window monitor WAVs."""
from __future__ import annotations

import argparse
import csv
import gzip
from pathlib import Path

import analyze


def read_rows(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    numeric = {"time_sec", "tracked_freq_hz", "reference_freq_hz"}
    integer = {"pitch_valid", "reference_voiced"}
    with opener(path, "rt", newline="") as f:
        rows = []
        for raw in csv.DictReader(f):
            row = dict(raw)
            for key in numeric:
                row[key] = float(row.get(key) or 0)
            for key in integer:
                row[key] = int(row.get(key) or 0)
            rows.append(row)
    return rows


def local_rows(rows, start, stop):
    return [dict(row, time_sec=row["time_sec"] - start) for row in rows if start - .1 <= row["time_sec"] <= stop + .1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input", type=Path)
    p.add_argument("--baseline", type=Path, default=Path("tools/tracker_lab/baseline/frames.csv.gz"))
    p.add_argument("--best", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, default=Path("tracker_runs/audio_compare"))
    args = p.parse_args()
    y, sr, _, _ = analyze.load_audio(args.input, 0, None)
    baseline, best = read_rows(args.baseline), read_rows(args.best)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    analyze.render_monitor(y, sr, baseline, args.output_dir / "baseline_tracker_monitor.wav")
    analyze.render_monitor(y, sr, best, args.output_dir / "best_tracker_monitor.wav")
    for label, start, stop in (("octave_74s", 72, 79), ("octave_88s", 86, 92), ("octave_295s", 293, 300)):
        audio = y[int(start * sr):int(stop * sr)]
        analyze.render_monitor(audio, sr, local_rows(baseline, start, stop), args.output_dir / f"{label}_baseline.wav")
        analyze.render_monitor(audio, sr, local_rows(best, start, stop), args.output_dir / f"{label}_best.wav")


if __name__ == "__main__":
    main()
