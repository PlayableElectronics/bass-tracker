#include "ExpressionMidiProtocol.h"

namespace bass
{
namespace
{
constexpr uint8_t kControlChangeStatus = 0xB0 | ExpressionMidiProtocol::kChannel;

uint8_t ToMidi(float normalized)
{
    if(normalized <= 0.0f)
        return 0;
    if(normalized >= 1.0f)
        return 127;
    return static_cast<uint8_t>(normalized * 127.0f + 0.5f);
}

float FromMidi(uint8_t value)
{
    return static_cast<float>(value) / 127.0f;
}

uint8_t RawToMidi(ExpressionFeature feature, float raw)
{
    const float maximum = ExpressionFeatureDomainMaximum(feature);
    if(ExpressionFeatureIsBipolar(feature))
        return ToMidi(0.5f + 0.5f * raw / maximum);
    return ToMidi(raw / maximum);
}

void AppendCc(uint8_t* bytes, size_t capacity, size_t& used,
              uint8_t controller, uint8_t value)
{
    if(used + 3 > capacity)
        return;
    bytes[used++] = kControlChangeStatus;
    bytes[used++] = controller;
    bytes[used++] = value;
}
} // namespace

void ExpressionMidiProtocol::Init()
{
    selected_feature_ = ExpressionFeature::Amplitude;
    manual_low_fraction_ = 0.0f;
}

bool ExpressionMidiProtocol::HandleControlChange(uint8_t channel,
                                                  uint8_t controller,
                                                  uint8_t value,
                                                  ExpressionCalibration& calibration)
{
    if(channel != kChannel)
        return false;
    switch(controller)
    {
        case kControlCommand:
            if(value == 1)
                calibration.Start();
            else if(value == 2)
                calibration.Freeze();
            else if(value == 3)
                calibration.Reset();
            else
                return false;
            return true;
        case kControlFeature:
            selected_feature_ = static_cast<ExpressionFeature>(
                value < kExpressionFeatureCount ? value : kExpressionFeatureCount - 1);
            return true;
        case kControlRangeMode:
            if(value == 0)
                calibration.RestoreAuto(selected_feature_);
            else if(value == 1)
                calibration.SetFeatureMode(selected_feature_, CalibrationRangeMode::Manual);
            else if(value == 2)
                calibration.LockCurrentRange(selected_feature_);
            else
                return false;
            return true;
        case kControlManualLow:
            manual_low_fraction_ = FromMidi(value);
            return true;
        case kControlManualHigh:
        {
            const float maximum = ExpressionFeatureDomainMaximum(selected_feature_);
            calibration.SetManualRange(selected_feature_, manual_low_fraction_ * maximum,
                                       FromMidi(value) * maximum);
            return true;
        }
        case kControlDuration:
            calibration.SetDuration(1.0f + FromMidi(value) * 119.0f);
            return true;
        default: return false;
    }
}

size_t ExpressionMidiProtocol::BuildTelemetry(const ExpressionFrame& expression,
                                               const CalibrationStatus& calibration,
                                               uint8_t* bytes,
                                               size_t capacity) const
{
    size_t used = 0;
    AppendCc(bytes, capacity, used, kTelemetryState,
             static_cast<uint8_t>(calibration.state));
    const float progress = calibration.duration_seconds > 0.0f
                               ? calibration.elapsed_seconds / calibration.duration_seconds
                               : 0.0f;
    AppendCc(bytes, capacity, used, kTelemetryProgress, ToMidi(progress));
    const FeatureCalibrationStatus& amplitude = calibration.features[
        static_cast<size_t>(ExpressionFeature::Amplitude)];
    AppendCc(bytes, capacity, used, kTelemetryAmplitudeLow,
             RawToMidi(ExpressionFeature::Amplitude, amplitude.learned_low));
    AppendCc(bytes, capacity, used, kTelemetryAmplitudeHigh,
             RawToMidi(ExpressionFeature::Amplitude, amplitude.learned_high));
    const FeatureCalibrationStatus& selected = calibration.features[
        static_cast<size_t>(selected_feature_)];
    AppendCc(bytes, capacity, used, kTelemetrySelectedLow,
             RawToMidi(selected_feature_, selected.learned_low));
    AppendCc(bytes, capacity, used, kTelemetrySelectedHigh,
             RawToMidi(selected_feature_, selected.learned_high));
    for(size_t i = 0; i < kExpressionFeatureCount; ++i)
    {
        const ExpressionFeature feature = static_cast<ExpressionFeature>(i);
        AppendCc(bytes, capacity, used, kTelemetryNormalizedBase + i,
                 ToMidi(GetExpressionValue(expression.normalized, feature)));
        AppendCc(bytes, capacity, used, kTelemetryRawBase + i,
                 RawToMidi(feature, GetExpressionValue(expression.raw, feature)));
    }
    return used;
}
} // namespace bass
