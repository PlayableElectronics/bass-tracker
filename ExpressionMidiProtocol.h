#pragma once

#include <cstddef>
#include <cstdint>

#include "ExpressionCalibration.h"
#include "ModulationMatrix.h"
#include "ResynthesisEngine.h"

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
    static constexpr uint8_t kControlEngineParameter = 40;
    static constexpr uint8_t kControlEngineValueMsb = 41;
    static constexpr uint8_t kControlEngineValueLsb = 42;
    static constexpr uint8_t kControlModeSelect = 43;
    static constexpr uint8_t kControlModeRatioMsb = 44;
    static constexpr uint8_t kControlModeRatioLsb = 45;
    static constexpr uint8_t kControlModeWeightMsb = 46;
    static constexpr uint8_t kControlModeWeightLsb = 47;
    static constexpr uint8_t kControlRouteSelect = 48;
    static constexpr uint8_t kControlRouteEnabled = 49;
    static constexpr uint8_t kControlRouteSource = 50;
    static constexpr uint8_t kControlRouteDestination = 51;
    static constexpr uint8_t kControlRouteAmountMsb = 52;
    static constexpr uint8_t kControlRouteAmountLsb = 53;
    static constexpr uint8_t kControlRouteCurveMsb = 54;
    static constexpr uint8_t kControlRouteCurveLsb = 55;
    static constexpr uint8_t kControlRouteSmoothingMsb = 56;
    static constexpr uint8_t kControlRouteSmoothingLsb = 57;
    static constexpr uint8_t kControlMacroSelect = 58;
    static constexpr uint8_t kControlMacroValueMsb = 59;
    static constexpr uint8_t kControlMacroValueLsb = 60;
    static constexpr uint8_t kControlUncertaintyMsb = 61;
    static constexpr uint8_t kControlUncertaintyLsb = 62;
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
    static constexpr uint8_t kTelemetryDestinationBase = 45;
    static constexpr uint8_t kTelemetryBaseParameterMsb = 92;
    static constexpr uint8_t kTelemetryBaseParameterLsb = 100;
    static constexpr uint8_t kTelemetryModeRatioMsb = 108;
    static constexpr uint8_t kTelemetryModeRatioLsb = 113;
    static constexpr uint8_t kTelemetryModeWeightMsb = 118;
    static constexpr uint8_t kTelemetryModeWeightLsb = 123;
    static constexpr uint8_t kTelemetryUncertaintyInfluence = 59;
    static constexpr uint8_t kTelemetryMacroBase = 65;

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
                             ExpressionCalibration& calibration,
                             ResynthesisEngine* engine = nullptr,
                             ModulationMatrix* matrix = nullptr);
    size_t BuildTelemetry(const ExpressionFrame& expression,
                          const CalibrationStatus& calibration,
                          uint8_t* bytes,
                          size_t capacity,
                          const ModulationFrame* modulation = nullptr,
                          const ResynthesisEngine* engine = nullptr,
                          const ModulationMatrix* matrix = nullptr) const;

  private:
    void ApplyManualRange(ExpressionCalibration& calibration);
    void ApplyRoute(ModulationMatrix* matrix);
    ExpressionFeature selected_feature_ = ExpressionFeature::Amplitude;
    uint16_t manual_low_14_ = 0;
    uint16_t manual_high_14_ = k14BitMaximum;
    uint16_t engine_value_14_ = 0;
    uint16_t mode_ratio_14_ = 0;
    uint16_t mode_weight_14_ = k14BitMaximum;
    uint16_t route_amount_14_ = 8192;
    uint16_t route_curve_14_ = 8192;
    uint16_t route_smoothing_14_ = 0;
    uint16_t uncertainty_14_ = k14BitMaximum;
    uint8_t selected_engine_parameter_ = 0;
    uint8_t selected_mode_ = 0;
    uint8_t selected_route_ = 0;
    uint8_t selected_macro_ = 0;
    ModulationRoute route_ = {};
};
} // namespace bass
