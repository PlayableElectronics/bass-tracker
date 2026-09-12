#!/usr/bin/env python3
"""Mac-only counterfactuals for the two tracker root causes from forensics.

The detector, selected adaptive stability layer, and envelope_02 gain are
frozen inputs.  This script only replays the causal candidate-family/pre-slew
stage with narrowly scoped alternatives, then measures the resulting final
trajectory.  Nothing here changes firmware or the committed tracker.
"""
from __future__ import annotations

import argparse
import copy
import csv
import gzip
import json
import math
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf

import analyze
import envelope_lab
import forensics
import octave_lab
import replay_family
import stability_lab


ROOT = Path(__file__).resolve().parent
BASELINE = ROOT / "baseline" / "frames.csv.gz"
STABILITY = ROOT / "experiments" / "stability_v1" / "frames.csv.gz"
SOURCE = ROOT.parent.parent / "basik hehe.wav"
EVENT_CONTEXT_SEC = 0.200
ERROR_CENTS = 100.0
CORRECT_CENTS = 50.0


@dataclass(frozen=True)
class RootFixConfig:
    name: str
    fix_a_recovery: bool = False
    fix_b_guard: bool = False
    # A: only snap back after a short, large detour returns to a strong raw
    # winner that was recently credible before that detour.
    recovery_anchor_score: float = 0.75
    recovery_return_score: float = 0.90
    recovery_anchor_match_cents: float = 100.0
    recovery_departure_cents: float = 250.0
    recovery_return_cents: float = 70.0
    recovery_max_frames: int = 6
    recovery_attack_window_sec: float = 0.20
    recovery_anchor_max_age_frames: int = 4
    recovery_mode: str = "direct"
    recovery_slew: float = 0.85
    # B: only delay a *new upward 2x escalation* that is weaker than an
    # established, already-confirmed current family. Normal acquisition and
    # ordinary octave-family recovery retain the original two frames.
    guard_established_frames: int = 6
    guard_pre_match_cents: float = 100.0
    guard_max_relative_score: float = 0.97
    guard_confirm_frames: int = 6


CONFIGS = (
    RootFixConfig("rootfix_baseline"),
    RootFixConfig("rootfix_A", fix_a_recovery=True),
    RootFixConfig("rootfix_A_fast", fix_a_recovery=True, recovery_mode="fast", recovery_slew=0.85),
    RootFixConfig("rootfix_B", fix_b_guard=True),
    RootFixConfig("rootfix_B4", fix_b_guard=True, guard_confirm_frames=4),
    RootFixConfig("rootfix_AB", fix_a_recovery=True, fix_b_guard=True),
)


def cents(a: float, b: float) -> float:
    return 1200.0 * math.log2(a / b) if a > 0 and b > 0 else float("nan")


def close(a: float, b: float, limit: float) -> bool:
    return a > 0 and b > 0 and abs(cents(a, b)) <= limit


def top_is_selected(top, selected) -> bool:
    return bool(top and selected and abs(top["freq"] - selected["freq"]) < 1e-9)


def source_rows():
    return replay_family.read_rows(BASELINE)


def family_guard_applies(cfg, top, proposed, multiple, prior_promoted, prior_streak, previous_pre, in_attack_window):
    if not cfg.fix_b_guard or not in_attack_window or not top or not proposed:
        return False
    is_upward_two = proposed["freq"] > top["freq"] and multiple == 2
    established = (prior_streak >= cfg.guard_established_frames and
                   close(prior_promoted, top["freq"], cfg.guard_pre_match_cents) and
                   close(previous_pre, top["freq"], cfg.guard_pre_match_cents))
    weak_escalation = proposed["score"] / max(top["score"], 1e-12) < cfg.guard_max_relative_score
    return is_upward_two and established and weak_escalation


