#include <cmath>

#include "AnalysisConfig.h"
#include "EnvelopeFollower.h"

namespace bass
{
namespace
{
constexpr float kEnvelopeAttackSeconds = 0.0015f;
constexpr float kEnvelopeReleaseSeconds = 0.080f;
constexpr float kAttackDecaySeconds = 0.030f;
constexpr float kAttackSlopeGain = 250.0f;
constexpr float kOnsetThreshold = 0.18f;
constexpr float kOnsetRearmThreshold = 0.08f;
constexpr float kGateReleaseSeconds = 0.015f;
constexpr float kOnsetRearmSeconds = 0.040f;

float Coefficient(float seconds, float sample_rate)
{
    return 1.0f - std::exp(-1.0f / (seconds * sample_rate));
}

float Clamp01(float value)
{
    return value < 0.0f ? 0.0f : (value > 1.0f ? 1.0f : value);
}
} // namespace

void EnvelopeFollower::Init(float sample_rate)
{
    envelope_ = 0.0f;
    previous_envelope_ = 0.0f;
    attack_ = 0.0f;
    gate_release_samples_ = 0;
    onset_rearm_samples_ = 0;
    gate_release_limit_ = static_cast<uint32_t>(kGateReleaseSeconds * sample_rate);
    onset_rearm_limit_ = static_cast<uint32_t>(kOnsetRearmSeconds * sample_rate);
    gate_ = false;
    onset_latched_ = false;
    onset_armed_ = true;
    attack_coefficient_ = Coefficient(kEnvelopeAttackSeconds, sample_rate);
    release_coefficient_ = Coefficient(kEnvelopeReleaseSeconds, sample_rate);
    attack_decay_coefficient_ = std::exp(-1.0f / (kAttackDecaySeconds * sample_rate));
}

void EnvelopeFollower::Process(float sample)
{
    const float magnitude = std::fabs(sample);
    const float coefficient = magnitude > envelope_ ? attack_coefficient_
                                                     : release_coefficient_;
    previous_envelope_ = envelope_;
    envelope_ += coefficient * (magnitude - envelope_);

    const float positive_slope = envelope_ - previous_envelope_;
    const float scaled_slope = Clamp01(positive_slope * kAttackSlopeGain);
    attack_ *= attack_decay_coefficient_;
    if(scaled_slope > attack_)
        attack_ = scaled_slope;

    if(!gate_ && envelope_ >= kGateOnThreshold)
    {
        gate_ = true;
        gate_release_samples_ = 0;
    }
    else if(gate_ && envelope_ <= kGateOffThreshold)
    {
        ++gate_release_samples_;
        if(gate_release_samples_ >= gate_release_limit_)
            gate_ = false;
    }
    else
    {
        gate_release_samples_ = 0;
    }

    if(onset_rearm_samples_ > 0)
        --onset_rearm_samples_;
    if(!onset_armed_ && attack_ <= kOnsetRearmThreshold && onset_rearm_samples_ == 0)
        onset_armed_ = true;

    if(onset_armed_ && attack_ >= kOnsetThreshold
       && envelope_ >= kOnsetMinimumEnvelope)
    {
        onset_latched_ = true;
        onset_armed_ = false;
        onset_rearm_samples_ = onset_rearm_limit_;
    }
}

SignalState EnvelopeFollower::ConsumeState()
{
    SignalState result = {envelope_, attack_, gate_, onset_latched_};
    onset_latched_ = false;
    return result;
}
} // namespace bass
