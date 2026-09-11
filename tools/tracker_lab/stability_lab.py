#!/usr/bin/env python3
"""Mac-only causal stability experiments on octave-family tracker output.

The input is a complete causal octave-family trajectory.  Experiments here
preserve its candidate/family decisions and change only the final, causal
frequency conditioning step.  This makes jitter work independently auditable.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import math
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import analyze
import octave_lab
import replay_family


SLIDE_REGIONS = [
    (159.70, 160.25, "slide_160s"),
    (162.75, 163.40, "slide_163s"),
    (170.15, 170.75, "slide_170s"),
    (375.50, 376.25, "slide_376s"),
]
SLICES_PATH = Path(__file__).with_name("stability_slices.json")


@dataclass
class StabilityConfig:
    method: str = "adaptive_median3"
    median_window: int = 3
    stable_alpha: float = 0.18
    moving_alpha: float = 0.72
    motion_cents: float = 12.0
    bypass_cents: float = 140.0
    stable_reference_delta_cents: float = 10.0
    micro_jump_cents: float = 35.0
    return_cents: float = 18.0
    return_frames: int = 4
    persistence_cents: float = 28.0
    persistence_match_cents: float = 18.0


def cents(a: float, b: float) -> float:
    return 1200.0 * math.log2(a / b) if a > 0 and b > 0 else 0.0


def recompute_row(row):
    if row["pitch_valid"] and row["reference_voiced"] and row["reference_freq_hz"] > 0:
        row["error_cents"] = cents(row["tracked_freq_hz"], row["reference_freq_hz"])
    else:
        row["error_cents"] = ""
    row["classification"] = analyze.classify(row)
    row["octave_error"] = 1 if row["classification"] == "octave_up" else -1 if row["classification"] == "octave_down" else 0


def stabilize(rows, cfg: StabilityConfig):
    """Apply a causal median/adaptive-one-pole layer in log-frequency space."""
    rows = copy.deepcopy(rows)
    targets: deque[float] = deque(maxlen=max(3, cfg.median_window * 2))
    out = 0.0
    previous_env = 0.0
    pending_target = 0.0
    for row in rows:
        target = float(row["tracked_freq_hz"])
        if not row["pitch_valid"] or target <= 0:
            targets.clear(); out = 0.0
            row["stability_mode"] = "invalid"
            row["stability_alpha"] = 0.0
            recompute_row(row)
            continue
        targets.append(target)
        median_target = float(np.median(list(targets)[-cfg.median_window:]))
        if cfg.method == "none":
            conditioned = target
            mode, alpha = "passthrough", 1.0
        elif cfg.method == "median3":
            conditioned = median_target
            mode, alpha = "median", 1.0
        elif cfg.method == "persistence":
            # A possible isolated tracker excursion is held for one causal
            # hop.  A consistent replacement wins immediately on its second
            # observation.  Small musical motion is never held.
            step = abs(cents(target, out)) if out else 0.0
            if not out or step < cfg.persistence_cents:
                conditioned = target
                pending_target = 0.0
                mode, alpha = "pass-small", 1.0
            elif pending_target and abs(cents(target, pending_target)) <= cfg.persistence_match_cents:
                conditioned = target
                pending_target = 0.0
                mode, alpha = "confirmed", 1.0
            else:
                conditioned = out
                pending_target = target
                mode, alpha = "hold-one", 0.0
        else:
            # A causal trend compares the newest short median with an older
            # short median. Random nearby peaks do not form a trend; slides,
            # bends, attacks, and genuine note changes do.
            past = list(targets)
            filter_target = median_target if cfg.method == "adaptive_median3" else target
            trend = cents(filter_target, float(np.median(past[-6:-3]))) if len(past) >= 6 else 0.0
            step = cents(filter_target, out) if out else 0.0
            attack = bool(row.get("onset", 0)) or (previous_env > 0 and row["envelope"] > previous_env * 1.25)
            family_change = bool(row.get("family_promoted", 0))
            moving = attack or family_change or abs(step) >= cfg.bypass_cents or abs(trend) >= cfg.motion_cents
            alpha = cfg.moving_alpha if moving else cfg.stable_alpha
            mode = "moving" if moving else "stable"
            if not out:
                conditioned = filter_target
            else:
                # Interpolate in log-frequency space so smoothing is cents
                # symmetric above/below the target.
                conditioned = out * (2.0 ** (alpha * cents(filter_target, out) / 1200.0))
        row["stability_input_hz"] = target
        row["tracked_freq_hz"] = conditioned
        row["stability_mode"] = mode
        row["stability_alpha"] = alpha
        out, previous_env = conditioned, row["envelope"]
        recompute_row(row)
    return rows


def stable_mask(rows, ref_delta_limit):
    n = len(rows)
    result = np.zeros(n, dtype=bool)
    for i in range(4, n):
        window = rows[i - 4:i + 1]
        if not all(r["reference_voiced"] and r["pitch_valid"] and r["error_cents"] != "" and abs(float(r["error_cents"])) <= 100 for r in window):
            continue
        deltas = [abs(cents(window[j]["reference_freq_hz"], window[j - 1]["reference_freq_hz"])) for j in range(1, len(window))]
        result[i] = max(deltas) <= ref_delta_limit
    return result


def percentile(values, q):
    return float(np.percentile(values, q)) if len(values) else None


def stability_metrics(rows, cfg: StabilityConfig):
    dt = octave_lab.frame_dt(rows)
    stable = stable_mask(rows, cfg.stable_reference_delta_cents)
    deltas, local_stds, micro_events, candidate_events, suspicious_events, stable_moves = [], [], [], [], [], []
    for i in range(1, len(rows)):
        if stable[i] and stable[i - 1]:
            delta = abs(cents(rows[i]["tracked_freq_hz"], rows[i - 1]["tracked_freq_hz"]))
            deltas.append(delta)
            reference_delta = abs(cents(rows[i]["reference_freq_hz"], rows[i - 1]["reference_freq_hz"]))
            stable_moves.append({"time_sec": rows[i]["time_sec"], "tracked_delta_cents": delta, "reference_delta_cents": reference_delta})
            if delta >= 8.0 and delta >= reference_delta + 6.0:
                suspicious_events.append({"time_sec": rows[i]["time_sec"], "tracked_delta_cents": delta, "reference_delta_cents": reference_delta})
    for i in range(4, len(rows)):
        if np.all(stable[i - 4:i + 1]):
            values = [1200 * math.log2(r["tracked_freq_hz"]) for r in rows[i - 4:i + 1]]
            local_stds.append(float(np.std(values)))
    last_event_end = -1
    for i in range(1, len(rows) - 1):
        if i <= last_event_end or not (stable[i] and stable[i - 1]):
            continue
        delta = abs(cents(rows[i]["tracked_freq_hz"], rows[i - 1]["tracked_freq_hz"]))
        candidate_delta = abs(cents(rows[i].get("raw_freq_hz", 0), rows[i - 1].get("raw_freq_hz", 0)))
        if delta >= cfg.micro_jump_cents:
            for j in range(i + 1, min(len(rows), i + cfg.return_frames + 1)):
                if stable[j] and abs(cents(rows[j]["tracked_freq_hz"], rows[i - 1]["tracked_freq_hz"])) <= cfg.return_cents:
                    micro_events.append({"time_sec": rows[i]["time_sec"], "return_time_sec": rows[j]["time_sec"], "duration_sec": (j - i + 1) * dt, "tracked_delta_cents": delta, "reference_delta_cents": abs(cents(rows[i]["reference_freq_hz"], rows[i - 1]["reference_freq_hz"]))})
                    last_event_end = j
                    break
        if candidate_delta >= cfg.micro_jump_cents:
            for j in range(i + 1, min(len(rows), i + cfg.return_frames + 1)):
                if stable[j] and abs(cents(rows[j].get("raw_freq_hz", 0), rows[i - 1].get("raw_freq_hz", 0))) <= cfg.return_cents:
                    candidate_events.append({"time_sec": rows[i]["time_sec"], "return_time_sec": rows[j]["time_sec"], "duration_sec": (j - i + 1) * dt, "candidate_delta_cents": candidate_delta})
                    break
    transitions = transition_metrics(rows)
    slides = slide_metrics(rows)
    return {
        "definition": {
            "stable_region": "five consecutive voiced, valid, within-100-cent frames with every reference frame delta <= 10 cents",
            "micro_jump": "a >=35-cent tracked frame step in a stable region that returns within 18 cents of its prior value within four causal hops",
            "frame_delta": "absolute cents difference between adjacent tracked frames in stable regions",
        },
        "stable_region_duration_sec": int(np.sum(stable)) * dt,
        "stable_region_frame_delta_cents": {"median": percentile(deltas, 50), "p90": percentile(deltas, 90), "p99": percentile(deltas, 99), "max": max(deltas) if deltas else None},
        "stable_region_short_term_std_cents": {"median": percentile(local_stds, 50), "p90": percentile(local_stds, 90), "p99": percentile(local_stds, 99)},
        "micro_jump_count": len(micro_events),
        "micro_jump_duration_sec": sum(x["duration_sec"] for x in micro_events),
        "candidate_micro_switch_count": len(candidate_events),
        "worst_micro_jumps": sorted(micro_events, key=lambda x: x["tracked_delta_cents"], reverse=True)[:20],
        "suspicious_excess_motion_count": len(suspicious_events),
        "worst_suspicious_excess_motion": sorted(suspicious_events, key=lambda x: x["tracked_delta_cents"], reverse=True)[:20],
        "worst_stable_frame_moves": sorted(stable_moves, key=lambda x: x["tracked_delta_cents"], reverse=True)[:20],
        "state_frame_delta_cents": state_metrics(rows, stable),
        "transition": transitions,
        "slides": slides,
        "regression_slices": regression_slice_metrics(rows),
    }


def distribution(values):
    return {"count": len(values), "median": percentile(values, 50), "p90": percentile(values, 90), "p99": percentile(values, 99)}


def state_metrics(rows, stable):
    """Evaluation-only attack/transition/slide/decay separation."""
    dt = octave_lab.frame_dt(rows)
    slide = np.asarray([any(start <= r["time_sec"] <= stop for start, stop, _ in SLIDE_REGIONS) for r in rows])
    attack = np.zeros(len(rows), dtype=bool)
    transition = np.zeros(len(rows), dtype=bool)
    decay = np.zeros(len(rows), dtype=bool)
    attack_frames = max(1, int(round(.10 / dt)))
    for i, row in enumerate(rows):
        if row["reference_voiced"] and (i == 0 or not rows[i - 1]["reference_voiced"]):
            attack[i:min(len(rows), i + attack_frames)] = True
        if i and row["reference_voiced"] and rows[i - 1]["reference_voiced"] and abs(cents(row["reference_freq_hz"], rows[i - 1]["reference_freq_hz"])) >= 30:
            transition[max(0, i - 1):min(len(rows), i + attack_frames)] = True
        if i >= 45 and row["reference_voiced"]:
            recent_peak = max(float(r["envelope"]) for r in rows[i - 45:i + 1])
            falling = float(row["envelope"]) < float(rows[i - 5]["envelope"])
            decay[i] = recent_peak > 0 and float(row["envelope"]) <= .45 * recent_peak and falling
    masks = {
        "stable_sustain": stable & ~attack & ~transition & ~slide & ~decay,
        "attack": attack,
        "transition": transition,
        "slide_or_bend": slide,
        "decay": decay,
    }
    result = {}
    for name, mask in masks.items():
        values = []
        for i in range(1, len(rows)):
            if mask[i] and mask[i - 1] and rows[i]["pitch_valid"] and rows[i - 1]["pitch_valid"]:
                values.append(abs(cents(rows[i]["tracked_freq_hz"], rows[i - 1]["tracked_freq_hz"])))
        result[name] = distribution(values)
    result["definitions"] = {
        "attack": "first 100 ms after each pYIN unvoiced-to-voiced boundary",
        "transition": "100 ms after a >=30-cent pYIN frame step",
        "slide_or_bend": "frames in the fixed named slide windows",
        "decay": "voiced, falling envelope below 45% of the preceding 480-ms peak",
    }
    return result


def regression_slice_metrics(rows):
    if not SLICES_PATH.exists():
        return {}
    manifest = json.loads(SLICES_PATH.read_text())
    dt = octave_lab.frame_dt(rows)
    result = {}
    for partition in ("development", "holdout"):
        result[partition] = []
        for item in manifest[partition]:
            selected = [r for r in rows if item["start_sec"] <= r["time_sec"] <= item["end_sec"]]
            errors = [abs(float(r["error_cents"])) for r in selected if r["reference_voiced"] and r["pitch_valid"] and r["error_cents"] != ""]
            frame_deltas = [abs(cents(selected[i]["tracked_freq_hz"], selected[i - 1]["tracked_freq_hz"])) for i in range(1, len(selected)) if selected[i]["pitch_valid"] and selected[i - 1]["pitch_valid"]]
            result[partition].append({
                **item,
                "median_abs_cents": percentile(errors, 50),
                "p90_abs_cents": percentile(errors, 90),
                "within_25": sum(x <= 25 for x in errors) / len(errors) if errors else None,
                "octave_down_duration_sec": sum(r["classification"] == "octave_down" for r in selected) * dt,
                "octave_up_duration_sec": sum(r["classification"] == "octave_up" for r in selected) * dt,
                "frame_delta_cents": distribution(frame_deltas),
            })
    return result


def transition_metrics(rows):
    dt = octave_lab.frame_dt(rows)
    lags = []
    for i in range(1, len(rows) - 4):
        current, previous = rows[i], rows[i - 1]
        if not (current["reference_voiced"] and previous["reference_voiced"] and current["pitch_valid"]):
            continue
        change = abs(cents(current["reference_freq_hz"], previous["reference_freq_hz"]))
        if change < 80:
            continue
        # New target must settle enough to avoid treating a slide as a note step.
        if any(not rows[j]["reference_voiced"] or abs(cents(rows[j]["reference_freq_hz"], current["reference_freq_hz"])) > 30 for j in range(i + 1, min(i + 4, len(rows)))):
            continue
        for j in range(i, min(len(rows), i + int(.30 / dt) + 1)):
            if rows[j]["pitch_valid"] and abs(cents(rows[j]["tracked_freq_hz"], current["reference_freq_hz"])) <= 50:
                lags.append(rows[j]["time_sec"] - current["time_sec"])
                break
    return {"definition": "reference step >=80 cents settling within three frames; lag is first subsequent tracker frame within 50 cents", "event_count": len(lags), "lag_median_sec": percentile(lags, 50), "lag_p90_sec": percentile(lags, 90)}


def slide_metrics(rows):
    reports = []
    for start, stop, name in SLIDE_REGIONS:
        selected = [r for r in rows if start <= r["time_sec"] <= stop and r["reference_voiced"] and r["pitch_valid"]]
        if len(selected) < 4:
            continue
        t = np.asarray([r["time_sec"] for r in selected])
        ref = np.asarray([1200 * math.log2(r["reference_freq_hz"]) for r in selected])
        tracked = np.asarray([1200 * math.log2(r["tracked_freq_hz"]) for r in selected])
        best_lag, best_error = 0.0, float("inf")
        for lag in np.arange(0, .129, .0106666667):
            shifted = np.interp(t + lag, t, tracked, left=np.nan, right=np.nan)
            error = np.nanmedian(np.abs(shifted - ref))
            if error < best_error:
                best_lag, best_error = float(lag), float(error)
        reports.append({"name": name, "start_sec": start, "end_sec": stop, "reference_span_cents": float(np.ptp(ref)), "tracker_span_cents": float(np.ptp(tracked)), "reference_slope_cents_per_sec": float(np.polyfit(t, ref, 1)[0]), "tracker_slope_cents_per_sec": float(np.polyfit(t, tracked, 1)[0]), "estimated_causal_lag_sec": best_lag, "max_abs_deviation_cents": float(np.max(np.abs(tracked - ref)) )})
    return reports


def plot_stability(rows, metrics, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    t = np.asarray([r["time_sec"] for r in rows])
    tr = np.asarray([r["tracked_freq_hz"] for r in rows])
    ref = np.asarray([r["reference_freq_hz"] for r in rows])
    stable = stable_mask(rows, StabilityConfig().stable_reference_delta_cents)
    delta = np.full(len(rows), np.nan)
    for i in range(1, len(rows)):
        if stable[i] and stable[i - 1]: delta[i] = cents(tr[i], tr[i - 1])
    plt.figure(figsize=(16, 4)); plt.axhline(0, color="k", linewidth=.5); plt.plot(t, delta, linewidth=.45); plt.ylim(-150, 150); plt.xlabel("time (s)"); plt.ylabel("stable-region tracked frame delta (cents)"); plt.grid(alpha=.2); plt.tight_layout(); plt.savefig(out / "stability.png", dpi=150); plt.close()
    zoom = out / "stability_failures"; zoom.mkdir(exist_ok=True)
    for index, event in enumerate(metrics["worst_micro_jumps"][:8], 1):
        center = event["time_sec"]; mask = (t >= center - .35) & (t <= center + .35)
        plt.figure(figsize=(11, 4)); plt.plot(t[mask], ref[mask], label="pYIN reference"); plt.plot(t[mask], tr[mask], label="tracked"); plt.yscale("log"); plt.ylim(20, 250); plt.title(f"micro-jump {event['tracked_delta_cents']:.1f} cents at {center:.3f}s"); plt.xlabel("time (s)"); plt.ylabel("Hz"); plt.legend(); plt.grid(alpha=.2); plt.tight_layout(); plt.savefig(zoom / f"micro_{index:02d}_{center:.3f}s.png", dpi=150); plt.close()
    for index, event in enumerate(metrics["worst_stable_frame_moves"][:6], 1):
        center = event["time_sec"]; mask = (t >= center - .35) & (t <= center + .35)
        plt.figure(figsize=(11, 4)); plt.plot(t[mask], ref[mask], label="pYIN reference"); plt.plot(t[mask], tr[mask], label="stability output")
        source = np.asarray([float(r.get("stability_input_hz", r["tracked_freq_hz"])) for r in rows])
        plt.plot(t[mask], source[mask], label="octave_v1 input", alpha=.7); plt.yscale("log"); plt.ylim(20, 250)
        plt.title(f"large stable-frame movement {event['tracked_delta_cents']:.1f} cents at {center:.3f}s"); plt.xlabel("time (s)"); plt.ylabel("Hz"); plt.legend(); plt.grid(alpha=.2); plt.tight_layout(); plt.savefig(zoom / f"movement_{index:02d}_{center:.3f}s.png", dpi=150); plt.close()
    slides = out / "slides"; slides.mkdir(exist_ok=True)
    for start, stop, name in SLIDE_REGIONS:
        mask = (t >= start) & (t <= stop)
        if not np.any(mask): continue
        plt.figure(figsize=(11, 4)); plt.plot(t[mask], ref[mask], label="pYIN reference"); plt.plot(t[mask], tr[mask], label="tracked"); plt.yscale("log"); plt.ylim(25, 180); plt.title(name); plt.xlabel("time (s)"); plt.ylabel("Hz"); plt.legend(); plt.grid(alpha=.2); plt.tight_layout(); plt.savefig(slides / f"{name}.png", dpi=150); plt.close()


def write_run(rows, cfg, out: Path, input_path: Path):
    out.mkdir(parents=True, exist_ok=True)
    report = analyze.summary(rows, rows[-1]["time_sec"] + octave_lab.frame_dt(rows))
    report["frequency_band_metrics"] = octave_lab.band_metrics(rows)
    report["holdout_metrics"] = octave_lab.holdout_metrics(rows)
    metrics = stability_metrics(rows, cfg)
    report["stability_metrics"] = metrics
    events = octave_lab.event_runs(rows); report["important_remaining_events"] = events[:20]
    octave_lab.plot_outputs(rows, out, events)
    plot_stability(rows, metrics, out)
    hypotheses = {
        "none": "Unmodified input trajectory used as a control.",
        "median3": "A causal median-of-three may reject isolated frequency excursions with one-hop latency.",
        "persistence": "A >=28-cent replacement must repeat before replacing the current trajectory.",
        "adaptive_median3": "Median-of-three plus a log-frequency one-pole may stabilize sustains while bypassing movement.",
        "adaptive_onepole": "A log-frequency one-pole is active only for nearby non-trending motion; attacks, confirmed family promotion, >=8-cent trends, and >=140-cent steps bypass it at full speed.",
    }
    config = {"experiment": cfg.method, "hypothesis": hypotheses[cfg.method], "input_frames": str(input_path), "stability_config": asdict(cfg)}
    (out / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / "stability_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    with (out / "summary.txt").open("w") as f:
        for k, v in report.items():
            if k not in {"frequency_band_metrics", "holdout_metrics", "stability_metrics", "important_remaining_events"}: f.write(f"{k}: {v}\n")
        f.write("\nStability metrics:\n" + json.dumps(metrics, indent=2) + "\n")
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (out / "frames.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=Path("tools/tracker_lab/experiments/octave_v1/frames.csv.gz"))
    p.add_argument("--output-dir", type=Path, default=Path("tracker_runs/stability"))
    p.add_argument("--method", choices=("none", "median3", "adaptive_median3", "adaptive_onepole", "persistence"), default="adaptive_median3")
    p.add_argument("--stable-alpha", type=float, default=.18)
    p.add_argument("--moving-alpha", type=float, default=.72)
    p.add_argument("--motion-cents", type=float, default=12.)
    p.add_argument("--persistence-cents", type=float, default=28.)
    p.add_argument("--persistence-match-cents", type=float, default=18.)
    args = p.parse_args()
    cfg = StabilityConfig(method=args.method, stable_alpha=args.stable_alpha, moving_alpha=args.moving_alpha, motion_cents=args.motion_cents, persistence_cents=args.persistence_cents, persistence_match_cents=args.persistence_match_cents)
    rows = replay_family.read_rows(args.input)
    for row in rows:
        # These fields were added by the octave-family experiment and are not
        # needed by its original CSV reader. Parse them explicitly here rather
        # than relying on truthiness of the strings "0" and "1".
        row["family_promoted"] = int(row.get("family_promoted", 0) or 0)
        row["family_relative_score"] = float(row.get("family_relative_score", 0) or 0)
        row["family_multiple"] = int(row.get("family_multiple", 0) or 0)
    report = write_run(stabilize(rows, cfg), cfg, args.output_dir, args.input)
    print(json.dumps({"output_dir": str(args.output_dir), **report}, indent=2))


if __name__ == "__main__":
    main()
