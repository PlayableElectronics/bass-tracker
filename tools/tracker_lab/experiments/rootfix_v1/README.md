# Root-fix v1 — Mac-only counterfactual experiment

This experiment addresses only the two tracker-state causes identified by the
forensic analysis in `ffb154e58277a933591613b7c984ca43cb746914`.  It replays
the frozen `stability_v1` candidate trajectory from `basik hehe.wav` and
retains the proven octave-family selector, adaptive-stability layer, and the
frozen `envelope_02` gain trace.  It does not modify the source tracker,
detector, envelope, or any Daisy firmware.

## Reproduction

From the repository root:

```bash
caffeinate -dims env MPLCONFIGDIR=/private/tmp/mpl-tracker \
  .venv-tracker-lab/bin/python tools/tracker_lab/rootfix_lab.py \
  --output-root tracker_runs/rootfix_final6 --render
```

The replay asserts exact parity between its `rootfix_baseline` and the frozen
tracker trajectory before applying any counterfactual.  It also asserts that
all rendered variants use the identical `envelope_02` gain trace.

## Variants

| Variant | Intervention | Full-track result |
| --- | --- | --- |
| Baseline | No intervention | 67 forensic frames / 31 events |
| A | Direct recovery from a short stale slew excursion | 59 frames / 31 events |
| B | Guard a weak high-harmonic promotion from a stable stronger raw winner | 59 frames / 30 events |
| A+B | Both narrow interventions | 55 frames / 30 events |

### Fix A — direct stale-slew recovery

During the first 200 ms after an existing onset, record a recently credible
selected/raw-top pitch (`score >= 0.75`) which matches the pre-slew output
within 100 cents.  If the target then departs by more than 250 cents and, no
later than six frames, raw candidate #1 returns within 70 cents of that anchor
with score `>= 0.90`, set the pre-stability output directly to the returned
target.  The rule has no effect outside that bounded attack window.  The
selected trial uses direct recovery; the faster-slew alternative was retained
only in ignored run output and was weaker.

### Fix B — established-family promotion guard

Only in the same 200 ms post-onset window, escalate promotion confirmation
from the frozen normal two frames to six frames when all of the following hold:

- the proposed replacement is an octave-up member of the raw-top family;
- the currently promoted/pre-slew pitch has already matched that raw-top
  member for at least six frames and within 100 cents;
- the proposed higher candidate is weaker than `0.97 * raw_top_score`.

This is not a global preference for either octave.  New acquisition and
ordinary family recovery retain the existing two-frame rule.

## Selected result: A+B

| Metric | Baseline | A | B | A+B |
| --- | ---: | ---: | ---: | ---: |
| Median absolute error (cents) | 5.08 | 5.08 | 5.08 | 5.08 |
| P90 absolute error (cents) | 12.32 | 12.13 | 12.20 | **12.11** |
| Within ±25 cents | 94.46% | 94.59% | 94.55% | **94.63%** |
| Within ±50 cents | 95.90% | 95.98% | 95.98% | **96.01%** |
| Octave-down duration (s) | 1.952 | 1.952 | 1.952 | 1.952 |
| Octave-up duration (s) | 0.544 | 0.544 | 0.533 | **0.533** |
| Stable-region delta P90 (cents) | 1.357 | 1.360 | 1.353 | 1.357 |
| Forensic error frames | 67 | 59 | 59 | **55** |
| Forensic error events | 31 | 31 | 30 | **30** |

Fix A reduces the forensic slew/state-lag group from 55 to 47 frames and
reduces frozen-target-return recovery from 32.0 ms median / 48.0 ms P90 to
10.7 ms / 21.3 ms.  It fires on 31 frames (0.331 s) across the full recording.
Its counterfactual comparison has 28 helpful, 18 neutral, one harmful, and
137 reference-uncertain changed frames.

Fix B eliminates the four weak-promotion target-selection frames in the
176.416 s event.  It fires for five frames (53.3 ms), in one event only; all
12 changed output frames are classified as 11 helpful and one neutral, with no
harmful or false correction.

### Important event trajectories

At 176.416 s, baseline follows the weak octave-up promotion:

```text
61.86 -> 92.79 -> 108.25 -> 115.98 -> 119.85 Hz
```

Fix A retains that transient but returns directly to 61.86 Hz when the strong
raw candidate returns at 176.544 s.  Fix B and A+B keep the output near
61.86 Hz throughout, because the weak `123.71 Hz @ 0.922` promotion cannot
displace the stable `61.86 Hz @ 0.990` raw winner.

At 152.928 s the detector is genuinely wrong initially; Fix B correctly does
nothing.  Once the ~47 Hz raw target returns, Fix A/A+B remove the stale
pre-slew tail: baseline rises `34.30 -> 39.66 -> 42.77 Hz`, while A/A+B move
to `47.06 Hz` at 152.949 s.

## Low-frequency and continuous-playing controls

| Reference band | Baseline ±25 | A+B ±25 | Baseline octave up/down (s) | A+B octave up/down (s) |
| --- | ---: | ---: | ---: | ---: |
| 25–50 Hz | 98.09% | 98.22% | 0.331 / 0.000 | 0.331 / 0.000 |
| 50–75 Hz | 94.37% | 94.69% | 0.213 / 0.000 | 0.203 / 0.000 |
| 75–110 Hz | 81.84% | 81.84% | 0.000 / 1.909 | 0.000 / 1.909 |
| 110–200 Hz | 60.49% | 60.49% | 0.000 / 0.043 | 0.000 / 0.043 |

The `low_octave_recovery_69` and `slide_160` controls have exactly zero
frequency difference between baseline and A+B.  `control_164` is likewise
unchanged.

## Artifacts

- `summary.json` — complete A+B full-track metrics, bands, forensic metrics,
  correction counts, and rule-fire counts.
- `baseline_vs_A.json`, `baseline_vs_B.json`, `baseline_vs_AB.json` — direct
  comparisons from the same replay.
- `forensic_comparison.json` and `counterfactual_corrections.json` —
  event-stage and every changed-frame attribution.
- `frames.csv.gz` — complete A+B frame trace (6.5 MB compressed).
- `plots/` — two root-cause events plus clean, low-frequency, and slide
  controls.

Full-track listening files are deliberately not committed:

```text
tracker_runs/rootfix_final6/rootfix_baseline.wav
tracker_runs/rootfix_final6/rootfix_A.wav
tracker_runs/rootfix_final6/rootfix_B.wav
tracker_runs/rootfix_final6/rootfix_AB.wav
tracker_runs/rootfix_final6/audio_compare/
```

Each has `LEFT = original bass` and `RIGHT = tracked sine`, with the same
frozen envelope gain in every version.

## Recommendation

Use A+B as the candidate for subsequent human listening.  The combination is
small, causal, and surgical: it removes 12 of 67 forensic frames, preserves
the original octave-down result exactly, and does not modify the selected
low-frequency or slide controls.  It is not ported here; this commit contains
only Mac laboratory code and results.
