#include <cmath>

#include "ExpressionCalibration.h"

namespace bass
{
namespace
{
constexpr float kFastOuterRate = 0.05f;
constexpr float kSlowInnerRate = 0.001f;
constexpr uint32_t kOutlierProtectionSamples = 24;

float Clamp(float value, float low, float high)
{
    return value < low ? low : (value > high ? high : value);
}

float MinimumSpan(ExpressionFeature feature, float fraction, float reference)
{
    // Audio amplitude and attack have no dependable absolute hardware scale.
    // Their minimum useful span must follow the learned signal magnitude, not
    // a 0..1 codec-domain constant. Bounded score-like features retain a
    // sensible domain-relative floor.
    if(feature == ExpressionFeature::Amplitude
       || feature == ExpressionFeature::AttackStrength)
    {
        const float scale = std::fabs(reference) > 1.0e-7f
                                ? std::fabs(reference) : 1.0e-7f;
        return scale * fraction;
    }
    return ExpressionFeatureDomainMaximum(feature) * fraction;
}
} // namespace

void ExpressionCalibration::Init(const CalibrationConfig& config)
{
    config_ = config;
    Reset();
}

void ExpressionCalibration::Start(float duration_seconds)
{
    const float duration = duration_seconds > 0.0f ? duration_seconds
                                                    : config_.duration_seconds;
    Reset();
    config_.duration_seconds = duration > 0.0f ? duration : 30.0f;
    state_ = CalibrationState::Calibrating;
}

void ExpressionCalibration::Freeze()
{
    if(state_ != CalibrationState::Calibrating)
        return;
    for(size_t i = 0; i < kExpressionFeatureCount; ++i)
        FinalizeRange(ranges_[i], static_cast<ExpressionFeature>(i));
    state_ = CalibrationState::Frozen;
}

void ExpressionCalibration::Reset()
{
    elapsed_seconds_ = 0.0f;
    state_ = CalibrationState::Uncalibrated;
    for(size_t i = 0; i < kExpressionFeatureCount; ++i)
    {
        const ExpressionFeature feature = static_cast<ExpressionFeature>(i);
        const float maximum = ExpressionFeatureDomainMaximum(feature);
        ranges_[i] = {};
        ranges_[i].soft_high = maximum;
        ranges_[i].learned_high = maximum;
        ranges_[i].manual_high = maximum;
        ranges_[i].locked_high = maximum;
    }
}

float ExpressionCalibration::CalibrationValue(const ExpressionValues& raw,
                                              ExpressionFeature feature) const
{
    const float value = GetExpressionValue(raw, feature);
    return ExpressionFeatureIsBipolar(feature) ? std::fabs(value) : value;
}

void ExpressionCalibration::UpdateRange(RunningRange& range,
                                        float value,
                                        ExpressionFeature feature)
{
    const float maximum = ExpressionFeatureDomainMaximum(feature);
    value = Clamp(value, 0.0f, maximum);
    if(!range.initialized)
    {
        range.initialized = true;
        range.sample_count = 1;
        range.mean = value;
        range.soft_low = value;
        range.soft_high = value;
        return;
    }

    float accepted = value;
    if(range.sample_count >= kOutlierProtectionSamples)
    {
        const float variance = range.sample_count > 1
                                   ? range.m2 / static_cast<float>(range.sample_count - 1)
                                   : 0.0f;
        const float deviation = std::sqrt(variance > 0.0f ? variance : 0.0f);
        const float guard = deviation > 0.0f ? 4.0f * deviation
                                              : MinimumSpan(feature, config_.minimum_range_fraction,
                                                            range.mean);
        accepted = Clamp(value, range.mean - guard, range.mean + guard);
    }
    ++range.sample_count;
    const float delta = accepted - range.mean;
    range.mean += delta / static_cast<float>(range.sample_count);
    range.m2 += delta * (accepted - range.mean);

    const float low_rate = accepted < range.soft_low ? kFastOuterRate : kSlowInnerRate;
    const float high_rate = accepted > range.soft_high ? kFastOuterRate : kSlowInnerRate;
    range.soft_low += low_rate * (accepted - range.soft_low);
    range.soft_high += high_rate * (accepted - range.soft_high);
}

void ExpressionCalibration::FinalizeRange(RunningRange& range,
                                          ExpressionFeature feature)
{
    const float maximum = ExpressionFeatureDomainMaximum(feature);
    const float reference = std::fabs(range.mean) > std::fabs(range.soft_high)
                                ? range.mean : range.soft_high;
    const float minimum_span = MinimumSpan(feature, config_.minimum_range_fraction,
                                           reference);
    if(!range.initialized)
    {
        range.learned_low = 0.0f;
        range.learned_high = maximum;
        return;
    }

    float low = Clamp(range.soft_low, 0.0f, maximum);
    float high = Clamp(range.soft_high, 0.0f, maximum);
    if(high - low < minimum_span)
    {
        const float midpoint = 0.5f * (low + high);
        low = Clamp(midpoint - 0.5f * minimum_span, 0.0f, maximum);
        high = Clamp(low + minimum_span, 0.0f, maximum);
        low = Clamp(high - minimum_span, 0.0f, maximum);
    }
    range.learned_low = low;
    range.learned_high = high;
}

void ExpressionCalibration::Update(const ExpressionValues& raw, float frame_seconds)
{
    if(state_ != CalibrationState::Calibrating)
        return;
    for(size_t i = 0; i < kExpressionFeatureCount; ++i)
        UpdateRange(ranges_[i], CalibrationValue(raw, static_cast<ExpressionFeature>(i)),
                    static_cast<ExpressionFeature>(i));
    elapsed_seconds_ += frame_seconds;
    if(elapsed_seconds_ >= config_.duration_seconds)
        Freeze();
}

void ExpressionCalibration::ActiveRange(const RunningRange& range,
                                        float& low,
                                        float& high) const
{
    switch(range.mode)
    {
        case CalibrationRangeMode::Manual:
            low = range.manual_low;
            high = range.manual_high;
            return;
        case CalibrationRangeMode::Locked:
            low = range.locked_low;
            high = range.locked_high;
            return;
        case CalibrationRangeMode::Auto:
        default:
            low = range.learned_low;
            high = range.learned_high;
            return;
    }
}

ExpressionValues ExpressionCalibration::Normalize(const ExpressionValues& raw) const
{
    ExpressionValues normalized = {};
    for(size_t i = 0; i < kExpressionFeatureCount; ++i)
    {
        const ExpressionFeature feature = static_cast<ExpressionFeature>(i);
        float low = 0.0f;
        float high = ExpressionFeatureDomainMaximum(feature);
        ActiveRange(ranges_[i], low, high);
        const float span = high > low ? high - low : 1.0f;
        const float value = CalibrationValue(raw, feature);
        float output = Clamp((value - low) / span, 0.0f, 1.0f);
        if(ExpressionFeatureIsBipolar(feature) && GetExpressionValue(raw, feature) < 0.0f)
            output = -output;
        SetExpressionValue(normalized, feature, output);
    }
    return normalized;
}

CalibrationStatus ExpressionCalibration::Status() const
{
    CalibrationStatus status = {};
    status.state = state_;
    status.elapsed_seconds = elapsed_seconds_;
    status.duration_seconds = config_.duration_seconds;
    for(size_t i = 0; i < kExpressionFeatureCount; ++i)
    {
        const RunningRange& range = ranges_[i];
        FeatureCalibrationStatus& feature = status.features[i];
        feature.sample_count = range.sample_count;
        feature.mean = range.mean;
        feature.standard_deviation = range.sample_count > 1
                                       ? std::sqrt(range.m2 / static_cast<float>(range.sample_count - 1))
                                       : 0.0f;
        feature.learned_low = range.learned_low;
        feature.learned_high = range.learned_high;
        ActiveRange(range, feature.active_low, feature.active_high);
        feature.mode = range.mode;
    }
    return status;
}

void ExpressionCalibration::SetManualRange(ExpressionFeature feature, float low, float high)
{
    RunningRange& range = ranges_[static_cast<size_t>(feature)];
    const float maximum = ExpressionFeatureDomainMaximum(feature);
    low = Clamp(low, 0.0f, maximum);
    high = Clamp(high, 0.0f, maximum);
    const float span = MinimumSpan(feature, config_.minimum_range_fraction,
                                   std::fabs(low) > std::fabs(high) ? low : high);
    if(high - low < span)
        high = Clamp(low + span, 0.0f, maximum);
    range.manual_low = low;
    range.manual_high = high;
    range.mode = CalibrationRangeMode::Manual;
}

void ExpressionCalibration::RestoreAuto(ExpressionFeature feature)
{
    ranges_[static_cast<size_t>(feature)].mode = CalibrationRangeMode::Auto;
}

void ExpressionCalibration::LockCurrentRange(ExpressionFeature feature)
{
    RunningRange& range = ranges_[static_cast<size_t>(feature)];
    ActiveRange(range, range.locked_low, range.locked_high);
    range.mode = CalibrationRangeMode::Locked;
}

void ExpressionCalibration::SetFeatureMode(ExpressionFeature feature,
                                           CalibrationRangeMode mode)
{
    if(mode == CalibrationRangeMode::Locked)
        LockCurrentRange(feature);
    else
        ranges_[static_cast<size_t>(feature)].mode = mode;
}

void ExpressionCalibration::SetDuration(float seconds)
{
    if(seconds > 0.0f)
        config_.duration_seconds = seconds;
}
} // namespace bass
