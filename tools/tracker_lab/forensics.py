#!/usr/bin/env python3
"""Read-only, stage-by-stage forensic replay of the selected Mac tracker.

The replay starts with the committed baseline candidate trace, replays the
committed octave_v1 family state machine and then the selected stability_v1
one-pole.  It asserts parity against both committed trajectories before making
any error attribution.  It never changes a tracker decision.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import analyze
import octave_lab
import replay_family


ROOT = Path(__file__).resolve().parent
BASELINE = ROOT / "baseline" / "frames.csv.gz"
OCTAVE = ROOT / "experiments" / "octave_v1" / "frames.csv.gz"
STABILITY = ROOT / "experiments" / "stability_v1" / "frames.csv.gz"
ATTACKS = ROOT / "attack_hypothesis" / "attacks.csv.gz"
REFERENCE_CONFIDENCE = 0.30
CORRECT_CANDIDATE_CENTS = 65.0
ERROR_CENTS = 100.0
EVENT_CONTEXT_SEC = 0.200
PLOT_EVENT_LIMIT = 10


@dataclass(frozen=True)
class FamilyConfig:
    family_ratio: float = 0.92
    harmonic_tolerance: float = 0.055
    promote_confirm_frames: int = 2
    sustain_slew: float = 0.42
    promoted_slew: float = 0.50


@dataclass(frozen=True)
class StabilityConfig:
    stable_alpha: float = 0.45
    moving_alpha: float = 1.0
    motion_cents: float = 8.0
    bypass_cents: float = 140.0


def cents(a: float, b: float) -> float:
    return 1200.0 * math.log2(a / b) if a > 0 and b > 0 else float("nan")


def finite(value: float) -> bool:
    return bool(np.isfinite(value))


def fnum(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def candidate_dicts(row):
    return [{"rank": rank, "freq": float(row[f"c{rank}_freq"]), "score": float(row[f"c{rank}_score"])}
            for rank in range(1, 5) if float(row[f"c{rank}_freq"]) > 0]


def candidate_near(candidates, target, tolerance=CORRECT_CANDIDATE_CENTS):
    matches = [candidate for candidate in candidates if abs(cents(candidate["freq"], target)) <= tolerance]
    return min(matches, key=lambda candidate: candidate["rank"]) if matches else None


def family_details(candidates, cfg: FamilyConfig):
    """Exact octave_lab family decision, retaining every eligible relation."""
    if not candidates:
        return None, None, False, 0.0, 0, []
    top = max(candidates, key=lambda candidate: candidate["score"])
    eligible = []
    for high in candidates:
        for low in candidates:
            multiple = octave_lab.related_multiple(high["freq"], low["freq"], cfg.harmonic_tolerance)
            if multiple and high["score"] >= cfg.family_ratio * top["score"]:
                eligible.append({"high_rank": high["rank"], "high_freq": high["freq"], "high_score": high["score"],
                                 "low_rank": low["rank"], "low_freq": low["freq"], "low_score": low["score"],
                                 "multiple": multiple})
    if not eligible:
        return top, top, False, 0.0, 0, eligible
    choice = max(eligible, key=lambda item: (item["high_freq"], item["high_score"]))
    proposed = next(candidate for candidate in candidates if candidate["rank"] == choice["high_rank"])
    return top, proposed, True, proposed["score"] / max(top["score"], 1e-12), choice["multiple"], eligible


def replay_trace(baseline_rows, tracker_cfg, family_cfg, stability_cfg):
    """Replay both realtime stages while writing causal internal state."""
    pre_frequency = pre_confidence = 0.0
    has_pitch, hold = False, 0
    promotion_streak = 0
    previous_promoted_frequency = 0.0
    targets: deque[float] = deque(maxlen=6)
    stability_out = 0.0
    previous_envelope = 0.0
    trace = []

    for source in baseline_rows:
        candidates = candidate_dicts(source)
        top, proposed, promotion_proposed, relative_score, multiple, eligible = family_details(candidates, family_cfg)
        previous_promoted_before = previous_promoted_frequency
        streak_before = promotion_streak
        promotion_confirmed = promotion_proposed
        if promotion_proposed and proposed is not None:
            if previous_promoted_frequency > 0 and abs(math.log2(proposed["freq"] / previous_promoted_frequency)) < 0.18:
                promotion_streak += 1
            else:
                promotion_streak = 1
            previous_promoted_frequency = proposed["freq"]
            promotion_confirmed = promotion_streak >= family_cfg.promote_confirm_frames
        else:
            promotion_streak = 0
            previous_promoted_frequency = 0.0
        selected = proposed if (promotion_proposed and promotion_confirmed) else top
        selected_confidence = min(1.0, selected["score"]) if selected else 0.0
        can_acquire = bool(selected and source["gate"] and source["envelope"] >= tracker_cfg.gate_on and
                           selected_confidence >= tracker_cfg.acquire_confidence)
        can_hold = bool(selected and source["gate"] and source["envelope"] >= tracker_cfg.gate_off and
                        selected_confidence >= tracker_cfg.hold_confidence)
        previous_pre = pre_frequency if has_pitch else 0.0
        slew = 0.0
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
            pre_confidence *= .90
            slew_source = "hold_previous"
        else:
            pre_frequency, pre_confidence, has_pitch, slew_source = 0.0, 0.0, False, "invalidate"

        # Exact selected stability_v1 adaptive-one-pole logic, with its causal
        # history retained for explanation rather than altered.
        stability_history_before = list(targets)
        pre_target = selected["freq"] if selected else 0.0
        if not has_pitch or pre_frequency <= 0:
            targets.clear()
            final_frequency = 0.0
            stability_mode, alpha = "invalid", 0.0
            trend = step = 0.0
            attack_flag = family_flag = large_step_flag = motion_flag = False
            # Match stability_lab: invalid frames clear filter frequency/history
            # but intentionally do not advance the prior valid envelope.
            stability_out = final_frequency
        else:
            target = pre_frequency
            targets.append(target)
            history = list(targets)
            trend = cents(target, float(np.median(history[-6:-3]))) if len(history) >= 6 else 0.0
            step = cents(target, stability_out) if stability_out else 0.0
            attack_flag = bool(source["onset"]) or (previous_envelope > 0 and source["envelope"] > previous_envelope * 1.25)
            family_flag = bool(promotion_confirmed)
            large_step_flag = abs(step) >= stability_cfg.bypass_cents
            motion_flag = attack_flag or family_flag or large_step_flag or abs(trend) >= stability_cfg.motion_cents
            alpha = stability_cfg.moving_alpha if motion_flag else stability_cfg.stable_alpha
            stability_mode = "moving" if motion_flag else "stable"
            final_frequency = target if not stability_out else stability_out * (2.0 ** (alpha * cents(target, stability_out) / 1200.0))
            stability_out, previous_envelope = final_frequency, source["envelope"]
        row = {
            "time_sec": source["time_sec"], "onset": int(source["onset"]), "envelope": source["envelope"], "gate": int(source["gate"]),
            "reference_freq_hz": source["reference_freq_hz"], "reference_voiced": int(source["reference_voiced"]),
            "reference_confidence": source["reference_confidence"],
            "top_raw_candidate_freq": top["freq"] if top else 0.0, "top_raw_candidate_score": top["score"] if top else 0.0,
            "family_candidate_freq": proposed["freq"] if proposed else 0.0, "family_candidate_score": proposed["score"] if proposed else 0.0,
            "family_multiple": multiple, "family_relative_score": relative_score,
            "family_promotion_proposed": int(promotion_proposed), "family_promotion_streak_before": streak_before,
            "family_promotion_streak": promotion_streak, "family_promotion_confirmed": int(promotion_confirmed),
            "previous_promoted_frequency": previous_promoted_before,
            "selected_candidate_freq": selected["freq"] if selected else 0.0,
            "selected_candidate_score": selected["score"] if selected else 0.0,
            "previous_pre_stability_freq": previous_pre, "pre_stability_target_freq": pre_target,
            "pre_stability_output_freq": pre_frequency if has_pitch else 0.0,
            "selected_slew": slew, "slew_source": slew_source, "hold_frames_remaining": hold,
            "stability_history": json.dumps(stability_history_before), "stability_trend_cents": trend,
            "stability_step_cents": step, "stability_attack_flag": int(attack_flag),
            "stability_family_flag": int(family_flag), "stability_large_step_flag": int(large_step_flag),
            "stability_motion_flag": int(motion_flag), "stability_mode": stability_mode, "stability_alpha": alpha,
            "final_tracked_freq": final_frequency, "pitch_valid": int(has_pitch), "tracker_confidence": pre_confidence,
            "family_eligible_relations": json.dumps(eligible),
        }
        for rank in range(1, 5):
            candidate = next((item for item in candidates if item["rank"] == rank), None)
            row[f"candidate{rank}_freq"] = candidate["freq"] if candidate else 0.0
            row[f"candidate{rank}_score"] = candidate["score"] if candidate else 0.0
        trace.append(row)
    return trace


def assert_parity(trace, octave_rows, stability_rows):
    assert len(trace) == len(octave_rows) == len(stability_rows)
    errors = {"octave_selected": [], "pre_stability": [], "final": [], "family_promoted": [], "stability_alpha": []}
    for replay, octave, stability in zip(trace, octave_rows, stability_rows):
        errors["octave_selected"].append(abs(replay["selected_candidate_freq"] - octave["raw_freq_hz"]))
        errors["pre_stability"].append(abs(replay["pre_stability_output_freq"] - octave["tracked_freq_hz"]))
        errors["final"].append(abs(replay["final_tracked_freq"] - stability["tracked_freq_hz"]))
        errors["family_promoted"].append(abs(replay["family_promotion_confirmed"] - int(octave["family_promoted"])))
        errors["stability_alpha"].append(abs(replay["stability_alpha"] - float(stability["stability_alpha"])))
    maxima = {name: float(max(values)) for name, values in errors.items()}
    assert maxima["octave_selected"] < 1e-8, maxima
    assert maxima["pre_stability"] < 1e-8, maxima
    assert maxima["final"] < 1e-8, maxima
    assert maxima["family_promoted"] == 0.0, maxima
    assert maxima["stability_alpha"] < 1e-8, maxima
    return maxima


def read_attack_contexts():
    with gzip.open(ATTACKS, "rt", newline="") as handle:
        records = list(csv.DictReader(handle))
    contexts = []
    for record in records:
        if record["reference_usable"] != "1" or fnum(record["max_error_to_reference_cents"]) < ERROR_CENTS:
            continue
        contexts.append({"attack_index": int(record["attack_index"]), "onset": fnum(record["onset_time_sec"]),
                         "end": fnum(record["event_end_sec"]), "reference": fnum(record["settled_reference_freq_hz"]),
                         "peak": fnum(record["peak_time_sec"]), "peak_envelope": fnum(record["peak_envelope"])})
    return contexts


def attribute_frame(row, reference):
    """First pipeline stage that is inconsistent with the settled target."""
    if not row["pitch_valid"] or row["final_tracked_freq"] <= 0:
        return "F_previous_state_hold", "invalid final output while attack context remains active", "slew_or_state_lag"
    final_error = abs(cents(row["final_tracked_freq"], reference))
    if final_error < ERROR_CENTS:
        return "", "", ""
    candidates = [{"rank": rank, "freq": row[f"candidate{rank}_freq"], "score": row[f"candidate{rank}_score"]}
                  for rank in range(1, 5) if row[f"candidate{rank}_freq"] > 0]
    top_correct = bool(candidates and abs(cents(row["top_raw_candidate_freq"], reference)) <= ERROR_CENTS)
    family_correct = row["family_candidate_freq"] > 0 and abs(cents(row["family_candidate_freq"], reference)) <= ERROR_CENTS
    selected_correct = row["selected_candidate_freq"] > 0 and abs(cents(row["selected_candidate_freq"], reference)) <= ERROR_CENTS
    pre_correct = row["pre_stability_output_freq"] > 0 and abs(cents(row["pre_stability_output_freq"], reference)) <= ERROR_CENTS
    if row["slew_source"] == "hold_previous":
        return "F_previous_state_hold", "candidate path did not update pre-stability state; held prior output", "slew_or_state_lag"
    if not top_correct:
        return "A_detector_top_candidate_wrong", "highest-scoring raw candidate is not within 100 cents of settled reference", "target_selection_error"
    if not family_correct and not selected_correct:
        return "B_family_selector_changes_correct_top", "top raw candidate is correct but family proposal/effective selection is not", "target_selection_error"
    if family_correct and not selected_correct and row["family_promotion_proposed"] and not row["family_promotion_confirmed"]:
        return "C_promotion_confirmation_delays_correct_family", "correct family proposal was replaced by top raw candidate pending confirmation", "target_selection_error"
    if selected_correct and not pre_correct:
        return "D_pre_stability_slew_lag", "selected target is correct but causal pre-stability slew has not reached it", "slew_or_state_lag"
    if pre_correct:
        return "E_adaptive_stability_lag", "pre-stability output is correct but adaptive one-pole output remains wrong", "stability_lag"
    return "H_other_state_interaction", "selection target and output disagree with reference without a single earlier-stage condition", "target_selection_error"


def map_contexts(trace, contexts):
    dt = trace[1]["time_sec"] - trace[0]["time_sec"]
    by_time = []
    for context in contexts:
        indices = [index for index, row in enumerate(trace) if context["onset"] <= row["time_sec"] <= context["end"]]
        for index in indices:
            row = trace[index]
            error = cents(row["final_tracked_freq"], context["reference"])
            category, detail, group = attribute_frame(row, context["reference"])
            correct_candidate = candidate_near([{"rank": rank, "freq": row[f"candidate{rank}_freq"], "score": row[f"candidate{rank}_score"]}
                                                 for rank in range(1, 5) if row[f"candidate{rank}_freq"] > 0], context["reference"])
            row["attack_index"] = context["attack_index"]
            row["settled_reference_freq"] = context["reference"]
            row["error_to_reference_cents"] = error
            row["classification"] = analyze.classify({"pitch_valid": int(row["pitch_valid"]), "reference_voiced": 1,
                                                        "reference_freq_hz": context["reference"], "tracked_freq_hz": row["final_tracked_freq"],
                                                        "error_cents": error})
            row["correct_candidate_present"] = int(correct_candidate is not None)
            row["correct_candidate_rank"] = correct_candidate["rank"] if correct_candidate else 0
            row["correct_candidate_score"] = correct_candidate["score"] if correct_candidate else 0.0
            row["primary_attribution"] = category
            row["attribution_detail"] = detail
            row["attribution_group"] = group
            by_time.append((context, index))
    return by_time, dt


def contiguous_error_events(trace, contexts, dt):
    events = []
    for context in contexts:
        indices = [index for index, row in enumerate(trace) if row.get("attack_index") == context["attack_index"] and
                   finite(row.get("error_to_reference_cents", float("nan"))) and abs(row["error_to_reference_cents"]) >= ERROR_CENTS]
        current = []
        for index in indices:
            if current and index != current[-1] + 1:
                events.append(build_event(trace, context, current, dt, len(events) + 1))
                current = []
            current.append(index)
        if current:
            events.append(build_event(trace, context, current, dt, len(events) + 1))
    return events


def build_event(trace, context, indices, dt, event_id):
    first = trace[indices[0]]
    worst = max((trace[index] for index in indices), key=lambda row: abs(row["error_to_reference_cents"]))
    primary = first["primary_attribution"]
    all_causes = Counter(trace[index]["primary_attribution"] for index in indices)
    recovery = None
    for index in range(indices[-1] + 1, len(trace)):
        row = trace[index]
        if row["time_sec"] > context["end"]:
            break
        nearby = trace[index:index + 3]
        if len(nearby) == 3 and all(abs(cents(item["final_tracked_freq"], context["reference"])) <= 50 for item in nearby):
            recovery = (row["time_sec"] - trace[indices[-1]]["time_sec"]) * 1000.0
            break
    return {"event_id": event_id, "attack_index": context["attack_index"], "event_start_sec": first["time_sec"],
            "event_end_sec": trace[indices[-1]]["time_sec"], "duration_sec": len(indices) * dt,
            "attack_onset_sec": context["onset"],
            "reference_freq_hz": context["reference"], "max_error_cents": worst["error_to_reference_cents"],
            "primary_failure_stage": primary, "secondary_factor": "; ".join(key for key in all_causes if key != primary),
            "correct_candidate_present": first["correct_candidate_present"], "correct_candidate_rank": first["correct_candidate_rank"],
            "correct_candidate_score": first["correct_candidate_score"], "wrong_selected_freq": first["selected_candidate_freq"],
            "recovery_time_ms": recovery if recovery is not None else "", "error_frame_count": len(indices),
            "frame_cause_counts": json.dumps(dict(all_causes), sort_keys=True)}


def select_controls(trace, contexts):
    controls = []
    bad_attacks = {context["attack_index"] for context in contexts}
    all_onsets = sorted({row["attack_index"] for row in trace if row.get("attack_index")})
    # Context mapping only contains error attacks, so derive controls directly
    # from complete trace after adding contexts separately in main.
    control_candidates = []
    for attack in all_onsets:
        if attack in bad_attacks:
            continue
        rows = [row for row in trace if row.get("attack_index") == attack]
        if not rows:
            continue
        errors = [abs(row["error_to_reference_cents"]) for row in rows if finite(row.get("error_to_reference_cents", float("nan")))]
        if not errors or max(errors) >= 50:
            continue
        strongest_relation, strongest_row = 0.0, None
        for row in rows:
            candidate_set = [{"freq": row[f"candidate{rank}_freq"], "score": row[f"candidate{rank}_score"]}
                             for rank in range(1, 5) if row[f"candidate{rank}_freq"] > 0]
            for high in candidate_set:
                for low in candidate_set:
                    if octave_lab.related_multiple(high["freq"], low["freq"], .055):
                        strength = min(high["score"], low["score"])
                        if strength > strongest_relation:
                            strongest_relation, strongest_row = strength, row
        if strongest_row is not None:
            strongest_row = dict(strongest_row)
            strongest_row["control_ambiguity_score"] = strongest_relation
            strongest_row["control_max_error_cents"] = max(errors)
            control_candidates.append(strongest_row)
    return sorted(control_candidates, key=lambda row: row["control_ambiguity_score"], reverse=True)[:5]


def event_window(event):
    """Dedicated requested windows retain meaningful lead-in and recovery."""
    onset = event["attack_onset_sec"]
    if abs(onset - 176.416) < .01:
        return 176.35, 176.60
    if abs(onset - 152.928) < .01:
        return 152.85, 153.15
    return event["event_start_sec"] - .075, event["event_end_sec"] + .100


def plot_event(trace, event, output):
    start, stop = event_window(event)
    rows = [row for row in trace if start <= row["time_sec"] <= stop]
    t = np.asarray([row["time_sec"] for row in rows])
    figure, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True, constrained_layout=True)
    axes[0].plot(t, [row["envelope"] for row in rows], label="input envelope", color="#4477aa")
    axes[0].scatter([row["time_sec"] for row in rows if row["onset"]], [row["envelope"] for row in rows if row["onset"]], marker="|", s=160, color="#222222", label="onset")
    axes[0].set_ylabel("envelope"); axes[0].legend(loc="upper right")
    for rank, color in ((1, "#999999"), (2, "#bbbbbb"), (3, "#cccccc"), (4, "#dddddd")):
        axes[1].scatter(t, [row[f"candidate{rank}_freq"] if row[f"candidate{rank}_freq"] > 0 else np.nan for row in rows],
                        s=[9 + 22 * max(0, row[f"candidate{rank}_score"]) for row in rows], color=color, alpha=.55,
                        label=f"candidate {rank}" if rank == 1 else None)
    axes[1].plot(t, [row["top_raw_candidate_freq"] for row in rows], color="#66aa55", linewidth=1.0, label="top raw")
    axes[1].plot(t, [row["family_candidate_freq"] for row in rows], color="#cc6677", linewidth=1.1, label="family proposal")
    axes[1].plot(t, [row["selected_candidate_freq"] for row in rows], color="#332288", linestyle="--", linewidth=1.2, label="selected target")
    axes[1].plot(t, [row["pre_stability_output_freq"] for row in rows], color="#aa4499", linewidth=1.4, label="pre-stability")
    axes[1].plot(t, [row["final_tracked_freq"] for row in rows], color="#000000", linewidth=1.7, label="final")
    axes[1].axhline(event["reference_freq_hz"], color="#ddcc77", linewidth=1.8, label="settled pYIN reference")
    proposed = [row for row in rows if row["family_promotion_proposed"]]
    confirmed = [row for row in rows if row["family_promotion_confirmed"]]
    bad = [row for row in rows if row.get("event_id") == event["event_id"]]
    axes[1].scatter([row["time_sec"] for row in proposed], [row["family_candidate_freq"] for row in proposed], marker="^", color="#cc6677", s=30, label="promotion proposed")
    axes[1].scatter([row["time_sec"] for row in confirmed], [row["selected_candidate_freq"] for row in confirmed], marker="s", facecolors="none", edgecolors="#332288", s=45, label="promotion confirmed")
    axes[1].scatter([row["time_sec"] for row in bad], [row["final_tracked_freq"] for row in bad], marker="x", color="#d62728", s=38, label="error frame")
    axes[1].set_ylabel("Hz"); axes[1].set_xlabel("time (s)"); axes[1].legend(loc="upper right", ncol=2, fontsize=8)
    figure.suptitle(f"Forensic event {event['event_id']}: {event['primary_failure_stage']} @ {event['event_start_sec']:.3f}s")
    figure.savefig(output, dpi=150); plt.close(figure)


def frame_line(row):
    candidates = ", ".join(f"#{rank} {row[f'candidate{rank}_freq']:.2f}@{row[f'candidate{rank}_score']:.3f}"
                           for rank in range(1, 5) if row[f"candidate{rank}_freq"] > 0)
    return (f"t={row['time_sec']:.6f} env={row['envelope']:.5f} pYIN={row.get('reference_freq_hz', 0):.2f} "
            f"(conf={row.get('reference_confidence', 0):.2f}) settled_ref={row.get('settled_reference_freq', 0):.2f} "
            f"top={row['top_raw_candidate_freq']:.2f}@{row['top_raw_candidate_score']:.3f}; [{candidates}]\n"
            f"  family={row['family_candidate_freq']:.2f}@{row['family_candidate_score']:.3f} "
            f"proposed={row['family_promotion_proposed']} streak={row['family_promotion_streak']} confirmed={row['family_promotion_confirmed']} "
            f"multiple={row['family_multiple']} -> selected={row['selected_candidate_freq']:.2f}; "
            f"pre {row['previous_pre_stability_freq']:.2f}->{row['pre_stability_output_freq']:.2f} ({row['slew_source']}, slew={row['selected_slew']:.2f}); "
            f"stability={row['stability_mode']} alpha={row['stability_alpha']:.2f}; final={row['final_tracked_freq']:.2f}; "
            f"error={row.get('error_to_reference_cents', float('nan')):.1f}; attribution={row.get('primary_attribution', '')}\n")


def write_event_markdown(trace, event, output):
    start, stop = event_window(event)
    rows = [row for row in trace if start <= row["time_sec"] <= stop]
    lines = [f"# Event {event['event_id']} — {event['event_start_sec']:.3f} s", "",
             f"- Settled reference: {event['reference_freq_hz']:.3f} Hz", f"- Error duration: {event['duration_sec'] * 1000:.1f} ms", f"- Maximum error: {event['max_error_cents']:.1f} cents", f"- Primary failure: `{event['primary_failure_stage']}`", f"- First wrong selected target: {event['wrong_selected_freq']:.3f} Hz", "", "## Frame-by-frame replay", ""]
    for index, row in enumerate(rows, start=1):
        lines.extend([f"### Frame {index}", "", "```text", frame_line(row).rstrip(), "```", ""])
    output.write_text("\n".join(lines))


def write_controls_markdown(trace, controls, output):
    lines = ["# Ambiguous but correct controls", "", "These attacks contain at least one 1:2 or 1:3 candidate relation but remain within 50 cents of their settled reference throughout the mapped 200 ms context. The first control is a near-equal-score, confirmed promotion; the others show weaker harmonic relatives that correctly do not qualify for promotion.", ""]
    for row in controls:
        lines.extend([f"## Attack {row['attack_index']} @ {row['time_sec']:.3f} s", "",
                      f"Strongest 1:2/1:3 pair minimum score: {row['control_ambiguity_score']:.3f}; maximum reference error in context: {row['control_max_error_cents']:.1f} cents.",
                      "", "```text", frame_line(row).rstrip(), "```", ""])
    output.write_text("\n".join(lines))


def full_trace_fields(trace):
    return list(dict.fromkeys(key for row in trace for key in row.keys()))


def write_csv(path, rows, fields=None):
    if not rows:
        return
    fields = fields or list(rows[0].keys())
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def read_rows(path):
    return replay_family.read_rows(path)


def attach_all_attack_contexts(trace):
    """Map all strict-reference attacks for controls; errors are selected later."""
    with gzip.open(ATTACKS, "rt", newline="") as handle:
        records = list(csv.DictReader(handle))
    all_contexts = [{"attack_index": int(record["attack_index"]), "onset": fnum(record["onset_time_sec"]),
                     "end": fnum(record["event_end_sec"]), "reference": fnum(record["settled_reference_freq_hz"])}
                    for record in records if record["reference_usable"] == "1"]
    for context in all_contexts:
        for row in trace:
            if context["onset"] <= row["time_sec"] <= context["end"]:
                row["attack_index"] = context["attack_index"]
                row["settled_reference_freq"] = context["reference"]
                row["error_to_reference_cents"] = cents(row["final_tracked_freq"], context["reference"])
                row["classification"] = analyze.classify({"pitch_valid": int(row["pitch_valid"]), "reference_voiced": 1,
                                                            "reference_freq_hz": context["reference"], "tracked_freq_hz": row["final_tracked_freq"],
                                                            "error_cents": row["error_to_reference_cents"]})
    return all_contexts


def root_cause_report(events, trace):
    stages = ("A_detector_top_candidate_wrong", "B_family_selector_changes_correct_top",
              "C_promotion_confirmation_delays_correct_family", "D_pre_stability_slew_lag",
              "E_adaptive_stability_lag", "F_previous_state_hold", "G_reference_uncertain", "H_other_state_interaction")
    event_counter = Counter(event["primary_failure_stage"] for event in events)
    frames = [row for row in trace if row.get("primary_attribution")]
    frame_counter = Counter(row["primary_attribution"] for row in frames)
    groups = Counter(row["attribution_group"] for row in frames)
    candidate_present = sum(row["correct_candidate_present"] for row in frames)
    candidate_rank = Counter(row["correct_candidate_rank"] for row in frames)
    top_correct = sum(abs(cents(row["top_raw_candidate_freq"], row["settled_reference_freq"])) <= ERROR_CENTS for row in frames)
    selected_correct = sum(abs(cents(row["selected_candidate_freq"], row["settled_reference_freq"])) <= ERROR_CENTS for row in frames)
    pre_correct = sum(abs(cents(row["pre_stability_output_freq"], row["settled_reference_freq"])) <= ERROR_CENTS for row in frames)
    return {"event_primary_counts": {stage: event_counter[stage] for stage in stages},
            "error_frame_primary_counts": {stage: frame_counter[stage] for stage in stages},
            "error_frame_group_counts": {group: groups[group] for group in ("target_selection_error", "slew_or_state_lag", "stability_lag")},
            "candidate_evidence_error_frames": {"total": len(frames), "correct_candidate_present": candidate_present,
                                                "correct_candidate_rank_counts": {str(rank): candidate_rank[rank] for rank in range(0, 5)},
                                                "top_raw_within_100_cents": top_correct, "selected_target_within_100_cents": selected_correct,
                                                "pre_stability_within_100_cents": pre_correct},
            "ranking": [{"stage": stage, "event_count": event_counter[stage], "error_frame_count": frame_counter[stage]}
                        for stage in sorted(stages, key=lambda stage: (event_counter[stage], frame_counter[stage]), reverse=True) if event_counter[stage] or frame_counter[stage]]}


def peak_candidate_cases(trace):
    """The ten earlier peak-error cases, augmented with causal stage data."""
    with gzip.open(ATTACKS, "rt", newline="") as handle:
        records = list(csv.DictReader(handle))
    cases = []
    for record in records:
        if record["reference_usable"] != "1" or abs(fnum(record["peak_to_reference_cents"])) < ERROR_CENTS:
            continue
        peak_time, reference = fnum(record["peak_time_sec"]), fnum(record["settled_reference_freq_hz"])
        row = min(trace, key=lambda item: abs(item["time_sec"] - peak_time))
        candidates = [{"rank": rank, "freq": row[f"candidate{rank}_freq"], "score": row[f"candidate{rank}_score"]}
                      for rank in range(1, 5) if row[f"candidate{rank}_freq"] > 0]
        reference_candidate = candidate_near(candidates, reference)
        top_is_c1 = abs(row["top_raw_candidate_freq"] - row["candidate1_freq"]) < 1e-8
        selected_correct = abs(cents(row["selected_candidate_freq"], reference)) <= ERROR_CENTS
        pre_correct = abs(cents(row["pre_stability_output_freq"], reference)) <= ERROR_CENTS
        if selected_correct and not pre_correct:
            explanation = "reference candidate is selected; pre-stability slew is still converging from prior state"
        elif top_is_c1 and reference_candidate and reference_candidate["rank"] == 1 and not selected_correct:
            explanation = "correct candidate #1 is replaced by family selection"
        elif not top_is_c1:
            explanation = "candidate list #1 is not the strongest raw score on this frame"
        else:
            explanation = "top raw candidate itself is not the settled-reference candidate"
        cases.append({"attack_index": int(record["attack_index"]), "onset_time_sec": fnum(record["onset_time_sec"]),
                      "peak_time_sec": peak_time, "reference_freq_hz": reference,
                      "candidate1_freq": row["candidate1_freq"], "candidate1_score": row["candidate1_score"],
                      "candidate1_is_strongest_raw": int(top_is_c1), "top_raw_freq": row["top_raw_candidate_freq"],
                      "top_raw_score": row["top_raw_candidate_score"], "reference_candidate_rank": reference_candidate["rank"] if reference_candidate else 0,
                      "reference_candidate_score": reference_candidate["score"] if reference_candidate else 0.0,
                      "family_candidate_freq": row["family_candidate_freq"], "family_promotion_confirmed": row["family_promotion_confirmed"],
                      "selected_candidate_freq": row["selected_candidate_freq"], "pre_stability_output_freq": row["pre_stability_output_freq"],
                      "final_tracked_freq": row["final_tracked_freq"], "error_to_reference_cents": row.get("error_to_reference_cents", cents(row["final_tracked_freq"], reference)),
                      "primary_attribution": row.get("primary_attribution", ""), "explanation": explanation})
    return cases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    tracker_cfg = analyze.TrackerConfig()
    family_cfg, stability_cfg = FamilyConfig(), StabilityConfig()
    baseline, octave_rows, stability_rows = read_rows(BASELINE), read_rows(OCTAVE), read_rows(STABILITY)
    trace = replay_trace(baseline, tracker_cfg, family_cfg, stability_cfg)
    parity = assert_parity(trace, octave_rows, stability_rows)
    all_contexts = attach_all_attack_contexts(trace)
    error_contexts = read_attack_contexts()
    map_contexts(trace, error_contexts)
    dt = trace[1]["time_sec"] - trace[0]["time_sec"]
    events = contiguous_error_events(trace, error_contexts, dt)
    for event in events:
        for row in trace:
            if event["event_start_sec"] <= row["time_sec"] <= event["event_end_sec"] and row.get("attack_index") == event["attack_index"] and abs(row.get("error_to_reference_cents", 0)) >= ERROR_CENTS:
                row["event_id"] = event["event_id"]
    controls = select_controls(trace, error_contexts)
    output = args.output_dir; output.mkdir(parents=True, exist_ok=True)
    events_dir = output / "events"; plots_dir = output / "plots"
    events_dir.mkdir(exist_ok=True); plots_dir.mkdir(exist_ok=True)
    with gzip.open(output / "frame_trace.csv.gz", "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=full_trace_fields(trace), extrasaction="ignore", lineterminator="\n")
        writer.writeheader(); writer.writerows(trace)
    write_csv(output / "summary.csv", events)
    root_causes = root_cause_report(events, trace)
    peak_cases = peak_candidate_cases(trace)
    write_csv(output / "candidate1_peak_cases.csv", peak_cases)
    report = {"source": str(BASELINE), "pipeline": {"family": family_cfg.__dict__, "stability": stability_cfg.__dict__},
              "parity_max_abs_error": parity, "strict_reference_attack_contexts": len(all_contexts),
              "attack_error_contexts": len(error_contexts), "error_events": len(events), "error_frames": sum(event["error_frame_count"] for event in events),
              "root_causes": root_causes, "peak_candidate_cases": peak_cases, "events": events,
              "controls": [{"attack_index": row["attack_index"], "time_sec": row["time_sec"], "reference": row["settled_reference_freq"]} for row in controls]}
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "root_causes.json").write_text(json.dumps(root_causes, indent=2) + "\n")
    important = sorted(events, key=lambda event: abs(event["max_error_cents"]), reverse=True)[:PLOT_EVENT_LIMIT]
    # Always retain the two explicitly requested events even if they fall just below a cutoff.
    important_ids = {event["event_id"] for event in important}
    for event in events:
        if abs(event["event_start_sec"] - 176.501333) < .03 or abs(event["event_start_sec"] - 152.928) < .08:
            important_ids.add(event["event_id"])
    for event in events:
        if event["event_id"] in important_ids:
            stem = f"{event['attack_onset_sec']:.3f}".replace(".", "_")
            plot_event(trace, event, plots_dir / f"event_{stem}.png")
            write_event_markdown(trace, event, events_dir / f"{event['attack_onset_sec']:.3f}.md")
    write_controls_markdown(trace, controls, events_dir / "controls.md")
    print(json.dumps({"output_dir": str(output), "parity": parity, "events": len(events), "root_causes": root_causes}, indent=2))


if __name__ == "__main__":
    main()
