#!/usr/bin/env python3
"""Mac-only causal attack-acquisition experiments on fixed tracker/envelope data.

The input tracker trajectory and the selected envelope_v1 decay gain are copied
unchanged.  This layer only derives an attack-time multiplier and, for one
rejected connected-note experiment, a separate audible oscillator frequency.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from dataclasses import asdict, dataclass
from collections import deque
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf

import envelope_lab


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent.parent / "basik hehe.wav"
INPUT = ROOT / "experiments" / "stability_v1" / "frames.csv.gz"
STABILITY_SUMMARY = ROOT / "experiments" / "stability_v1" / "summary.json"
ATTACK_WINDOW_SEC = .128
TRIGGER_RISE_RATIO = 1.25
TRIGGER_COOLDOWN_SEC = .040
QUALITY_CENTS = 40.0
CONNECTED_GAIN = .60
PLOTS = [(152.88, 153.12, "attack_152s"), (158.16, 158.42, "attack_158s"),
         (161.80, 162.08, "attack_162s"), (176.36, 176.64, "attack_176s"),
         (180.02, 180.30, "attack_180s")]


@dataclass(frozen=True)
class AcquisitionConfig:
    name: str
    description: str
    strategy: str
    confirmation_frames: int = 2
    fade_ms: float = 0.0
    quiet_gain: float = 0.0
    hold_connected_pitch: bool = False
    enable_connected_rise: bool = False
    bypass_continuous_motion: bool = False


CONFIGS = (
    AcquisitionConfig("attack_A1", "Mute while one quality frame is required.", "mute", 1),
    AcquisitionConfig("attack_strategy_A", "Mute until two causal quality frames agree.", "mute", 2),
    AcquisitionConfig("attack_A3", "Mute until three causal quality frames agree.", "mute", 3),
    AcquisitionConfig("attack_strategy_B", "Very quiet while acquiring, then 10 ms fade after trust; bypass a continuous pitch motion.",
                      "fade", 2, 10.0, .10, False, False, True),
    AcquisitionConfig("attack_B20", "Very quiet while acquiring, then 20 ms fade after trust.", "fade", 2, 20.0, .10),
    AcquisitionConfig("attack_B30", "Very quiet while acquiring, then 30 ms fade after trust.", "fade", 2, 30.0, .10),
    AcquisitionConfig("attack_B40", "Very quiet while acquiring, then 40 ms fade after trust.", "fade", 2, 40.0, .10),
    AcquisitionConfig("attack_strategy_C", "Hold prior trusted pitch during connected acquisition; detached attacks mute.",
                      "hold", 2, 0.0, 0.0, True),
    AcquisitionConfig("attack_B_connected_probe", "Rejected probe: also trigger from connected envelope rises.",
                      "fade", 2, 10.0, .10, False, True),
    AcquisitionConfig("attack_B_no_motion_bypass", "Probe: 10 ms fade without continuous-motion protection.",
                      "fade", 2, 10.0, .10),
)


def cents(a, b):
    return 1200.0 * math.log2(a / b) if a > 0 and b > 0 else 0.0


def fnum(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def source_rows():
    return envelope_lab.apply_envelope(envelope_lab.load_rows(INPUT), envelope_lab.CONFIGS[1])


def attack_trigger(row, previous, previous_base_gain, since_trigger, enable_connected_rise):
    explicit = bool(row["onset"])
    rise = previous is not None and row["envelope"] > previous["envelope"] * TRIGGER_RISE_RATIO
    connected_rise = rise and previous_base_gain >= CONNECTED_GAIN
    return since_trigger >= TRIGGER_COOLDOWN_SEC and (explicit or (enable_connected_rise and connected_rise)), explicit, connected_rise


def quality(row, previous_raw, previous_promoted):
    raw = row["raw_freq_hz"]
    final = row["tracked_freq_hz"]
    return (bool(row["pitch_valid"]) and raw > 0 and final > 0 and previous_raw > 0
            and not row["family_promoted"] and not previous_promoted
            and abs(cents(raw, final)) <= QUALITY_CENTS
            and abs(cents(raw, previous_raw)) <= QUALITY_CENTS)


def continuous_motion(recent_frequencies):
    """Two recent same-direction >=10-cent moves identify an ongoing slide."""
    if len(recent_frequencies) < 3:
        return False
    steps = [cents(recent_frequencies[i], recent_frequencies[i - 1])
             for i in range(1, len(recent_frequencies))]
    signed = [step for step in steps if abs(step) >= 10.0]
    return len(signed) >= 2 and signed[-1] * signed[-2] > 0 and abs(signed[-1]) + abs(signed[-2]) >= 80.0


def apply_acquisition(base_rows, cfg: AcquisitionConfig | None):
    """Derive audible fields only; all source tracker and envelope fields are immutable."""
    dt = envelope_lab.frame_dt(base_rows)
    rows = [dict(row) for row in base_rows]
    acquiring = False
    attack_start = -1e9
    last_trigger = -1e9
    agreement = 0
    trusted = True
    connected = False
    attack_gain = 1.0
    previous_raw = 0.0
    previous_promoted = False
    previous = None
    previous_base_gain = 0.0
    last_trusted_frequency = 0.0
    trigger_count = 0
    recent_frequencies = deque(maxlen=4)
    for row in rows:
        base_gain = row["synth_gain"]
        trigger, explicit, connected_rise = attack_trigger(row, previous, previous_base_gain,
                                                            row["time_sec"] - last_trigger,
                                                            bool(cfg and cfg.enable_connected_rise))
        if trigger:
            last_trigger = row["time_sec"]
            trigger_count += 1
        recent_with_current = list(recent_frequencies) + [row["tracked_freq_hz"]]
        motion_bypass = bool(cfg and cfg.bypass_continuous_motion and continuous_motion(recent_with_current))
        if cfg is not None and trigger and not motion_bypass:
            acquiring, trusted, agreement = True, False, 0
            attack_start = row["time_sec"]
            connected = previous_base_gain >= CONNECTED_GAIN
            # A detached note has no prior audible target. A connected note
            # may use this separate synthesis-only value for strategy C.
            if last_trusted_frequency <= 0:
                last_trusted_frequency = row["tracked_freq_hz"]
            attack_gain = cfg.quiet_gain if cfg.strategy == "fade" else 0.0

        elapsed = row["time_sec"] - attack_start
        inside_window = acquiring and elapsed < ATTACK_WINDOW_SEC
        row_quality = quality(row, previous_raw, previous_promoted) if inside_window else True
        if cfg is not None and inside_window:
            agreement = agreement + 1 if row_quality else 0
            trusted = agreement >= cfg.confirmation_frames
            if cfg.strategy == "mute":
                attack_gain = 1.0 if trusted else 0.0
            elif cfg.strategy == "fade":
                # Start quiet immediately. Once quality is confirmed, a small
                # causal one-pole fades in without changing decay behavior.
                target = 1.0 if trusted else cfg.quiet_gain
                coefficient = 1.0 - math.exp(-dt / (cfg.fade_ms / 1000.0))
                attack_gain += coefficient * (target - attack_gain)
            elif cfg.strategy == "hold":
                attack_gain = 1.0 if (connected and not trusted) or trusted else 0.0
        elif cfg is not None:
            acquiring, trusted, agreement, attack_gain = False, True, 0, 1.0

        audio_frequency = row["tracked_freq_hz"]
        hold_active = bool(cfg and cfg.hold_connected_pitch and inside_window and connected and not trusted)
        if hold_active:
            audio_frequency = last_trusted_frequency
        final_gain = base_gain * attack_gain if cfg is not None else base_gain
        row["acquisition_trigger"] = int(trigger)
        row["acquisition_explicit_onset"] = int(trigger and explicit)
        row["acquisition_connected_rise"] = int(trigger and connected_rise)
        row["acquisition_motion_bypass"] = int(trigger and motion_bypass)
        row["attack_acquiring"] = int(bool(cfg and inside_window))
        row["attack_connected"] = int((inside_window and connected) if cfg else (trigger and previous_base_gain >= CONNECTED_GAIN))
        row["acquisition_quality"] = int(bool(cfg and row_quality))
        row["agreement_counter"] = agreement if cfg else 0
        row["pitch_trusted"] = int(trusted)
        row["attack_gain"] = attack_gain if cfg else 1.0
        row["final_synth_gain"] = float(np.clip(final_gain, 0.0, 1.0))
        row["audio_frequency_hz"] = audio_frequency
        row["connected_pitch_hold"] = int(hold_active)
        row["stability_bypass"] = int(row.get("stability_mode") == "moving")
        if trusted and row["pitch_valid"] and row["tracked_freq_hz"] > 0:
            last_trusted_frequency = row["tracked_freq_hz"]
        previous_raw = row["raw_freq_hz"]
        previous_promoted = bool(row["family_promoted"])
        previous, previous_base_gain = row, base_gain
        if row["tracked_freq_hz"] > 0:
            recent_frequencies.append(row["tracked_freq_hz"])
    if any(a["tracked_freq_hz"] != b["tracked_freq_hz"] for a, b in zip(base_rows, rows)):
        raise RuntimeError("attack acquisition must never modify tracked pitch")
    return rows, trigger_count


def attack_window_mask(rows):
    dt = envelope_lab.frame_dt(rows)
    mask = np.zeros(len(rows), dtype=bool)
    last = -1e9
    for i, row in enumerate(rows):
        if row["acquisition_trigger"]:
            last = row["time_sec"]
        mask[i] = row["time_sec"] - last < ATTACK_WINDOW_SEC
    return mask, dt


def events(rows, final=True, limit=24):
    attack, dt = attack_window_mask(rows)
    gain = np.asarray([row["final_synth_gain"] if final else row["synth_gain"] for row in rows])
    error = np.asarray([abs(cents(row["audio_frequency_hz"] if final else row["tracked_freq_hz"], row["reference_freq_hz"]))
                        if row["reference_voiced"] else 0.0 for row in rows])
    bad = attack & np.asarray([row["reference_voiced"] and row["pitch_valid"] and value >= 100 for row, value in zip(rows, error)])
    result, start = [], None
    for i, enabled in enumerate(bad):
        if enabled and start is None:
            start = i
        if start is not None and (not enabled or i == len(bad) - 1):
            end = i if enabled else i - 1
            source = rows[start]
            result.append({
                "start_sec": source["time_sec"], "end_sec": rows[end]["time_sec"],
                "duration_sec": (end - start + 1) * dt,
                "weighted_error_cent_seconds": float(np.sum(error[start:end + 1] * gain[start:end + 1]) * dt),
                "max_error_cents": float(np.max(error[start:end + 1])),
                "onset": source["onset"], "envelope": source["envelope"], "base_synth_gain": source["synth_gain"],
                "raw_candidates_hz": [{"frequency_hz": fnum(source.get(f"c{n}_freq")), "score": fnum(source.get(f"c{n}_score"))}
                                      for n in range(1, 5)],
                "pre_stability_freq_hz": fnum(source.get("stability_input_hz")),
                "final_tracked_freq_hz": source["tracked_freq_hz"], "reference_freq_hz": source["reference_freq_hz"],
                "tracker_confidence": source["tracker_confidence"], "family_promoted": source["family_promoted"],
                "stability_bypass": source["stability_bypass"],
            })
            start = None
    return sorted(result, key=lambda item: item["weighted_error_cent_seconds"], reverse=True)[:limit]


def distribution(values):
    return {"count": len(values), "median_sec": float(np.median(values)) if values else None,
            "p90_sec": float(np.percentile(values, 90)) if values else None}


def metrics(rows, trigger_count, baseline=False):
    attack, dt = attack_window_mask(rows)
    gain = np.asarray([row["final_synth_gain"] for row in rows])
    base = np.asarray([row["synth_gain"] for row in rows])
    audio = np.asarray([row["audio_frequency_hz"] for row in rows])
    ref = np.asarray([row["reference_freq_hz"] for row in rows])
    voiced = np.asarray([bool(row["reference_voiced"]) for row in rows])
    valid = np.asarray([bool(row["pitch_valid"]) for row in rows])
    error = np.asarray([abs(cents(a, b)) for a, b in zip(audio, ref)])
    octave = (error >= 950) & (error <= 1250) & voiced & valid
    large = (error >= 100) & voiced & valid
    attack_valid = attack & voiced & valid
    trusted_delays, gain_delays, connected_gaps = [], [], []
    untrusted_guard_expirations = 0
    trigger_indices = [i for i, row in enumerate(rows) if row["acquisition_trigger"] and not row["acquisition_motion_bypass"]]
    for i in trigger_indices:
        stop = min(len(rows), i + int(round(ATTACK_WINDOW_SEC / dt)))
        trusted = next((j for j in range(i, stop) if rows[j]["pitch_trusted"]), None)
        if trusted is not None:
            trusted_delays.append((trusted - i) * dt)
        elif not baseline:
            untrusted_guard_expirations += 1
        baseline_hit = next((j for j in range(i, stop) if base[j] >= .5), None)
        final_hit = next((j for j in range(i, stop) if gain[j] >= .5), None)
        if baseline_hit is not None and final_hit is not None:
            gain_delays.append(max(0.0, (final_hit - baseline_hit) * dt))
        if rows[i]["attack_connected"]:
            connected_gaps.append(float(np.count_nonzero((base[i:stop] >= .5) & (gain[i:stop] < .1)) * dt))
    slide = {}
    for start, stop, name in envelope_lab.SLIDES:
        mask = np.asarray([start <= row["time_sec"] <= stop for row in rows])
        slide[name] = {"final_gain_median": float(np.median(gain[mask])), "final_gain_min": float(np.min(gain[mask])),
                       "gain_below_0_5_sec": float(np.count_nonzero(gain[mask] < .5) * dt),
                       "pitch_lag_change_sec": 0.0}
    return {
        "definition": {
            "attack_window": "first 128 ms after an acquisition trigger; selected B uses explicit onset only, while the rejected connected-rise probe also uses >1.25x envelope rises (40 ms rearm)",
            "quality": "pitch valid, no current/previous family promotion, raw-to-final <=40 cents, and current-to-prior raw <=40 cents",
            "attack_error": "reference voiced + tracker valid error >=100 cents; durations are final-synth-gain weighted",
        },
        "trigger_count": trigger_count,
        "acquisition_activated_count": len(trigger_indices),
        "continuous_motion_bypass_count": int(sum(row["acquisition_motion_bypass"] for row in rows)),
        "attack_reference_valid_duration_sec": float(np.count_nonzero(attack_valid) * dt),
        "attack_wrong_pitch_duration_sec": float(np.count_nonzero(attack_valid & (error >= 100) & (gain >= .1)) * dt),
        "attack_octave_error_weighted_duration_sec": float(np.sum(gain[attack & octave]) * dt),
        "attack_large_error_weighted_duration_sec": float(np.sum(gain[attack & large]) * dt),
        "attack_weighted_error_cent_seconds": float(np.sum(error[attack_valid] * gain[attack_valid]) * dt),
        "time_to_trusted_pitch": distribution(trusted_delays),
        "untrusted_at_128ms_guard_expiry_count": untrusted_guard_expirations,
        "added_audible_onset_latency": distribution(gain_delays),
        "connected_note_gap_duration": distribution(connected_gaps),
        "slides": slide,
        "full_track_audible_octave_weighted_duration_sec": float(np.sum(gain[octave]) * dt),
        "full_track_audible_large_weighted_duration_sec": float(np.sum(gain[large]) * dt),
        "tracker_trajectory_unchanged": True,
        "frozen_full_track_tracker_metrics": frozen_tracker_metrics(),
        "ranked_attack_failures": events(rows),
    }


def frozen_tracker_metrics():
    source = json.loads(STABILITY_SUMMARY.read_text())
    return {key: source[key] for key in ("median_absolute_cents_error", "p90_absolute_cents_error", "within_25_cents",
                                          "within_50_cents", "octave_up_duration_sec", "octave_down_duration_sec",
                                          "pitch_coverage", "tracker_valid_duration_sec")}


def write_trace(rows, path):
    names = ["time_sec", "envelope", "synth_gain", "acquisition_trigger", "acquisition_explicit_onset",
             "acquisition_connected_rise", "attack_acquiring", "attack_connected", "acquisition_quality",
             "acquisition_motion_bypass", "agreement_counter", "pitch_trusted", "attack_gain", "final_synth_gain", "connected_pitch_hold",
             "raw_freq_hz", "stability_input_hz", "tracked_freq_hz", "audio_frequency_hz", "tracker_confidence",
             "family_promoted", "stability_bypass", "reference_freq_hz", "reference_voiced", "error_cents",
             "c1_freq", "c1_score", "c2_freq", "c2_score", "c3_freq", "c3_score", "c4_freq", "c4_score"]
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names); writer.writeheader()
        writer.writerows([{name: row.get(name, "") for name in names} for row in rows])


def plot(rows, start, stop, title, path):
    data = [row for row in rows if start <= row["time_sec"] <= stop]
    t = np.asarray([row["time_sec"] for row in data])
    base = np.asarray([row["synth_gain"] for row in data])
    factor = np.asarray([row["attack_gain"] for row in data])
    final = np.asarray([row["final_synth_gain"] for row in data])
    tracked = np.asarray([row["tracked_freq_hz"] for row in data])
    audio = np.asarray([row["audio_frequency_hz"] for row in data])
    ref = np.asarray([row["reference_freq_hz"] for row in data])
    err = np.asarray([abs(cents(row["audio_frequency_hz"], row["reference_freq_hz"])) for row in data])
    figure, axes = plt.subplots(3, 1, figsize=(12, 7), sharex=True, constrained_layout=True)
    axes[0].plot(t, base, label="frozen envelope_02", color="#4477aa")
    axes[0].plot(t, factor, label="acquisition gain", color="#66aa55")
    axes[0].plot(t, final, label="final synth gain", color="#cc6677", linewidth=2)
    for row in data:
        if row["acquisition_trigger"]: axes[0].axvline(row["time_sec"], color="#222222", linestyle=":", alpha=.5)
    axes[0].set_ylim(-.05, 1.05); axes[0].set_ylabel("gain"); axes[0].legend(loc="upper right", ncol=3); axes[0].set_title(title)
    axes[1].plot(t, tracked, label="fixed tracked pitch", color="#332288")
    axes[1].plot(t, audio, label="audible oscillator pitch", color="#aa4499", linestyle="--")
    axes[1].plot(t, np.where(ref > 0, ref, np.nan), label="pYIN reference", color="#ddcc77")
    axes[1].set_ylabel("Hz"); axes[1].legend(loc="upper right")
    axes[2].plot(t, err, label="audible-pitch error", color="#aa4499")
    axes[2].plot(t, [100 if row["pitch_trusted"] else 0 for row in data], label="trusted ×100", color="#888888")
    axes[2].axhline(100, color="#777777", linestyle="--", linewidth=.8); axes[2].set_ylabel("cents"); axes[2].set_xlabel("time (s)"); axes[2].legend(loc="upper right")
    figure.savefig(path, dpi=150); plt.close(figure)


def render(source, rows, output, start=None, stop=None):
    y, sr = sf.read(source, dtype="float32", always_2d=True); y = np.mean(y, axis=1)
    if start is not None: y = y[int(start * sr):int(stop * sr)]
    t = np.asarray([row["time_sec"] for row in rows])
    freq = np.asarray([row["audio_frequency_hz"] for row in rows])
    gain = np.asarray([row["final_synth_gain"] for row in rows])
    samples = np.arange(len(y), dtype=np.float64) / sr + (start or 0.0)
    f = np.interp(samples, t, freq, left=0, right=0); g = np.interp(samples, t, gain, left=0, right=0)
    phase = np.cumsum(2 * np.pi * f / sr)
    sf.write(output, np.column_stack((y, .18 * g * np.sin(phase))).astype(np.float32), sr, subtype="PCM_24")


def save(base, cfg, root, render_audio=False):
    name = "attack_baseline" if cfg is None else cfg.name
    directory = root / name; directory.mkdir(parents=True, exist_ok=True)
    rows, triggers = apply_acquisition(base, cfg)
    result = metrics(rows, triggers, cfg is None)
    config = {"baseline": cfg is None, **(asdict(cfg) if cfg else {})}
    for filename, payload in (("config.json", config), ("attack_metrics.json", result),
                              ("summary.json", {"config": config, "attack_metrics": result})):
        with open(directory / filename, "w") as handle: json.dump(payload, handle, indent=2)
    with open(directory / "summary.txt", "w") as handle:
        handle.write(f"{name}\nattack large error: {result['attack_large_error_weighted_duration_sec']:.4f} gain-seconds\n")
    write_trace(rows, directory / "attack_trace.csv")
    for start, stop, label in PLOTS: plot(rows, start, stop, f"{name}: {label}", directory / f"{label}.png")
    if render_audio:
        render(SOURCE, rows, directory / f"{name}.wav")
        for start, stop, label in PLOTS: render(SOURCE, rows, directory / f"{name}_{label}.wav", start, stop)
    return result, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--render-names", nargs="*", default=[])
    parser.add_argument("--selected", choices=[cfg.name for cfg in CONFIGS], default="attack_strategy_B")
    args = parser.parse_args()
    base = source_rows()
    results, output_rows = {}, {}
    result, rows = save(base, None, args.output_root, "attack_baseline" in args.render_names)
    results["attack_baseline"], output_rows["attack_baseline"] = result, rows
    for cfg in CONFIGS:
        result, rows = save(base, cfg, args.output_root, cfg.name in args.render_names)
        results[cfg.name], output_rows[cfg.name] = result, rows
    with open(args.output_root / "comparison.json", "w") as handle: json.dump(results, handle, indent=2)
    with open(args.output_root / "baseline_vs_best.json", "w") as handle:
        json.dump({"baseline": results["attack_baseline"], "selected": args.selected,
                   "selected_metrics": results[args.selected]}, handle, indent=2)
    with open(args.output_root / "attack_failures.json", "w") as handle:
        json.dump(results["attack_baseline"]["ranked_attack_failures"], handle, indent=2)
    # Keep the requested A/B/C naming as well as a stable name for the selected
    # listening artifact.  These files live only in ignored tracker_runs/.
    if args.selected in args.render_names:
        selected_rows = output_rows[args.selected]
        selected_dir = args.output_root / args.selected
        render(SOURCE, selected_rows, selected_dir / "attack_best.wav")
        for start, stop, label in PLOTS:
            render(SOURCE, selected_rows, selected_dir / f"attack_best_{label}.wav", start, stop)


if __name__ == "__main__":
    main()