def replay(rows, tracker_cfg, family_cfg, stability_cfg, cfg: RootFixConfig):
    """Replay the frozen pipeline, applying only the named counterfactuals."""
    pre_frequency = pre_confidence = 0.0
    has_pitch, hold = False, 0
    promotion_streak = 0
    previous_promoted_frequency = 0.0
    promotion_required_frames = family_cfg.promote_confirm_frames
    targets: deque[float] = deque(maxlen=6)
    stability_out, previous_envelope = 0.0, 0.0

    trusted_frequency, trusted_age = 0.0, 999999
    excursion_active, excursion_frames = False, 0
    excursion_anchor = 0.0
    last_onset = -1e9
    trace = []
    for source in rows:
        if source["onset"]:
            last_onset = source["time_sec"]
        in_recovery_attack_window = source["time_sec"] - last_onset <= cfg.recovery_attack_window_sec
        candidates = forensics.candidate_dicts(source)
        top, proposed, promotion_proposed, relative_score, multiple, eligible = forensics.family_details(candidates, family_cfg)
        previous_pre = pre_frequency if has_pitch else 0.0
        prior_promoted, prior_streak = previous_promoted_frequency, promotion_streak
        guard_new_escalation = False
        family_guard_active = False

        if promotion_proposed and proposed is not None:
            same_proposal = previous_promoted_frequency > 0 and close(proposed["freq"], previous_promoted_frequency, 216.0)
            if same_proposal:
                promotion_streak += 1
            else:
                guard_new_escalation = family_guard_applies(
                    cfg, top, proposed, multiple, prior_promoted, prior_streak, previous_pre,
                    in_recovery_attack_window)
                promotion_streak = 1
                promotion_required_frames = (cfg.guard_confirm_frames if guard_new_escalation
                                             else family_cfg.promote_confirm_frames)
            previous_promoted_frequency = proposed["freq"]
            family_guard_active = promotion_required_frames > family_cfg.promote_confirm_frames
            promotion_confirmed = promotion_streak >= promotion_required_frames
        else:
            promotion_streak = 0
            previous_promoted_frequency = 0.0
            promotion_required_frames = family_cfg.promote_confirm_frames
            promotion_confirmed = False
        selected = proposed if (promotion_proposed and promotion_confirmed) else top
        selected_confidence = min(1.0, selected["score"]) if selected else 0.0
        can_acquire = bool(selected and source["gate"] and source["envelope"] >= tracker_cfg.gate_on and
                           selected_confidence >= tracker_cfg.acquire_confidence)
        can_hold = bool(selected and source["gate"] and source["envelope"] >= tracker_cfg.gate_off and
                        selected_confidence >= tracker_cfg.hold_confidence)

        target_anchor_credible = bool(selected and top_is_selected(top, selected) and
                                      selected_confidence >= cfg.recovery_anchor_score)
        target_return_credible = bool(selected and top_is_selected(top, selected) and
                                      selected_confidence >= cfg.recovery_return_score)
        recovery_triggered = False
        recovery_reason = ""
        if cfg.fix_a_recovery and has_pitch and selected and in_recovery_attack_window:
            if excursion_active:
                excursion_frames += 1
                if target_return_credible and close(selected["freq"], excursion_anchor, cfg.recovery_return_cents) and can_hold:
                    recovery_triggered = True
                    recovery_reason = "strong_raw_target_returns_to_recent_credible_anchor"
                    excursion_active = False
                elif excursion_frames > cfg.recovery_max_frames:
                    excursion_active = False
            elif (trusted_frequency > 0 and trusted_age <= cfg.recovery_anchor_max_age_frames and can_hold and
                  not close(selected["freq"], trusted_frequency, cfg.recovery_departure_cents)):
                excursion_active, excursion_frames, excursion_anchor = True, 0, trusted_frequency

        slew, slew_source = 0.0, ""
        if not has_pitch and can_acquire:
            pre_frequency, pre_confidence, has_pitch, hold = selected["freq"], selected_confidence, True, tracker_cfg.hold_frames
            slew, slew_source = 1.0, "acquire"
        elif has_pitch and can_hold:
            slew = family_cfg.promoted_slew if promotion_confirmed else family_cfg.sustain_slew
            pre_frequency += slew * (selected["freq"] - pre_frequency)
            pre_confidence, hold = selected_confidence, tracker_cfg.hold_frames
            slew_source = "confirmed_family" if promotion_confirmed else "sustain"
        elif has_pitch and hold > 0:
            hold -= 1
            pre_confidence *= 0.90
            slew_source = "hold_previous"
        else:
            pre_frequency, pre_confidence, has_pitch, slew_source = 0.0, 0.0, False, "invalidate"

        if recovery_triggered and has_pitch and selected:
            if cfg.recovery_mode == "fast":
                pre_frequency += cfg.recovery_slew * (selected["freq"] - pre_frequency)
                slew, slew_source = cfg.recovery_slew, "rootfix_fast_recovery"
            else:
                pre_frequency = selected["freq"]
                slew, slew_source = 1.0, "rootfix_direct_recovery"
            pre_confidence, hold = selected_confidence, tracker_cfg.hold_frames

        if target_anchor_credible and has_pitch and close(selected["freq"], pre_frequency, cfg.recovery_anchor_match_cents):
            trusted_frequency = selected["freq"]
            trusted_age = 0
        else:
            trusted_age += 1
        if not has_pitch:
            trusted_frequency = 0.0
            trusted_age = 999999
            excursion_active = False

        history_before = list(targets)
        if not has_pitch or pre_frequency <= 0:
            targets.clear()
            final_frequency, stability_out = 0.0, 0.0
            stability_mode, alpha, trend, step = "invalid", 0.0, 0.0, 0.0
            attack_flag = family_flag = large_step_flag = motion_flag = False
        else:
            targets.append(pre_frequency)
            history = list(targets)
            trend = cents(pre_frequency, float(np.median(history[-6:-3]))) if len(history) >= 6 else 0.0
            step = cents(pre_frequency, stability_out) if stability_out else 0.0
            attack_flag = bool(source["onset"]) or (previous_envelope > 0 and source["envelope"] > previous_envelope * 1.25)
            family_flag = bool(promotion_confirmed)
            large_step_flag = abs(step) >= stability_cfg.bypass_cents
            motion_flag = attack_flag or family_flag or large_step_flag or abs(trend) >= stability_cfg.motion_cents
            alpha = stability_cfg.moving_alpha if motion_flag else stability_cfg.stable_alpha
            stability_mode = "moving" if motion_flag else "stable"
            final_frequency = pre_frequency if not stability_out else stability_out * (2.0 ** (alpha * cents(pre_frequency, stability_out) / 1200.0))
            stability_out, previous_envelope = final_frequency, source["envelope"]

        row = dict(source)
        row.update({
            "raw_freq_hz": selected["freq"] if selected else 0.0,
            "raw_confidence": selected["score"] if selected else 0.0,
            "top_raw_candidate_freq": top["freq"] if top else 0.0,
            "top_raw_candidate_score": top["score"] if top else 0.0,
            "family_candidate_freq": proposed["freq"] if proposed else 0.0,
            "family_candidate_score": proposed["score"] if proposed else 0.0,
            "family_multiple": multiple,
            "family_relative_score": relative_score,
            "family_promotion_proposed": int(promotion_proposed),
            "family_promotion_streak_before": prior_streak,
            "family_promotion_streak": promotion_streak,
            "family_promotion_confirmed": int(promotion_confirmed),
            "family_promoted": int(promotion_confirmed),
            "family_guard_active": int(family_guard_active),
            "family_guard_new_escalation": int(guard_new_escalation),
            "family_guard_required_frames": promotion_required_frames if family_guard_active else family_cfg.promote_confirm_frames,
            "previous_promoted_frequency": prior_promoted,
            "selected_candidate_freq": selected["freq"] if selected else 0.0,
            "selected_candidate_score": selected["score"] if selected else 0.0,
            "previous_pre_stability_freq": previous_pre,
            "pre_stability_target_freq": selected["freq"] if selected else 0.0,
            "pre_stability_output_freq": pre_frequency if has_pitch else 0.0,
            "stability_input_hz": pre_frequency if has_pitch else 0.0,
            "selected_slew": slew,
            "slew_source": slew_source,
            "hold_frames_remaining": hold,
            "trusted_frequency_hz": trusted_frequency,
            "trusted_frequency_age_frames": trusted_age,
            "recovery_attack_window": int(in_recovery_attack_window),
            "recovery_excursion_active": int(excursion_active),
            "recovery_excursion_anchor_hz": excursion_anchor if excursion_active else 0.0,
            "recovery_excursion_frames": excursion_frames if excursion_active else 0,
            "recovery_triggered": int(recovery_triggered),
            "recovery_reason": recovery_reason,
            "stability_history": json.dumps(history_before),
            "stability_trend_cents": trend, "stability_step_cents": step,
            "stability_attack_flag": int(attack_flag), "stability_family_flag": int(family_flag),
            "stability_large_step_flag": int(large_step_flag), "stability_motion_flag": int(motion_flag),
            "stability_mode": stability_mode, "stability_alpha": alpha,
            "final_tracked_freq": final_frequency, "tracked_freq_hz": final_frequency,
            "pitch_valid": int(has_pitch), "tracker_confidence": pre_confidence,
            "family_eligible_relations": json.dumps(eligible),
        })
        for rank in range(1, 5):
            row[f"candidate{rank}_freq"] = source.get(f"c{rank}_freq", 0.0)
            row[f"candidate{rank}_score"] = source.get(f"c{rank}_score", 0.0)
        row["error_cents"] = cents(final_frequency, row["reference_freq_hz"]) if (has_pitch and row["reference_voiced"] and row["reference_freq_hz"] > 0) else ""
        row["classification"] = analyze.classify(row)
        row["octave_error"] = 1 if row["classification"] == "octave_up" else -1 if row["classification"] == "octave_down" else 0
        trace.append(row)
    return trace


