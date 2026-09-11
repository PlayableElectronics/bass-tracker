# Audible-envelope experiment v1

This is a Mac-only post-tracker synth-envelope experiment. It reads the
committed `stability_v1` trajectory unchanged and derives a separate causal
`synth_gain`; it does not alter `pitch_valid`, `tracked_freq_hz`, candidate
selection, confidence, gate, onset, or any pitch-tracker configuration.

## Source and exact run

- Source: `basik hehe.wav` (intentionally untracked), mono 48 kHz, 24-bit PCM,
  581.523708 s.
- Fixed realtime trajectory:
  `tools/tracker_lab/experiments/stability_v1/frames.csv.gz`.
- Evaluation reference only: the existing librosa pYIN trace (4,096-sample
  frame, 240-sample hop, 25–500 Hz, voiced-confidence threshold 0.30).

The recorded full-run command was:

```bash
caffeinate -dims env MPLCONFIGDIR=/private/tmp/mpl-tracker \
  .venv-tracker-lab/bin/python tools/tracker_lab/envelope_lab.py \
  --output-root tracker_runs/envelope_20260911 \
  --render-names current_fixed_gain envelope_01 envelope_02
```

Regenerate the metrics and curated-source data without WAV rendering by
omitting `--render-names`. Monitor WAVs are intentionally local and ignored.

## Selected envelope: `envelope_02`

The chosen envelope is a small causal source-level control layer, not a pitch
gate:

1. Map the existing measured input envelope logarithmically from `0.0012`
   (zero) to `0.012` (one), clamped to 0…1.
2. Hysteretically latch audibility at `0.0020`, and only release the latch at
   `0.0012`. Between those values an already-audible note remains connected.
3. While latched, use the normalized source level as target gain; pitch-valid
   is only an oscillator-availability condition, not the source of amplitude.
4. Smooth target rises with a 4 ms one-pole attack and falls with a 120 ms
   one-pole release. This avoids cutoff clicks while fading the late tail.

No tracker confidence taper is selected. The tested 0.70…1.00 taper below
30% normalized level had no material benefit, while source level already
explains the desired tail behavior more directly.

The other explicit candidates were a gentler `.0012/.0007`, 180 ms release
version (`envelope_01`) and that same version plus the confidence taper
(`envelope_03`). `envelope_02` is selected because it cuts tail-error energy
more while retaining unity median gain on correct and strong clean notes.

## Fixed-gain comparison

`current_fixed_gain` matches the prior monitor: a valid tracker drives a
constant right-channel sine level. All duration figures below are
gain-weighted seconds (`sum(synth_gain) × 10.667 ms`), so they measure how
much incorrect pitch remains audible rather than changing tracker coverage.

| Metric | Fixed monitor | Selected envelope |
| --- | ---: | ---: |
| Valid-sine audible duration | 420.811 s | 364.140 s |
| Audible octave-error duration | 2.496 s | 1.650 s |
| Audible large-error duration | 5.376 s | 3.832 s |
| Audible late-tail error duration | 0.213 s | 0.099 s |
| Late-tail error energy | 215.0 cent·s | 120.9 cent·s |
| Median gain on correct reference notes | 1.000 | 1.000 |
| Strong clean note time below 0.9 gain | 0.000 s | 0.000 s |
| Onset to gain ≥0.5, median / P90 | 0 / 0 ms | 0 / 0 ms |
| Onset to gain ≥0.9, median / P90 | 0 / 0 ms | 0 / 0 ms |

The zero-hop attack result occurs because all 233 evaluated onset frames are
already above the selected source threshold at the lab frame rate. It does not
assert sample-level zero latency; it says this layer adds no measured analysis
hop of onset delay.

## Decay and connected-playing audit

The representative late residual at **432.715–432.789 s** is a roughly
1,900-cent octave/subharmonic error after the source has collapsed. Its
gain-weighted duration falls from 85.3 ms to 15.1 ms; gain is at most 0.236
during the error and continues toward zero. See `decays/decay_432s.png`.

The 169.440–169.461 s large error stays at unity gain. Its input level is
still strong, so suppressing it would violate the goal of keeping audible
tracker mistakes exposed during real notes. The envelope is deliberately not
an error hider.

All selected slide regions retain median gain 1.0; their minima are 1.000,
0.703, 0.746, and 0.914, with no frame below 0.5 gain. `slide_163s.png`
documents the lowest selected slide minimum. The selected long-decay views
are `decays/decay_130s.png`, `decays/decay_250s.png`, and
`decays/decay_432s.png`.

The pitch trajectory itself is identical to `stability_v1`; ordinary tracker
accuracy, coverage, octave metrics, and false-positive counts are therefore
unchanged. The envelope only adds audible-weighted measures in
`audible_metrics.json` and the complete control trace in `gain_trace.csv.gz`.

## Local audible artifacts

These were generated locally and are ignored by Git (left = original bass,
right = tracked sine multiplied by the named gain):

- `tracker_runs/envelope_20260911/current_fixed_gain/current_fixed_gain.wav`
- `tracker_runs/envelope_20260911/envelope_01/envelope_01.wav`
- `tracker_runs/envelope_20260911/envelope_02/envelope_02.wav`
- Each directory also contains focused `*_decay_130s.wav`, `*_decay_250s.wav`,
  and `*_decay_432s.wav` excerpts.

## Eventual Daisy port (not performed here)

The minimum embedded addition would be one log-normalized source-level
calculation, an audible-latch boolean, a target gain float, and a smoothed-gain
float. The existing input-envelope, gate/onset, and pitch-valid outputs can be
read as inputs; tracked pitch continues running even when gain is zero. The
audio path would use the existing final tracked oscillator frequency and
multiply only its output by the final `audible_synth_gain`. This experiment
does not modify Daisy code or change any tracker algorithm or threshold.
