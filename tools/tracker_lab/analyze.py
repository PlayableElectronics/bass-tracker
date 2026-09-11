#!/usr/bin/env python3
"""Offline reference vs Daisy-realistic bass pitch tracker laboratory."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import librosa
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf
from scipy.signal import butter, lfilter


@dataclass
class TrackerConfig:
    sample_rate: int = 48000
    decimation: int = 4
    analysis_rate: int = 12000
    window: int = 512
    hop: int = 128
    fmin: float = 30.0
    fmax: float = 400.0
    lowpass_hz: float = 1200.0
    gate_on: float = 0.000015
    gate_off: float = 0.000008
    acquire_confidence: float = 0.64
    hold_confidence: float = 0.46
    hold_frames: int = 9
    onset_continuity_octaves: float = 0.85
    sustain_continuity_octaves: float = 0.22
    harmonic_tolerance: float = 0.055
    raw_score_weight: float = 0.78
    double_harmonic_bonus: float = 0.28
    triple_harmonic_bonus: float = 0.18
    subharmonic_penalty: float = 0.24
    third_harmonic_penalty: float = 0.14
    continuity_weight: float = 0.34


def load_audio(path: Path, start: float, duration: float | None):
    info = sf.info(path)
    y, sr = sf.read(path, start=int(start * info.samplerate),
                     stop=None if duration is None else int((start + duration) * info.samplerate),
                     dtype="float32", always_2d=True)
    if y.shape[1] > 1:
        channel_corr = float(np.corrcoef(y[:, 0], y[:, 1])[0, 1])
        y = np.mean(y, axis=1)
    else:
        channel_corr = None
        y = y[:, 0]
    if sr != 48000:
        y = librosa.resample(y, orig_sr=sr, target_sr=48000)
        sr = 48000
    return y.astype(np.float32), sr, info, channel_corr


def signal_metrics(y: np.ndarray):
    return {"peak": float(np.max(np.abs(y))), "rms": float(np.sqrt(np.mean(y * y))),
            "peak_dbfs": float(20 * np.log10(max(np.max(np.abs(y)), 1e-12))),
            "rms_dbfs": float(20 * np.log10(max(np.sqrt(np.mean(y * y)), 1e-12)))}


def offline_reference(y, sr, cfg):
    hop = 240
    f0, voiced, prob = librosa.pyin(y, fmin=25.0, fmax=500.0, sr=sr,
                                    frame_length=4096, hop_length=hop,
                                    center=True, fill_na=np.nan,
                                    max_transition_rate=35.92,
                                    resolution=0.2, n_thresholds=50)
    times = librosa.times_like(f0, sr=sr, hop_length=hop)
    confidence = np.nan_to_num(prob, nan=0.0)
    # The supplied 24-bit studio take is intentionally quiet (about -38.5 dBFS
    # RMS); pYIN's probability scale tops out below the usual 0.5 threshold.
    voiced = np.nan_to_num(voiced, nan=False).astype(bool) & (confidence >= 0.30)
    return times, np.nan_to_num(f0, nan=0.0), voiced, confidence


def lowpass_and_decimate(y, cfg):
    # Causal first-order conditioning, matching the embedded concept.
    dc_prev_x = dc_prev_y = lp = 0.0
    lp_a = 1.0 - math.exp(-2 * math.pi * cfg.lowpass_hz / cfg.sample_rate)
    out = np.empty(len(y) // cfg.decimation, dtype=np.float32)
    n = 0
    for i in range(0, len(y) - cfg.decimation + 1, cfg.decimation):
        acc = 0.0
        for sample in y[i:i + cfg.decimation]:
            blocked = float(sample) - dc_prev_x + 0.995 * dc_prev_y
            dc_prev_x, dc_prev_y = float(sample), blocked
            lp += lp_a * (blocked - lp)
            acc += lp
        out[n] = acc / cfg.decimation
        n += 1
    return out[:n]


def envelope_trace(y, cfg):
    attack_c = 1 - math.exp(-1 / (0.0015 * cfg.sample_rate))
    release_c = 1 - math.exp(-1 / (0.080 * cfg.sample_rate))
    env = 0.0
    gate = False
    release_count = 0
    release_limit = int(.015 * cfg.sample_rate)
    values = np.empty(len(y), dtype=np.float32)
    gates = np.zeros(len(y), dtype=bool)
    onsets = np.zeros(len(y), dtype=bool)
    prev = 0.0
    attack = 0.0
    onset_armed = True
    rearm = 0
    for i, sample in enumerate(y):
        mag = abs(float(sample))
        c = attack_c if mag > env else release_c
        prev, env = env, env + c * (mag - env)
        slope = max(0.0, min(1.0, (env - prev) * 250.0))
        attack = max(slope, attack * math.exp(-1 / (.030 * cfg.sample_rate)))
        if not gate and env >= cfg.gate_on:
            gate, release_count = True, 0
        elif gate and env <= cfg.gate_off:
            release_count += 1
            if release_count >= release_limit:
                gate = False
        else:
            release_count = 0
        if rearm:
            rearm -= 1
        if not onset_armed and attack <= .08 and rearm == 0:
            onset_armed = True
        if onset_armed and attack >= .18 and env >= cfg.gate_on:
            onsets[i] = True
            onset_armed, rearm = False, int(.040 * cfg.sample_rate)
        values[i], gates[i] = env, gate
    return values, gates, onsets


def candidates_for_window(frame, cfg):
    frame = frame - np.mean(frame)
    lags = np.arange(int(cfg.analysis_rate / cfg.fmax), int(cfg.analysis_rate / cfg.fmin) + 1)
    correlations = np.zeros(len(lags), dtype=np.float32)
    for j, lag in enumerate(lags):
        x, z = frame[:-lag], frame[lag:]
        denom = math.sqrt(float(np.dot(x, x) * np.dot(z, z)))
        correlations[j] = float(np.dot(x, z) / denom) if denom > 1e-12 else 0.0
    peaks = []
    for j in range(1, len(lags) - 1):
        if correlations[j] >= correlations[j - 1] and correlations[j] > correlations[j + 1]:
            peaks.append((float(cfg.analysis_rate / lags[j]), float(correlations[j]), int(lags[j])))
    if not peaks:
        j = int(np.argmax(correlations))
        peaks = [(float(cfg.analysis_rate / lags[j]), float(correlations[j]), int(lags[j]))]
    peaks.sort(key=lambda x: x[1], reverse=True)
    return peaks[:6]


def near_ratio(measured, expected, tol):
    return expected > 0 and abs(measured - expected) / expected <= tol


def track_realtime(y, sr, cfg):
    filtered = lowpass_and_decimate(y, cfg)
    env, gate, onsets = envelope_trace(y, cfg)
    frame_count = max(0, (len(filtered) - cfg.window) // cfg.hop + 1)
    rows = []
    tracked = 0.0
    confidence = 0.0
    has_pitch = False
    hold = 0
    wide = 0
    previous_onset = False
    for n in range(frame_count):
        start = n * cfg.hop
        frame = filtered[start:start + cfg.window]
        cands = candidates_for_window(frame, cfg)
        t = (start + cfg.window / 2) / cfg.analysis_rate
        sample_end = min(len(y), int((start + cfg.hop) * cfg.decimation))
        env_value = float(env[max(0, sample_end - 1)])
        gate_value = bool(gate[max(0, sample_end - 1)])
        onset = bool(np.any(onsets[max(0, sample_end - cfg.decimation * cfg.hop):sample_end]))
        if onset:
            wide = 10
        allow_wide = wide > 0
        wide = max(0, wide - 1)
        selected_score = -1.0
        selected = None
        for candidate in cands:
            freq, score, _ = candidate
            combined = score * cfg.raw_score_weight
            for other in cands:
                if other is candidate:
                    continue
                if near_ratio(other[0], freq * 2, cfg.harmonic_tolerance):
                    combined += cfg.double_harmonic_bonus * other[1]
                elif near_ratio(other[0], freq * 3, cfg.harmonic_tolerance):
                    combined += cfg.triple_harmonic_bonus * other[1]
                elif near_ratio(other[0], freq * .5, cfg.harmonic_tolerance):
                    combined -= cfg.subharmonic_penalty * other[1]
                elif near_ratio(other[0], freq / 3, cfg.harmonic_tolerance):
                    combined -= cfg.third_harmonic_penalty * other[1]
            if has_pitch:
                tol = cfg.onset_continuity_octaves if allow_wide else cfg.sustain_continuity_octaves
                dist = abs(math.log(freq / tracked, 2)) if freq > 0 and tracked > 0 else 1
                combined += cfg.continuity_weight * confidence * max(0, 1 - dist / tol)
            if combined > selected_score:
                selected_score, selected = combined, candidate
        selected_conf = 0.0 if selected is None else min(1.0, selected[1] * .72 + max(0, min(1, selected_score)) * .28)
        can_acquire = selected is not None and gate_value and env_value >= cfg.gate_on and selected_conf >= cfg.acquire_confidence
        can_hold = selected is not None and gate_value and env_value >= cfg.gate_off and selected_conf >= cfg.hold_confidence
        if not has_pitch and can_acquire:
            tracked, confidence, has_pitch, hold = selected[0], selected_conf, True, cfg.hold_frames
        elif has_pitch and can_hold:
            slew = .70 if allow_wide else .42
            tracked += slew * (selected[0] - tracked)
            confidence, hold = selected_conf, cfg.hold_frames
        elif has_pitch and hold > 0:
            hold -= 1
            confidence *= .90
        else:
            has_pitch, confidence = False, 0.0
        row = {"time_sec": t, "raw_freq_hz": cands[0][0] if cands else 0.0,
               "raw_confidence": cands[0][1] if cands else 0.0,
               "tracked_freq_hz": tracked if has_pitch else 0.0,
               "tracker_confidence": confidence, "pitch_valid": int(has_pitch),
               "envelope": env_value, "gate": int(gate_value), "onset": int(onset)}
        for j in range(4):
            row[f"c{j+1}_freq"] = cands[j][0] if j < len(cands) else 0.0
            row[f"c{j+1}_score"] = cands[j][1] if j < len(cands) else 0.0
        rows.append(row)
    return rows


def interpolate_reference(rows, times, f0, voiced, confidence):
    for row in rows:
        t = row["time_sec"]
        row["reference_freq_hz"] = float(np.interp(t, times, f0, left=0, right=0))
        idx = int(np.clip(np.searchsorted(times, t), 0, len(times) - 1))
        row["reference_voiced"] = int(bool(voiced[idx]))
        row["reference_confidence"] = float(confidence[idx])
        if row["pitch_valid"] and row["reference_voiced"] and row["reference_freq_hz"] > 0:
            row["error_cents"] = 1200 * math.log2(row["tracked_freq_hz"] / row["reference_freq_hz"])
        else:
            row["error_cents"] = ""
        row["classification"] = classify(row)
        row["octave_error"] = (1 if row["classification"] == "octave_up" else
                                -1 if row["classification"] == "octave_down" else 0)


def classify(row):
    ref, tr = row["reference_freq_hz"], row["tracked_freq_hz"]
    rv, tv = bool(row["reference_voiced"]), bool(row["pitch_valid"])
    if rv and not tv:
        return "dropout"
    if tv and not rv:
        return "false_positive"
    if not rv or not tv:
        return "unvoiced"
    cents = float(row["error_cents"])
    if abs(abs(cents) - 1200) < 90:
        return "octave_up" if cents > 0 else "octave_down"
    if abs(abs(cents) - 1902) < 110 or abs(abs(cents) - 2400) < 130:
        return "third/subharmonic_error"
    if abs(cents) <= 50:
        return "correct"
    return "large_pitch_error"


def summary(rows, duration):
    voiced = [r for r in rows if r["reference_voiced"]]
    both = [r for r in voiced if r["pitch_valid"] and r["error_cents"] != ""]
    errors = np.abs([float(r["error_cents"]) for r in both]) if both else np.array([])
    def count(cls): return sum(r["classification"] == cls for r in rows)
    valid = sum(bool(r["pitch_valid"]) for r in rows)
    jumps = sum(bool(rows[i]["pitch_valid"] and rows[i-1]["pitch_valid"] and rows[i-1]["tracked_freq_hz"] > 0 and abs(1200 * math.log2(rows[i]["tracked_freq_hz"] / rows[i-1]["tracked_freq_hz"])) > 600) for i in range(1, len(rows)))
    stable = 0.0
    current = 0
    for r in rows:
        if r["classification"] == "correct":
            current += 1
            stable = max(stable, current)
        else:
            current = 0
    result = {"duration_sec": duration, "total_frames": len(rows),
              "voiced_duration_sec": len(voiced) * (rows[1]["time_sec"] - rows[0]["time_sec"]) if len(rows) > 1 else 0,
              "tracker_valid_duration_sec": valid * (rows[1]["time_sec"] - rows[0]["time_sec"]) if len(rows) > 1 else 0,
              "pitch_coverage": len(both) / len(voiced) if voiced else 0,
              "median_absolute_cents_error": float(np.median(errors)) if errors.size else None,
              "p90_absolute_cents_error": float(np.percentile(errors, 90)) if errors.size else None,
              "within_25_cents": float(np.mean(errors <= 25)) if errors.size else 0,
              "within_50_cents": float(np.mean(errors <= 50)) if errors.size else 0,
              "octave_up_frames": count("octave_up"), "octave_down_frames": count("octave_down"),
              "dropout_frames": count("dropout"), "false_positive_frames": count("false_positive"),
              "large_pitch_error_frames": count("large_pitch_error"), "pitch_jump_count": jumps,
              "longest_stable_correct_sec": stable * (rows[1]["time_sec"] - rows[0]["time_sec"]) if len(rows) > 1 else 0}
    result["octave_up_duration_sec"] = result["octave_up_frames"] * (rows[1]["time_sec"] - rows[0]["time_sec"]) if len(rows) > 1 else 0
    result["octave_down_duration_sec"] = result["octave_down_frames"] * (rows[1]["time_sec"] - rows[0]["time_sec"]) if len(rows) > 1 else 0
    result.update(acquisition_latency(rows))
    return result


def acquisition_latency(rows):
    """Approximate causal tracker acquisition after offline-reference onsets."""
    if len(rows) < 2:
        return {"acquisition_event_count": 0,
                "median_acquisition_latency_sec": None,
                "p90_acquisition_latency_sec": None,
                "latency_method": "reference voiced onset to first valid frame within 100 cents"}
    dt = rows[1]["time_sec"] - rows[0]["time_sec"]
    latencies = []
    last_onset = -1e9
    for i, row in enumerate(rows):
        if not row["reference_voiced"] or (i > 0 and rows[i - 1]["reference_voiced"]):
            continue
        if row["time_sec"] - last_onset < 0.10:
            continue
        last_onset = row["time_sec"]
        for candidate in rows[i:min(len(rows), i + int(0.75 / dt) + 1)]:
            if (candidate["pitch_valid"] and candidate["error_cents"] != "" and
                    abs(float(candidate["error_cents"])) <= 100):
                latencies.append(candidate["time_sec"] - row["time_sec"])
                break
    values = np.asarray(latencies, dtype=float)
    return {"acquisition_event_count": int(values.size),
            "median_acquisition_latency_sec": float(np.median(values)) if values.size else None,
            "p90_acquisition_latency_sec": float(np.percentile(values, 90)) if values.size else None,
            "latency_method": "reference voiced onset to first valid tracker frame within 100 cents"}


def render_monitor(y, sr, rows, path, reference=False):
    times = np.arange(len(y)) / sr
    freqs = np.interp(times, [r["time_sec"] for r in rows], [r["reference_freq_hz"] if reference else r["tracked_freq_hz"] for r in rows], left=0, right=0)
    valid = np.interp(times, [r["time_sec"] for r in rows], [float(r["reference_voiced"] if reference else r["pitch_valid"]) for r in rows], left=0, right=0)
    phase = np.cumsum(2 * np.pi * freqs / sr)
    gain = np.minimum(1.0, np.maximum(0.0, valid)) * .18
    right = np.sin(phase) * gain
    sf.write(path, np.column_stack((y, right)).astype(np.float32), sr, subtype="PCM_24")


def plot_outputs(rows, out, failures):
    t = np.array([r["time_sec"] for r in rows]); ref = np.array([r["reference_freq_hz"] for r in rows]); raw = np.array([r["raw_freq_hz"] for r in rows]); tr = np.array([r["tracked_freq_hz"] for r in rows]); valid = np.array([r["pitch_valid"] for r in rows], bool); rv = np.array([r["reference_voiced"] for r in rows], bool); conf = np.array([r["tracker_confidence"] for r in rows]); err = np.array([float(r["error_cents"]) if r["error_cents"] != "" else np.nan for r in rows])
    plt.figure(figsize=(16, 6)); plt.plot(t, np.where(rv, ref, np.nan), label="offline reference", linewidth=.8); plt.plot(t, np.where(raw > 0, raw, np.nan), label="raw candidate", alpha=.35, linewidth=.5); plt.plot(t, np.where(valid, tr, np.nan), label="realtime tracked", linewidth=1); plt.yscale("log"); plt.ylim(20, 550); plt.xlabel("time (s)"); plt.ylabel("frequency (Hz)"); plt.legend(); plt.grid(alpha=.2); plt.tight_layout(); plt.savefig(out / "pitch.png", dpi=150); plt.close()
    plt.figure(figsize=(16, 4)); plt.axhline(0, color="k", linewidth=.5); plt.axhline(1200, color="r", alpha=.35); plt.axhline(-1200, color="r", alpha=.35); plt.plot(t, err, linewidth=.7); plt.ylim(-2500, 2500); plt.xlabel("time (s)"); plt.ylabel("error (cents)"); plt.grid(alpha=.2); plt.tight_layout(); plt.savefig(out / "error.png", dpi=150); plt.close()
    plt.figure(figsize=(16, 3)); plt.plot(t, conf, label="tracker confidence"); plt.fill_between(t, 0, valid.astype(float), alpha=.2, label="pitch valid"); plt.ylim(0, 1.05); plt.xlabel("time (s)"); plt.ylabel("confidence / valid"); plt.legend(); plt.grid(alpha=.2); plt.tight_layout(); plt.savefig(out / "confidence.png", dpi=150); plt.close()
    failure_dir = out / "failures"; failure_dir.mkdir(exist_ok=True)
    for i, event in enumerate(failures[:12], 1):
        center = event["time_sec"]; mask = (t >= center - 1.5) & (t <= center + 1.5); plt.figure(figsize=(12, 4)); plt.plot(t[mask], np.where(rv[mask], ref[mask], np.nan), label="reference"); plt.plot(t[mask], np.where(valid[mask], tr[mask], np.nan), label="tracked"); plt.plot(t[mask], np.where(raw[mask] > 0, raw[mask], np.nan), alpha=.35, label="raw"); plt.yscale("log"); plt.ylim(20, 550); plt.title(f"{event['classification']} at {center:.3f}s"); plt.legend(); plt.grid(alpha=.2); plt.tight_layout(); plt.savefig(failure_dir / f"failure_{i:03d}_{center:.3f}s.png", dpi=150); plt.close()


def main():
    p = argparse.ArgumentParser(); p.add_argument("input", type=Path); p.add_argument("--output-dir", type=Path, default=Path("tracker_runs/baseline")); p.add_argument("--start", type=float, default=0); p.add_argument("--duration", type=float, default=None); args = p.parse_args()
    out = args.output_dir; out.mkdir(parents=True, exist_ok=True); cfg = TrackerConfig()
    y, sr, info, channel_corr = load_audio(args.input, args.start, args.duration)
    metrics = signal_metrics(y); ref_t, ref_f, ref_v, ref_c = offline_reference(y, sr, cfg); rows = track_realtime(y, sr, cfg); interpolate_reference(rows, ref_t, ref_f, ref_v, ref_c); report = summary(rows, len(y) / sr)
    failures = [r for r in rows if r["classification"] in {"octave_up", "octave_down", "dropout", "false_positive", "large_pitch_error"}]
    sf.write(out / "reference.wav", y, sr, subtype="PCM_24")
    render_monitor(y, sr, rows, out / "tracker_monitor.wav", False); render_monitor(y, sr, rows, out / "reference_monitor.wav", True); plot_outputs(rows, out, failures)
    config = asdict(cfg); config.update({"input": str(args.input), "sample_rate": sr, "source_channels": info.channels, "source_subtype": info.subtype, "channel_correlation": channel_corr, "audio_metrics": metrics})
    (out / "config.json").write_text(json.dumps(config, indent=2) + "\n"); (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    fields = list(rows[0].keys());
    with (out / "frames.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    with (out / "summary.txt").open("w") as f:
        for k, v in report.items(): f.write(f"{k}: {v}\n")
        f.write("\nFailure events (first 30):\n")
        for r in failures[:30]: f.write(f"{r['time_sec']:.3f}s {r['classification']} ref={r['reference_freq_hz']:.2f} tracked={r['tracked_freq_hz']:.2f}\n")
    print(json.dumps({"output_dir": str(out), **report}, indent=2))


if __name__ == "__main__":
    main()
