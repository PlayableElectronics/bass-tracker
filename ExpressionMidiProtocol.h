#pragma once

#include <cstddef>
#include <cstdint>

#include "ExpressionCalibration.h"

namespace bass
{
// MIDI channel 16 (zero-based channel 15) keeps control/telemetry separate
// from a musician's normal MIDI traffic. The protocol intentionally uses CCs
// only, so it is observable and controllable from plain WebMIDI.
class ExpressionMidiProtocol
{
  public:
    static constexpr uint8_t kChannel = 15;
    static constexpr uint8_t kControlCommand = 20;
    static constexpr uint8_t kControlFeature = 21;
    static constexpr uint8_t kControlRangeMode = 22;
    static constexpr uint8_t kControlManualLowMsb = 23;
    static constexpr uint8_t kControlManualHighMsb = 24;
    static constexpr uint8_t kControlDuration = 25;
    static constexpr uint8_t kControlManualLowLsb = 26;
    static constexpr uint8_t kControlManualHighLsb = 27;
    static constexpr uint8_t kTelemetryState = 12;
    static constexpr uint8_t kTelemetryProgress = 13;
    static constexpr uint8_t kTelemetryAmplitudeLowMsb = 14;
    static constexpr uint8_t kTelemetryAmplitudeHighMsb = 15;
    static constexpr uint8_t kTelemetrySelectedLowMsb = 16;
    static constexpr uint8_t kTelemetrySelectedHighMsb = 17;
    static constexpr uint8_t kTelemetryAmplitudeLowLsb = 61;
    static constexpr uint8_t kTelemetryAmplitudeHighLsb = 62;
    static constexpr uint8_t kTelemetrySelectedLowLsb = 63;
    static constexpr uint8_t kTelemetrySelectedHighLsb = 64;
    static constexpr uint8_t kTelemetryNormalizedBase = 30;
    static constexpr uint8_t kTelemetryRawMsbBase = 70;
    static constexpr uint8_t kTelemetryRawLsbBase = 81;

    static constexpr uint16_t k14BitMaximum = 16383;

    static uint16_t EncodeUnipolar14(float normalized);
    static float DecodeUnipolar14(uint16_t value);
    static uint16_t EncodeBipolar14(float normalized);
    static float DecodeBipolar14(uint16_t value);
    static uint16_t EncodeRaw14(ExpressionFeature feature, float raw);
    static float DecodeRaw14(ExpressionFeature feature, uint16_t value);

    void Init();
    bool HandleControlChange(uint8_t channel,
                             uint8_t controller,
                             uint8_t value,
                             ExpressionCalibration& calibration);
    size_t BuildTelemetry(const ExpressionFrame& expression,
                          const CalibrationStatus& calibration,
                          uint8_t* bytes,
                          size_t capacity) const;

  private:
    void ApplyManualRange(ExpressionCalibration& calibration);
    ExpressionFeature selected_feature_ = ExpressionFeature::Amplitude;
    uint16_t manual_low_14_ = 0;
    uint16_t manual_high_14_ = k14BitMaximum;
};
} // namespace bass
