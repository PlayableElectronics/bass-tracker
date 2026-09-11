#pragma once

#include <cstddef>
#include <cstdint>

#include "AnalysisTypes.h"

namespace bass
{
struct PitchTrackerState
{
    float tracked_frequency_hz;
    float previous_frequency_hz;
    // The octave-family tracker runs before the final stability conditioner.
    // Keeping this separate prevents the conditioner from feeding back into
    // family selection or its causal slew.
    float pre_stability_frequency_hz;
    float confidence;
    float previous_envelope;
    float previous_promoted_frequency_hz;
    float stability_targets_hz[6];
    bool has_pitch;
    bool family_promoted;
    bool stability_bypass;
    uint32_t stable_frames;
    uint32_t unstable_frames;
    uint32_t promotion_streak;
    uint32_t stability_target_count;
};

struct PitchTrackResult
{
    float frequency_hz;
    float confidence;
    bool valid;
    float pre_stability_frequency_hz;
    bool family_promoted;
    bool stability_bypass;
};

class PitchTracker
{
  public:
    void Init();
    PitchTrackResult Update(const PitchCandidate* candidates,
                            size_t candidate_count,
                            const SignalState& signal);
    const PitchTrackerState& State() const;

  private:
    float ApplyStability(float target_hz,
                         const SignalState& signal,
                         bool family_promoted);
    void ResetStability();
    PitchTrackerState state_ = {};
    uint32_t hold_frames_remaining_ = 0;
};
} // namespace bass
