# Bass Analysis / Experimental Resynthesis Instrument

## Purpose of this document

This document records the design direction, experiments, discoveries, rejected approaches and current state of the project.

Future agents should read this BEFORE changing the pitch tracker or synthesis architecture.

Repository:

`PlayableElectronics/bass-tracker`

Hardware target:

`Electro-Smith Daisy Seed`

Primary development strategy:

```text id="g7xihx"
Mac/offline experimentation
        ↓
measurement + listening
        ↓
small proven algorithm
        ↓
Daisy implementation
        ↓
real instrument listening
```

---

# 1. Long-term objective

This project began as a bass pitch tracker but the intended instrument is now broader.

We want to analyze a live electric bass and use its physical performance characteristics to drive a new real-time synthesis/resynthesis engine.

This is NOT intended to become:

* a bass-to-MIDI converter;
* a normal guitar synth;
* a conventional FM synth;
* a normal subtractive synth;
* an emulation of a commercial guitar synthesizer.

The desired result should be a new instrument.

Central design principle:

> **tracker uncertainty = expressive control**

Information that conventional pitch trackers reject as noise or ambiguity may contain musically valuable information.

Examples:

* transient complexity;
* harmonic competition;
* octave ambiguity;
* broadband attack energy;
* fret/string noise;
* changing harmonic structure;
* instability;
* pitch motion;
* decay characteristics.

The stable fundamental and unstable/residual information should therefore be treated separately.

---

# 2. Intended architecture

Long-term architecture:

```text id="gw3p5f"
                LIVE BASS
                    |
                    v
                 ANALYSIS
                    |
        +-----------+------------+
        |                        |
        v                        v
 FUNDAMENTAL PATH          EXPRESSION PATH
 stable/conservative       rich/raw/ambiguous
        |                        |
        +-----------+------------+
                    |
                    v
          CALIBRATION /
          NORMALIZATION
                    |
                    v
          EXPRESSION BUS
                    |
                    v
          MODULATION MATRIX
                    |
                    v
        EXPERIMENTAL RESYNTH
```

The fundamental path answers:

```text id="3ywtck"
"What pitch should the synthesis structure follow?"
```

The expression path answers:

```text id="l8w7gm"
"What is physically/musically happening around that pitch?"
```

---

# 3. Input philosophy

Do not preprocess the instrument into a sterile tracking signal.

In particular, do not introduce compression simply to make tracking easier.

The studio analysis recording was:

```text id="n11q53"
bass
 -> DI box
 -> professional studio recording
```

Real Daisy testing was performed using:

```text id="4nxj8m"
DIFFERENT active bass
 -> direct input
 -> Daisy
```

The algorithm has therefore already been exercised under significantly different source conditions.

This is important.

Do not assume the studio recording represents the exact instrument or input chain used live.

---

# 4. Adaptation philosophy

The device should adapt to the connected instrument/setup.

However, it should NOT continuously adapt forever.

Desired workflow:

```text id="tvsdz2"
START CALIBRATION
       ↓
musician plays normally
       ↓
device learns operating ranges
       ↓
FREEZE
       ↓
PERFORMANCE
```

During performance, calibration values remain fixed.

This is important for predictability.

A player must be able to learn the instrument.

The same gesture should not gradually produce different behavior because background estimators continue drifting.

Calibration can be explicitly restarted.

---

# 5. What calibration may learn

Instrument/setup-dependent characteristics may include:

```text id="wcx8yx"
noise floor
playing amplitude range
attack-strength range
brightness range
harmonicity range
candidate-score distribution
ambiguity range
transient/noise range
decay behavior
pitch-motion range
```

Calibration should prefer relative/self-normalized statistics over constants derived from one recording.

---

# 6. What calibration must NOT learn

Do NOT learn:

```text id="64vmhl"
bass tuning
E/A/D/G assumptions
musical scale
preferred notes
MIDI notes
song-specific pitch probabilities
```

Pitch remains continuous.

---

# 7. WebMIDI calibration/control

There is already HTML/WebMIDI infrastructure associated with this project.

The intended calibration interface should allow:

```text id="g1wqzj"
START CALIBRATION
FREEZE
RESET
```

and show:

```text id="7w3qjk"
raw measurements
learned ranges
normalized expression controls
calibration state
```

Useful calibration values may support:

```text id="h6w9t9"
AUTO
MANUAL
LOCKED
```

so the player can accept learned values or deliberately override them.

