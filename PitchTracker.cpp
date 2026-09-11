#include <cmath>

#include "AnalysisConfig.h"
#include "PitchTracker.h"

namespace bass
{
namespace
{
constexpr float kAcquireConfidence = 0.64f;
constexpr float kHoldConfidence = 0.46f;
constexpr uint32_t kPitchHoldFrames = 9;

// Exact selected Mac octave_v1 configuration.
constexpr float kFamilyPromotionRatio = 0.92f;
constexpr float kHarmonicTolerance = 0.055f;
constexpr float kSustainPitchSlew = 0.42f;
constexpr float kPromotedPitchSlew = 0.50f;
constexpr uint32_t kPromotionConfirmFrames = 2;
constexpr float kPromotionContinuityOctaves = 0.18f;

// Exact selected Mac stability_v1 configuration.
constexpr float kStableAlpha = 0.45f;
constexpr float kMotionAlpha = 1.0f;
constexpr float kMotionCents = 8.0f;
constexpr float kLargeStepBypassCents = 140.0f;
constexpr size_t kStabilityHistorySize = 6;

float Clamp01(float value)
{
    return value < 0.0f ? 0.0f : (value > 1.0f ? 1.0f : value);
}

int RelatedMultiple(float high, float low)
{
    if(low <= 0.0f || high <= low)
        return 0;
    const float ratio = high / low;
    if(std::fabs(ratio - 2.0f) / 2.0f <= kHarmonicTolerance)
        return 2;
    if(std::fabs(ratio - 3.0f) / 3.0f <= kHarmonicTolerance)
        return 3;
    return 0;
}

float OctaveDistance(float a, float b)
{
    return a > 0.0f && b > 0.0f ? std::fabs(std::log2(a / b)) : 0.0f;
}

float Cents(float a, float b)
{
    return a > 0.0f && b > 0.0f ? 1200.0f * std::log2(a / b) : 0.0f;
}

float Median3(float a, float b, float c)
{
    if(a > b)
    {
        const float swap = a;
        a = b;
        b = swap;
    }
    if(b > c)
    {
        const float swap = b;
        b = c;
        c = swap;
    }
    if(a > b)
    {
        const float swap = a;
        a = b;
        b = swap;
    }
    return b;
}

const PitchCandidate* TopCandidate(const PitchCandidate* candidates,
                                   size_t candidate_count)
{
    const PitchCandidate* top = nullptr;
    for(size_t i = 0; i < candidate_count; ++i)
    {
        if(top == nullptr || candidates[i].score > top->score)
            top = &candidates[i];
    }
    return top;
}

const PitchCandidate* FamilyCandidate(const PitchCandidate* candidates,
                                      size_t candidate_count,
                                      bool& promoted)
{
    promoted = false;
    const PitchCandidate* top = TopCandidate(candidates, candidate_count);
    if(top == nullptr)
        return nullptr;

    const PitchCandidate* chosen = nullptr;
    for(size_t high_index = 0; high_index < candidate_count; ++high_index)
    {
        const PitchCandidate& high = candidates[high_index];
        for(size_t low_index = 0; low_index < candidate_count; ++low_index)
        {
            const PitchCandidate& low = candidates[low_index];
            if(RelatedMultiple(high.frequency_hz, low.frequency_hz) == 0
               || high.score < kFamilyPromotionRatio * top->score)
                continue;

            if(chosen == nullptr || high.frequency_hz > chosen->frequency_hz
               || (high.frequency_hz == chosen->frequency_hz
                   && high.score > chosen->score))
                chosen = &high;
        }
    }
    if(chosen == nullptr)
        return top;
    promoted = true;
    return chosen;
}
} // namespace

void PitchTracker::Init()
{
    state_ = {};
    hold_frames_remaining_ = 0;
}

void PitchTracker::ResetStability()
{
    state_.tracked_frequency_hz = 0.0f;
    state_.stability_target_count = 0;
    state_.stability_bypass = false;
}

float PitchTracker::ApplyStability(float target_hz,
                                   const SignalState& signal,
                                   bool family_promoted)
{
    if(state_.stability_target_count < kStabilityHistorySize)
    {
        state_.stability_targets_hz[state_.stability_target_count++] = target_hz;
    }
    else
    {
        for(size_t i = 1; i < kStabilityHistorySize; ++i)
            state_.stability_targets_hz[i - 1] = state_.stability_targets_hz[i];
        state_.stability_targets_hz[kStabilityHistorySize - 1] = target_hz;
    }

    const float trend = state_.stability_target_count == kStabilityHistorySize
                            ? Cents(target_hz, Median3(state_.stability_targets_hz[0],
                                                        state_.stability_targets_hz[1],
                                                        state_.stability_targets_hz[2]))
                            : 0.0f;
    const float step = Cents(target_hz, state_.tracked_frequency_hz);
    const bool attack = signal.onset
                        || (state_.previous_envelope > 0.0f
                            && signal.envelope > state_.previous_envelope * 1.25f);
    const bool moving = attack || family_promoted
                        || std::fabs(step) >= kLargeStepBypassCents
                        || std::fabs(trend) >= kMotionCents;
    const float alpha = moving ? kMotionAlpha : kStableAlpha;

    if(state_.tracked_frequency_hz <= 0.0f || alpha >= 1.0f)
        state_.tracked_frequency_hz = target_hz;
    else
        state_.tracked_frequency_hz *= std::pow(2.0f, alpha * step / 1200.0f);

    state_.previous_envelope = signal.envelope;
    state_.stability_bypass = moving;
    return state_.tracked_frequency_hz;
}

PitchTrackResult PitchTracker::Update(const PitchCandidate* candidates,
                                      size_t candidate_count,
                                      const SignalState& signal)
{
    bool proposed_promotion = false;
    const PitchCandidate* selected = FamilyCandidate(candidates, candidate_count,
                                                      proposed_promotion);
    const PitchCandidate* top = TopCandidate(candidates, candidate_count);

    bool confirmed_promotion = false;
    if(proposed_promotion && selected != nullptr)
    {
        if(state_.previous_promoted_frequency_hz > 0.0f
           && OctaveDistance(selected->frequency_hz,
                             state_.previous_promoted_frequency_hz)
                  < kPromotionContinuityOctaves)
        {
            ++state_.promotion_streak;
        }
        else
            state_.promotion_streak = 1;
        state_.previous_promoted_frequency_hz = selected->frequency_hz;
        confirmed_promotion = state_.promotion_streak >= kPromotionConfirmFrames;
    }
    else
    {
        state_.promotion_streak = 0;
        state_.previous_promoted_frequency_hz = 0.0f;
    }
    if(proposed_promotion && !confirmed_promotion)
        selected = top;

    const float tracked_confidence = selected == nullptr
                                         ? 0.0f
                                         : Clamp01(selected->score);
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
            state_.pre_stability_frequency_hz = selected->frequency_hz;
            state_.confidence = tracked_confidence;
            state_.has_pitch = true;
            state_.stable_frames = 1;
            state_.unstable_frames = 0;
            hold_frames_remaining_ = kPitchHoldFrames;
        }
    }
    else if(can_hold)
    {
        const float slew = confirmed_promotion ? kPromotedPitchSlew
                                               : kSustainPitchSlew;
        state_.pre_stability_frequency_hz += slew * (selected->frequency_hz
                                                      - state_.pre_stability_frequency_hz);
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

    state_.family_promoted = confirmed_promotion;
    if(state_.has_pitch)
    {
        state_.previous_frequency_hz = state_.tracked_frequency_hz;
        ApplyStability(state_.pre_stability_frequency_hz, signal,
                       confirmed_promotion);
    }
    else
        ResetStability();

    return {state_.tracked_frequency_hz,
            state_.confidence,
            state_.has_pitch,
            state_.has_pitch ? state_.pre_stability_frequency_hz : 0.0f,
            confirmed_promotion,
            state_.stability_bypass};
}

const PitchTrackerState& PitchTracker::State() const
{
    return state_;
}
} // namespace bass
