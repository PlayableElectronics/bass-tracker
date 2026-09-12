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

uint8_t NormalizedToMidi(ExpressionFeature feature, float normalized)
{
    return ExpressionFeatureIsBipolar(feature)
               ? ToMidi(0.5f + 0.5f * normalized)
               : ToMidi(normalized);
}

float FromMidi(uint8_t value)
{
    return static_cast<float>(value) / 127.0f;
}

uint16_t Clamp14(int value)
{
    return static_cast<uint16_t>(value < 0 ? 0 : (value > 16383 ? 16383 : value));
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

void AppendCc14(uint8_t* bytes, size_t capacity, size_t& used,
                uint8_t msb_controller, uint8_t lsb_controller, uint16_t value)
{
    AppendCc(bytes, capacity, used, msb_controller,
             static_cast<uint8_t>(value >> 7));
    AppendCc(bytes, capacity, used, lsb_controller,
             static_cast<uint8_t>(value & 0x7f));
}
} // namespace

uint16_t ExpressionMidiProtocol::EncodeUnipolar14(float normalized)
{
    const float value = normalized < 0.0f ? 0.0f : (normalized > 1.0f ? 1.0f : normalized);
    return Clamp14(static_cast<int>(value * 16383.0f + 0.5f));
}

float ExpressionMidiProtocol::DecodeUnipolar14(uint16_t value)
{
    return static_cast<float>(value > k14BitMaximum ? k14BitMaximum : value)
           / static_cast<float>(k14BitMaximum);
}

uint16_t ExpressionMidiProtocol::EncodeBipolar14(float normalized)
{
    const float value = normalized < -1.0f ? -1.0f : (normalized > 1.0f ? 1.0f : normalized);
    return EncodeUnipolar14(0.5f + 0.5f * value);
}

float ExpressionMidiProtocol::DecodeBipolar14(uint16_t value)
{
    return DecodeUnipolar14(value) * 2.0f - 1.0f;
}

uint16_t ExpressionMidiProtocol::EncodeRaw14(ExpressionFeature feature, float raw)
{
    const float maximum = ExpressionFeatureDomainMaximum(feature);
    if(maximum <= 0.0f)
        return 0;
    return ExpressionFeatureIsBipolar(feature)
               ? EncodeBipolar14(raw / maximum)
               : EncodeUnipolar14(raw / maximum);
}

float ExpressionMidiProtocol::DecodeRaw14(ExpressionFeature feature, uint16_t value)
{
    const float maximum = ExpressionFeatureDomainMaximum(feature);
    return (ExpressionFeatureIsBipolar(feature) ? DecodeBipolar14(value)
                                                  : DecodeUnipolar14(value)) * maximum;
}

void ExpressionMidiProtocol::Init()
{
    selected_feature_ = ExpressionFeature::Amplitude;
    manual_low_14_ = 0;
    manual_high_14_ = k14BitMaximum;
}

void ExpressionMidiProtocol::ApplyManualRange(ExpressionCalibration& calibration)
{
    const float maximum = ExpressionFeatureDomainMaximum(selected_feature_);
    calibration.SetManualRange(selected_feature_,
                               DecodeUnipolar14(manual_low_14_) * maximum,
                               DecodeUnipolar14(manual_high_14_) * maximum);
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
        case kControlManualLowMsb:
            manual_low_14_ = static_cast<uint16_t>((value << 7) | (manual_low_14_ & 0x7f));
            return true;
        case kControlManualLowLsb:
            manual_low_14_ = static_cast<uint16_t>((manual_low_14_ & 0x3f80) | value);
            return true;
        case kControlManualHighMsb:
            manual_high_14_ = static_cast<uint16_t>((value << 7) | (manual_high_14_ & 0x7f));
            ApplyManualRange(calibration);
            return true;
        case kControlManualHighLsb:
            manual_high_14_ = static_cast<uint16_t>((manual_high_14_ & 0x3f80) | value);
            ApplyManualRange(calibration);
            return true;
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
    AppendCc14(bytes, capacity, used, kTelemetryAmplitudeLowMsb,
                kTelemetryAmplitudeLowLsb,
                EncodeUnipolar14(amplitude.learned_low
                                 / ExpressionFeatureDomainMaximum(ExpressionFeature::Amplitude)));
    AppendCc14(bytes, capacity, used, kTelemetryAmplitudeHighMsb,
                kTelemetryAmplitudeHighLsb,
                EncodeUnipolar14(amplitude.learned_high
                                 / ExpressionFeatureDomainMaximum(ExpressionFeature::Amplitude)));
    const FeatureCalibrationStatus& selected = calibration.features[
        static_cast<size_t>(selected_feature_)];
    AppendCc14(bytes, capacity, used, kTelemetrySelectedLowMsb,
                kTelemetrySelectedLowLsb, EncodeUnipolar14(
                    selected.learned_low / ExpressionFeatureDomainMaximum(selected_feature_)));
    AppendCc14(bytes, capacity, used, kTelemetrySelectedHighMsb,
                kTelemetrySelectedHighLsb, EncodeUnipolar14(
                    selected.learned_high / ExpressionFeatureDomainMaximum(selected_feature_)));
    for(size_t i = 0; i < kExpressionFeatureCount; ++i)
    {
        const ExpressionFeature feature = static_cast<ExpressionFeature>(i);
        AppendCc(bytes, capacity, used, kTelemetryNormalizedBase + i,
                 NormalizedToMidi(feature, GetExpressionValue(expression.normalized, feature)));
        AppendCc14(bytes, capacity, used, kTelemetryRawMsbBase + i,
                   kTelemetryRawLsbBase + i,
                   EncodeRaw14(feature, GetExpressionValue(expression.raw, feature)));
    }
    return used;
}
} // namespace bass
