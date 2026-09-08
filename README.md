# Daisy Seed Bass Analyzer

First working libDaisy milestone for a monophonic bass analyzer. The firmware
passes the left codec input to both outputs and reports envelope, onset,
normalized-autocorrelation pitch, confidence and gate state over USB serial.

## Signal path

- 48 kHz audio, 16-sample blocks
- DC blocker, coefficient 0.995
- one-pole low-pass at approximately 1.2 kHz
- envelope follower: 1.5 ms attack, 80 ms release
- 4x decimation to 12 kHz
- 512-sample analysis window with 128-sample hop
- normalized autocorrelation search over lags 30 through 400
- initial gate threshold 0.003

The first detector deliberately reports raw strongest-lag results. Octave
correction, continuity tracking and confidence hysteresis are future work.

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

Example output:

```text
F=41.24  CONF=0.973  ENV=0.151  ATT=0.310  G=1
```

Use a suitable instrument input, buffer or DI/preamp for a passive bass
pickup. The firmware expects the Daisy audio codec input, not a GPIO pin.
