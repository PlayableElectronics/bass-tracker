#!/usr/bin/env python3
import argparse, json
from pathlib import Path

def main():
    p = argparse.ArgumentParser(); p.add_argument("baseline", type=Path); p.add_argument("experiment", type=Path); args = p.parse_args()
    a = json.loads((args.baseline / "summary.json").read_text()); b = json.loads((args.experiment / "summary.json").read_text())
    keys = ["pitch_coverage", "median_absolute_cents_error", "p90_absolute_cents_error", "within_25_cents", "within_50_cents", "octave_up_frames", "octave_down_frames", "dropout_frames", "false_positive_frames", "pitch_jump_count"]
    print("metric\tbaseline\texperiment\tdelta\tdirection")
    for k in keys:
        av, bv = a.get(k), b.get(k); delta = None if av is None or bv is None else bv - av
        better = "improved" if ((k in {"pitch_coverage", "within_25_cents", "within_50_cents"} and delta and delta > 0) or (k not in {"pitch_coverage", "within_25_cents", "within_50_cents"} and delta and delta < 0)) else ("regressed" if delta else "same")
        print(f"{k}\t{av}\t{bv}\t{delta}\t{better}")
if __name__ == "__main__": main()
