# Octave-family experiment v1

This is a Mac-only experiment. No Daisy source, embedded build file, or
firmware configuration was changed.

## Evidence and decision

The committed baseline candidate trace showed that the long octave-down runs
were not ordinary cents errors: a low candidate (for example 46 Hz) was
receiving an explicit bonus from a near-equal 92 Hz candidate, while the
92 Hz candidate was penalized for the low candidate. That makes the long
period/subharmonic choice structurally favoured.

The replacement is candidate-relative harmonic-family selection. For every
causal 512-sample / 12 kHz window, the strongest autocorrelation candidate
is still the default. A higher 2x or 3x member may represent the family only
when its own normalized autocorrelation score is at least 92% of the strongest
candidate's score. Weak upper peaks therefore do not convert a real low
fundamental into an octave-up result. A candidate-family promotion must persist
for two 10.667 ms hops, then moves with a causal 0.50 slew. There is no MIDI
quantization, tuning knowledge, look-ahead, offline FFT, or pYIN input to the
realtime selection.

The full result is a deterministic replay over the committed 54,514-window
baseline candidate trace. This holds the source, causal front end, candidate
set, gate, and pYIN alignment constant, and evaluates the new realtime state
machine across the entire 581.52 s recording. `octave_lab.py` contains the
same selector operating directly on the WAV front end for future source runs.

## Source and reference

- Source: `basik hehe.wav` (intentionally untracked), mono 48 kHz, 24-bit PCM,
  581.523708 s.
- Evaluation reference: librosa pYIN, 4,096 samples / 240-sample hop, 25–500
  Hz, 0.2 resolution, 50 thresholds; voiced confidence threshold **0.30**.
- Development slices: 70–80 s, 84–94 s, and 290–302 s. The fixed hold-out is
  20–60, 120–180, 220–280, 320–380, and 440–520 s.

## Full comparison

| Metric | Committed baseline | Octave v1 |
| --- | ---: | ---: |
| Octave-down duration | 46.240 s | 1.952 s |
| Octave-up duration | 0.000 s | 0.544 s |
| Median absolute error | 8.04 cents | 5.11 cents |
| P90 absolute error | 1207.10 cents | 12.34 cents |
| Within 25 cents | 62.68% | 94.46% |
| Within 50 cents | 62.94% | 95.90% |
| Dropouts | 0 | 0 |
| Pitch jumps | 134 | 292 |

The fixed hold-out has 0.021 s octave-down, 0.437 s octave-up, 5.20-cent
median error, 11.72-cent P90, and 96.53% within 25 cents. The rejected
aggressive 85% variant reduced octave-down further but created 5.056 s of
octave-up, including 3.563 s in the 25–50 Hz band; it is not this result.

Frequency-band results make the remaining low-note trade-off explicit:

| Reference band | Baseline down / up | v1 down / up | v1 median | v1 within 25 |
| --- | ---: | ---: | ---: | ---: |
| 25–50 Hz | 0.000 / 0.000 s | 0.000 / 0.331 s | 4.77 cents | 97.88% |
| 50–75 Hz | 28.555 / 0.000 s | 0.000 / 0.555 s | 5.59 cents | 96.01% |
| 75–110 Hz | 17.685 / 0.000 s | 1.888 / 0.000 s | 4.24 cents | 84.06% |

The 252.683–253.067 s apparent 46-to-93 Hz regression is explicitly
`reference_uncertain`: pYIN confidence is only 0.32 and independent offline
YIN alternates between both octaves there. It remains counted in the metrics;
it was not discarded or tuned away.

Remaining significant failures include 97.579–98.048 s (92-to-46 Hz),
88.021–88.416 s, 109.781–110.123 s, and 74.037–74.325 s. Representative
zooms are in `failures/`.

## Contents and regeneration

- `best_config.json`, `summary.json`, and `baseline_vs_best.json` are the
  complete machine-readable report.
- `frames.csv.gz` is the compressed 54,514-frame experimental trajectory.
- `pitch.png`, `error.png`, `confidence.png`, and `failures/` are curated
  review plots.

Regenerate the full result from the committed baseline candidate trace:

```bash
caffeinate -dims env MPLCONFIGDIR=/private/tmp/mpl-tracker \
  .venv-tracker-lab/bin/python tools/tracker_lab/replay_family.py \
  --baseline tools/tracker_lab/baseline/frames.csv.gz \
  --family-ratio 0.92 --confirm-frames 2 --promoted-slew 0.50 \
  --output-dir tracker_runs/octave_v1
```

Create local, intentionally uncommitted audible comparisons (left: original
bass; right: tracker sine) and the three failure excerpts:

```bash
caffeinate -dims env MPLCONFIGDIR=/private/tmp/mpl-tracker \
  .venv-tracker-lab/bin/python tools/tracker_lab/render_audio_comparison.py \
  "basik hehe.wav" --best tracker_runs/octave_v1/frames.csv \
  --output-dir tracker_runs/audio_compare
```

Current local outputs are `tracker_runs/audio_compare/baseline_tracker_monitor.wav`,
`tracker_runs/audio_compare/best_tracker_monitor.wav`, and the
`octave_{74s,88s,295s}_{baseline,best}.wav` excerpts. They are intentionally
ignored and are not committed.

Porting later would require only the small 1:2/1:3 candidate-family pass,
two-frame confirmation state, and promotion slew in the Daisy tracker. It
requires no FFT, buffers beyond the current causal analysis window, pYIN, or
future samples. This experiment does **not** perform that port.
