#include <cmath>

#include "AnalysisTypes.h"
#include "ExpressionBus.h"

namespace bass
{
namespace
{
constexpr float kEpsilon = 1.0e-9f;
constexpr float kPitchMotionDomainCents = 600.0f;
constexpr float kPitchInstabilityDomainCents = 600.0f;

float Clamp(float value, float low, float high)
{
    return value < low ? low : (value > high ? high : value);
}

float Clamp01(float value)
{
    return Clamp(value, 0.0f, 1.0f);
}

float Cents(float a, float b)
{
    return a > 0.0f && b > 0.0f ? 1200.0f * std::log2(a / b) : 0.0f;
}

int RelatedMultiple(float high, float low)
{
    if(low <= 0.0f || high <= low)
        return 0;
    const float ratio = high / low;
    if(std::fabs(ratio - 2.0f) / 2.0f <= 0.055f)
        return 2;
    if(std::fabs(ratio - 3.0f) / 3.0f <= 0.055f)
        return 3;
    return 0;
}

float OctaveTension(const PitchCandidate* candidates, size_t candidate_count)
{
    if(candidates == nullptr || candidate_count < 2 || candidates[0].score <= 0.0f)
        return 0.0f;

    const float top_score = candidates[0].score;
    float tension = 0.0f;
    for(size_t high = 0; high < candidate_count; ++high)
    {
        for(size_t low = 0; low < candidate_count; ++low)
        {
            if(RelatedMultiple(candidates[high].frequency_hz,
                               candidates[low].frequency_hz)
               == 0)
                continue;
            const float competing = candidates[high].score < candidates[low].score
                                        ? candidates[high].score
                                        : candidates[low].score;
            tension = tension > competing / top_score ? tension
                                                       : competing / top_score;
        }
    }
    return Clamp01(tension);
}
} // namespace

float GetExpressionValue(const ExpressionValues& values, ExpressionFeature feature)
{
    return values.values[static_cast<size_t>(feature)];
}

void SetExpressionValue(ExpressionValues& values,
                        ExpressionFeature feature,
                        float value)
{
    values.values[static_cast<size_t>(feature)] = value;
}

const char* ExpressionFeatureName(ExpressionFeature feature)
{
    static constexpr const char* kNames[] = {
        "amplitude", "attack_strength", "brightness", "periodicity",
        "tracker_confidence", "candidate_competition", "octave_tension",
        "noise_transient", "decay_rate", "pitch_motion", "pitch_instability",
    };
    const size_t index = static_cast<size_t>(feature);
    return index < kExpressionFeatureCount ? kNames[index] : "unknown";
}

bool ExpressionFeatureIsBipolar(ExpressionFeature feature)
{
    return feature == ExpressionFeature::PitchMotion;
}

float ExpressionFeatureDomainMaximum(ExpressionFeature feature)
{
    switch(feature)
    {
        case ExpressionFeature::PitchMotion: return kPitchMotionDomainCents;
        case ExpressionFeature::PitchInstability: return kPitchInstabilityDomainCents;
        default: return 1.0f;
    }
}

void ExpressionAnalyzer::Init()
{
    previous_envelope_ = 0.0f;
    previous_pitch_hz_ = 0.0f;
}

ExpressionFrame ExpressionAnalyzer::Update(uint32_t sequence,
                                           uint32_t ms,
                                           float tracked_frequency_hz,
                                           float pre_stability_frequency_hz,
                                           float tracker_confidence,
                                           bool pitch_valid,
                                           const PitchCandidate* candidates,
                                           size_t candidate_count,
                                           const SignalState& signal,
                                           float input_rms,
                                           float filtered_rms)
{
    ExpressionFrame frame = {};
    frame.sequence = sequence;
    frame.ms = ms;
    frame.pitch_hz = pitch_valid ? tracked_frequency_hz : 0.0f;
    frame.pitch_valid = pitch_valid;

    const float top_score = candidate_count > 0 ? Clamp01(candidates[0].score) : 0.0f;
    const float second_score = candidate_count > 1 ? Clamp01(candidates[1].score) : 0.0f;
    const float filtered_energy = filtered_rms * filtered_rms;
    const float input_energy = input_rms * input_rms;
    const float residual_energy = input_energy > filtered_energy
                                      ? input_energy - filtered_energy : 0.0f;
    const float brightness = input_rms > kEpsilon
                                 ? std::sqrt(residual_energy) / input_rms : 0.0f;
    const float decay = previous_envelope_ > kEpsilon && signal.envelope < previous_envelope_
                            ? (previous_envelope_ - signal.envelope) / previous_envelope_
                            : 0.0f;
    const float motion = pitch_valid && previous_pitch_hz_ > 0.0f
                             ? Clamp(Cents(tracked_frequency_hz, previous_pitch_hz_),
                                     -kPitchMotionDomainCents, kPitchMotionDomainCents)
                             : 0.0f;
    const float instability = pitch_valid && pre_stability_frequency_hz > 0.0f
                                  ? Clamp(std::fabs(Cents(pre_stability_frequency_hz,
                                                          tracked_frequency_hz)),
                                          0.0f, kPitchInstabilityDomainCents)
                                  : 0.0f;

    SetExpressionValue(frame.raw, ExpressionFeature::Amplitude, signal.envelope);
    SetExpressionValue(frame.raw, ExpressionFeature::AttackStrength, signal.attack);
    SetExpressionValue(frame.raw, ExpressionFeature::Brightness, Clamp01(brightness));
    SetExpressionValue(frame.raw, ExpressionFeature::Periodicity, top_score);
    SetExpressionValue(frame.raw, ExpressionFeature::TrackerConfidence,
                       Clamp01(tracker_confidence));
    SetExpressionValue(frame.raw, ExpressionFeature::CandidateCompetition,
                       top_score > kEpsilon ? Clamp01(second_score / top_score) : 0.0f);
    SetExpressionValue(frame.raw, ExpressionFeature::OctaveTension,
                       OctaveTension(candidates, candidate_count));
    SetExpressionValue(frame.raw, ExpressionFeature::NoiseTransient,
                       Clamp01((1.0f - top_score) * Clamp01(brightness) + signal.attack));
    SetExpressionValue(frame.raw, ExpressionFeature::DecayRate, Clamp01(decay));
    SetExpressionValue(frame.raw, ExpressionFeature::PitchMotion, motion);
    SetExpressionValue(frame.raw, ExpressionFeature::PitchInstability, instability);

    previous_envelope_ = signal.envelope;
    previous_pitch_hz_ = pitch_valid ? tracked_frequency_hz : 0.0f;
    return frame;
}
} // namespace bass
