#include <cmath>

#include "PitchTracker.h"

namespace bass
{
namespace
{
constexpr float kAcquireConfidence = 0.64f;
constexpr float kHoldConfidence = 0.46f;
// These match the calibrated signal-gate hysteresis.  Pitch acquisition has
// its own hysteresis, but must not demand an envelope level the signal gate
// can never reach on the present bass-input gain staging.
constexpr float kAcquireEnvelope = 0.0025f;
constexpr float kHoldEnvelope = 0.0015f;
constexpr uint32_t kPitchHoldFrames = 9;
constexpr uint32_t kWideContinuityFrames = 10;

constexpr float kRawScoreWeight = 0.78f;
constexpr float kDoubleHarmonicBonus = 0.28f;
constexpr float kTripleHarmonicBonus = 0.18f;
constexpr float kSubharmonicPenalty = 0.24f;
constexpr float kThirdHarmonicPenalty = 0.14f;
constexpr float kContinuityWeight = 0.34f;
constexpr float kSustainContinuityOctaves = 0.22f;
constexpr float kOnsetContinuityOctaves = 0.85f;
constexpr float kHarmonicTolerance = 0.055f;
constexpr float kOnsetPitchSlew = 0.70f;
constexpr float kSustainPitchSlew = 0.42f;

float Clamp01(float value)
{
    return value < 0.0f ? 0.0f : (value > 1.0f ? 1.0f : value);
}

bool NearRatio(float measured, float expected, float tolerance)
{
    return expected > 0.0f && std::fabs(measured - expected) / expected <= tolerance;
}

float OctaveDistance(float a, float b)
{
    return std::fabs(std::log(a / b) / std::log(2.0f));
}
} // namespace

void PitchTracker::Init()
{
    state_ = {0.0f, 0.0f, 0.0f, false, 0, 0};
    hold_frames_remaining_ = 0;
    wide_continuity_frames_ = 0;
}

float PitchTracker::ScoreCandidate(const PitchCandidate& candidate,
                                   const PitchCandidate* candidates,
                                   size_t candidate_count,
                                   bool allow_wide_continuity) const
{
    float combined = candidate.score * kRawScoreWeight;
    for(size_t i = 0; i < candidate_count; ++i)
    {
        const PitchCandidate& related = candidates[i];
        if(related.frequency_hz == candidate.frequency_hz)
            continue;
        if(NearRatio(related.frequency_hz, candidate.frequency_hz * 2.0f,
                     kHarmonicTolerance))
            combined += kDoubleHarmonicBonus * related.score;
        else if(NearRatio(related.frequency_hz, candidate.frequency_hz * 3.0f,
                          kHarmonicTolerance))
            combined += kTripleHarmonicBonus * related.score;
        else if(NearRatio(related.frequency_hz, candidate.frequency_hz * 0.5f,
                          kHarmonicTolerance))
            combined -= kSubharmonicPenalty * related.score;
        else if(NearRatio(related.frequency_hz, candidate.frequency_hz / 3.0f,
                          kHarmonicTolerance))
            combined -= kThirdHarmonicPenalty * related.score;
    }

    if(state_.has_pitch && state_.tracked_frequency_hz > 0.0f)
    {
        const float tolerance = allow_wide_continuity
                                    ? kOnsetContinuityOctaves
                                    : kSustainContinuityOctaves;
        const float distance = OctaveDistance(candidate.frequency_hz,
                                              state_.tracked_frequency_hz);
        const float continuity = Clamp01(1.0f - distance / tolerance);
        combined += kContinuityWeight * state_.confidence * continuity;
    }
    return combined;
}

PitchTrackResult PitchTracker::Update(const PitchCandidate* candidates,
                                      size_t candidate_count,
                                      const SignalState& signal)
{
    if(signal.onset)
        wide_continuity_frames_ = kWideContinuityFrames;
    const bool wide_continuity = wide_continuity_frames_ > 0;
    if(wide_continuity_frames_ > 0)
        --wide_continuity_frames_;

    const PitchCandidate* selected = nullptr;
    float selected_score = 0.0f;
    for(size_t i = 0; i < candidate_count; ++i)
    {
        const float score = ScoreCandidate(candidates[i], candidates,
                                           candidate_count, wide_continuity);
        if(selected == nullptr || score > selected_score)
        {
            selected = &candidates[i];
            selected_score = score;
        }
    }

    const float tracked_confidence = selected == nullptr
                                         ? 0.0f
                                         : Clamp01(selected->score * 0.72f
                                                   + Clamp01(selected_score) * 0.28f);
    const bool can_acquire = selected != nullptr && signal.gate
                             && signal.envelope >= kAcquireEnvelope
                             && tracked_confidence >= kAcquireConfidence;
    const bool can_hold = selected != nullptr && signal.gate
                          && signal.envelope >= kHoldEnvelope
                          && tracked_confidence >= kHoldConfidence;

    if(!state_.has_pitch)
    {
        if(can_acquire)
        {
            state_.tracked_frequency_hz = selected->frequency_hz;
            state_.previous_frequency_hz = selected->frequency_hz;
            state_.confidence = tracked_confidence;
            state_.has_pitch = true;
            state_.stable_frames = 1;
            state_.unstable_frames = 0;
            hold_frames_remaining_ = kPitchHoldFrames;
        }
    }
    else if(can_hold)
    {
        state_.previous_frequency_hz = state_.tracked_frequency_hz;
        const float slew = wide_continuity ? kOnsetPitchSlew : kSustainPitchSlew;
        state_.tracked_frequency_hz += slew * (selected->frequency_hz
                                                - state_.tracked_frequency_hz);
        state_.confidence = tracked_confidence;
        ++state_.stable_frames;
        state_.unstable_frames = 0;
        hold_frames_remaining_ = kPitchHoldFrames;
    }
    else if(hold_frames_remaining_ > 0)
    {
        --hold_frames_remaining_;
        state_.confidence *= 0.90f;
        ++state_.unstable_frames;
    }
    else
    {
        state_.has_pitch = false;
        state_.confidence = 0.0f;
        state_.stable_frames = 0;
        ++state_.unstable_frames;
    }

    return {state_.tracked_frequency_hz, state_.confidence, state_.has_pitch};
}

const PitchTrackerState& PitchTracker::State() const
{
    return state_;
}
} // namespace bass