Calibration presets should eventually be saveable/loadable.

---

# 8. Modulation matrix

The future synthesis engine should not have hardwired mappings from analysis to synthesis.

Use a modulation matrix.

Conceptually:

```text id="7bkdhf"
EXPRESSION SOURCE
      ↓
amount / curve / smoothing
      ↓
SYNTH DESTINATION
```

Routing amount should be bipolar where useful:

```text id="9sxdc4"
-1 ... +1
```

Possible expression sources include:

```text id="9x4dkc"
pitch
amplitude
attack strength
brightness
harmonicity
ambiguity
octave tension
candidate competition
noise/transient amount
decay rate
pitch motion
pitch instability
```

Possible future destinations might include:

```text id="8vn0eu"
excitation
oscillator relationships
mode amplitudes
mode damping
mode spread
coupling
feedback
nonlinearity
spectral distribution
noise excitation
resonator structure
```

Mappings must be configurable.

---

# 9. Synthesis philosophy

Do NOT automatically build a conventional FM synthesizer.

FM is allowed as one primitive.

Modal synthesis is allowed as one primitive.

Neither defines the instrument.

Potential building blocks include:

```text id="j8bpyt"
coupled oscillators
inharmonic oscillator banks
modal resonators
feedback networks
waveguide-like systems
FM / phase modulation
cross-modulation
nonlinear interactions
waveshaping
stochastic excitation
dynamic resonator networks
spectral redistribution
```

The synthesis architecture should eventually be designed around the information produced by the bass-analysis system.

The goal is not necessarily to recreate bass timbre.

The goal is to transfer the physical complexity and gestures of bass playing into a different synthetic system.

---

# 10. Pitch-tracker development history

The tracker was developed iteratively using a professional studio bass recording and Mac-side replay/evaluation.

The original tracker produced substantial octave errors.

A sequence of experiments followed.

---

# 11. octave_v1

A successful octave-family selection experiment substantially reduced octave-down errors.

The key idea was to evaluate related candidates as a harmonic/octave family rather than blindly preferring lower subharmonics.

Approximate selected values included:

```text id="0rr7t3"
family promotion ratio ~0.92
promotion persistence = 2 frames
```

Exact values must always be obtained from committed source/configuration rather than this recap.

The important result was a dramatic reduction in octave-down tracking.

This was considered a major improvement.

---

# 12. stability_v1

After octave correction, audible beating/wobble remained.

A causal adaptive stability layer was tested.

The winning implementation uses light smoothing in stable regions while bypassing smoothing during:

```text id="71i1oa"
movement
attack
family promotion
large transitions
```

Approximate selected values included:

```text id="4gzai9"
stable alpha ~0.45
motion threshold ~8 cents
large-step bypass ~140 cents
```

Again, committed implementation is authoritative.

Human listening confirmed that `stability_best` was clearly improved.

This was subsequently ported to Daisy.

---

# 13. Daisy validation

The octave + stability implementation was tested on Daisy using a different active bass connected directly.

It was generally stable.

Remaining audible errors appeared primarily around note attacks/transitions and low-level tails.

This led to several experiments.

---

# 14. Decay envelope experiment

Late-decay pitch errors were often audible even though musically the synthesized sound should already be disappearing.

A separate audible synthesis envelope was investigated.

Selected Mac envelope was approximately:

```text id="63db7x"
audible_on  ~0.0020
audible_off ~0.0012
attack      ~4 ms
release     ~120 ms
```

This helped tails.

Important conceptual separation:

```text id="5m5b97"
pitch tracker:
"What frequency exists?"

synth envelope:
"Should the listener hear synthesis right now?"
```

Do not solve low-level tail errors by destroying tracker coverage.

---

# 15. Rejected attack gain suppression

An experiment attempted to suppress attack artifacts by reducing synthesis gain while pitch was being acquired.

One selected version reduced gain to approximately 10% and waited for pitch trust before fading up.

Metrics improved.

Human listening REJECTED it.

Reason:

> It killed the natural sharp bass attack while some pitch glitches remained.

This is an important lesson:

**metric improvement is not sufficient if musical response becomes worse.**

Do NOT resurrect this approach merely because its metrics look good.

---

# 16. Rejected generic attack-frequency masking

Frequency-only guards were then tested.

A narrow octave guard barely activated and did not solve the audible problem.

This demonstrated that remaining errors were broader than isolated one-frame octave flips.

---

