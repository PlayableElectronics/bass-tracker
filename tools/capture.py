#!/usr/bin/env python3
"""Capture Daisy bass-analyzer CSV output and label a single test take."""

import argparse
import csv
from datetime import datetime
from pathlib import Path
import re
import sys
import time

try:
    import serial
except ImportError as exc:
    raise SystemExit("pyserial is required: python3 -m pip install pyserial") from exc


CSV_FIELDS = [
    "seq", "ms", "raw_freq_hz", "tracked_freq_hz", "raw_confidence",
    "tracked_confidence", "envelope", "attack", "gate", "pitch_valid",
    "onset", "input_peak", "input_rms", "filtered_peak", "filtered_rms",
    "c1_freq", "c1_score", "c2_freq", "c2_score", "c3_freq", "c3_score",
    "c4_freq", "c4_score",
]


def safe_label(label: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "_", label).strip("._")
    if not result:
        raise argparse.ArgumentTypeError("test label must contain a letter or number")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="USB serial port, for example /dev/ttyACM0")
    parser.add_argument("label", type=safe_label, help="test label, for example open_E")
    parser.add_argument("--duration", type=float, default=None,
                        help="capture duration in seconds; omit for Ctrl-C")
    args = parser.parse_args()
    if args.duration is not None and args.duration <= 0:
        parser.error("--duration must be greater than zero")

    capture_dir = Path("captures")
    capture_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = capture_dir / f"{args.label}_{timestamp}.csv"
    started = time.monotonic()
    row_count = 0

    try:
        with serial.Serial(args.port, 115200, timeout=0.25) as device, \
             output_path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=["label"] + CSV_FIELDS)
            writer.writeheader()
            print(f"capturing {args.label} to {output_path}", file=sys.stderr)
            while args.duration is None or time.monotonic() - started < args.duration:
                line = device.readline().decode("utf-8", errors="replace").strip()
                if not line or line.startswith("seq,"):
                    continue
                values = next(csv.reader([line]))
                if len(values) != len(CSV_FIELDS) or not values[0].isdigit():
                    continue
                writer.writerow(dict(zip(["label"] + CSV_FIELDS,
                                         [args.label] + values)))
                row_count += 1
            output.flush()
    except KeyboardInterrupt:
        print("capture interrupted", file=sys.stderr)

    print(f"wrote {row_count} rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
