# Stability experiment v1

This is a Mac-only post-selection experiment on the committed octave-family
trajectory. No Daisy source, embedded build file, threshold, candidate-family
decision, or firmware configuration was changed.

## Source, reference, and exact run

- Source: `basik hehe.wav` (intentionally untracked), mono 48 kHz, 24-bit PCM,
  581.523708 s.
- Realtime input trajectory: committed octave-family v1
  `tools/tracker_lab/experiments/octave_v1/frames.csv.gz`.
- Evaluation reference: librosa pYIN, 4,096 samples / 240-sample hop, 25–500
  Hz, 0.2 resolution, 50 thresholds; reference voiced-confidence threshold
  **0.30**.
- All filtering is causal and uses only current/past tracker frames. pYIN is
  evaluation-only and is never an input to the realtime algorithm.

The exact full-recording command was:

```bash
caffeinate -dims env MPLCONFIGDIR=/private/tmp/mpl-tracker \
  .venv-tracker-lab/bin/python tools/tracker_lab/stability_lab.py \
  --input tools/tracker_lab/experiments/octave_v1/frames.csv.gz \
  --method adaptive_onepole --stable-alpha 0.45 \
  --moving-alpha 1.0 --motion-cents 8 \
  --output-dir tracker_runs/stability_final_best
```

## Algorithm

The successful octave-family selector remains unchanged. Its output enters a
small adaptive one-pole in log-frequency/cents space:

- Nearby, non-trending motion uses alpha 0.45.
- A causal trend of at least 8 cents, a detected attack, an already-confirmed
  family promotion, or a step of at least 140 cents uses alpha 1.0.
- Alpha 1.0 is a true bypass, so detected slides and note changes do not gain
  filter latency.
- There is no median filter in the selected result, no future samples, no MIDI
  quantization, no semitone snapping, and no tuning/fretboard knowledge.

The experiment sweep also tested causal median-of-3, adaptive median plus
one-pole, 20/28/40-cent candidate persistence, stable alpha 0.18–0.65, motion
threshold 4–12 cents, and faster octave-promotion slew. Median variants lost
accuracy and added delay. Persistence increased octave-down duration to about
3.33 s. Faster promotion increased octave-up duration. Those variants were
rejected.

## Full-recording comparison

| Metric | Original baseline | Octave v1 | Stability v1 |
| --- | ---: | ---: | ---: |
| Octave down | 46.240 s | 1.952 s | 1.952 s |
| Octave up | 0.000 s | 0.544 s | 0.544 s |
| Median absolute error | 8.041 cents | 5.109 cents | 5.077 cents |
| P90 absolute error | 1207.098 cents | 12.343 cents | 12.319 cents |
| Within 25 cents | 62.681% | 94.464% | 94.464% |
| Within 50 cents | 62.941% | 95.903% | 95.903% |
| Pitch jumps (>600 cents) | 134 | 292 | 292 |

The jump-count audit found that 287 of octave v1's 292 counted jumps are
outside a continuously pYIN-stable voiced span. The sole fully stable-voiced
case is the necessary f/2-to-f correction at 74.315 s. This is why the selected
filter does not optimize the raw jump count.

## Stability metrics

The primary stability mask requires five consecutive reference-voiced,
tracker-valid, within-100-cent frames, with every pYIN frame delta no larger
than 10 cents. It covers 76.224 s for octave v1. Original-baseline stability
numbers are not directly comparable because its octave-wrong frames are
excluded, leaving only 49.195 s.

| Correct-octave stable metric | Octave v1 | Stability v1 |
| --- | ---: | ---: |
| Median absolute frame delta | 0.004 cents | 0.011 cents |
| P90 absolute frame delta | 2.023 cents | 1.357 cents |
| P99 absolute frame delta | 4.596 cents | 4.599 cents |
| P90 5-frame cents standard deviation | 1.973 cents | 1.712 cents |
| P99 5-frame cents standard deviation | 3.286 cents | 3.292 cents |
| Stable-sustain P90 frame delta | 2.015 cents | 1.275 cents |
| Decay P90 frame delta | 2.810 cents | 1.671 cents |
| Short return-type micro-jumps | 0 | 0 |

