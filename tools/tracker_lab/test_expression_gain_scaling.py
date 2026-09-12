#!/usr/bin/env python3
"""Gain-invariance validation for finite expression calibration.

This is a validation fixture only: it replays the committed studio WAV at
synthetic input gains and checks that each independent calibration maps the
same performance gesture to a similar normalized amplitude/attack trajectory.
It does not alter the production audio path or tracker configuration.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import soundfile as sf


def frame_rms(samples: np.ndarray, hop: int) -> np.ndarray:
    usable = samples[: len(samples) // hop * hop].reshape(-1, hop)
    return np.sqrt(np.mean(usable * usable, axis=1))


def minimum_span(reference: float) -> float:
    return max(abs(reference), 1.0e-7) * 0.02


def soft_range(values: np.ndarray) -> tuple[float, float]:
    """Same fast-outer / slow-inner estimator used by ExpressionCalibration."""
    mean = m2 = low = high = float(values[0])
    count = 1
    for value in values[1:]:
        accepted = float(value)
        if count >= 24:
            deviation = math.sqrt(max(m2 / max(count - 1, 1), 0.0))
            guard = 4.0 * deviation if deviation > 0.0 else minimum_span(mean)
            accepted = min(max(accepted, mean - guard), mean + guard)
        count += 1
        delta = accepted - mean
        mean += delta / count
        m2 += delta * (accepted - mean)
        low += (0.05 if accepted < low else 0.001) * (accepted - low)
        high += (0.05 if accepted > high else 0.001) * (accepted - high)
    span = minimum_span(max(abs(mean), abs(high)))
    if high - low < span:
        midpoint = 0.5 * (low + high)
        low, high = max(0.0, midpoint - 0.5 * span), midpoint + 0.5 * span
    return low, high


def normalize(values: np.ndarray) -> np.ndarray:
    low, high = soft_range(values)
    return np.clip((values - low) / (high - low), 0.0, 1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path, nargs="?", default=Path("basik hehe.wav"))
    args = parser.parse_args()
    audio, sample_rate = sf.read(args.wav, always_2d=True, dtype="float32")
    source = audio.mean(axis=1)
    hop = max(1, round(sample_rate / 93.75))
    rms = frame_rms(source, hop)
    attack = np.maximum(np.diff(rms, prepend=rms[0]), 0.0)

    normalized: dict[float, tuple[np.ndarray, np.ndarray]] = {}
    for gain in (0.25, 1.0, 2.5):
        normalized[gain] = (normalize(rms * gain), normalize(attack * gain))

    reference_amp, reference_attack = normalized[1.0]
    for gain in (0.25, 2.5):
        amp, atk = normalized[gain]
        amp_error = float(np.median(np.abs(amp - reference_amp)))
        attack_error = float(np.median(np.abs(atk - reference_attack)))
        print(f"gain={gain:.2f} amplitude_median_abs_delta={amp_error:.6f} "
              f"attack_median_abs_delta={attack_error:.6f}")
        assert amp_error <= 0.03
        assert attack_error <= 0.03
    print(f"frames={len(rms)} sample_rate={sample_rate} hop={hop} status=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
