# Attack early/peak/settled hypothesis

This is a read-only analysis of the committed `stability_v1` trajectory. It
does not change the tracker, the envelope, Daisy firmware, or the source WAV.

## Input and method

- Source: `basik hehe.wav` — mono, 48 kHz, 24-bit PCM; 581.524 s.
- Frozen realtime trace: `tools/tracker_lab/experiments/stability_v1/frames.csv.gz`.
- Reference: the existing pYIN columns in that trace. A settled reference is
  usable only when 80–180 ms after an onset contains at least four voiced pYIN
  frames at the established confidence threshold of 0.30.
- Earliest credible pitch is the first post-onset frozen tracker frame that is
  pitch-valid, positive, and has confidence at least 0.46 (the existing
  tracker hold-confidence value). This definition is causal and does not use
  later reference information.
- Peak pitch is measured at the largest input-envelope sample in 0–100 ms
  after each onset. Settled pitch is a median, not a single frame.

Run from the repository root:

```bash
caffeinate -dims env MPLCONFIGDIR=/private/tmp/mpl-tracker \
  .venv-tracker-lab/bin/python tools/tracker_lab/attack_hypothesis.py \
  --output-dir tracker_runs/attack_hypothesis_final
```

## Result

The proposed pattern is **not common** in the reference-usable attacks. Of
233 onset events, 55 had a usable high-confidence settled pYIN target; 178
are retained in `attacks.csv.gz` as `reference_usable=0`, not silently
discarded.

| Target / measurement | ±10 cents | ±25 cents | ±50 cents | ±100 cents |
| --- | ---: | ---: | ---: | ---: |
| First credible vs settled pYIN (n=55) | 6 / 55 (10.9%) | 12 / 55 (21.8%) | 18 / 55 (32.7%) | 27 / 55 (49.1%) |
| Envelope peak vs settled pYIN (n=55) | 15 / 55 (27.3%) | 24 / 55 (43.6%) | 37 / 55 (67.3%) | 45 / 55 (81.8%) |
| First credible vs settled tracker (n=209) | 20 / 209 (9.6%) | 46 / 209 (22.0%) | 70 / 209 (33.5%) | 101 / 209 (48.3%) |
| Envelope peak vs settled tracker (n=209) | 32 / 209 (15.3%) | 73 / 209 (34.9%) | 107 / 209 (51.2%) | 145 / 209 (69.4%) |

With pYIN as the target, first pitch is materially closer than peak only
1 / 55 (1.8%) times; peak is materially closer 34 / 55 (61.8%) times; 20 / 55
(36.4%) are effectively equal (within 10 cents of each other). Median
absolute error is 104.0 cents at the earliest credible frame versus 30.1
cents at the envelope peak.

Pattern A (first within 50 cents, peak at least 100 cents wrong, later
reference settled) occurred **0 / 55** times. Pattern B (both first and peak
at least 100 cents wrong, later reference settled) occurred 10 / 55 (18.2%);
Pattern C (correct through peak) 18 / 55 (32.7%); and mixed Pattern D 27 / 55
(49.1%). The equivalent tracker-settled cross-check also has zero Pattern A
events.

There are 31 / 55 (56.4%) attacks with some >=100-cent excursion anywhere in
the 200 ms analysis window. Only 2 / 55 (3.6%) are initially within 50 cents
but later develop such an excursion: 150.133 s and 176.416 s. Of the 31
large-error events, the maximum occurs before the envelope peak in 12 (38.7%),
near it (within two frame hops) in 18 (58.1%), and after it in 1 (3.2%).
Thirty recover to a three-frame 50-cent neighborhood within the 200 ms window
(median 32.0 ms; P90 42.7 ms). The 176.416 s event is the exception: it is
correct at onset and at the 176.459 s envelope maximum, then rises toward the
123.7 Hz candidate about 43 ms later while pYIN remains near 61.6 Hz.

For the 10 reference-supported attacks whose **peak** tracker error is at
least 100 cents, the settled reference pitch is still among the top four peak
candidates in 9 / 10 (90.0%): rank 1 eight times, rank 3 once, and absent once.

Hard attacks are a small usable subset (n=6), so they do not support a strong
generalization: first/peak within 50 cents is 16.7% / 50.0%. Soft attacks
(n=41) are 31.7% / 70.7%; medium (n=8) are 50.0% / 62.5%. Usable settled
reference targets were only in 25–50 Hz (n=38) and 50–75 Hz (n=17); there are
no valid statistics for 75–110 Hz or 110–200 Hz from this strict pYIN filter.

## Artifacts

- `summary.json` / `summary.txt`: machine-readable and concise report.
- `attacks.csv.gz`: one row per onset with first, peak, settled, candidate,
  timing, octave, confidence, and classification fields.
- `summary_scatter_hist.png`: first-versus-peak error and distributions.
- `examples/`: 16 representative plots. In particular, see
  `attack_217_176.416s.png` (the reported late excursion) and
  `attack_199_152.928s.png` (a peak-time wrong/recovered event).

Conclusion: the specific “early correct -> peak wrong -> recovery” hypothesis
is weakly supported at best (2 / 55 only when the whole 200 ms window is
considered, and 0 / 55 at the actual envelope maximum). No correction strategy
is proposed or implemented here.
