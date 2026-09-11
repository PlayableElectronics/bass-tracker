# Tracker lab

Run the repeatable Mac-side baseline:

```bash
.venv-tracker-lab/bin/python tools/tracker_lab/analyze.py \
  "basik hehe.wav" --output-dir tracker_runs/baseline
```

The run produces `frames.csv`, `summary.txt`, `summary.json`, `config.json`,
`pitch.png`, `error.png`, `confidence.png`, failure zooms, and the two stereo
monitor WAVs. The left channel is the original bass; the right channel is
either the causal tracker or offline pYIN reference sine.

The offline reference is librosa pYIN. The realtime path is independent,
causal, fixed-window normalized autocorrelation with bounded candidates,
harmonic reasoning, hysteresis, and temporal continuity matching the Daisy
design constraints. No Daisy source files are imported or modified.

Compare runs with:

```bash
.venv-tracker-lab/bin/python tools/tracker_lab/compare.py \
  tracker_runs/baseline tracker_runs/experiment_01
```
