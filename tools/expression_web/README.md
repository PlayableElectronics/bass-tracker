# Expression WebMIDI monitor

Open `index.html` in a browser with WebMIDI support (Chromium-based browsers
are the practical choice), choose the Daisy input/output ports, then use the
calibration controls. The page sends and receives MIDI CC messages on MIDI
channel 16. State, progress, and normalized values use 7-bit CC; raw values
and calibration ranges use paired 14-bit CC messages. Each pair is sent MSB
first, then LSB, and decoded as `(MSB << 7) | LSB`.

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
| 23/26, 24/27 | browser → Daisy | manual low/high as 14-bit MSB/LSB pairs mapped into the feature's documented raw domain |
| 25 | browser → Daisy | calibration duration mapped to 1–120 seconds |
| 12 / 13 | Daisy → browser | calibration state / elapsed-duration progress |
| 14/61, 15/62 | Daisy → browser | learned amplitude floor / high range as 14-bit pairs, `0..1` audio domain |
| 16/63, 17/64 | Daisy → browser | learned low / high range for the selected feature as 14-bit pairs |
| 30–40 | Daisy → browser | normalized v1 expression sources |
| 70–80 with 81–91 | Daisy → browser | raw sources as 14-bit MSB/LSB pairs mapped to documented domains |

Unipolar values use `0..16383 = 0..1`. Bipolar live values use centered
encoding: `-1 = 0`, `0 = 8192`, `+1 = 16383`. `pitch_motion` raw telemetry is
signed; its learned and active calibration ranges are magnitude-only because
calibration uses absolute-value statistics.

Telemetry is emitted at approximately 9.4 Hz, intentionally slower than the
93.75 Hz expression update rate so diagnostic transport cannot disturb audio.