# 17. Early-pitch hypothesis

Human listening suggested a possible pattern:

```text id="grzmew"
correct at beginning
wrong during amplitude peak
correct after attack
```

This was tested quantitatively rather than assumed.

Commit:

`ed2ea535d85aed6a923c020de4b6ebefd4313325`

Result:

**hypothesis NOT supported as a common pattern.**

233 attacks analyzed.

55 had usable settled pYIN references.

First credible pitch vs settled reference:

```text id="9em53a"
±10c   10.9%
±25c   21.8%
±50c   32.7%
±100c  49.1%
```

Envelope-peak pitch:

```text id="qqox59"
±10c   27.3%
±25c   43.6%
±50c   67.3%
±100c  81.8%
```

Peak was generally BETTER than initial pitch.

Therefore do not implement a generic early-pitch latch.

---

# 18. Important candidate discovery

The same attack analysis revealed something much more important.

For peak-time errors >=100 cents:

```text id="8ab2dt"
correct settled pitch still in top 4:
9/10
```

and:

```text id="xmvss9"
correct pitch candidate rank #1:
8/10
```

This suggested that detection itself often already had the answer.

The tracker was sometimes making the wrong state/selection decision.

---

# 19. Forensic tracker analysis

Commit:

`ffb154e58277a933591613b7c984ca43cb746914`

Forensic analysis examined:

```text id="pobp6n"
31 attack-error events
67 error frames
```

Results:

```text id="f8mtw2"
correct reference candidate present:
63/67 = 94.0%

correct candidate raw rank #1:
57/67 = 85.1%

target-selection errors:
12 frames

slew/state-lag errors:
55 frames

adaptive-stability-caused:
0 frames
```

Dominant failure:

```text id="wt0fj5"
pre-stability slew lag
22 events / 52 frames
```

This was a major finding.

---

# 20. Example: 176.416 s

At approximately 176.416 s the tracker is initially correct.

Around the failure:

```text id="g4u00m"
reference ~61.56 Hz

raw candidate #1:
~61.86 Hz
score ~0.990

2x candidate:
~123.71 Hz
score ~0.922
```

The high candidate barely satisfied the existing family-promotion ratio for two consecutive frames.

It was promoted even though the stronger correct candidate remained available.

Pre-stability slew then produced approximately:

```text id="1ng14b"
61.86
→ 92.79
→ 108.25
→ 119.85 Hz
```

When candidate selection returned to ~61.86 Hz, ordinary slew delayed recovery.

Adaptive stability was bypassed and was NOT responsible.

---

# 21. Example: 152.928 s

This was a different failure.

Raw detector result was genuinely poor:

```text id="k9s9q4"
candidate #1:
~30.69 Hz @ 0.573

reference candidate:
~46.69 Hz
candidate #3 @ ~0.193
```

So the first error was a genuine detector/top-candidate failure.

However, when the correct target returned one frame later, stale hold/slew extended the audible mistake.

This distinction is important:

```text id="n98crz"
detector mistake
+
unnecessarily slow tracker recovery
```

---

# 22. Root-cause fixes

A later experiment tested:

```text id="jpmf6i"
A — fast recovery from transient stale slew

B — guard against weak high-harmonic promotion
```

A+B improved results.

Reported comparison included approximately:

```text id="et9krh"
forensic error frames:
67 → 55

forensic error events:
31 → 30

P90 error:
12.32c → 12.11c

within ±25c:
94.46% → 94.63%

octave-up duration:
0.544 s → 0.533 s

octave-down:
unchanged ~1.952 s
```

Fast recovery reduced recovery latency approximately:

```text id="aqe79n"
median:
32 ms → 10.7 ms

P90:
48 ms → 21.3 ms
```

The harmonic guard fixed the known 176.416-type promotion failure.

The tracker is improved but NOT perfect.

That is acceptable for the current stage.

---

# 23. Current pitch-tracker policy

Do not endlessly optimize the remaining artifacts against the studio recording.

There is concern about overfitting.

The studio recording and live Daisy bass are already different instruments/input chains.

Future improvements should favor:

```text id="3vv4s6"
structural rules
relative measurements
adaptive normalization
```

over:

```text id="r4o5aw"
fixed recording-specific levels
timestamp-specific fixes
note-specific heuristics
```

The current tracker should be treated as the v1 foundation while the broader instrument architecture is developed.

---

# 24. Tracker uncertainty is useful

