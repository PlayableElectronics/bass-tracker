# Ambiguous but correct controls

These attacks contain at least one 1:2 or 1:3 candidate relation but remain within 50 cents of their settled reference throughout the mapped 200 ms context. The first control is a near-equal-score, confirmed promotion; the others show weaker harmonic relatives that correctly do not qualify for promotion.

## Attack 209 @ 164.469 s

Strongest 1:2/1:3 pair minimum score: 0.988; maximum reference error in context: 30.6 cents.

```text
t=164.469333 env=0.03837 pYIN=74.05 (conf=0.69) settled_ref=74.05 top=74.07@0.993; [#1 74.07@0.993, #2 36.92@0.988, #3 150.00@0.008, #4 49.38@0.002]
  family=74.07@0.993 proposed=1 streak=10 confirmed=1 multiple=2 -> selected=74.07; pre 74.04->74.06 (confirmed_family, slew=0.50); stability=moving alpha=1.00; final=74.06; error=0.0; attribution=
```

## Attack 194 @ 149.600 s

Strongest 1:2/1:3 pair minimum score: 0.389; maximum reference error in context: 15.6 cents.

```text
t=149.600000 env=0.06882 pYIN=47.74 (conf=0.01) settled_ref=46.65 top=50.00@0.725; [#1 50.00@0.725, #2 102.56@0.389, #3 31.09@0.364, #4 34.88@0.220]
  family=50.00@0.725 proposed=0 streak=0 confirmed=0 multiple=0 -> selected=50.00; pre 44.96->47.07 (sustain, slew=0.42); stability=moving alpha=1.00; final=47.07; error=15.6; attribution=
```

## Attack 178 @ 138.517 s

Strongest 1:2/1:3 pair minimum score: 0.341; maximum reference error in context: 8.3 cents.

```text
t=138.517333 env=0.03562 pYIN=46.65 (conf=0.32) settled_ref=46.65 top=46.88@0.991; [#1 46.88@0.991, #2 31.41@0.383, #3 94.49@0.341, #4 60.61@-0.038]
  family=46.88@0.991 proposed=0 streak=0 confirmed=0 multiple=0 -> selected=46.88; pre 46.80->46.83 (sustain, slew=0.42); stability=stable alpha=0.45; final=46.84; error=6.8; attribution=
```

## Attack 187 @ 145.152 s

Strongest 1:2/1:3 pair minimum score: 0.316; maximum reference error in context: 37.0 cents.

```text
t=145.152000 env=0.03208 pYIN=46.65 (conf=0.32) settled_ref=46.92 top=46.88@0.987; [#1 46.88@0.987, #2 30.77@0.405, #3 90.23@0.316, #4 32.35@0.276]
  family=46.88@0.987 proposed=0 streak=0 confirmed=0 multiple=0 -> selected=46.88; pre 46.88->46.88 (sustain, slew=0.42); stability=stable alpha=0.45; final=46.88; error=-1.7; attribution=
```

## Attack 161 @ 126.667 s

Strongest 1:2/1:3 pair minimum score: 0.291; maximum reference error in context: 37.0 cents.

```text
t=126.666667 env=0.04312 pYIN=46.65 (conf=0.32) settled_ref=46.65 top=46.88@0.995; [#1 46.88@0.995, #2 32.17@0.575, #3 30.85@0.489, #4 101.69@0.291]
  family=46.88@0.995 proposed=0 streak=0 confirmed=0 multiple=0 -> selected=46.88; pre 46.88->46.88 (sustain, slew=0.42); stability=stable alpha=0.45; final=46.88; error=8.3; attribution=
```
