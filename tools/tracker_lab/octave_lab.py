#!/usr/bin/env python3
"""Mac-only harmonic-family tracker experiments.

This intentionally imports the committed baseline laboratory for conditioning,
candidate extraction, pYIN evaluation, and file formats.  It changes only the
host-side candidate-family decision, so it is safe to compare experiments
without touching firmware or the committed baseline algorithm.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import analyze


@dataclass
class FamilyConfig:
    """Parameters for the causal, candidate-relative family decision.

    A candidate can replace a lower 1:2 or 1:3 relative only when it has a
    nearly equal normalized-autocorrelation score.  This protects a genuine
    low fundamental whose octave is merely a weaker harmonic peak.
    """
    family_ratio: float = 0.92
    harmonic_tolerance: float = 0.055
    promote_confirm_frames: int = 2
    sustain_slew: float = 0.42
    promoted_slew: float = 0.70


def related_multiple(high: float, low: float, tolerance: float) -> int | None:
    if low <= 0 or high <= low:
        return None
    ratio = high / low
    for multiple in (2, 3):
        if abs(ratio - multiple) / multiple <= tolerance:
            return multiple
    return None


def family_candidate(cands, cfg: FamilyConfig):
    """Pick the family representative from a single causal analysis window.

    The top autocorrelation candidate remains the default.  A higher member
    is eligible only if it is a 2x/3x relative of a lower candidate *and* its
    score is at least ``family_ratio`` of the strongest candidate.  Choosing
    the highest eligible member makes the family decision before temporal
    smoothing, rather than rewarding the long-period/subharmonic candidate.
    """
    if not cands:
        return None, False, 0.0, 0
    top = max(cands, key=lambda x: x[1])
    eligible = []
    for high in cands:
        for low in cands:
            multiple = related_multiple(high[0], low[0], cfg.harmonic_tolerance)
            if multiple and high[1] >= cfg.family_ratio * top[1]:
                eligible.append((high, low, multiple))
    if not eligible:
        return top, False, 0.0, 0
    # The highest candidate is the fundamental hypothesis represented by all
    # of its lower autocorrelation aliases.  Ties favour the higher raw score.
    chosen, base, multiple = max(eligible, key=lambda item: (item[0][0], item[0][1]))
    return chosen, True, chosen[1] / max(top[1], 1e-12), multiple


def track_family_realtime(y, cfg: analyze.TrackerConfig, family_cfg: FamilyConfig):
    filtered = analyze.lowpass_and_decimate(y, cfg)
    env, gate, onsets = analyze.envelope_trace(y, cfg)
    frame_count = max(0, (len(filtered) - cfg.window) // cfg.hop + 1)
    rows = []
    tracked = confidence = 0.0
    has_pitch = False
    hold = 0
    promotion_streak = 0
    previous_promoted_frequency = 0.0

    for n in range(frame_count):
        start = n * cfg.hop
        cands = analyze.candidates_for_window(filtered[start:start + cfg.window], cfg)
        selected, promoted, relative_score, multiple = family_candidate(cands, family_cfg)

        # Require two nearby analysis frames before accepting a family change.
        # This is causal (~21 ms at the laboratory hop) and prevents one noisy
        # ambiguous frame from creating an octave jump.
        confirmed = promoted
        if promoted and selected is not None:
            if (previous_promoted_frequency > 0 and
                    abs(math.log2(selected[0] / previous_promoted_frequency)) < 0.18):
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

        t = (start + cfg.window / 2) / cfg.analysis_rate
        sample_end = min(len(y), int((start + cfg.hop) * cfg.decimation))
        env_value = float(env[max(0, sample_end - 1)])
        gate_value = bool(gate[max(0, sample_end - 1)])
        onset = bool(np.any(onsets[max(0, sample_end - cfg.decimation * cfg.hop):sample_end]))
        selected_conf = 0.0 if selected is None else min(1.0, selected[1])
        can_acquire = (selected is not None and gate_value and env_value >= cfg.gate_on and
                       selected_conf >= cfg.acquire_confidence)
        can_hold = (selected is not None and gate_value and env_value >= cfg.gate_off and
                    selected_conf >= cfg.hold_confidence)
        if not has_pitch and can_acquire:
            tracked, confidence, has_pitch, hold = selected[0], selected_conf, True, cfg.hold_frames
        elif has_pitch and can_hold:
            slew = family_cfg.promoted_slew if confirmed else family_cfg.sustain_slew
            tracked += slew * (selected[0] - tracked)
            confidence, hold = selected_conf, cfg.hold_frames
        elif has_pitch and hold > 0:
            hold -= 1
            confidence *= .90
        else:
            has_pitch, confidence = False, 0.0

        row = {
            "time_sec": t,
            "raw_freq_hz": selected[0] if selected else 0.0,
            "raw_confidence": selected[1] if selected else 0.0,
            "tracked_freq_hz": tracked if has_pitch else 0.0,
            "tracker_confidence": confidence,
            "pitch_valid": int(has_pitch),
            "envelope": env_value,
            "gate": int(gate_value),
            "onset": int(onset),
            "family_promoted": int(confirmed),
            "family_relative_score": relative_score,
            "family_multiple": multiple,
        }
        for j in range(4):
            row[f"c{j + 1}_freq"] = cands[j][0] if j < len(cands) else 0.0
            row[f"c{j + 1}_score"] = cands[j][1] if j < len(cands) else 0.0
        rows.append(row)
    return rows


def frame_dt(rows):
    return rows[1]["time_sec"] - rows[0]["time_sec"] if len(rows) > 1 else 0.0


def metric_subset(rows, source_dt=None):
    """Run the baseline metric definition on a selected complete frame set."""
    if not rows:
        return {}
    # Frequency bands and hold-out intervals are discontinuous selections from
    # the full trace. Re-time a copy at the original hop so duration and run
    # metrics cannot be inflated by gaps between selected source frames.
    dt = source_dt if source_dt is not None else frame_dt(rows)
    contiguous = [dict(row, time_sec=i * dt) for i, row in enumerate(rows)]
    return analyze.summary(contiguous, len(contiguous) * dt)


def band_metrics(rows):
    result = {}
    dt = frame_dt(rows)
    for lo, hi in ((25, 50), (50, 75), (75, 110), (110, 200), (200, 500)):
        subset = [r for r in rows if r["reference_voiced"] and lo <= r["reference_freq_hz"] < hi]
        report = metric_subset(subset, dt)
        report["reference_band_hz"] = f"{lo}-{hi}"
        result[f"{lo}-{hi}"] = report
    return result


def holdout_metrics(rows):
    """Fixed, disjoint hold-out intervals chosen before family tuning.

    These intervals exclude the three development failure regions and retain
    low-note, sustained, and moving trajectories in the full take.
    """
    intervals = [(20, 60), (120, 180), (220, 280), (320, 380), (440, 520)]
    subset = [r for r in rows if any(lo <= r["time_sec"] < hi for lo, hi in intervals)]
    report = metric_subset(subset, frame_dt(rows))
    report["intervals_sec"] = intervals
    return report


def event_runs(rows, wanted={"octave_down", "octave_up", "large_pitch_error"}):
    dt = frame_dt(rows)
    events, start, collected = [], None, []
    for row in rows + [None]:
        if row is not None and row["classification"] in wanted:
            if start is None:
                start = row["time_sec"]
            collected.append(row)
            continue
        if start is not None:
            events.append({
                "start_sec": start,
                "end_sec": collected[-1]["time_sec"],
                "duration_sec": len(collected) * dt,
                "classification": collected[0]["classification"],
                "reference_median_hz": float(np.median([r["reference_freq_hz"] for r in collected])),
                "tracked_median_hz": float(np.median([r["tracked_freq_hz"] for r in collected])),
            })
        start, collected = None, []
    return sorted(events, key=lambda x: x["duration_sec"], reverse=True)


def plot_outputs(rows, out: Path, events):
    t = np.asarray([r["time_sec"] for r in rows])
    ref = np.asarray([r["reference_freq_hz"] for r in rows])
    raw = np.asarray([r["raw_freq_hz"] for r in rows])
    tracked = np.asarray([r["tracked_freq_hz"] for r in rows])
    valid = np.asarray([r["pitch_valid"] for r in rows], bool)
    voiced = np.asarray([r["reference_voiced"] for r in rows], bool)
    confidence = np.asarray([r["tracker_confidence"] for r in rows])
    promoted = np.asarray([r["family_promoted"] for r in rows], bool)
    error = np.asarray([float(r["error_cents"]) if r["error_cents"] != "" else np.nan for r in rows])
    plt.figure(figsize=(16, 6))
    plt.plot(t, np.where(voiced, ref, np.nan), label="pYIN reference", linewidth=.8)
    plt.plot(t, np.where(raw > 0, raw, np.nan), label="family representative", alpha=.40, linewidth=.5)
    plt.plot(t, np.where(valid, tracked, np.nan), label="tracked", linewidth=1)
    plt.scatter(t[promoted], tracked[promoted], s=2, label="confirmed family promotion")
    plt.yscale("log"); plt.ylim(20, 550); plt.xlabel("time (s)"); plt.ylabel("frequency (Hz)")
    plt.legend(); plt.grid(alpha=.2); plt.tight_layout(); plt.savefig(out / "pitch.png", dpi=150); plt.close()
    plt.figure(figsize=(16, 4)); plt.axhline(0, color="k", linewidth=.5); plt.axhline(1200, color="r", alpha=.35); plt.axhline(-1200, color="r", alpha=.35)
    plt.plot(t, error, linewidth=.7); plt.ylim(-2500, 2500); plt.xlabel("time (s)"); plt.ylabel("error (cents)"); plt.grid(alpha=.2); plt.tight_layout(); plt.savefig(out / "error.png", dpi=150); plt.close()
    plt.figure(figsize=(16, 3)); plt.plot(t, confidence, label="tracker confidence"); plt.fill_between(t, 0, valid.astype(float), alpha=.2, label="pitch valid")
    plt.ylim(0, 1.05); plt.xlabel("time (s)"); plt.ylabel("confidence / valid"); plt.legend(); plt.grid(alpha=.2); plt.tight_layout(); plt.savefig(out / "confidence.png", dpi=150); plt.close()
    failure_dir = out / "failures"; failure_dir.mkdir(exist_ok=True)
    for i, event in enumerate(events[:8], 1):
        center = (event["start_sec"] + event["end_sec"]) / 2
        mask = (t >= center - 1.5) & (t <= center + 1.5)
        plt.figure(figsize=(12, 4)); plt.plot(t[mask], np.where(voiced[mask], ref[mask], np.nan), label="pYIN reference")
        plt.plot(t[mask], np.where(valid[mask], tracked[mask], np.nan), label="family tracked")
        plt.plot(t[mask], np.where(raw[mask] > 0, raw[mask], np.nan), alpha=.40, label="family candidate")
        plt.yscale("log"); plt.ylim(20, 550); plt.title(f"{event['classification']} {event['start_sec']:.3f}-{event['end_sec']:.3f}s")
        plt.legend(); plt.grid(alpha=.2); plt.tight_layout(); plt.savefig(failure_dir / f"failure_{i:02d}_{center:.3f}s.png", dpi=150); plt.close()


def write_outputs(y, sr, info, channel_corr, rows, out: Path, cfg, family_cfg, args):
    out.mkdir(parents=True, exist_ok=True)
    analyze.interpolate_reference(rows, *analyze.offline_reference(y, sr, cfg))
    report = analyze.summary(rows, len(y) / sr)
    report["frequency_band_metrics"] = band_metrics(rows)
    report["holdout_metrics"] = holdout_metrics(rows)
    events = event_runs(rows)
    report["important_remaining_events"] = events[:20]
    plot_outputs(rows, out, events)
    if not args.no_monitors:
        analyze.render_monitor(y, sr, rows, out / "tracker_monitor.wav", False)
        analyze.render_monitor(y, sr, rows, out / "reference_monitor.wav", True)
    config = {
        "experiment": "candidate-relative harmonic-family selection",
        "hypothesis": "A high 2x/3x candidate with near-equal autocorrelation score is a stronger fundamental hypothesis than its long-period alias; weak upper harmonics must not promote real low notes.",
        "baseline_tracker_config": asdict(cfg),
        "family_config": asdict(family_cfg),
        "input": str(args.input), "start_sec": args.start, "duration_sec": len(y) / sr,
        "sample_rate": sr, "source_channels": info.channels, "source_subtype": info.subtype,
        "channel_correlation": channel_corr, "audio_metrics": analyze.signal_metrics(y),
    }
    (out / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    with (out / "summary.txt").open("w") as f:
        for key, value in report.items():
            if key not in {"frequency_band_metrics", "holdout_metrics", "important_remaining_events"}:
                f.write(f"{key}: {value}\n")
        f.write("\nFrequency bands:\n" + json.dumps(report["frequency_band_metrics"], indent=2) + "\n")
        f.write("\nHold-out:\n" + json.dumps(report["holdout_metrics"], indent=2) + "\n")
        f.write("\nRemaining events:\n" + json.dumps(events[:20], indent=2) + "\n")
    fields = list(rows[0])
    with (out / "frames.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("tracker_runs/octave_exp"))
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--family-ratio", type=float, default=.92)
    parser.add_argument("--confirm-frames", type=int, default=2)
    parser.add_argument("--promoted-slew", type=float, default=.70)
    parser.add_argument("--no-monitors", action="store_true")
    args = parser.parse_args()
    cfg = analyze.TrackerConfig()
    family_cfg = FamilyConfig(family_ratio=args.family_ratio, promote_confirm_frames=args.confirm_frames,
                              promoted_slew=args.promoted_slew)
    y, sr, info, channel_corr = analyze.load_audio(args.input, args.start, args.duration)
    rows = track_family_realtime(y, cfg, family_cfg)
    report = write_outputs(y, sr, info, channel_corr, rows, args.output_dir, cfg, family_cfg, args)
    print(json.dumps({"output_dir": str(args.output_dir), **report}, indent=2))


if __name__ == "__main__":
    main()