Do NOT throw away candidate information merely because it loses the fundamental-pitch decision.

Example:

```text id="15ejq4"
candidate A:
61 Hz @ 0.98

candidate B:
122 Hz @ 0.91
```

Pitch path may decide:

```text id="ewr5gx"
61 Hz
```

Expression path should retain information about B.

Possible derived control:

```text id="ow5ly1"
octave tension
harmonic ambiguity
candidate competition
```

This may drive the future synthesis engine.

Thus:

```text id="qkq6nb"
wrong for pitch
!=
useless for synthesis
```

---

# 25. Expression bus direction

Candidate v1 expression signals include:

```text id="hd7hde"
pitch
amplitude
attack strength
brightness
harmonicity / periodicity
ambiguity
octave tension
candidate competition
noise/transient amount
decay rate
pitch motion
pitch instability
```

Each should ideally have:

```text id="u09p4c"
raw representation
+
calibrated normalized representation
```

Do not prematurely smooth away interesting information.

Where useful, maintain fast/raw and slow/smoothed forms.

---

# 26. Modulation philosophy

Expression should not have hardcoded synthesis meaning.

Use a modulation matrix.

For example:

```text id="rxo29l"
ambiguity       → structural instability
brightness      → spectral distribution
attack strength → excitation
octave tension  → mode interaction
noise amount    → stochastic component
pitch motion    → morphing/coupling
```

But these are examples only.

The musician should be able to decide how much each source controls each destination.

---

# 27. Future synthesis

The synthesis engine should be approached experimentally.

Previous related work by the project owner includes:

* scanned synthesis;
* modal banks;
* FM banks;
* inharmonic oscillator banks;
* handpan-like synthesis;
* resonators;
* feedback;
* FPGA DSP;
* physical-model-inspired structures.

These ideas may inform the future engine.

However, do not simply combine them into a generic feature-heavy synth.

The goal is to discover a synthesis system whose internal dynamics respond meaningfully to the expression bus.

A particularly interesting direction is to let uncertainty alter the **structure or coupling of the synthesis system**, rather than merely map it to conventional parameters such as filter cutoff.

---

# 28. Human listening is authoritative

Several experiments produced numerically improved results that sounded musically worse.

Therefore evaluation hierarchy is:

```text id="1hrxau"
correctness / regressions
        +
quantitative evidence
        +
HUMAN LISTENING
```

Do not automatically promote the numerically best candidate to production.

Always provide A/B listening artifacts for perceptually significant changes.

---

# 29. Development rules for future agents

Before changing the tracker:

1. Identify the actual failure.
2. Measure it.
3. Determine which stage causes it.
4. Test a minimal Mac-side counterfactual.
5. Compare full-track regressions.
6. Produce listening artifacts.
7. Only then consider Daisy port.

Do not pile generic smoothing layers onto unexplained errors.

---

# 30. Things explicitly rejected

Do NOT casually reintroduce:

```text id="b0l9ct"
heavy attack muting
attack gain suppression
long pitch acquisition delays
generic output pitch holding
MIDI quantization
bass-tuning assumptions
continuous uncontrolled adaptation
compression purely to help tracking
```

These conflict with the project's musical direction or have already failed listening tests.

---

# 31. Immediate next milestone

Build:

```text id="3b53le"
CALIBRATION
+
NORMALIZED EXPRESSION BUS
+
WEBMIDI OBSERVABILITY
+
MODULATION MATRIX ARCHITECTURE
```

before spending substantial effort on the final synthesis engine.

Calibration should learn instrument/setup-specific operating ranges for a finite period and then freeze.

The web tool should make those learned values visible and manually adjustable.

---

# 32. Long-term artistic principle

The project should preserve the distinction:

```text id="9d0ikb"
PITCH PATH
stable
predictable
conservative

EXPRESSION PATH
dynamic
ambiguous
physical
potentially chaotic
```

The latter is not an error channel.

It is part of the instrument.

The ultimate aim is to create a synthesis system where the bass player's real physical gestures—attack, harmonic competition, instability, brightness, noise, slides, decay and ambiguity—drive a synthetic object with its own sonic identity.

The goal is not simply:

```text id="o9v3dh"
bass → detected note → synth
```

It is:

```text id="v4svab"
bass performance
      ↓
physical/temporal analysis
      ↓
stable structure + expressive uncertainty
      ↓
configurable interaction
      ↓
new synthetic behaviour
```

That is the direction future work should preserve.
