# Daisy Seed Bass Analyzer

Tracker v2 is a monophonic bass analyzer for Daisy Seed. The firmware passes
the left codec input to both outputs and emits a CSV analysis record for every
completed pitch frame over USB serial.

The pitch path is intentionally only one part of the instrument front end.
`docs/ExpressionArchitecture.md` documents the separate raw/calibrated
expression bus and future resynthesis modulation boundary. It does not alter
pitch tracking or add a synthesis engine.

## Signal path

- 48 kHz audio, 16-sample blocks
- DC blocker, coefficient 0.995
- one-pole low-pass at approximately 1.2 kHz
- envelope follower: 1.5 ms attack, 80 ms release, hysteretic signal gate
- 4x decimation to 12 kHz
- 512-sample analysis window with 128-sample hop
- normalized autocorrelation search over lags 30 through 400 (approximately
  30–400 Hz at the 12 kHz analysis rate)
- top six autocorrelation local-maximum candidates
- harmonic/subharmonic evidence, temporal continuity and pitch hysteresis
- separate onset/attack, signal-gate and pitch-valid states

## Amplitude calibration

The current provisional amplitude thresholds are centralized in
`AnalysisConfig.h`:

```text
gate on:             0.000015
gate off:            0.000008
onset minimum:       0.000010
pitch acquire:       0.000015
pitch hold:          0.000008
```

They are based on the 2026-09-09 real-bass calibration capture, whose envelope
was approximately 0.000019 median, 0.000020 at the 90th percentile, and
0.000021 at the 95th percentile and maximum. That capture did not contain a
labelled silence interval, so collect a silence capture before treating these
values as final.

The raw strongest autocorrelation candidate remains in the CSV output for
debugging. `tracked_*` fields come from the candidate tracker; no MIDI-note
quantization is performed.

## Build

The Makefile expects the standard DaisyExamples layout on the lab Pi:

```bash
make -j1 LIBDAISY_DIR=/home/pi/DaisyExamples/libDaisy \
  DAISYSP_DIR=/home/pi/DaisyExamples/DaisySP
```

The repository workspace wrapper builds the deployed copy with:

```bash
./tools/daisy build /home/pi/CODEX-daisy/bass-analyzer
```

## Flash

```bash
./tools/daisy flash \
  /home/pi/CODEX-daisy/bass-analyzer/build/BassAnalyzer.bin
```

The wrapper probes the STM32 target, flashes at `0x08000000`, resets it, and
verifies the image by reading it back.

## USB serial monitor

On the lab Pi, the Daisy appears as `/dev/ttyACM0` after the firmware starts:

```bash
ssh pi@daisies.local \
  'stty -F /dev/ttyACM0 115200 raw -echo; cat /dev/ttyACM0'
```

The two lines printed by libDaisy while USB logging starts are non-CSV. All
subsequent analysis lines use this header:

```text
seq,ms,raw_freq_hz,tracked_freq_hz,raw_confidence,tracked_confidence,envelope,attack,gate,pitch_valid,onset,input_peak,input_rms,filtered_peak,filtered_rms,c1_freq,c1_score,c2_freq,c2_score,c3_freq,c3_score,c4_freq,c4_score,pre_stability_freq_hz,final_tracked_freq_hz,family_promoted,stability_bypass
```

Use a suitable instrument input, buffer or DI/preamp for a passive bass
pickup. The firmware expects the Daisy audio codec input, not a GPIO pin.

## Expression calibration and WebMIDI

The normal firmware retains CDC CSV diagnostics. In addition to the existing
numeric frame rows it emits compact `expr` telemetry lines at about 11.7 Hz;
they contain raw and normalized expression values and can be ignored by the
existing capture tool.

Expression calibration is explicit and finite:

```text
UNCALIBRATED -> START -> CALIBRATING -> FREEZE (or timed freeze) -> FROZEN
```

Only `CALIBRATING` updates learned ranges. In `FROZEN` performance the
calibration is deterministic until the musician starts a new calibration.

The optional `EXPRESSION_USB_MIDI=1` build exposes that state and the
expression frame to [the WebMIDI calibration page](tools/expression_web/).
This installed libDaisy version cannot expose CDC and MIDI simultaneously, so
that flag deliberately replaces CDC only in that alternate build. See
`tools/expression_web/README.md` for the protocol and browser workflow.

## Capturing labelled tests

Install pyserial on the host that sees the Daisy USB serial device, then run:

```bash
python3 tools/capture.py /dev/ttyACM0 open_E --duration 10
```

The capture script creates a timestamped file in `captures/`, adds a `label`
column, skips startup text and malformed rows, and handles `Ctrl-C` cleanly.
CSV captures are tracked in Git for later offline analysis.

Recommended labelled captures:

```text
silence
open_B
open_E
open_A
open_D
open_G
E_12th
soft_E
hard_E
muted_E
hammer_E_Fsharp
slide_E_A
slide_A_E
chromatic_E_string
```

For each open string, capture about 10 seconds, pluck four or five times, and
allow each pluck to decay between notes.
