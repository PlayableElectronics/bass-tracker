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
    static constexpr uint8_t kControlManualLow = 23;
    static constexpr uint8_t kControlManualHigh = 24;
    static constexpr uint8_t kControlDuration = 25;
    static constexpr uint8_t kTelemetryState = 12;
    static constexpr uint8_t kTelemetryProgress = 13;
    static constexpr uint8_t kTelemetryAmplitudeLow = 14;
    static constexpr uint8_t kTelemetryAmplitudeHigh = 15;
    static constexpr uint8_t kTelemetrySelectedLow = 16;
    static constexpr uint8_t kTelemetrySelectedHigh = 17;
    static constexpr uint8_t kTelemetryNormalizedBase = 30;
    static constexpr uint8_t kTelemetryRawBase = 50;

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
    ExpressionFeature selected_feature_ = ExpressionFeature::Amplitude;
    float manual_low_fraction_ = 0.0f;
};
} // namespace bass