def attach_frozen_gain(rows):
    gains = envelope_lab.apply_envelope(envelope_lab.load_rows(STABILITY), envelope_lab.CONFIGS[1])
    assert len(rows) == len(gains)
    for row, gain_row in zip(rows, gains):
        row["synth_gain"] = gain_row["synth_gain"]
        row["final_synth_gain"] = gain_row["synth_gain"]
    return rows


def frame_dt(rows):
    return rows[1]["time_sec"] - rows[0]["time_sec"]


def annotate_forensics(rows):
    rows = copy.deepcopy(rows)
    forensics.attach_all_attack_contexts(rows)
    contexts = forensics.read_attack_contexts()
    forensics.map_contexts(rows, contexts)
    events = forensics.contiguous_error_events(rows, contexts, frame_dt(rows))
    return rows, contexts, events, forensics.root_cause_report(events, rows)


def recovery_latencies(baseline_rows, variant_rows, contexts):
    """Timing from a frozen baseline target-return frame to a settled variant."""
    dt = frame_dt(baseline_rows)
    results = []
    for context in contexts:
        indices = [i for i, row in enumerate(baseline_rows) if context["onset"] <= row["time_sec"] <= context["end"]]
        was_wrong_target = False
        for i in indices:
            base = baseline_rows[i]
            selected_correct = close(base["selected_candidate_freq"], context["reference"], ERROR_CENTS)
            base_wrong = abs(cents(base["final_tracked_freq"], context["reference"])) >= ERROR_CENTS
            if not selected_correct:
                was_wrong_target = True
                continue
            if not (was_wrong_target and base_wrong):
                continue
            end = min(len(variant_rows), i + 12)
            for j in range(i, end - 2):
                if all(close(variant_rows[k]["final_tracked_freq"], context["reference"], CORRECT_CENTS) for k in range(j, j + 3)):
                    results.append({"attack_index": context["attack_index"], "target_return_time_sec": base["time_sec"],
                                    "recovery_time_ms": (j - i) * dt * 1000.0})
                    break
            break
    values = [item["recovery_time_ms"] for item in results]
    return {"count": len(values), "median_ms": float(np.median(values)) if values else None,
            "p90_ms": float(np.percentile(values, 90)) if values else None, "events": results}


