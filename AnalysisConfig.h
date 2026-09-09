#pragma once

namespace bass
{
// Calibrated from captures/bass-tracker-2026-09-09-calibration-60s.csv.
// The capture has no separately labelled silence interval, so these remain
// provisional until a true silence/control capture is collected.
constexpr float kGateOnThreshold = 0.000015f;
constexpr float kGateOffThreshold = 0.000008f;
constexpr float kOnsetMinimumEnvelope = 0.000010f;

// Keep pitch-valid hysteresis on the same calibrated amplitude scale as the
// signal gate.  Onset is intentionally not part of acquisition.
constexpr float kAcquireEnvelope = kGateOnThreshold;
constexpr float kHoldEnvelope = kGateOffThreshold;
} // namespace bass
