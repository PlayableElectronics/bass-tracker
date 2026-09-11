#!/usr/bin/env python3
"""Read-only test of early/peak/settled pitch behavior at existing onsets."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import envelope_lab


ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "experiments" / "stability_v1" / "frames.csv.gz"
REFERENCE_CONFIDENCE = .30
EARLY_TRACKER_CONFIDENCE = .46  # Existing embedded hold-confidence, evaluation only here.
SETTLE_START_SEC = .080
SETTLE_STOP_SEC = .180
PEAK_STOP_SEC = .100
PRE_CONTEXT_SEC = .032
POST_CONTEXT_SEC = .200
CANDIDATE_MATCH_CENTS = 65.0
PLOT_LIMIT = 16


def cents(a, b):
    return 1200.0 * math.log2(a / b) if a > 0 and b > 0 else float("nan")


def pitch_relation(error):
    """Coarse, interpretable relation to a settled target; no tracker decision."""
    if not np.isfinite(error):
        return "unavailable"
    if abs(error) < 700.0:
        return "same_octave"
    if 900.0 <= abs(error) <= 1500.0:
        return "octave_up" if error > 0 else "octave_down"
    return "other_large_error"


def fnum(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_median(values):
    return float(np.median(values)) if values else 0.0


def candidate_set(row):
    return [{"rank": rank, "frequency_hz": fnum(row.get(f"c{rank}_freq")),
             "score": fnum(row.get(f"c{rank}_score"), -1.0)} for rank in range(1, 5)]


def candidate_match(row, target):
    matches = [candidate for candidate in candidate_set(row)
               if candidate["frequency_hz"] > 0 and abs(cents(candidate["frequency_hz"], target)) <= CANDIDATE_MATCH_CENTS]
    if not matches:
        return False, 0, 0.0
    best = min(matches, key=lambda candidate: candidate["rank"])
    return True, best["rank"], best["score"]


def event_end(rows, onset_index):
    limit = rows[onset_index]["time_sec"] + POST_CONTEXT_SEC
    next_onset = next((row["time_sec"] for row in rows[onset_index + 1:] if row["onset"]), limit)
    return min(limit, next_onset)


def early_credible(rows, onset_index, end_time):
    for index in range(onset_index, len(rows)):
        row = rows[index]
        if row["time_sec"] >= end_time:
            break
        if row["pitch_valid"] and row["tracked_freq_hz"] > 0 and row["tracker_confidence"] >= EARLY_TRACKER_CONFIDENCE:
            return index
    return None


def settled(rows, onset_index, end_time):
    onset = rows[onset_index]["time_sec"]
    selected = [row for row in rows[onset_index:] if onset + SETTLE_START_SEC <= row["time_sec"] <= min(onset + SETTLE_STOP_SEC, end_time)]
    tracker = [row["tracked_freq_hz"] for row in selected if row["pitch_valid"] and row["tracked_freq_hz"] > 0]
    ref_rows = [row for row in selected if row["reference_voiced"] and row["reference_confidence"] >= REFERENCE_CONFIDENCE and row["reference_freq_hz"] > 0]
    return {
        "tracker_freq": safe_median(tracker), "tracker_frame_count": len(tracker),
        "reference_freq": safe_median([row["reference_freq_hz"] for row in ref_rows]),
        "reference_confidence": safe_median([row["reference_confidence"] for row in ref_rows]),
        "reference_frame_count": len(ref_rows), "reference_usable": len(ref_rows) >= 4,
        "window_start_sec": onset + SETTLE_START_SEC, "window_stop_sec": min(onset + SETTLE_STOP_SEC, end_time),
    }


def time_to_settled_neighborhood(rows, start_index, end_time, target):
    """First causal three-frame return to a 50-cent neighborhood of target."""
    if target <= 0:
        return float("nan")
    start_time = rows[start_index]["time_sec"]
    consecutive = 0
    for index in range(start_index, len(rows)):
        row = rows[index]
        if row["time_sec"] > end_time:
            break
        close = (row["pitch_valid"] and row["tracked_freq_hz"] > 0 and
                 abs(cents(row["tracked_freq_hz"], target)) <= 50.0)
        consecutive = consecutive + 1 if close else 0
        if consecutive >= 3:
            return (rows[index - 2]["time_sec"] - start_time) * 1000.0
    return float("nan")


def classify(first_error, peak_error, reference_usable):
    if not reference_usable or not np.isfinite(first_error) or not np.isfinite(peak_error):
        return "E_reference_uncertain"
    first_close, peak_wrong = abs(first_error) <= 50.0, abs(peak_error) >= 100.0
    if first_close and peak_wrong:
        return "A_first_close_peak_wrong"
    if abs(first_error) >= 100.0 and peak_wrong:
        return "B_first_wrong_peak_wrong"
    if first_close and abs(peak_error) <= 50.0:
        return "C_correct_through_peak"
    return "D_mixed_or_large_difference"


def strength_classes(records):
    peaks = np.asarray([record["peak_envelope"] for record in records])
    low, high = np.quantile(peaks, [.333333, .666667])
    for record in records:
        record["attack_strength_class"] = "soft" if record["peak_envelope"] <= low else "medium" if record["peak_envelope"] <= high else "hard"
    return {"soft_upper_peak_envelope": float(low), "medium_upper_peak_envelope": float(high)}


def band(value):
    for low, high, name in ((25, 50, "25-50"), (50, 75, "50-75"), (75, 110, "75-110"), (110, 200, "110-200")):
        if low <= value < high:
            return name
    return "outside_or_uncertain"


def build_records(rows):
    records = []
    onset_indices = [index for index, row in enumerate(rows) if row["onset"]]
    for attack_index, onset_index in enumerate(onset_indices, start=1):
        onset = rows[onset_index]["time_sec"]
        end = event_end(rows, onset_index)
        event_indices = [index for index, row in enumerate(rows) if onset - PRE_CONTEXT_SEC <= row["time_sec"] <= end]
        post_indices = [index for index in event_indices if onset <= rows[index]["time_sec"] <= min(onset + PEAK_STOP_SEC, end)]
        peak_index = max(post_indices, key=lambda index: rows[index]["envelope"]) if post_indices else onset_index
        first_index = early_credible(rows, onset_index, end)
        settle = settled(rows, onset_index, end)
        first = rows[first_index] if first_index is not None else None
        peak = rows[peak_index]
        previous = rows[onset_index - 1] if onset_index else None
        first_tracker = first["tracked_freq_hz"] if first else 0.0
        first_raw = first["raw_freq_hz"] if first else 0.0
        first_conf = first["tracker_confidence"] if first else 0.0
        tracker_target, reference_target = settle["tracker_freq"], settle["reference_freq"]
        first_to_tracker = cents(first_tracker, tracker_target)
        peak_to_tracker = cents(peak["tracked_freq_hz"], tracker_target)
        first_to_reference = cents(first_tracker, reference_target) if settle["reference_usable"] else float("nan")
        peak_to_reference = cents(peak["tracked_freq_hz"], reference_target) if settle["reference_usable"] else float("nan")
        tracker_present, tracker_rank, tracker_score = candidate_match(peak, tracker_target)
        reference_present, reference_rank, reference_score = candidate_match(peak, reference_target) if settle["reference_usable"] else (False, 0, 0.0)
        generic_present, generic_rank, generic_score = ((reference_present, reference_rank, reference_score)
                                                        if settle["reference_usable"] else
                                                        (tracker_present, tracker_rank, tracker_score))
        generic_first_octave = (int(np.isfinite(first_to_reference) and abs(first_to_reference) < 700)
                                if settle["reference_usable"] else int(np.isfinite(first_to_tracker) and abs(first_to_tracker) < 700))
        generic_peak_octave = (int(np.isfinite(peak_to_reference) and abs(peak_to_reference) < 700)
                               if settle["reference_usable"] else int(np.isfinite(peak_to_tracker) and abs(peak_to_tracker) < 700))
        error_rows = []
        if settle["reference_usable"]:
            for index in event_indices:
                row = rows[index]
                if onset <= row["time_sec"] <= end and row["pitch_valid"] and row["tracked_freq_hz"] > 0:
                    error_rows.append((abs(cents(row["tracked_freq_hz"], reference_target)), index))
        max_error, max_error_index = max(error_rows, default=(float("nan"), None))
        max_error_row = rows[max_error_index] if max_error_index is not None else None
        if max_error_row is None:
            max_error_phase = "unavailable"
        elif max_error_row["time_sec"] < peak["time_sec"] - 2 * (rows[1]["time_sec"] - rows[0]["time_sec"]):
            max_error_phase = "before_peak"
        elif max_error_row["time_sec"] <= peak["time_sec"] + 2 * (rows[1]["time_sec"] - rows[0]["time_sec"]):
            max_error_phase = "near_peak"
        else:
            max_error_phase = "after_peak"
        record = {
            "attack_index": attack_index, "onset_time_sec": onset, "event_end_sec": end,
            "first_time_sec": first["time_sec"] if first else 0.0, "first_offset_ms": (first["time_sec"] - onset) * 1000 if first else float("nan"),
            "first_tracked_freq_hz": first_tracker, "first_raw_freq_hz": first_raw, "first_confidence": first_conf,
            "first_stability_input_hz": first.get("stability_input_hz", 0.0) if first else 0.0,
            "first_family_promoted": first["family_promoted"] if first else 0,
            "first_stability_mode": first.get("stability_mode", "") if first else "",
            "first_candidates": json.dumps(candidate_set(first)) if first else "[]",
            "previous_tracked_freq_hz": previous["tracked_freq_hz"] if previous else 0.0,
            "previous_pitch_valid": previous["pitch_valid"] if previous else 0,
            "peak_time_sec": peak["time_sec"], "peak_offset_ms": (peak["time_sec"] - onset) * 1000,
            "peak_envelope": peak["envelope"], "peak_tracked_freq_hz": peak["tracked_freq_hz"], "peak_raw_freq_hz": peak["raw_freq_hz"],
            "peak_reference_freq_hz": peak["reference_freq_hz"], "peak_reference_voiced": peak["reference_voiced"],
            "peak_reference_confidence": peak["reference_confidence"], "peak_tracker_confidence": peak["tracker_confidence"],
            "peak_family_promoted": peak["family_promoted"], "peak_stability_mode": peak.get("stability_mode", ""),
            "peak_stability_input_hz": peak.get("stability_input_hz", 0.0),
            "peak_candidates": json.dumps(candidate_set(peak)),
            "settled_tracker_freq_hz": tracker_target, "settled_tracker_frame_count": settle["tracker_frame_count"],
            "settled_reference_freq_hz": reference_target, "settled_reference_confidence": settle["reference_confidence"],
            "settled_reference_frame_count": settle["reference_frame_count"], "reference_usable": int(settle["reference_usable"]),
            "settled_window_start_sec": settle["window_start_sec"], "settled_window_stop_sec": settle["window_stop_sec"],
            "first_to_tracker_cents": first_to_tracker, "peak_to_tracker_cents": peak_to_tracker,
            "first_to_reference_cents": first_to_reference, "peak_to_reference_cents": peak_to_reference,
            "first_same_octave_as_tracker_settled": int(np.isfinite(first_to_tracker) and abs(first_to_tracker) < 700),
            "peak_same_octave_as_tracker_settled": int(np.isfinite(peak_to_tracker) and abs(peak_to_tracker) < 700),
            "first_same_octave_as_reference_settled": int(np.isfinite(first_to_reference) and abs(first_to_reference) < 700),
            "peak_same_octave_as_reference_settled": int(np.isfinite(peak_to_reference) and abs(peak_to_reference) < 700),
            "settled_tracker_candidate_present_at_peak": int(tracker_present), "settled_tracker_candidate_rank_at_peak": tracker_rank,
            "settled_tracker_candidate_score_at_peak": tracker_score,
            "settled_reference_candidate_present_at_peak": int(reference_present), "settled_reference_candidate_rank_at_peak": reference_rank,
            "settled_reference_candidate_score_at_peak": reference_score,
            "settled_candidate_present_at_peak": int(generic_present), "settled_candidate_rank_at_peak": generic_rank,
            "settled_candidate_score_at_peak": generic_score,
            "first_same_octave": generic_first_octave, "peak_same_octave": generic_peak_octave,
            "first_to_tracker_relation": pitch_relation(first_to_tracker), "peak_to_tracker_relation": pitch_relation(peak_to_tracker),
            "first_to_reference_relation": pitch_relation(first_to_reference), "peak_to_reference_relation": pitch_relation(peak_to_reference),
            "time_first_to_peak_ms": (peak["time_sec"] - first["time_sec"]) * 1000 if first else float("nan"),
            "time_peak_to_settle_window_ms": (settle["window_start_sec"] - peak["time_sec"]) * 1000,
            "time_peak_to_tracker_settled_ms": time_to_settled_neighborhood(rows, peak_index, end, tracker_target),
            "time_peak_to_reference_settled_ms": time_to_settled_neighborhood(rows, peak_index, end, reference_target) if settle["reference_usable"] else float("nan"),
            "max_error_time_sec": max_error_row["time_sec"] if max_error_row else float("nan"),
            "max_error_to_reference_cents": max_error, "max_error_phase": max_error_phase,
            "time_max_error_to_reference_settled_ms": time_to_settled_neighborhood(rows, max_error_index, end, reference_target) if max_error_index is not None else float("nan"),
        }
        record["pattern_tracker"] = classify(first_to_tracker, peak_to_tracker, settle["tracker_frame_count"] >= 4)
        record["pattern_reference"] = classify(first_to_reference, peak_to_reference, settle["reference_usable"])
        record["pattern_class"] = record["pattern_reference"]
        record["first_close_then_any_large_error"] = int(settle["reference_usable"] and abs(first_to_reference) <= 50.0 and max_error >= 100.0)
        record["settled_reference_band"] = band(reference_target) if settle["reference_usable"] else "outside_or_uncertain"
        records.append(record)
    strength = strength_classes(records)
    return records, strength


def percentage(numerator, denominator):
    return float(numerator / denominator * 100.0) if denominator else None


def target_stats(records, target):
    usable = ([record for record in records if record["reference_usable"]]
              if target == "reference" else
              [record for record in records if record["settled_tracker_frame_count"] >= 4])
    usable = [record for record in usable if np.isfinite(record[f"first_to_{target}_cents"]) and np.isfinite(record[f"peak_to_{target}_cents"])]
    first = np.asarray([abs(record[f"first_to_{target}_cents"]) for record in usable])
    peak = np.asarray([abs(record[f"peak_to_{target}_cents"]) for record in usable])
    thresholds = {str(limit): {"first_count": int(np.count_nonzero(first <= limit)), "first_percent": percentage(np.count_nonzero(first <= limit), len(usable)),
                               "peak_count": int(np.count_nonzero(peak <= limit)), "peak_percent": percentage(np.count_nonzero(peak <= limit), len(usable))}
                  for limit in (10, 25, 50, 100)}
    delta = first - peak
    return {
        "usable_attacks": len(usable), "thresholds": thresholds,
        "first_closer_count": int(np.count_nonzero(delta < -10.0)), "first_closer_percent": percentage(np.count_nonzero(delta < -10.0), len(usable)),
        "peak_closer_count": int(np.count_nonzero(delta > 10.0)), "peak_closer_percent": percentage(np.count_nonzero(delta > 10.0), len(usable)),
        "approximately_equal_count": int(np.count_nonzero(abs(delta) <= 10.0)), "approximately_equal_percent": percentage(np.count_nonzero(abs(delta) <= 10.0), len(usable)),
        "first_median_abs_cents": float(np.median(first)) if len(first) else None,
        "peak_median_abs_cents": float(np.median(peak)) if len(peak) else None,
    }


def grouped(records, key, selector=lambda record: True):
    result = {}
    for value in sorted({record[key] for record in records}):
        selected = [record for record in records if record[key] == value and selector(record) and
                    np.isfinite(record["first_to_reference_cents"]) and np.isfinite(record["peak_to_reference_cents"])]
        if not selected:
            continue
        first = np.asarray([abs(record["first_to_reference_cents"]) for record in selected])
        peak = np.asarray([abs(record["peak_to_reference_cents"]) for record in selected])
        result[value] = {"count": len(selected), "first_within_50_percent": percentage(np.count_nonzero(first <= 50), len(selected)),
                         "peak_within_50_percent": percentage(np.count_nonzero(peak <= 50), len(selected)),
                         "pattern_A_percent": percentage(sum(record["pattern_reference"] == "A_first_close_peak_wrong" for record in selected), len(selected)),
                         "first_median_abs_cents": float(np.median(first)), "peak_median_abs_cents": float(np.median(peak))}
    return result


def reference_band_summary(records):
    result = {}
    for name in ("25-50", "50-75", "75-110", "110-200"):
        selected = [record for record in records if record["reference_usable"] and record["settled_reference_band"] == name and
                    np.isfinite(record["first_to_reference_cents"]) and np.isfinite(record["peak_to_reference_cents"])]
        if not selected:
            result[name] = {"count": 0, "first_within_50_percent": None, "peak_within_50_percent": None,
                            "pattern_A_percent": None, "first_median_abs_cents": None, "peak_median_abs_cents": None}
            continue
        result[name] = grouped(selected, "settled_reference_band")[name]
    return result


def max_error_events(records):
    usable = [record for record in records if record["reference_usable"] and np.isfinite(record["max_error_to_reference_cents"])]
    large = [record for record in usable if record["max_error_to_reference_cents"] >= 100.0]
    first_close_large = [record for record in large if record["first_close_then_any_large_error"]]
    phases = {phase: sum(record["max_error_phase"] == phase for record in large) for phase in ("before_peak", "near_peak", "after_peak")}
    recovered = [record for record in large if np.isfinite(record["time_max_error_to_reference_settled_ms"])]
    return {
        "usable_attacks": len(usable), "any_large_error_count": len(large), "any_large_error_percent": percentage(len(large), len(usable)),
        "first_close_then_any_large_error_count": len(first_close_large),
        "first_close_then_any_large_error_percent": percentage(len(first_close_large), len(usable)),
        "max_error_phase_counts": phases,
        "max_error_phase_percent_of_large_errors": {phase: percentage(count, len(large)) for phase, count in phases.items()},
        "recovered_within_attack_window_count": len(recovered),
        "recovered_within_attack_window_percent": percentage(len(recovered), len(large)),
        "recovery_median_ms": safe_median([record["time_max_error_to_reference_settled_ms"] for record in recovered]),
        "recovery_p90_ms": float(np.percentile([record["time_max_error_to_reference_settled_ms"] for record in recovered], 90)) if recovered else None,
    }


def relation_counts(records, target):
    usable = [record for record in records if (record["reference_usable"] if target == "reference" else record["settled_tracker_frame_count"] >= 4)]
    return {phase: {relation: sum(record[f"{phase}_to_{target}_relation"] == relation for record in usable)
                    for relation in ("same_octave", "octave_up", "octave_down", "other_large_error", "unavailable")}
            for phase in ("first", "peak")}


def phase_stats(rows, records):
    """Classify tracker errors versus reference settled target around the envelope peak."""
    before = near = after = total = 0
    dt = rows[1]["time_sec"] - rows[0]["time_sec"]
    for record in records:
        if not record["reference_usable"]:
            continue
        start, stop, peak = record["onset_time_sec"], record["event_end_sec"], record["peak_time_sec"]
        for row in rows:
            if not start <= row["time_sec"] <= stop or not row["pitch_valid"]:
                continue
            error = abs(cents(row["tracked_freq_hz"], record["settled_reference_freq_hz"]))
            if not np.isfinite(error) or error < 100:
                continue
            total += 1
            if row["time_sec"] < peak - 2 * dt:
                before += 1
            elif row["time_sec"] <= peak + 2 * dt:
                near += 1
            else:
                after += 1
    return {"wrong_frame_count": total, "before_peak_count": before, "near_peak_count": near, "after_peak_count": after,
            "before_peak_percent": percentage(before, total), "near_peak_percent": percentage(near, total), "after_peak_percent": percentage(after, total)}


def candidate_evidence(records):
    selected = [record for record in records if record["reference_usable"] and abs(record["peak_to_reference_cents"]) >= 100]
    present = [record for record in selected if record["settled_reference_candidate_present_at_peak"]]
    ranks = [record["settled_reference_candidate_rank_at_peak"] for record in present]
    return {"peak_wrong_attack_count": len(selected), "settled_reference_present_top4_count": len(present),
            "settled_reference_present_top4_percent": percentage(len(present), len(selected)),
            "candidate_rank_counts": {str(rank): ranks.count(rank) for rank in range(1, 5)},
            "median_relative_score_to_top": safe_median([record["settled_reference_candidate_score_at_peak"] /
                                                           max(candidate["score"] for candidate in json.loads(record["peak_candidates"])) for record in present])}


def write_csv(records, path):
    fields = list(records[0].keys())
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(records)


def plot_summary(records, output):
    selected = [record for record in records if record["reference_usable"]]
    first = np.asarray([record["first_to_reference_cents"] for record in selected])
    peak = np.asarray([record["peak_to_reference_cents"] for record in selected])
    strength = [record["attack_strength_class"] for record in selected]
    color = {"soft": "#4477aa", "medium": "#66aa55", "hard": "#cc6677"}
    figure, axes = plt.subplots(1, 2, figsize=(13, 5), constrained_layout=True)
    for level in color:
        mask = np.asarray([value == level for value in strength])
        axes[0].scatter(first[mask], peak[mask], label=level, color=color[level], alpha=.75)
    axes[0].axline((0, 0), slope=1, color="#777777", linestyle="--")
    axes[0].axhline(0, color="#999999", linewidth=.6); axes[0].axvline(0, color="#999999", linewidth=.6)
    axes[0].set_xlim(-1400, 1400); axes[0].set_ylim(-1400, 1400)
    axes[0].set_xlabel("first credible − settled reference (cents)"); axes[0].set_ylabel("peak − settled reference (cents)")
    axes[0].set_title("Early versus envelope-peak error"); axes[0].legend()
    axes[1].hist([abs(first), abs(peak)], bins=np.linspace(0, 1300, 27), label=["first credible", "envelope peak"], color=["#4477aa", "#cc6677"], alpha=.7)
    axes[1].set_xlabel("absolute cents from settled reference"); axes[1].set_ylabel("attacks"); axes[1].set_title("Attack-phase error distribution"); axes[1].legend()
    figure.savefig(output, dpi=150); plt.close(figure)


def plot_attack(rows, record, output):
    start, stop = record["onset_time_sec"] - PRE_CONTEXT_SEC, record["event_end_sec"]
    selected = [row for row in rows if start <= row["time_sec"] <= stop]
    time = np.asarray([row["time_sec"] for row in selected])
    envelope = np.asarray([row["envelope"] for row in selected])
    raw = np.asarray([row["raw_freq_hz"] for row in selected])
    tracked = np.asarray([row["tracked_freq_hz"] for row in selected])
    reference = np.asarray([row["reference_freq_hz"] for row in selected])
    figure, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True, constrained_layout=True)
    axes[0].plot(time, envelope, color="#4477aa", label="input envelope")
    axes[0].axvline(record["onset_time_sec"], color="#222222", linestyle=":", label="onset")
    axes[0].axvline(record["peak_time_sec"], color="#cc6677", linestyle="--", label="envelope peak")
    axes[0].set_ylabel("envelope"); axes[0].legend(loc="upper right")
    axes[1].plot(time, raw, color="#66aa55", label="raw")
    axes[1].plot(time, tracked, color="#332288", label="fixed tracked")
    axes[1].plot(time, np.where(reference > 0, reference, np.nan), color="#ddcc77", label="pYIN")
    for row in selected:
        for candidate in candidate_set(row):
            if candidate["frequency_hz"] > 0:
                axes[1].scatter(row["time_sec"], candidate["frequency_hz"], color="#999999", s=9 + 20 * max(0, candidate["score"]), alpha=.35)
    axes[1].axvline(record["onset_time_sec"], color="#222222", linestyle=":")
    axes[1].axvline(record["peak_time_sec"], color="#cc6677", linestyle="--")
    if record["first_time_sec"]:
        axes[1].scatter(record["first_time_sec"], record["first_tracked_freq_hz"], color="#000000", marker="o", zorder=5, label="first credible")
    axes[1].axvspan(record["settled_window_start_sec"], record["settled_window_stop_sec"], color="#dddddd", alpha=.35, label="settled window")
    axes[1].set_ylabel("Hz"); axes[1].set_xlabel("time (s)"); axes[1].legend(loc="upper right", ncol=2)
    figure.suptitle(f"attack {record['attack_index']} @ {record['onset_time_sec']:.3f}s — {record['pattern_reference']}")
    figure.savefig(output, dpi=150); plt.close(figure)


def choose_examples(records):
    selected = [record for record in records if record["reference_usable"]]
    examples = []
    # Main reported attack glitch and the strongest reference-supported peak error.
    examples.extend([record for record in records if record["attack_index"] in (217, 199)])
    for pattern in ("A_first_close_peak_wrong", "B_first_wrong_peak_wrong", "D_mixed_or_large_difference"):
        examples.extend(sorted([record for record in selected if record["pattern_reference"] == pattern], key=lambda record: abs(record["peak_to_reference_cents"]), reverse=True)[:5])
    examples.extend(sorted([record for record in selected if record["pattern_reference"] == "C_correct_through_peak"], key=lambda record: record["peak_envelope"], reverse=True)[:5])
    for name in ("25-50", "50-75", "75-110", "110-200"):
        examples.extend(sorted([record for record in selected if record["settled_reference_band"] == name], key=lambda record: record["peak_envelope"], reverse=True)[:2])
    unique = {}
    for record in examples:
        unique[record["attack_index"]] = record
    return list(unique.values())[:PLOT_LIMIT]


def summary(records, strength, rows):
    usable = [record for record in records if record["reference_usable"]]
    patterns = {name: sum(record["pattern_reference"] == name for record in records) for name in
                ("A_first_close_peak_wrong", "B_first_wrong_peak_wrong", "C_correct_through_peak", "D_mixed_or_large_difference", "E_reference_uncertain")}
    return {
        "definitions": {"early_tracker_confidence_min": EARLY_TRACKER_CONFIDENCE, "reference_confidence_min": REFERENCE_CONFIDENCE,
                        "peak_window_sec": [0.0, PEAK_STOP_SEC], "settled_window_sec": [SETTLE_START_SEC, SETTLE_STOP_SEC],
                        "credible": "pitch_valid, positive tracked frequency, confidence at or above existing 0.46 hold threshold",
                        "reference_usable": "at least four voiced pYIN frames at or above 0.30 confidence in settled window"},
        "total_attacks": len(records), "reference_usable_attacks": len(usable), "reference_uncertain_attacks": len(records) - len(usable),
        "strength_thresholds": strength, "using_settled_tracker": target_stats(records, "tracker"), "using_settled_reference": target_stats(records, "reference"),
        "pattern_counts": patterns, "pattern_percent_of_total": {name: percentage(value, len(records)) for name, value in patterns.items()},
        "pattern_percent_of_reference_usable": {name: percentage(value, len(usable)) for name, value in patterns.items() if name != "E_reference_uncertain"},
        "candidate_evidence_at_wrong_peak": candidate_evidence(records), "wrong_frame_phase_vs_peak": phase_stats(rows, records),
        "frequency_band_reference": reference_band_summary(records),
        "attack_strength_reference": grouped(records, "attack_strength_class", lambda record: record["reference_usable"]),
        "any_large_error_in_attack": max_error_events(records),
        "relation_counts_using_settled_reference": relation_counts(records, "reference"),
        "relation_counts_using_settled_tracker": relation_counts(records, "tracker"),
        "pattern_counts_using_settled_tracker": {name: sum(record["pattern_tracker"] == name for record in records) for name in
                                                   ("A_first_close_peak_wrong", "B_first_wrong_peak_wrong", "C_correct_through_peak", "D_mixed_or_large_difference", "E_reference_uncertain")},
    }


def summary_text(report):
    reference = report["using_settled_reference"]
    tracker = report["using_settled_tracker"]
    candidate = report["candidate_evidence_at_wrong_peak"]
    patterns = report["pattern_counts"]
    lines = [
        "Attack hypothesis analysis — frozen stability_v1 trajectory",
        "",
        f"attacks: {report['total_attacks']} total; {report['reference_usable_attacks']} usable high-confidence reference; {report['reference_uncertain_attacks']} excluded as reference-uncertain.",
        f"first credible vs settled reference: ±10 {reference['thresholds']['10']['first_count']}/{reference['usable_attacks']} ({reference['thresholds']['10']['first_percent']:.1f}%); ±25 {reference['thresholds']['25']['first_count']}/{reference['usable_attacks']} ({reference['thresholds']['25']['first_percent']:.1f}%); ±50 {reference['thresholds']['50']['first_count']}/{reference['usable_attacks']} ({reference['thresholds']['50']['first_percent']:.1f}%).",
        f"peak vs settled reference: ±10 {reference['thresholds']['10']['peak_count']}/{reference['usable_attacks']} ({reference['thresholds']['10']['peak_percent']:.1f}%); ±25 {reference['thresholds']['25']['peak_count']}/{reference['usable_attacks']} ({reference['thresholds']['25']['peak_percent']:.1f}%); ±50 {reference['thresholds']['50']['peak_count']}/{reference['usable_attacks']} ({reference['thresholds']['50']['peak_percent']:.1f}%).",
        f"first closer than peak: {reference['first_closer_count']}/{reference['usable_attacks']} ({reference['first_closer_percent']:.1f}%); peak closer: {reference['peak_closer_count']}/{reference['usable_attacks']} ({reference['peak_closer_percent']:.1f}%); approximately equal: {reference['approximately_equal_count']}/{reference['usable_attacks']} ({reference['approximately_equal_percent']:.1f}%).",
        f"patterns: A={patterns['A_first_close_peak_wrong']}, B={patterns['B_first_wrong_peak_wrong']}, C={patterns['C_correct_through_peak']}, D={patterns['D_mixed_or_large_difference']}, E={patterns['E_reference_uncertain']}.",
        f"among {candidate['peak_wrong_attack_count']} reference-supported peak errors ≥100 cents, settled reference present in top four candidates: {candidate['settled_reference_present_top4_count']} ({candidate['settled_reference_present_top4_percent'] or 0:.1f}%).",
        f"tracker-target cross-check usable attacks: {tracker['usable_attacks']}.",
        f"any large error in the full 200 ms attack window: {report['any_large_error_in_attack']['any_large_error_count']}/{report['any_large_error_in_attack']['usable_attacks']} ({report['any_large_error_in_attack']['any_large_error_percent']:.1f}%); first close then later large error: {report['any_large_error_in_attack']['first_close_then_any_large_error_count']} ({report['any_large_error_in_attack']['first_close_then_any_large_error_percent']:.1f}%).",
        "",
        "Definitions: first credible = pitch-valid, positive frozen tracked frequency, confidence ≥0.46. Settled = median from 80–180 ms after the onset; reference requires ≥4 pYIN-voiced frames at confidence ≥0.30. Pattern A requires first ≤50 cents and peak ≥100 cents from settled reference.",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    rows = envelope_lab.load_rows(INPUT)
    records, strength = build_records(rows)
    report = summary(records, strength, rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(records, args.output_dir / "attacks.csv")
    with gzip.open(args.output_dir / "attacks.csv.gz", "wt", newline="") as handle:
        fields = list(records[0].keys()); writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(records)
    (args.output_dir / "attacks.csv").unlink()
    with open(args.output_dir / "summary.json", "w") as handle: json.dump(report, handle, indent=2)
    with open(args.output_dir / "summary.txt", "w") as handle:
        handle.write(summary_text(report))
    plot_summary(records, args.output_dir / "summary_scatter_hist.png")
    examples = choose_examples(records)
    examples_dir = args.output_dir / "examples"; examples_dir.mkdir(exist_ok=True)
    for record in examples:
        plot_attack(rows, record, examples_dir / f"attack_{record['attack_index']:03d}_{record['onset_time_sec']:.3f}s.png")
    with open(args.output_dir / "example_attacks.json", "w") as handle:
        json.dump([{key: value for key, value in record.items() if key not in ("first_candidates", "peak_candidates")} for record in examples], handle, indent=2)


if __name__ == "__main__":
    main()
