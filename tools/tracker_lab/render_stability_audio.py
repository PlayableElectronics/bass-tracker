#!/usr/bin/env python3
"""Render local-only monitor WAVs for baseline, octave_v1 and stability_v1."""
from __future__ import annotations

import argparse
from pathlib import Path

import analyze
import render_audio_comparison as monitor


WINDOWS = [
    ("attack_74", 73.85, 74.75),
    ("attack_88", 87.85, 88.80),
    ("slide_160", 159.60, 160.35),
    ("slide_163", 162.65, 163.50),
    ("decay_250", 249.70, 250.80),
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input", type=Path, help="source WAV, normally 'basik hehe.wav'")
    p.add_argument("--baseline", type=Path, default=Path("tools/tracker_lab/baseline/frames.csv.gz"))
    p.add_argument("--octave", type=Path, default=Path("tools/tracker_lab/experiments/octave_v1/frames.csv.gz"))
    p.add_argument("--stability", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, default=Path("tracker_runs/stability_audio_compare"))
    args = p.parse_args()

    source, sample_rate, _, _ = analyze.load_audio(args.input, 0, None)
    tracks = {
        "baseline": monitor.read_rows(args.baseline),
        "octave_v1": monitor.read_rows(args.octave),
        "stability_best": monitor.read_rows(args.stability),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for label, rows in tracks.items():
        analyze.render_monitor(source, sample_rate, rows, args.output_dir / f"{label}_tracker_monitor.wav")
    for name, start, stop in WINDOWS:
        excerpt = source[int(start * sample_rate):int(stop * sample_rate)]
        for label, rows in tracks.items():
            local = monitor.local_rows(rows, start, stop)
            analyze.render_monitor(excerpt, sample_rate, local, args.output_dir / f"{name}_{label}.wav")


if __name__ == "__main__":
    main()