def compare_corrections(baseline_rows, variant_rows):
    corrections = []
    for index, (old, new) in enumerate(zip(baseline_rows, variant_rows)):
        if abs(old["final_tracked_freq"] - new["final_tracked_freq"]) < 1e-9:
            continue
        if old["final_tracked_freq"] <= 0 or new["final_tracked_freq"] <= 0:
            continue
        if abs(cents(old["final_tracked_freq"], new["final_tracked_freq"])) < 5.0:
            continue
        reference, source = 0.0, ""
        if new.get("settled_reference_freq", 0) > 0:
            reference, source = new["settled_reference_freq"], "settled_attack_reference"
        elif new["reference_voiced"] and new["reference_confidence"] >= forensics.REFERENCE_CONFIDENCE:
            reference, source = new["reference_freq_hz"], "pYIN"
        history = variant_rows[max(0, index - 8):index + 1]
        if new["recovery_triggered"]:
            reason = "A_direct_recovery"
        elif new["family_guard_active"]:
            reason = "B_family_guard"
        elif any(item["recovery_triggered"] for item in history):
            reason = "A_recovery_settling"
        elif any(item["family_guard_active"] for item in history):
            reason = "B_guard_settling"
        else:
            reason = "state_convergence"
        if reference <= 0:
            outcome, old_error, new_error = "reference_uncertain", None, None
        else:
            old_error, new_error = abs(cents(old["final_tracked_freq"], reference)), abs(cents(new["final_tracked_freq"], reference))
            outcome = "helpful" if new_error < old_error - 10 else "harmful" if new_error > old_error + 10 else "neutral"
        corrections.append({"time_sec": new["time_sec"], "old_output_hz": old["final_tracked_freq"],
                            "new_output_hz": new["final_tracked_freq"], "reference_hz": reference,
                            "reference_source": source, "old_error_cents": old_error, "new_error_cents": new_error,
                            "reason": reason, "outcome": outcome})
    counts = {key: sum(item["outcome"] == key for item in corrections)
              for key in ("helpful", "neutral", "harmful", "reference_uncertain")}
    return corrections, {"correction_frame_count": len(corrections), **counts,
                         "new_false_corrections": counts["harmful"]}


