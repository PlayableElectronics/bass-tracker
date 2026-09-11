# Attack pitch v1 — frequency-only, Mac-only

The earlier `attack_v1` gain-acquisition experiment is **rejected by human
listening**: reducing gain during acquisition softens the natural bass attack.
This experiment retains the proven `octave_v1`, `stability_v1`, and
`envelope_02` behavior and changes only the frequency sent to the diagnostic
oscillator.  It never changes `tracked_freq_hz` or `synth_gain`.

## Fixed inputs and regeneration

- Source: `basik hehe.wav` — mono 48 kHz, 24-bit PCM WAV, 581.524 s.
- Frozen tracker trace: `tools/tracker_lab/experiments/stability_v1/frames.csv.gz`.
- Frozen gain: `envelope_02` from `tools/tracker_lab/envelope_lab.py`
  (on/off 0.0020/0.0012, attack/release 4/120 ms).
- Reference used for evaluation only: the existing pYIN trajectory in the
  frozen trace.

From the repository root, regenerate all ignored results and listening files:

```bash
caffeinate -dims env MPLCONFIGDIR=/private/tmp/mpl-tracker \
  .venv-tracker-lab/bin/python tools/tracker_lab/attack_pitch_lab.py \
  --output-root tracker_runs/attack_pitch_20260911 \
  --selected attack_pitch_B --render
```

The script asserts for every candidate that:

```text
tracked_freq_hz is unchanged
final_synth_gain == frozen envelope_02 synth_gain
```

Thus every monitor has the same sharp amplitude envelope; only the right
channel oscillator frequency differs.

## Failure diagnosis

There are two pYIN-supported attack-window errors of at least 100 cents in the
recording.  The main one is at **176.501–176.576 s**, after the explicit onset
at 176.416 s.  It is Pattern **A: correct → wrong → correct**, plus Pattern
**E: the correct frequency is already a stronger candidate**:

```text
before: raw/tracked/reference ≈ 61.9 / 61.9 / 61.6 Hz
bad:    raw = 123.7 Hz, tracked = 92.8 → 119.8 Hz, reference ≈ 61.6 Hz
after:  raw returns to 61.9 Hz and frozen tracked pitch recovers toward 62 Hz
```

During the bad frames, 61.86 Hz is the highest candidate (0.990–0.992), while
the raw 123.71 Hz candidate scores only 0.920–0.924.  The old 61.9 Hz family
member is therefore still strongly present, despite the raw selection and
family-promotion state.  `attack_pattern_report.json` contains the frame
context (onset, envelope, raw/pre-stability/tracked/reference frequencies,
candidates, family state, stability mode, and confidence).  The secondary
event at 152.971 s is a one-frame 102-cent non-octave settling transient.

No clean pYIN-confirmed genuine octave note transition occurs among the 233
explicit onsets in this source.  The lab consequently includes a causal
synthetic regression: a new 82 Hz candidate scoring 0.95 versus the old 41 Hz
candidate scoring 0.40 passes immediately.  Ordinary non-octave changes also
pass immediately.  This is a guardrail, not evaluation evidence replacing the
recording.

## Strategies tested

| Strategy | Causal idea | Result |
| --- | --- | --- |
| A | Hold the prior audible pitch only for connected attacks. | Rejected: 12 overrides and higher attack error from old-note smears. |
| B | Latch the first plausible tracked pitch at onset; guard only a contradictory 1:2 raw candidate that still has a strong latch-matching alternative. | **Selected**: one surgical override event. |
| C | Use previous audible member for longer candidate-relative octave confirmation. | Rejected: 20 overrides and stale-pitch regressions. |
| D | Local 250-cent slew during the same contradiction. | Rejected: partial reduction but leaves the audible wrong trajectory. |

## Selected strategy: `attack_pitch_B`

At each existing onset, latch the current frozen tracked frequency as the
first plausible attack frequency.  For the next 128 ms, start a guard only if
all of the following are true:

