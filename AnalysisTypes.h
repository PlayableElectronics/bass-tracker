#pragma once

#include <cstddef>
#include <cstdint>

#include "ExpressionBus.h"

namespace bass
{
constexpr size_t kMaxPitchCandidates = 6;

struct PitchCandidate
{
    float frequency_hz;
    float score;
    size_t lag;
};

struct SignalState
{
    float envelope;
    float attack;
    bool gate;
    bool onset;
};

struct BassAnalysis
{
    uint32_t sequence;
    uint32_t ms;
    float raw_frequency_hz;
    float tracked_frequency_hz;
    float pre_stability_frequency_hz;
    float raw_confidence;
    float tracked_confidence;
    float envelope;
    float attack;
    float input_peak;
    float input_rms;
    float filtered_peak;
    float filtered_rms;
    bool gate;
    bool pitch_valid;
    bool onset;
    bool family_promoted;
    bool stability_bypass;
    PitchCandidate candidates[kMaxPitchCandidates];
    size_t candidate_count;
    // Raw physical analysis and calibrated expression values are retained
    // alongside, not folded back into, the frozen pitch tracker.
    ExpressionFrame expression;
};
} // namespace bass