def contiguous_count(mask):
    events, active = 0, False
    for value in mask:
        if value and not active:
            events += 1
        active = bool(value)
    return events


def rule_fire_summary(rows):
    dt = frame_dt(rows)
    recovery = [bool(row["recovery_triggered"]) for row in rows]
    guard = [bool(row["family_guard_active"]) for row in rows]
    guard_start = [bool(row["family_guard_new_escalation"]) for row in rows]
    return {
        "fix_a_direct_recovery": {"trigger_frames": sum(recovery), "trigger_events": contiguous_count(recovery),
                                   "duration_sec": sum(recovery) * dt},
        "fix_b_family_guard": {"guard_frames": sum(guard), "guard_events": contiguous_count(guard),
                                 "new_escalation_events": sum(guard_start), "duration_sec": sum(guard) * dt},
    }


def full_metrics(rows):
    duration = rows[-1]["time_sec"] + frame_dt(rows)
    report = analyze.summary(rows, duration)
    report["frequency_band_metrics"] = octave_lab.band_metrics(rows)
    selected_stability_cfg = stability_lab.StabilityConfig(method="adaptive_onepole", stable_alpha=.45,
                                                            moving_alpha=1.0, motion_cents=8.0, bypass_cents=140.0)
    report["stability_metrics"] = stability_lab.stability_metrics(rows, selected_stability_cfg)
    return report