A return-type micro-jump is a >=35-cent tracker step while the reference is
stable that returns within 18 cents of the prior value in four hops. None were
found. The one >=8-cent excess-motion event is 160.480 s (17.0 cents), at the
edge of a continuous-motion passage; the filter intentionally leaves it
unchanged. Other largest stable-frame movements occur near 363.083, 359.008,
162.080, 166.261, and 167.787 s and are plotted in `failures/`.

## Responsiveness and continuous playing

The reference-step test finds two qualifying transitions. Median/P90 latency
is unchanged at 234.7/260.3 ms; that absolute figure includes pre-existing
tracker/reference acquisition behavior, while the stability layer adds zero
measured transition latency.

| Slice | Octave v1 lag | Stability v1 lag | Stability max deviation |
| --- | ---: | ---: | ---: |
| slide 159.70–160.25 s | 21.3 ms | 32.0 ms | 75.8 cents |
| slide 162.75–163.40 s | 32.0 ms | 32.0 ms | 14.5 cents |
| slide 170.15–170.75 s | 10.7 ms | 0.0 ms | 27.4 cents |
| slide 375.50–376.25 s | 32.0 ms | 42.7 ms | 49.9 cents |

The two worse slide-lag estimates differ by one analysis hop (10.667 ms).
No staircase was introduced because moving trajectories bypass the filter.
The fixed development/hold-out slice manifest and all per-slice results are in
`tools/tracker_lab/stability_slices.json` and `stability_metrics.json`.

On the pre-existing octave-lab hold-out, octave durations and within-25/50
rates are unchanged. P90 error improves from 11.724 to 11.688 cents; median
error regresses slightly from 5.204 to 5.280 cents.

## Frequency-band protection

| Reference band | Stability down / up | Octave v1 median -> stability | Octave v1 P90 -> stability |
| --- | ---: | ---: | ---: |
| 25–50 Hz | 0.000 / 0.331 s | 4.747 -> 4.640 cents | 10.023 -> 9.983 cents |
| 50–75 Hz | 0.000 / 0.213 s | 5.593 -> 5.593 cents | 14.049 -> 14.000 cents |
| 75–110 Hz | 1.909 / 0.000 s | 4.779 -> 4.779 cents | 1191.905 -> 1191.916 cents |

The stability layer does not change any low-band octave classification. The
25–50 Hz within-25 rate changes from 98.109% to 98.095% (one-frame-scale), an
explicit small regression rather than a hidden octave-up trade-off.

## Known regressions and limits

- Stable-region median frame delta rises from an effectively quantized 0.004
  to 0.011 cents, while P99 is effectively unchanged. The useful reduction is
  in the much larger P90 movement and decay/sustain distributions.
- Hold-out median absolute error rises by 0.076 cents.
- Slide-lag estimates at 160 s and 376 s rise by one 10.667 ms hop.
- The filter does not address octave v1's remaining octave failures around
  74.048–74.325, 88.032–88.299, 97.579–98.048, and 109.717–110.123 s.
- False-positive/voicing behavior remains intentionally out of scope.

## Audible artifacts and regeneration

Large monitor WAVs are local and intentionally ignored:

- `tracker_runs/stability_audio_compare/baseline_tracker_monitor.wav`
- `tracker_runs/stability_audio_compare/octave_v1_tracker_monitor.wav`
- `tracker_runs/stability_audio_compare/stability_best_tracker_monitor.wav`
- `tracker_runs/stability_audio_compare/{attack_74,attack_88,slide_160,slide_163,decay_250}_{baseline,octave_v1,stability_best}.wav`

Regenerate the three full monitors and all excerpts (left = original bass,
right = tracked sine):

```bash
caffeinate -dims env MPLCONFIGDIR=/private/tmp/mpl-tracker \
  .venv-tracker-lab/bin/python tools/tracker_lab/render_stability_audio.py \
  "basik hehe.wav" \
  --stability tracker_runs/stability_final_best/frames.csv \
  --output-dir tracker_runs/stability_audio_compare
```

`frames.csv.gz` is the complete 54,514-frame selected trajectory.
`baseline_vs_best.json`, `summary.json`, `stability_metrics.json`, overview
plots, stability zooms, and slide zooms are the curated review evidence. No
monitor WAV is committed.

## Eventual Daisy portability

A later port would add one log-frequency one-pole state, a six-frame trend
history, and the four causal bypass conditions after the octave-family
selector. It needs no FFT, pYIN, future samples, note model, or large buffer.
This experiment does not perform that port.
