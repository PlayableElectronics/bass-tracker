# Attack acquisition v1 (Mac-only)

This is a post-tracker, causal audibility experiment.  It uses the committed
`stability_v1` tracker trajectory unchanged and the already-selected
`envelope_02` decay envelope unchanged.  It does not alter a pitch, candidate,
confidence, gate, or analysis setting.

## Source and regeneration

- Source: `basik hehe.wav` — mono, 48 kHz, 24-bit PCM WAV, 581.524 s.
- Fixed tracker input: `tools/tracker_lab/experiments/stability_v1/frames.csv.gz`.
- Offline reference used for the reported error metrics: the existing pYIN
  trajectory in that trace.

From the repository root, regenerate the complete ignored run (including the
large listening WAVs) with:

```bash
caffeinate -dims env MPLCONFIGDIR=/private/tmp/mpl-tracker \
  .venv-tracker-lab/bin/python tools/tracker_lab/attack_lab.py \
  --output-root tracker_runs/attack_20260911 \
  --selected attack_strategy_B \
  --render-names attack_baseline attack_strategy_A attack_strategy_B attack_strategy_C
```

The script asserts that `tracked_freq_hz` is unchanged from the frozen input.
The generated local listening files are:

- `tracker_runs/attack_20260911/attack_baseline/attack_baseline.wav`
- `tracker_runs/attack_20260911/attack_strategy_A/attack_strategy_A.wav`
- `tracker_runs/attack_20260911/attack_strategy_B/attack_strategy_B.wav`
- `tracker_runs/attack_20260911/attack_strategy_B/attack_best.wav`
- `tracker_runs/attack_20260911/attack_strategy_C/attack_strategy_C.wav`

Each directory also has short excerpts for 152, 158, 162, 176, and 180 s.
These WAVs are deliberately not committed.

## Diagnosis

The worst attack-window glitch begins at **176.501 s**, shortly after an onset
at 176.416 s.  The frozen tracker moves from the approximately 62 Hz
trajectory through 92.8, 108.2, 116.0, and 119.9 Hz while the reference stays
near 61.6 Hz.  It produces up to 1153 cents error for 42.7 ms.  Candidate
evidence is ambiguous: 61.86 Hz (0.990), 30.93 Hz (0.973), 123.71 Hz (0.922),
and 41.24 Hz (0.918); the frame is family-promoted and stability bypasses for
the genuine large step.  The other ranked attack error is a single 10.7 ms,
102-cent settling frame at 152.971 s.  See `attack_176s.png` and
`attack_152s.png`.

## Selected behavior: `attack_strategy_B`

The final audible gain is:

```text
frozen envelope_02 synth gain × causal acquisition factor
```

An **explicit existing onset** begins acquisition (no new source-envelope-rise
trigger is enabled).  On an acquisition that is not a continuing pitch motion,
the factor is 0.10 while the pitch settles.  The pitch becomes trusted after
**two consecutive** quality frames.  A quality frame requires:

1. valid pitch;
2. no current or preceding family promotion;
3. raw-to-final tracked pitch agreement within **40 cents**; and
4. current-to-prior raw pitch agreement within **40 cents**.

After trust, a causal one-pole factor reaches full gain with a **10 ms** time
constant.  If trust never arrives, the 128 ms safety guard opens audio rather
than indefinitely muting a note.  The attack layer does not change oscillator
frequency; it only changes gain.

To protect continuous slides, acquisition is bypassed when current and past
tracked trajectory contains at least two same-direction moves of 10 cents or
more whose combined motion is at least 80 cents.  This is a causal exemption,
not a pitch-tracker adjustment.  Of 233 explicit onsets, it activated
acquisition 127 times and bypassed 106 apparent continuous motions.

The frozen underlying decay envelope remains `envelope_02`:

```text
audible on/off: 0.0020 / 0.0012
attack/release: 4 ms / 120 ms
```

## Strategies compared

All attack metrics cover the first 128 ms after an explicit onset and weight
pitch error by final audible gain.  `large` means absolute reference error of
at least 100 cents.

| Strategy | Attack weighted error (cent·s) | Large-error audibility (gain·s) | Median / P90 audible latency | Result |
| --- | ---: | ---: | ---: | --- |
| Frozen envelope_02 only | 76.94 | 0.0533 | 0 / 0 ms | Baseline |
| A: hard mute, two quality frames | 15.59 | 0.0000 | 42.7 / 74.7 ms | Rejected: audible gaps and slide mutes |
| B: 0.10 acquisition gain + 10 ms fade + motion bypass | 30.95 | 0.0149 | 21.3 / 64.0 ms | **Selected** |
| B without motion bypass | 21.08 | 0.0053 | 42.7 / 74.7 ms | Rejected: muted slides |
| C: hold previous pitch on connected attacks | 733.05 | 1.0773 | 0 / 0 ms | Rejected: wrong-note smearing |

Selected B reduces attack-window gain-weighted error by **59.8%** and
gain-weighted large-error duration by **72.0%** relative to the immediate
envelope.  On the 119 acquisitions that reached trust before the guard,
median/p90 time-to-trusted-pitch is 21.3/64.0 ms; eight reached the guard
without trust.

## Protections and known regression

The tracker output itself is byte-for-byte unchanged for this experiment.
Consequently the frozen full-track tracker metrics remain: median error 5.08
cents, P90 12.32 cents, within ±25 cents 94.46%, octave-up 0.544 s,
octave-down 1.952 s, and 100% pitch coverage on reference-voiced frames.

The selected layer adds no measured pitch lag and has zero median/P90
connected-note gap.  Of four checked slide regions, 160, 170, and 376 s stay
above half final gain throughout.  At 163 s it briefly reaches 0.10 gain for
**10.7 ms**; this is the known remaining slide/legato regression, shown in
`attack_162s.png`.  It is retained explicitly rather than hidden by the
metrics.

## Curated artifacts

- `summary.json`, `best_config.json`, and `attack_metrics.json`: selected
  configuration and measurements.
- `baseline_vs_best.json`: direct baseline/selected comparison.
- `attack_failures.json`: ranked baseline attack failures with candidates.
- `attack_trace.csv.gz`: selected full-frame gain and acquisition trace
  (3.7 MB compressed).
- `attack_152s.png`, `attack_162s.png`, `attack_176s.png`, `attack_180s.png`:
  representative settling, regression, worst failure, and secondary event
  plots.

## Future Daisy port (not performed here)

The minimal causal state is an acquisition-active flag, a 128 ms frame/timer,
previous raw frequency and family-promotion flag, a two-frame agreement
counter, a small recent tracked-frequency trend buffer for the motion bypass,
and the acquisition gain.  The rejected previous-pitch hold strategy is not
part of the selected design.  Porting should multiply the existing audible
envelope after its unchanged decay logic; it must not invalidate or modify the
pitch tracker.
