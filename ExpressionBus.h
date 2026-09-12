#pragma once

#include <cstddef>
#include <cstdint>

namespace bass
{
struct PitchCandidate;
struct SignalState;

// Pitch remains a continuous structural value. These deliberately exclude it:
// their job is to retain the physical and uncertain information around pitch.
enum class ExpressionFeature : uint8_t
{
    Amplitude = 0,
    AttackStrength,
    Brightness,
    Periodicity,
    TrackerConfidence,
    CandidateCompetition,
    OctaveTension,
    NoiseTransient,
    DecayRate,
    PitchMotion,
    PitchInstability,
    Count,
};

constexpr size_t kExpressionFeatureCount
    = static_cast<size_t>(ExpressionFeature::Count);

struct ExpressionValues
{
    float values[kExpressionFeatureCount] = {};
};

struct ExpressionFrame
{
    uint32_t sequence = 0;
    uint32_t ms = 0;
    float pitch_hz = 0.0f;
    bool pitch_valid = false;
    ExpressionValues raw = {};
    ExpressionValues normalized = {};
};

float GetExpressionValue(const ExpressionValues& values, ExpressionFeature feature);
void SetExpressionValue(ExpressionValues& values,
                        ExpressionFeature feature,
                        float value);
const char* ExpressionFeatureName(ExpressionFeature feature);
bool ExpressionFeatureIsBipolar(ExpressionFeature feature);
// A transport/UI range only. It does not affect DSP or calibration.
float ExpressionFeatureDomainMaximum(ExpressionFeature feature);

class ExpressionAnalyzer
{
  public:
    void Init();
    ExpressionFrame Update(uint32_t sequence,
                           uint32_t ms,
                           float tracked_frequency_hz,
                           float pre_stability_frequency_hz,
                           float tracker_confidence,
                           bool pitch_valid,
                           const PitchCandidate* candidates,
                           size_t candidate_count,
                           const SignalState& signal,
                           float input_rms,
                           float filtered_rms);

  private:
    float previous_envelope_ = 0.0f;
    float previous_pitch_hz_ = 0.0f;
};
} // namespace bass
