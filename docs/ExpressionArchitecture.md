# Expression-analysis architecture v1

```text
audio input
  ├─ existing pitch / envelope analysis ──> stable pitch path
  │                                          (unchanged)
  └─ ExpressionAnalyzer ──> raw ExpressionFrame
                               ↓
                     ExpressionCalibration
                               ↓
                        normalized frame
                               ↓
                       ModulationMatrix
                               ↓
                   future resynthesis engine
```

Pitch remains a continuous structural value. The expression frame deliberately
keeps uncertainty and residual evidence that a conventional tracker would
otherwise discard. No expression output feeds back into the pitch detector or
tracker.

## v1 sources

| Source | Raw source / meaning | Normalized range | Cost per analysis frame |
| --- | --- | --- | --- |
| amplitude | existing envelope | 0..1 | none beyond calibration |
| attack strength | existing onset-slope follower | 0..1 | none |
| brightness | high-frequency RMS residual relative to input RMS | 0..1 | two multiplies, subtraction, sqrt |
| periodicity | strongest normalized autocorrelation score | 0..1 | none |
| tracker confidence | selected tracker confidence | 0..1 | none |
| candidate competition | second/top candidate score | 0..1 | none |
| octave tension | strongest 1:2 or 1:3 candidate relationship | 0..1 | at most 36 small comparisons |
| noise/transient | bright, weakly periodic, or attack-like content | 0..1 | few scalar operations |
| decay rate | fractional envelope fall since prior frame | 0..1 | none |
| pitch motion | signed stable-pitch frame delta | -1..+1 | one log2 |
| pitch instability | pre-stability versus final-pitch deviation | 0..1 | one log2 |

`pitch_hz` and `pitch_valid` are retained in `ExpressionFrame`, but are not
calibrated expression sources. Candidate competition and octave tension retain
information even when the tracker selects one stable fundamental.

## Calibration

The global state machine is `UNCALIBRATED → CALIBRATING → FROZEN`.

- `START` resets learned statistics and begins a configurable finite interval
  (30 s default).
- During `CALIBRATING`, each source records a bounded online mean/variance and
  asymmetric soft extrema. After 24 samples, values are clipped to a four
  standard-deviation guard before affecting statistics. Fast outward / slow
  inward extrema approximate robust practical ranges without a histogram.
- `FREEZE` finalizes learned low/high ranges and stops all learning. The timer
  also freezes automatically at the configured duration.
- `RESET` clears learned statistics and restores uncalibrated physical domains.

Every source has a range mode: `AUTO` uses the learned frozen range, `MANUAL`
uses explicit bounds, and `LOCKED` snapshots the current active range. None of
these modes learns notes, tuning, scale, strings, or musical style.

`CalibrationStatus` is a fixed-size POD snapshot of state, elapsed time, and
all learned/active feature ranges. That is the intentionally simple future
serialization boundary for named calibration presets; no filesystem or preset
store is added to firmware in this milestone.

## Modulation matrix

The fixed-capacity matrix has 16 routes. A route specifies a source,
destination, bipolar amount, curve, optional smoothing, and enable flag. Its
destinations are abstract future resynthesis controls: excitation complexity,
spectral distribution, instability interaction, mode coupling, stochastic
excitation, resonator damping, and structural morph. No conventional synth,
FM voice, compressor, or pitch quantizer is implemented here.

At the current 93.75 Hz analysis rate, the new analysis is fixed-size and uses
no allocation, locks, filesystem, FFT, or future samples. The matrix is also
fixed-size; it costs at most 16 routes × 7 destinations of scalar work per
analysis frame, with no routes enabled in the firmware milestone.

## USB / UI boundary

The normal build keeps USB CDC CSV diagnostics, including a compact `expr`
line about 11.7 times per second. The optional USB-MIDI build exposes the
calibration protocol and expression telemetry to `tools/expression_web/`.
Because the installed libDaisy USB backend is non-composite, these are explicit
alternative build modes rather than two competing USB initializations.

## Validation

`tests/ExpressionHostTest.cpp` covers state transitions, frozen learning,
AUTO/MANUAL/LOCKED behavior, bounded normalized outputs, MIDI control decoding,
and matrix routing. `tools/tracker_lab/test_expression_gain_scaling.py` reads
the existing studio recording, replays it at 0.25×, 1×, and 2.5× synthetic
gains, and verifies that separate finite calibrations produce comparable
normalized amplitude and attack trajectories. This is test-only gain scaling;
the production input path remains untouched.
