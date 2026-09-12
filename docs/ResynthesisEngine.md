# Coupled inharmonic resynthesis engine

The first resynthesis engine is a small synthetic dynamical object, not a
pitch-to-sine effect or an FM voice. The final tracked frequency is its stable
structural root. Five oscillating modes use configurable inharmonic ratios and
exchange a small amount of energy as they run.

## Structure

The default ratios are `1.00, 1.37, 1.93, 2.71, 3.89`. They are not musical
note quantization: the root remains a continuous frequency in Hz, and the
ratios can be replaced through `ResynthesisEngine::SetModeRatio()`.

Each mode has a phase, bounded energy, and previous output. Per sample, the
mode oscillator updates its energy from the preceding mode, applies bounded
nonlinearity, and contributes to the output. A small bounded feedback term
perturbs upper-mode phase. A deterministic scalar generator scatters a little
energy during noisy attacks; it is not an unbounded noise source.

The analysis thread publishes only scalar controls and a pending excitation;
the audio callback consumes that pending excitation and owns all mode state.
This keeps the expensive/stateful part of the dynamical system on the audio
side while preserving the existing analysis-rate expression boundary.

The implementation has five modes, fixed arrays, no allocation, no locks, no
FFT and no delay line. The output is hard-limited to `±0.92` after soft
shaping. Coupling, feedback, energy, ratio spread and phase perturbation are
all clamped before they can affect the audio path.

## Parameters and routes

`BaseParameters` holds the sound's base state. Every analysis frame computes
current values as base parameters plus bounded modulation offsets; modulation
never overwrites the base preset. The default routes are:

| source | destination | amount | purpose |
| --- | --- | ---: | --- |
| amplitude | excitation_amount | 0.85 | input energy becomes internal excitation |
| attack_strength | excitation_complexity | 0.90 | hard attacks distribute more energy |
| brightness | upper_mode_energy | 0.80 | brighter gestures favor upper modes |
| candidate_competition | instability_interaction | 0.75 | ambiguity increases interaction |
| octave_tension | mode_coupling | 0.80 | competing octave families exchange energy |
| noise_transient | stochastic_excitation | 0.65 | transient residual scatters modes |
| pitch_instability | ratio_spread | 0.35 | uncertainty moves relationships slightly |
| decay_rate | damping | 0.70 | physical decay changes mode lifetime |
| pitch_motion | structural_morph | 0.22 | motion changes interaction texture |
| candidate_competition | feedback_amount | 0.45 | ambiguity changes bounded return energy |
| noise_transient | nonlinearity | 0.50 | transient residual changes shaping |
| attack_strength | output_texture | 0.25 | hard attacks add interaction texture |

The new abstract destinations also provide space for later WebMIDI editing:
`excitation_amount`, `upper_mode_energy`, `feedback_amount`, `nonlinearity`,
`damping`, `ratio_spread`, and `output_texture`, alongside the original matrix
destinations. The current engine uses the relevant destinations directly and
keeps all control values in bounded scalar ranges.

The browser exposes reversible exploration macros without replacing the
detailed controls: `SOFTNESS` reduces upper energy, feedback and nonlinearity
while increasing damping; `INTERACTION` increases bounded coupling/feedback;
`CHAOS` increases bounded interaction/nonlinearity; `ATTACK BODY` increases
attack excitation; and `HARMONICITY` interpolates custom ratios toward the
integer sequence 1..5. Macro values are offsets applied at frame evaluation,
so the reference base preset remains recoverable.

Uncertainty does not retune the structural root. Candidate competition,
octave tension, pitch instability, and noise/transient information alter
coupling, feedback, mode relationships, and excitation instead. With those
sources at zero, amplitude, brightness and attack still produce a playable
stable object.

## Calibration and output modes

The engine consumes the normalized `ExpressionFrame`; it does not learn or
adapt calibration ranges itself. Uncalibrated and calibrating devices still
produce audio using the calibration layer's conservative/default normalized
values. Frozen calibration makes the controls deterministic for performance.

The existing left-channel input monitor and USB diagnostics remain intact. The
right channel defaults to the diagnostic sine. Build the engine explicitly:

```sh
make RESYNTH_ENGINE=1 EXPRESSION_USB_MIDI=0
```

Use `RESYNTH_ENGINE=0` for the original sine monitor. The same engine switch
works with `EXPRESSION_USB_MIDI=1`; USB CDC and MIDI remain alternative
descriptors as documented in `ExpressionArchitecture.md`.

## Portability and cost

The audio callback owns mode phases, energies, the feedback state and the
small deterministic random state. Analysis updates only scalar controls and a
pending excitation value at the existing analysis rate. The boundary uses
fixed scalar state and no realtime synchronization primitive. On Daisy this is
five sine evaluations, five bounded nonlinearities, a handful of multiplies,
and one small feedback loop per sample, in addition to the existing analysis.
Exact CPU percentage should be measured with the target build's profiler; the
engine is intentionally small enough for the current 48 kHz / 16-sample audio
configuration.

Future work can add stereo mode distribution and alternate mode sets. Reverb,
a conventional FM architecture, compression, pitch quantization and a
persistent preset library are deliberately out of scope.

## Sound-design protocol

The browser sound preset format is readable JSON with the keys
`base_parameters`, `mode_ratios`, `mode_weights`, `macros`,
`uncertainty_influence`, and `routes`. It intentionally excludes calibration.
The reference preset is the exact original engine setup: ratios
`1, 1.37, 1.93, 2.71, 3.89`, weights `0.58, 0.30, 0.22, 0.16, 0.11`, and
all exploration macros at zero.

The extended CC assignments and 14-bit encoding are documented in
`ExpressionArchitecture.md`; all fine controls use normalized or signed
normalized 14-bit pairs and are mapped to safe engine domains on the device.

The browser sound-design panel edits all eight base parameters, five arbitrary
mode ratios, five bounded mode weights, the fixed-capacity modulation routes,
and five reversible exploration macros. `SOFTNESS`, `INTERACTION`, `CHAOS`,
`ATTACK BODY`, and `HARMONICITY` are exploration offsets evaluated from the
current base state; they do not replace the detailed controls. The
`UNCERTAINTY INFLUENCE` control scales only routes sourced by residual or
uncertainty features while leaving those expression measurements visible.
Sound presets are browser-side JSON and contain no calibration ranges. The
`Reference / Original` action restores the exact cbb8120 ratios, weights and
base setup, with macros cleared.
