# Committed baseline: `basik hehe.wav`

This directory is the curated, reviewable result of one complete replay using
the tracker-lab code and configuration committed in `4bc0a87`. It intentionally
omits the large derived WAV monitor files; regenerate them locally when needed.

## Source and command

- Source WAV: `basik hehe.wav` (not committed)
- Source format: mono, 48,000 Hz, 24-bit PCM WAV
- Duration: 581.523708 seconds (9:41.524)

The exact command used to create the ignored full run was:

```bash
caffeinate -dimsu env MPLCONFIGDIR=/private/tmp/mplconfig MPLBACKEND=Agg PYTHONUNBUFFERED=1 \
  .venv-tracker-lab/bin/python tools/tracker_lab/analyze.py \
  "basik hehe.wav" --output-dir tracker_runs/baseline_review
```

## Reference and tracker

The offline reference is librosa pYIN: 4,096-sample frames, a 240-sample hop,
25–500 Hz search range, 0.2 pitch-resolution, and 50 thresholds. Reference
frames require pYIN voiced confidence of at least **0.30**. The realtime path
is the committed causal, bounded normalized-autocorrelation tracker; this
baseline does not tune or change it.

## Results

- Total frames: 54,514
- pYIN voiced duration: 131.221 s
- Pitch coverage: 100.0%
- Median absolute error: 8.04 cents
- P90 absolute error: 1,207.10 cents
- Within 25 / 50 cents: 62.68% / 62.94%
- Octave-up / octave-down errors: 0 / 4,335 frames (46.240 s down)
- Dropouts: 0 frames; false positives: 27,147 frames
- Approximate acquisition-latency median / P90: 0.000 / 0.000 s. This is not
  a useful onset measure for this baseline because the tracker frequently stays
  valid in unvoiced regions.

Notable false-positive regions are 42.795–49.429 s, 253.131–260.992 s, and
283.851–294.976 s. Notable octave-down regions are 74.048–77.269 s,
88.032–90.635 s, and 294.987–298.336 s. Corresponding zooms are in
[`failures/`](failures/).

## Contents and regeneration

- `summary.txt`, `summary.json`, and `config.json` are the machine-readable
  baseline report and exact tracker configuration.
- `frames.csv.gz` is the 54,514-frame trajectory compressed from 13 MB CSV.
- `pitch.png`, `error.png`, and `confidence.png` are overview plots.

To regenerate the full artifact set, including the intentionally uncommitted
monitor WAVs, run the command above with a new `--output-dir`. To recreate this
curated directory from such a run, copy the three report files, the three
overview PNGs, `frames.csv.gz`, and representative failure PNGs only; do not
copy `tracker_monitor.wav` or `reference_monitor.wav`.