def write_csv(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(key for row in rows for key in row.keys()))
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def write_trace(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row.keys()))
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def render(rows, output, start=None, stop=None):
    source, sample_rate = sf.read(SOURCE, dtype="float32", always_2d=True)
    source = np.mean(source, axis=1)
    if start is not None:
        source = source[int(start * sample_rate):int(stop * sample_rate)]
    time = np.asarray([row["time_sec"] for row in rows])
    frequency = np.asarray([row["final_tracked_freq"] for row in rows])
    gain = np.asarray([row["final_synth_gain"] for row in rows])
    sample_time = np.arange(len(source), dtype=np.float64) / sample_rate + (start or 0.0)
    frequency = np.interp(sample_time, time, frequency, left=0.0, right=0.0)
    gain = np.interp(sample_time, time, gain, left=0.0, right=0.0)
    phase = np.cumsum(2 * np.pi * frequency / sample_rate)
    sf.write(output, np.column_stack((source, .18 * gain * np.sin(phase))).astype(np.float32), sample_rate, subtype="PCM_24")


def plot_comparison(outputs, start, stop, path, title):
    names = ["rootfix_baseline", "rootfix_A", "rootfix_B", "rootfix_AB"]
    base = outputs["rootfix_baseline"]
    selected = [row for row in base if start <= row["time_sec"] <= stop]
    time = np.asarray([row["time_sec"] for row in selected])
    figure, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True, constrained_layout=True)
    axes[0].plot(time, [row["envelope"] for row in selected], color="#4477aa", label="input envelope")
    axes[0].plot(time, [row["final_synth_gain"] for row in selected], color="#cc6677", label="frozen envelope_02 gain")
    axes[0].set_ylabel("level"); axes[0].legend(loc="upper right"); axes[0].set_title(title)
    for rank, color in ((1, "#bbbbbb"), (2, "#cccccc"), (3, "#dddddd")):
        axes[1].scatter(time, [row[f"c{rank}_freq"] if row[f"c{rank}_freq"] > 0 else np.nan for row in selected],
                        s=10, alpha=.45, color=color, label=f"candidate {rank}" if rank == 1 else None)
    styles = {"rootfix_baseline": ("#222222", "-"), "rootfix_A": ("#44aa99", "--"),
              "rootfix_B": ("#cc6677", "--"), "rootfix_AB": ("#332288", "-")}
    for name in names:
        rows = [row for row in outputs[name] if start <= row["time_sec"] <= stop]
        color, line = styles[name]
        axes[1].plot(time, [row["final_tracked_freq"] for row in rows], color=color, linestyle=line, linewidth=1.8, label=name)
    reference = np.asarray([row["reference_freq_hz"] for row in selected])
    axes[1].plot(time, np.where(reference > 0, reference, np.nan), color="#ddcc77", linewidth=1.4, label="pYIN")
    axes[1].set_ylabel("Hz"); axes[1].set_xlabel("time (s)"); axes[1].legend(loc="upper right", ncol=2, fontsize=8)
    figure.savefig(path, dpi=150); plt.close(figure)


def result_for_config(cfg, baseline_rows, tracker_cfg, family_cfg, stability_cfg):
    rows = attach_frozen_gain(replay(baseline_rows, tracker_cfg, family_cfg, stability_cfg, cfg))
    return rows


