# Selected-tracker forensic replay

This directory is a read-only forensic analysis of the committed `octave_v1`
and `stability_v1` Mac tracker trajectory. It does not alter detector,
candidate scoring, octave-family selection, promotion confirmation, slew,
stability, gate, or envelope behavior.

## Reproducibility

The replay consumes the frozen baseline candidate trace, the committed
`octave_v1` / `stability_v1` traces, and the committed attack-hypothesis
attack table. It was run with:

```sh
caffeinate -dims env MPLCONFIGDIR=/private/tmp/mpl-tracker \
  .venv-tracker-lab/bin/python tools/tracker_lab/forensics.py \
  --output tracker_runs/forensics_final6
```

It reproduces the selected pipeline exactly over all 54,514 frames:

| signal | maximum absolute difference |
| --- | ---: |
| octave-family selected candidate | 0 Hz |
| pre-stability output | 0 Hz |
| final stability output | 0 Hz |
| promotion flag | 0 |
| stability alpha | 0 |

## Scope and target set

The source attack analysis supplied 55 attacks with a usable settled pYIN
reference. This report examines the 31 attacks containing a >=100-cent error
in their first 200 ms, split into 31 contiguous error events (67 error
frames). The error target is the high-confidence settled pYIN frequency from
the existing attack analysis; per-frame pYIN is shown as context only.

## Main result

The detector is usually not the origin of these remaining attack artifacts.
The settled/reference candidate is present on 63/67 erroneous frames, and is
raw candidate #1 on 57/67. It is selected as the family target on 53/67, but
the pre-stability slew output is within 100 cents of reference on none of the
67 error frames.

| primary stage | events | error frames |
| --- | ---: | ---: |
| pre-stability slew lag | 22 | 52 |
| detector/top candidate wrong | 6 | 8 |
| previous-state hold | 2 | 3 |
| family selector changes correct top | 1 | 4 |
| promotion-confirmation delay | 0 | 0 |
| adaptive-stability lag | 0 | 0 |

`176.416 s` is the exceptional family-selection failure: repeated eligible
2:1 evidence promotes the 123.7 Hz third candidate over the correct 61.9 Hz
top candidate, then ordinary slew delays recovery. `152.928 s` is different:
the raw top candidate is initially 30.7 Hz while the 46.7 Hz reference is
weak candidate #3; after the raw target recovers, frozen hold/slew state
delays the audible trajectory.

## Files

- `summary.json` and `summary.csv`: one row per attack-error event.
- `root_causes.json`: frame and event root-cause counts plus candidate evidence.
- `candidate1_peak_cases.csv`: the ten previously identified wrong-peak cases
  and whether candidate #1 was selected or hidden by state/slew.
- `frame_trace.csv.gz`: full 54,514-frame causal replay with candidates,
  family state, promotion state, slew state, stability flags, and attribution.
- `events/`: frame-by-frame reports for major bad cases and five ambiguous but
  correct controls.
- `plots/`: event plots with envelope, candidates, reference, targets, and
  outputs.

## Interpretation only; no fix is included

The evidence supports future testing of two narrow tracker rules: transition
handling that avoids stale pre-stability slew when the selected target is
already credible, and a targeted guard against an eligible high harmonic
displacing a stronger correct top candidate. Those are hypotheses for a later
experiment, not changes made by this report.
