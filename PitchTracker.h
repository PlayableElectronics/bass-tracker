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
    float confidence;
    bool has_pitch;
    uint32_t stable_frames;
    uint32_t unstable_frames;
};

struct PitchTrackResult
{
    float frequency_hz;
    float confidence;
    bool valid;
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
    float ScoreCandidate(const PitchCandidate& candidate,
                         const PitchCandidate* candidates,
                         size_t candidate_count,
                         bool allow_wide_continuity) const;
    PitchTrackerState state_ = {};
    uint32_t hold_frames_remaining_ = 0;
    uint32_t wide_continuity_frames_ = 0;
};
} // namespace bass