def save_result(root, cfg, rows, baseline_annotated, contexts):
    directory = root / cfg.name; directory.mkdir(parents=True, exist_ok=True)
    annotated, _, events, causes = annotate_forensics(rows)
    corrections, correction_summary = compare_corrections(baseline_annotated, annotated)
    result = {"config": asdict(cfg), "full_metrics": full_metrics(rows),
              "forensic": {"error_events_remaining": len(events),
                            "error_frames_remaining": sum(event["error_frame_count"] for event in events),
                            "root_causes": causes,
                            "recovery_latency_after_frozen_target_return": recovery_latencies(baseline_annotated, annotated, contexts)},
              "corrections": correction_summary, "rule_fires": rule_fire_summary(rows)}
    (directory / "config.json").write_text(json.dumps(asdict(cfg), indent=2) + "\n")
    (directory / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    (directory / "forensic_comparison.json").write_text(json.dumps(result["forensic"], indent=2) + "\n")
    (directory / "counterfactual_corrections.json").write_text(json.dumps(corrections, indent=2) + "\n")
    write_trace(directory / "frames.csv.gz", annotated)
    return result, annotated


def key_comparison(baseline, variant):
    return {"baseline": baseline, "variant": variant}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    tracker_cfg = analyze.TrackerConfig()
    family_cfg, stability_cfg = forensics.FamilyConfig(), forensics.StabilityConfig()
    raw = source_rows()
    baseline_rows = result_for_config(CONFIGS[0], raw, tracker_cfg, family_cfg, stability_cfg)
    octave_rows, stability_rows = forensics.read_rows(forensics.OCTAVE), forensics.read_rows(forensics.STABILITY)
    parity = forensics.assert_parity(baseline_rows, octave_rows, stability_rows)
    baseline_annotated, contexts, _, _ = annotate_forensics(baseline_rows)
    outputs, results, annotated_outputs = {}, {}, {}
    for cfg in CONFIGS:
        rows = baseline_rows if cfg.name == "rootfix_baseline" else result_for_config(cfg, raw, tracker_cfg, family_cfg, stability_cfg)
        if any(a["synth_gain"] != b["synth_gain"] for a, b in zip(baseline_rows, rows)):
            raise RuntimeError(f"frozen gain changed in {cfg.name}")
        result, annotated = save_result(args.output_root, cfg, rows, baseline_annotated, contexts)
        outputs[cfg.name], results[cfg.name], annotated_outputs[cfg.name] = rows, result, annotated
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "comparison.json").write_text(json.dumps({"baseline_parity": parity, "experiments": results}, indent=2) + "\n")
    for name in ("rootfix_A", "rootfix_B", "rootfix_AB"):
        (args.output_root / f"baseline_vs_{name.split('_')[-1]}.json").write_text(json.dumps(key_comparison(results["rootfix_baseline"], results[name]), indent=2) + "\n")
    plots = args.output_root / "plots"; plots.mkdir(exist_ok=True)
    for start, stop, label in ((176.35, 176.62, "176_416"), (152.85, 153.10, "152_928"),
                               (164.40, 164.62, "control_164"), (69.24, 69.38, "low_octave_recovery_69"),
                               (159.65, 160.30, "slide_160")):
        plot_comparison(outputs, start, stop, plots / f"{label}.png", f"Root-fix comparison: {label}")
    if args.render:
        for name in ("rootfix_baseline", "rootfix_A", "rootfix_B", "rootfix_AB"):
            render(outputs[name], args.output_root / f"{name}.wav")
        compare = args.output_root / "audio_compare"; compare.mkdir(exist_ok=True)
        for start, stop, label in ((176.35, 176.62, "176"), (152.85, 153.10, "152"),
                                   (164.40, 164.62, "control_164"), (69.24, 69.38, "low_69"),
                                   (159.65, 160.30, "slide_160")):
            for name in ("rootfix_baseline", "rootfix_A", "rootfix_B", "rootfix_AB"):
                render(outputs[name], compare / f"{label}_{name}.wav", start, stop)
    compact = {name: {"error_frames": result["forensic"]["error_frames_remaining"],
                       "error_events": result["forensic"]["error_events_remaining"],
                       "octave_down_sec": result["full_metrics"]["octave_down_duration_sec"],
                       "octave_up_sec": result["full_metrics"]["octave_up_duration_sec"],
                       "median_cents": result["full_metrics"]["median_absolute_cents_error"],
                       "p90_cents": result["full_metrics"]["p90_absolute_cents_error"],
                       "within_25": result["full_metrics"]["within_25_cents"],
                       "corrections": result["corrections"]} for name, result in results.items()}
    print(json.dumps({"output_root": str(args.output_root), "parity": parity, "experiments": compact}, indent=2))


if __name__ == "__main__":
    main()
