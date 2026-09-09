#!/usr/bin/env python3
"""Print amplitude distributions for a bass-tracker CSV capture."""

import argparse
import csv
import math
from pathlib import Path


FIELDS = [
    "seq", "ms", "raw_freq_hz", "tracked_freq_hz", "raw_confidence",
    "tracked_confidence", "envelope", "attack", "gate", "pitch_valid",
    "onset", "input_peak", "input_rms", "filtered_peak", "filtered_rms",
    "c1_freq", "c1_score", "c2_freq", "c2_score", "c3_freq", "c3_score",
    "c4_freq", "c4_score",
]
AMPLITUDE_FIELDS = ("envelope", "input_peak", "input_rms", "filtered_peak", "filtered_rms")


def percentile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def rows(path):
    with path.open(newline="") as source:
        reader = csv.reader(source)
        for row in reader:
            if len(row) != len(FIELDS):
                continue
            try:
                yield {name: float(value.strip()) for name, value in zip(FIELDS, row)}
            except ValueError:
                continue


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    args = parser.parse_args()
    data = list(rows(args.capture))
    if not data:
        parser.error("no 23-field numeric CSV rows found")
    print(f"rows={len(data)}")
    for name in AMPLITUDE_FIELDS:
        values = [row[name] for row in data]
        print(
            f"{name}: min={min(values):.9f} median={percentile(values, .50):.9f} "
            f"p90={percentile(values, .90):.9f} p95={percentile(values, .95):.9f} "
            f"max={max(values):.9f}"
        )


if __name__ == "__main__":
    main()
