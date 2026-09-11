#!/usr/bin/env python3
"""Evaluate a family selector over the committed baseline candidate trace.

The baseline trace is the exact output of the committed causal front end for
all 54,514 windows. Replaying it makes harmonic-family experiments fast and
repeatable without changing the input, reference alignment, gate, or window.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from dataclasses import asdict
from pathlib import Path

import analyze
import octave_lab


NUMERIC = {"time_sec", "raw_freq_hz", "raw_confidence", "tracked_freq_hz", "tracker_confidence", "envelope", "reference_freq_hz", "reference_confidence"}
for i in range(1, 5):
    NUMERIC.update({f"c{i}_freq", f"c{i}_score"})
INTEGER = {"pitch_valid", "gate", "onset", "reference_voiced", "octave_error"}


def read_rows(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as f:
        result = []
        for original in csv.DictReader(f):
            row = dict(original)
            for key in NUMERIC:
                row[key] = float(row[key]) if row.get(key, "") != "" else 0.0
            for key in INTEGER:
                row[key] = int(row[key]) if row.get(key, "") != "" else 0
            result.append(row)
    return result


def replay(rows, tracker_cfg, family_cfg):
    tracked = confidence = 0.0
    has_pitch = False
    hold = 0
    promotion_streak = 0
    previous_promoted_frequency = 0.0
    for row in rows:
        cands = [(row[f"c{i}_freq"], row[f"c{i}_score"], 0) for i in range(1, 5) if row[f"c{i}_freq"] > 0]
        selected, promoted, relative_score, multiple = octave_lab.family_candidate(cands, family_cfg)
        confirmed = promoted
        if promoted and selected:
            if previous_promoted_frequency and abs(math.log2(selected[0] / previous_promoted_frequency)) < .18:
                promotion_streak += 1
            else:
                promotion_streak = 1
            previous_promoted_frequency = selected[0]
            confirmed = promotion_streak >= family_cfg.promote_confirm_frames
        else:
            promotion_streak = 0
            previous_promoted_frequency = 0.0
        if promoted and not confirmed:
            selected = max(cands, key=lambda x: x[1]) if cands else None
        selected_conf = min(1.0, selected[1]) if selected else 0.0
        can_acquire = bool(selected and row["gate"] and row["envelope"] >= tracker_cfg.gate_on and selected_conf >= tracker_cfg.acquire_confidence)
        can_hold = bool(selected and row["gate"] and row["envelope"] >= tracker_cfg.gate_off and selected_conf >= tracker_cfg.hold_confidence)
        if not has_pitch and can_acquire:
            tracked, confidence, has_pitch, hold = selected[0], selected_conf, True, tracker_cfg.hold_frames
        elif has_pitch and can_hold:
            slew = family_cfg.promoted_slew if confirmed else family_cfg.sustain_slew
            tracked += slew * (selected[0] - tracked)
            confidence, hold = selected_conf, tracker_cfg.hold_frames
        elif has_pitch and hold > 0:
            hold -= 1
            confidence *= .9
        else:
            has_pitch, confidence = False, 0.0
        row["raw_freq_hz"] = selected[0] if selected else 0.0
        row["raw_confidence"] = selected[1] if selected else 0.0
        row["tracked_freq_hz"] = tracked if has_pitch else 0.0
        row["tracker_confidence"] = confidence
        row["pitch_valid"] = int(has_pitch)
        row["family_promoted"] = int(confirmed)
        row["family_relative_score"] = relative_score
        row["family_multiple"] = multiple
        if has_pitch and row["reference_voiced"] and row["reference_freq_hz"] > 0:
            row["error_cents"] = 1200 * math.log2(tracked / row["reference_freq_hz"])
        else:
            row["error_cents"] = ""
        row["classification"] = analyze.classify(row)
        row["octave_error"] = 1 if row["classification"] == "octave_up" else -1 if row["classification"] == "octave_down" else 0
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", type=Path, default=Path("tools/tracker_lab/baseline/frames.csv.gz"))
    p.add_argument("--output-dir", type=Path, default=Path("tracker_runs/octave_replay"))
    p.add_argument("--family-ratio", type=float, default=.92)
    p.add_argument("--confirm-frames", type=int, default=2)
    p.add_argument("--promoted-slew", type=float, default=.70)
    args = p.parse_args()
    cfg = analyze.TrackerConfig()
    family = octave_lab.FamilyConfig(family_ratio=args.family_ratio, promote_confirm_frames=args.confirm_frames,
                                     promoted_slew=args.promoted_slew)
    rows = replay(read_rows(args.baseline), cfg, family)
    out = args.output_dir; out.mkdir(parents=True, exist_ok=True)
    report = analyze.summary(rows, rows[-1]["time_sec"] + (rows[1]["time_sec"] - rows[0]["time_sec"]))
    report["frequency_band_metrics"] = octave_lab.band_metrics(rows)
    report["holdout_metrics"] = octave_lab.holdout_metrics(rows)
    events = octave_lab.event_runs(rows); report["important_remaining_events"] = events[:20]
    octave_lab.plot_outputs(rows, out, events)
    config = {"experiment": "candidate-relative harmonic-family selection", "evaluation_mode": "full committed baseline candidate-trace replay", "baseline_frames": str(args.baseline), "baseline_tracker_config": asdict(cfg), "family_config": asdict(family)}
    (out / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    with (out / "summary.txt").open("w") as f:
        for k, v in report.items():
            if k not in {"frequency_band_metrics", "holdout_metrics", "important_remaining_events"}: f.write(f"{k}: {v}\n")
        f.write("\nFrequency bands:\n" + json.dumps(report["frequency_band_metrics"], indent=2) + "\n")
        f.write("\nHoldout:\n" + json.dumps(report["holdout_metrics"], indent=2) + "\n")
        f.write("\nEvents:\n" + json.dumps(events[:20], indent=2) + "\n")
    fields = list(rows[0])
    with (out / "frames.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    print(json.dumps({"output_dir": str(out), **report}, indent=2))


if __name__ == "__main__":
    main()