1. raw detector frequency is 850–1350 cents from that latch;
2. a current candidate within 65 cents of the latch exists; and
3. that latch-matching candidate score is at least **0.98×** the raw
   candidate score.

While guarded, the audible oscillator uses the latch, at full unchanged
amplitude.  The guard releases as soon as frozen tracked pitch recovers within
70 cents of the latch, a raw candidate becomes **1.08×** stronger than the
latch candidate, or after at most 12 analysis frames (128 ms).  Once started,
the guard may run past the 128 ms *initiation* window only to cover recovery
from that already-detected contradiction.  No future samples are used.

This does not use the previous note for detached attacks, does not quantize
pitch, and does not globally prevent octave changes.  The winning detector
candidate can still establish a genuine octave immediately.

## Results

All durations below are unweighted: gain is intentionally identical.

| Metric | Frozen audible frequency | `attack_pitch_B` |
| --- | ---: | ---: |
| Attack error | 76.94 cent·s | 35.92 cent·s |
| Attack wrong-pitch duration | 53.3 ms | 10.7 ms |
| Attack octave-error duration | 32.0 ms | 0.0 ms |
| First-256-ms large-error duration | 96.0 ms | 10.7 ms |
| First-256-ms octave-error duration | 32.0 ms | 0.0 ms |
| Full-track large-error duration | 4.523 s | 4.437 s |
| Full-track octave-error duration | 2.752 s | 2.720 s |

The selected layer overrides 8 frames in one event: **85.3 ms**, or
**0.0203%** of valid tracker frames.  Median/P90/maximum override duration are
all 85.3 ms because there is one event.  It changes no slide frame in the
160, 163, 170, or 376 s regression regions and adds no measured pitch lag.
The retained tracker metrics remain median 5.08 cents, P90 12.32 cents,
within ±25 cents 94.46%, octave-up 0.544 s, octave-down 1.952 s, and 100%
reference-voiced pitch coverage.

The selected policy deliberately does **not** repair the 152.971 s
non-octave settling error: its first plausible latch is already near that
trajectory, so no 1:2 contradiction exists.  This is the principal remaining
attack limitation.

## Listening files (local, uncommitted)

Full monitors (left original bass; right sine × the identical frozen
`envelope_02` gain):

- `tracker_runs/attack_pitch_20260911/attack_pitch_baseline/attack_pitch_baseline.wav`
- `tracker_runs/attack_pitch_20260911/attack_pitch_A/attack_pitch_A.wav`
- `tracker_runs/attack_pitch_20260911/attack_pitch_B/attack_pitch_B.wav`
- `tracker_runs/attack_pitch_20260911/attack_pitch_C/attack_pitch_C.wav`
- `tracker_runs/attack_pitch_20260911/attack_pitch_best.wav`

Focused A/B files are under `tracker_runs/attack_pitch_20260911/attack_compare/`:
`176_*`, `152_*`, `clean_126_*`, `slide_160_*`, and `legato_163_*`.  The source
does not contain a pYIN-verified octave-transition excerpt, so one is not
misrepresented as such here.

## Curated artifacts

- `best_config.json`, `summary.json`, `attack_pitch_metrics.json`, and
  `baseline_vs_best.json`: exact selected configuration and comparison.
- `attack_pattern_report.json`: detailed baseline failure contexts.
- `attack_pitch_trace.csv.gz`: selected full frame trace (3.5 MB compressed).
- `176_baseline.png` and `176.png`: direct worst-event comparison.
- `152.png`, `clean_126.png`, `slide_160.png`, and `legato_163.png`:
  remaining settling issue and regression checks.

## Future Daisy port (not performed)

The minimum causal state is: attack-active flag/timer, first-plausible attack
latch frequency, guard-active flag/frame counter, current candidate score near
the latch, current raw-candidate score, and the existing candidate frequencies.
The output-only frequency should replace oscillator frequency only while the
guard is active.  It must not alter pitch validity, tracker frequency, gain,
or the existing decay envelope.
