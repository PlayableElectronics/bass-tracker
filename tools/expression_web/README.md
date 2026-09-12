# Expression WebMIDI monitor

Open `index.html` in a browser with WebMIDI support (Chromium-based browsers
are the practical choice), choose the Daisy input/output ports, then use the
calibration controls. The page sends and receives ordinary MIDI CC messages on
MIDI channel 16.

The Daisy build defaults to USB CDC diagnostics. Build with
`EXPRESSION_USB_MIDI=1` to make the Seed enumerate as USB MIDI for this page:

```bash
make -j1 EXPRESSION_USB_MIDI=1 \
  LIBDAISY_DIR=/home/pi/DaisyExamples/libDaisy \
  DAISYSP_DIR=/home/pi/DaisyExamples/DaisySP
```

libDaisy's current USB implementation chooses either CDC or MIDI descriptors,
not a composite device. Therefore MIDI mode intentionally replaces CDC only
for that explicitly selected build; the normal firmware continues its existing
CSV logging unchanged.

## CC protocol

All controls and telemetry use status `0xBF` (channel 16):

| CC | Direction | Meaning |
| --- | --- | --- |
| 20 | browser → Daisy | `1` START, `2` FREEZE, `3` RESET calibration |
| 21 | browser → Daisy | selected expression feature `0..10` |
| 22 | browser → Daisy | `0` AUTO, `1` MANUAL, `2` LOCKED range mode |
| 23 / 24 | browser → Daisy | manual low / high mapped into feature's documented raw domain |
| 25 | browser → Daisy | calibration duration mapped to 1–120 seconds |
| 12 / 13 | Daisy → browser | calibration state / elapsed-duration progress |
| 14 / 15 | Daisy → browser | learned amplitude floor / high range, `0..1` audio domain |
| 16 / 17 | Daisy → browser | learned low / high range for the selected feature |
| 30–40 | Daisy → browser | normalized v1 expression sources |
| 50–60 | Daisy → browser | raw sources mapped to their documented display domains |

Telemetry is emitted at approximately 9.4 Hz, intentionally slower than the
93.75 Hz expression update rate so diagnostic transport cannot disturb audio.
