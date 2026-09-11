#!/usr/bin/env python3
"""Mac-only audible synth-envelope experiments on a fixed tracker trajectory.

This module deliberately never changes a tracker field.  It reads the committed
stability_v1 frames, derives a separate causal ``synth_gain`` control signal,
and evaluates/render that signal against the unchanged tracked oscillator pitch.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "experiments" / "stability_v1" / "frames.csv.gz"
DEFAULT_SOURCE = ROOT.parent.parent / "basik hehe.wav"
SLIDES = [(159.70, 160.25, "slide_160s"), (162.75, 163.40, "slide_163s"),
          (170.15, 170.75, "slide_170s"), (375.50, 376.25, "slide_376s")]
DECAYS = [(129.55, 130.45, "decay_130s"), (249.65, 250.85, "decay_250s"),
          (432.45, 433.00, "decay_432s")]


@dataclass(frozen=True)
class EnvelopeConfig:
    name: str
    description: str
    audible_on: float
    audible_off: float
    nominal_level: float
    attack_ms: float
    release_ms: float
    require_pitch_valid: bool = True
    confidence_tail_floor: float = 0.0


CONFIGS = (
    EnvelopeConfig("envelope_01", "Log-normalized source envelope with hysteresis and 180 ms release.",
                   0.0012, 0.0007, 0.020, 4.0, 180.0),
    EnvelopeConfig("envelope_02", "More conservative tail cutoff; same source-driven causal release.",
                   0.0020, 0.0012, 0.012, 4.0, 120.0),
    EnvelopeConfig("envelope_03", "Envelope_01 plus a deliberately mild confidence taper only below 30% gain.",
                   0.0012, 0.0007, 0.020, 4.0, 180.0, confidence_tail_floor=0.70),
)


def fnum(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def inum(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def load_rows(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in ("time_sec", "tracked_freq_hz", "raw_freq_hz", "envelope", "tracker_confidence",
                    "reference_freq_hz", "reference_confidence", "error_cents", "stability_alpha"):
            row[key] = fnum(row.get(key))
        for key in ("pitch_valid", "gate", "onset", "reference_voiced", "family_promoted"):
            row[key] = inum(row.get(key))
    return rows


def frame_dt(rows):
    return rows[1]["time_sec"] - rows[0]["time_sec"]


def log_normalize(level, off, nominal):
    if level <= off:
        return 0.0
    return float(np.clip(math.log(level / off) / math.log(nominal / off), 0.0, 1.0))


def apply_envelope(source_rows, cfg: EnvelopeConfig | None):
    """Return copied rows with gain fields; tracker trajectory stays byte-equivalent."""
    dt = frame_dt(source_rows)
    out = [dict(row) for row in source_rows]
    if cfg is None:
        for row in out:
            row["normalized_envelope"] = 1.0 if row["pitch_valid"] else 0.0
            row["synth_target_gain"] = row["normalized_envelope"]
            row["synth_gain"] = row["normalized_envelope"]
            row["audible_latched"] = row["pitch_valid"]
            row["tail_confidence_taper"] = 1.0
        return out

    latched = False
    gain = 0.0
    attack_c = 1.0 - math.exp(-dt / (cfg.attack_ms / 1000.0))
    release_c = 1.0 - math.exp(-dt / (cfg.release_ms / 1000.0))
    for row in out:
        env = row["envelope"]
        if not latched and env >= cfg.audible_on:
            latched = True
        elif latched and env <= cfg.audible_off:
            latched = False
        normalized = log_normalize(env, cfg.audible_off, cfg.nominal_level)
        taper = 1.0
        # Optional experimental taper is intentionally limited to quiet tails.
        if cfg.confidence_tail_floor and normalized < 0.30:
            confidence = float(np.clip(row["tracker_confidence"], 0.0, 1.0))
            taper = cfg.confidence_tail_floor + (1.0 - cfg.confidence_tail_floor) * confidence
        target = normalized * taper if latched else 0.0
        if cfg.require_pitch_valid and not row["pitch_valid"]:
            target = 0.0
        coefficient = attack_c if target > gain else release_c
        gain += coefficient * (target - gain)
        row["normalized_envelope"] = normalized
        row["synth_target_gain"] = target
        row["synth_gain"] = float(np.clip(gain, 0.0, 1.0))
        row["audible_latched"] = int(latched)
        row["tail_confidence_taper"] = taper
    return out


def decay_mask(rows, seconds=0.48):
    dt = frame_dt(rows)
    history = max(2, int(round(seconds / dt)))
    mask = np.zeros(len(rows), dtype=bool)
    for index in range(history, len(rows)):
        row = rows[index]
        peak = max(item["envelope"] for item in rows[index - history:index + 1])
        falling = row["envelope"] < rows[index - 5]["envelope"]
        mask[index] = peak > 0 and row["envelope"] <= 0.45 * peak and falling
    return mask


def duration(mask, dt):
    return float(np.count_nonzero(mask) * dt)


def weighted(mask, gain, dt):
    return float(np.sum(gain[mask]) * dt)


def contiguous_events(mask, rows, value, limit=12):
    dt = frame_dt(rows)
    events, start = [], None
    for i, enabled in enumerate(mask):
        if enabled and start is None:
            start = i
        if start is not None and (not enabled or i == len(mask) - 1):
            end = i if enabled and i == len(mask) - 1 else i - 1
            values = value[start:end + 1]
            events.append({"start_sec": rows[start]["time_sec"], "end_sec": rows[end]["time_sec"],
                           "duration_sec": (end - start + 1) * dt, "gain_seconds": float(np.sum(values) * dt),
                           "max_gain": float(np.max(values))})
            start = None
    return sorted(events, key=lambda item: (item["gain_seconds"], item["duration_sec"]), reverse=True)[:limit]


def attack_metrics(rows):
    dt = frame_dt(rows)
    gain = np.asarray([row["synth_gain"] for row in rows])
    onsets = [i for i, row in enumerate(rows) if row["onset"] and row["pitch_valid"]]
    results = {"eligible_onsets": len(onsets)}
    for threshold in (0.5, 0.9):
        delays = []
        for index in onsets:
            stop = min(len(rows), index + int(round(.25 / dt)))
            hit = next((j for j in range(index, stop) if gain[j] >= threshold), None)
            if hit is not None:
                delays.append((hit - index) * dt)
        results[f"gain_ge_{threshold}"] = {"count": len(delays), "median_sec": float(np.median(delays)) if delays else None,
                                             "p90_sec": float(np.percentile(delays, 90)) if delays else None}
    return results


def interval_gain(rows, intervals):
    gain = np.asarray([row["synth_gain"] for row in rows])
    result = {}
    for start, stop, name in intervals:
        mask = np.asarray([start <= row["time_sec"] <= stop for row in rows])
        values = gain[mask]
        result[name] = {"duration_sec": duration(mask, frame_dt(rows)), "gain_median": float(np.median(values)),
                        "gain_min": float(np.min(values)), "gain_below_0_5_sec": duration(values < .5, frame_dt(rows))}
    return result


def metrics(rows):
    dt = frame_dt(rows)
    gain = np.asarray([row["synth_gain"] for row in rows])
    valid = np.asarray([bool(row["pitch_valid"]) for row in rows])
    voiced = np.asarray([bool(row["reference_voiced"]) for row in rows])
    error = np.asarray([abs(row["error_cents"]) for row in rows])
    classes = np.asarray([row.get("classification", "") for row in rows])
    tail = decay_mask(rows)
    audible = gain >= .10
    octave = np.isin(classes, ("octave_up", "octave_down"))
    large = (classes == "large_pitch_error") | (error >= 100.0)
    false_positive = valid & ~voiced
    correct = voiced & (error < 25.0)
    strong_clean = correct & (np.asarray([row["envelope"] for row in rows]) >= .012)
    definition = {
        "audible": "synth_gain >= 0.10",
        "weighted_duration": "sum(synth_gain) * 10.667 ms per selected frame",
        "tail": "source envelope is falling and <=45% of its preceding 480 ms peak",
        "large_error": "classification is large_pitch_error or absolute reference error >=100 cents",
    }
    groups = {"octave_error": octave & voiced, "large_error": large & voiced,
              "false_positive": false_positive, "tail_error": tail & (large | octave),
              "tail_large_error": tail & large, "tail_octave_error": tail & octave}
    output = {"definition": definition, "source_duration_sec": rows[-1]["time_sec"] + dt,
              "audible_duration_sec": weighted(valid, gain, dt), "audible_binary_duration_sec": duration(audible & valid, dt),
              "attack": attack_metrics(rows), "slide_regions": interval_gain(rows, SLIDES),
              "decay_regions": interval_gain(rows, DECAYS), "worst_audible_tail_events": [], "errors": {}}
    output["clean_note_gain"] = {
        "correct_reference_weighted_duration_sec": weighted(correct, gain, dt),
        "correct_reference_median_gain": float(np.median(gain[correct])) if np.any(correct) else None,
        "strong_clean_definition": "reference voiced, <25-cent error, input envelope >= 0.012",
        "strong_clean_duration_sec": duration(strong_clean, dt),
        "strong_clean_median_gain": float(np.median(gain[strong_clean])) if np.any(strong_clean) else None,
        "strong_clean_gain_below_0_9_sec": duration(strong_clean & (gain < .9), dt),
    }
    for name, mask in groups.items():
        output["errors"][name] = {"raw_duration_sec": duration(mask, dt), "audible_duration_sec": duration(mask & audible, dt),
                                   "weighted_duration_sec": weighted(mask, gain, dt)}
    output["tail_error_energy_cent_seconds"] = float(np.sum(np.minimum(error[tail], 2400.0) * gain[tail]) * dt)
    output["large_error_energy_cent_seconds"] = float(np.sum(np.minimum(error[large & voiced], 2400.0) * gain[large & voiced]) * dt)
    output["worst_audible_tail_events"] = contiguous_events(tail & (large | octave) & (gain >= .02), rows, gain)
    return output


def write_csv(rows, path):
    names = ["time_sec", "envelope", "normalized_envelope", "audible_latched", "synth_target_gain", "synth_gain",
             "tail_confidence_taper", "gate", "onset", "pitch_valid", "tracked_freq_hz", "tracker_confidence",
             "reference_voiced", "reference_freq_hz", "reference_confidence", "error_cents", "classification",
             "family_promoted", "stability_mode", "stability_alpha"]
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows([{key: row.get(key, "") for key in names} for row in rows])


def plot_zoom(rows, start, stop, label, path):
    subset = [row for row in rows if start <= row["time_sec"] <= stop]
    times = np.asarray([row["time_sec"] for row in subset])
    env = np.asarray([row["envelope"] for row in subset])
    normalized = np.asarray([row["normalized_envelope"] for row in subset])
    gain = np.asarray([row["synth_gain"] for row in subset])
    pitch = np.asarray([row["tracked_freq_hz"] for row in subset])
    ref = np.asarray([row["reference_freq_hz"] for row in subset])
    error = np.asarray([row["error_cents"] for row in subset])
    figure, axes = plt.subplots(3, 1, figsize=(12, 7), sharex=True, constrained_layout=True)
    raw_axis = axes[0].twinx()
    raw_line = raw_axis.plot(times, env, label="input envelope (raw)", color="#4477aa", alpha=.8)
    normalized_line = axes[0].plot(times, normalized, label="normalized", color="#66aa55")
    gain_line = axes[0].plot(times, gain, label="audible synth gain", color="#cc6677", linewidth=2)
    axes[0].set_ylabel("normalized level / gain"); raw_axis.set_ylabel("raw input envelope")
    axes[0].legend(raw_line + normalized_line + gain_line,
                   [line.get_label() for line in raw_line + normalized_line + gain_line], loc="upper right", ncol=3)
    axes[0].set_title(label)
    axes[1].plot(times, pitch, label="fixed tracked pitch", color="#332288")
    axes[1].plot(times, np.where(ref > 0, ref, np.nan), label="pYIN reference", color="#ddcc77", alpha=.8)
    axes[1].set_ylabel("Hz"); axes[1].legend(loc="upper right")
    axes[2].plot(times, error, color="#aa4499", label="pitch error")
    axes[2].plot(times, [100 if row["pitch_valid"] else 0 for row in subset], color="#999999", label="pitch valid ×100")
    axes[2].axhline(100, linestyle="--", color="#777777", linewidth=.8); axes[2].set_ylabel("cents"); axes[2].set_xlabel("time (s)"); axes[2].legend(loc="upper right")
    figure.savefig(path, dpi=150); plt.close(figure)


def render_monitor(audio_path, rows, output_path, start=None, stop=None):
    y, sr = sf.read(audio_path, dtype="float32", always_2d=True)
    y = np.mean(y, axis=1)
    if start is not None:
        left, right = int(start * sr), int(stop * sr)
        y = y[left:right]
    frame_times = np.asarray([row["time_sec"] for row in rows])
    freq = np.asarray([row["tracked_freq_hz"] for row in rows])
    gain = np.asarray([row["synth_gain"] for row in rows])
    sample_times = np.arange(len(y), dtype=np.float64) / sr + (start or 0.0)
    f = np.interp(sample_times, frame_times, freq, left=0.0, right=0.0)
    g = np.interp(sample_times, frame_times, gain, left=0.0, right=0.0)
    phase = np.cumsum(2 * np.pi * f / sr)
    output = np.column_stack((y, .18 * g * np.sin(phase))).astype(np.float32)
    sf.write(output_path, output, sr, subtype="PCM_24")


def save_experiment(rows, cfg, output_root, source=None, render=False):
    name = "current_fixed_gain" if cfg is None else cfg.name
    directory = output_root / name
    directory.mkdir(parents=True, exist_ok=True)
    active = apply_envelope(rows, cfg)
    if any(abs(a["tracked_freq_hz"] - b["tracked_freq_hz"]) > 0 for a, b in zip(rows, active)):
        raise RuntimeError("envelope lab must never alter tracked_freq_hz")
    result = metrics(active)
    with open(directory / "config.json", "w") as handle: json.dump({"fixed_gain": cfg is None, **(asdict(cfg) if cfg else {})}, handle, indent=2)
    with open(directory / "audible_metrics.json", "w") as handle: json.dump(result, handle, indent=2)
    with open(directory / "summary.json", "w") as handle: json.dump({"config": {"fixed_gain": cfg is None, **(asdict(cfg) if cfg else {})}, "audible_metrics": result}, handle, indent=2)
    with open(directory / "summary.txt", "w") as handle:
        handle.write(f"{name}\nweighted audible duration: {result['audible_duration_sec']:.3f} s\n")
        for key, value in result["errors"].items(): handle.write(f"{key} weighted audible duration: {value['weighted_duration_sec']:.3f} s\n")
    write_csv(active, directory / "gain_trace.csv")
    plot_zoom(active, 0, min(20, active[-1]["time_sec"]), f"{name}: overview opening", directory / "overview.png")
    for start, stop, label in DECAYS + SLIDES:
        plot_zoom(active, start, stop, f"{name}: {label}", directory / f"{label}.png")
    if render:
        render_monitor(source, active, directory / f"{name}.wav")
        for start, stop, label in DECAYS:
            render_monitor(source, active, directory / f"{name}_{label}.wav", start, stop)
    return active, result, directory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--render-names", nargs="*", default=[],
                        help="Experiment names to render (for example current_fixed_gain envelope_01 envelope_02).")
    parser.add_argument("--selected", default="envelope_02", choices=[cfg.name for cfg in CONFIGS],
                        help="Chosen candidate written beside the full comparison.")
    args = parser.parse_args()
    rows = load_rows(args.input)
    results = {}
    fixed, fixed_metrics, _ = save_experiment(rows, None, args.output_root, args.source,
                                               "current_fixed_gain" in args.render_names)
    results["current_fixed_gain"] = fixed_metrics
    for cfg in CONFIGS:
        _, result, _ = save_experiment(rows, cfg, args.output_root, args.source,
                                       cfg.name in args.render_names)
        results[cfg.name] = result
    with open(args.output_root / "comparison.json", "w") as handle: json.dump(results, handle, indent=2)
    with open(args.output_root / "fixed_vs_best.json", "w") as handle:
        json.dump({"fixed_gain": results["current_fixed_gain"], "selected": args.selected,
                   "selected_metrics": results[args.selected]}, handle, indent=2)


if __name__ == "__main__":
    main()
