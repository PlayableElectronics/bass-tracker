#include <cassert>
#include <cmath>

#include "AnalysisTypes.h"
#include "ExpressionBus.h"
#include "ExpressionCalibration.h"
#include "ExpressionMidiProtocol.h"
#include "ModulationMatrix.h"

namespace
{
constexpr float kFrameSeconds = 128.0f / 12000.0f;

bool Near(float a, float b, float tolerance = 0.08f)
{
    return std::fabs(a - b) <= tolerance;
}

bass::ExpressionValues Raw(float gain, float shape)
{
    bass::ExpressionValues values = {};
    bass::SetExpressionValue(values, bass::ExpressionFeature::Amplitude, gain * shape);
    bass::SetExpressionValue(values, bass::ExpressionFeature::AttackStrength,
                             gain * (0.15f + 0.45f * shape));
    bass::SetExpressionValue(values, bass::ExpressionFeature::Brightness, 0.2f + 0.5f * shape);
    bass::SetExpressionValue(values, bass::ExpressionFeature::Periodicity, 0.7f + 0.2f * shape);
    bass::SetExpressionValue(values, bass::ExpressionFeature::TrackerConfidence,
                             0.65f + 0.25f * shape);
    bass::SetExpressionValue(values, bass::ExpressionFeature::CandidateCompetition,
                             0.1f + 0.6f * (1.0f - shape));
    bass::SetExpressionValue(values, bass::ExpressionFeature::OctaveTension,
                             0.15f + 0.5f * shape);
    bass::SetExpressionValue(values, bass::ExpressionFeature::NoiseTransient,
                             0.1f + 0.6f * shape);
    bass::SetExpressionValue(values, bass::ExpressionFeature::DecayRate,
                             0.1f * (1.0f - shape));
    bass::SetExpressionValue(values, bass::ExpressionFeature::PitchMotion,
                             (shape - 0.5f) * 160.0f);
    bass::SetExpressionValue(values, bass::ExpressionFeature::PitchInstability,
                             20.0f + 60.0f * (1.0f - shape));
    return values;
}

void Learn(bass::ExpressionCalibration& calibration, float gain)
{
    calibration.Start(0.30f);
    for(int i = 0; i < 30; ++i)
    {
        const float shape = 0.05f + 0.90f * static_cast<float>(i % 10) / 9.0f;
        calibration.Update(Raw(gain, shape), kFrameSeconds);
    }
    calibration.Freeze();
}
} // namespace

int main()
{
    // Expression analysis keeps uncertain candidate-family information instead
    // of dropping it after stable pitch selection.
    bass::ExpressionAnalyzer analyzer;
    analyzer.Init();
    const bass::PitchCandidate candidates[] = {
        {61.0f, 0.98f, 0}, {122.0f, 0.91f, 0}, {91.5f, 0.55f, 0},
    };
    const bass::SignalState active = {0.20f, 0.60f, true, true};
    bass::ExpressionFrame frame = analyzer.Update(1, 10, 61.0f, 61.0f, 0.93f,
                                                   true, candidates, 3, active,
                                                   0.30f, 0.24f);
    assert(bass::GetExpressionValue(frame.raw, bass::ExpressionFeature::OctaveTension) > 0.90f);
    assert(bass::GetExpressionValue(frame.raw, bass::ExpressionFeature::CandidateCompetition) > 0.90f);
    assert(bass::GetExpressionValue(frame.raw, bass::ExpressionFeature::Brightness) > 0.0f);

    bass::ExpressionCalibration calibration;
    calibration.Init();
    assert(calibration.Status().state == bass::CalibrationState::Uncalibrated);
    Learn(calibration, 1.0f);
    const bass::CalibrationStatus frozen = calibration.Status();
    assert(frozen.state == bass::CalibrationState::Frozen);
    assert(frozen.features[0].sample_count > 0);

    const bass::ExpressionValues before = calibration.Normalize(Raw(1.0f, 0.70f));
    for(int i = 0; i < 20; ++i)
        calibration.Update(Raw(10.0f, 1.0f), kFrameSeconds);
    const bass::CalibrationStatus after = calibration.Status();
    assert(Near(after.features[0].learned_high, frozen.features[0].learned_high, 0.00001f));
    for(size_t i = 0; i < bass::kExpressionFeatureCount; ++i)
    {
        const float value = before.values[i];
        assert(value >= -1.0f && value <= 1.0f);
    }

    calibration.SetManualRange(bass::ExpressionFeature::Amplitude, 0.10f, 0.30f);
    assert(calibration.Status().features[0].mode == bass::CalibrationRangeMode::Manual);
    calibration.RestoreAuto(bass::ExpressionFeature::Amplitude);
    assert(calibration.Status().features[0].mode == bass::CalibrationRangeMode::Auto);
    calibration.LockCurrentRange(bass::ExpressionFeature::Amplitude);
    assert(calibration.Status().features[0].mode == bass::CalibrationRangeMode::Locked);
    calibration.Reset();
    assert(calibration.Status().state == bass::CalibrationState::Uncalibrated);

    // Separate calibration adapts comparable gestures to changed input gain;
    // it is a test fixture, never a production input gain stage.
    bass::ExpressionCalibration unity;
    bass::ExpressionCalibration quarter;
    unity.Init();
    quarter.Init();
    Learn(unity, 1.0f);
    Learn(quarter, 0.25f);
    const bass::ExpressionValues unity_normalized = unity.Normalize(Raw(1.0f, 0.70f));
    const bass::ExpressionValues quarter_normalized = quarter.Normalize(Raw(0.25f, 0.70f));
    assert(Near(bass::GetExpressionValue(unity_normalized, bass::ExpressionFeature::Amplitude),
                bass::GetExpressionValue(quarter_normalized, bass::ExpressionFeature::Amplitude)));
    assert(Near(bass::GetExpressionValue(unity_normalized, bass::ExpressionFeature::AttackStrength),
                bass::GetExpressionValue(quarter_normalized, bass::ExpressionFeature::AttackStrength)));

    bass::ExpressionMidiProtocol midi;
    midi.Init();
    bass::ExpressionCalibration midi_calibration;
    midi_calibration.Init();
    assert(midi.HandleControlChange(15, bass::ExpressionMidiProtocol::kControlCommand, 1,
                                    midi_calibration));
    assert(midi_calibration.Status().state == bass::CalibrationState::Calibrating);
    assert(midi.HandleControlChange(15, bass::ExpressionMidiProtocol::kControlFeature, 0,
                                    midi_calibration));
    assert(midi.HandleControlChange(15, bass::ExpressionMidiProtocol::kControlManualLow, 16,
                                    midi_calibration));
    assert(midi.HandleControlChange(15, bass::ExpressionMidiProtocol::kControlManualHigh, 96,
                                    midi_calibration));
    assert(midi_calibration.Status().features[0].mode == bass::CalibrationRangeMode::Manual);
    assert(midi.HandleControlChange(15, bass::ExpressionMidiProtocol::kControlCommand, 2,
                                    midi_calibration));
    assert(midi_calibration.Status().state == bass::CalibrationState::Frozen);
    uint8_t telemetry[96] = {};
    assert(midi.BuildTelemetry(frame, midi_calibration.Status(), telemetry, sizeof(telemetry)) > 0);

    bass::ModulationMatrix matrix;
    matrix.Init();
    bass::ModulationRoute route = {};
    route.source = bass::ExpressionFeature::OctaveTension;
    route.destination = bass::ModulationDestination::ModeCoupling;
    route.amount = 0.8f;
    route.enabled = true;
    assert(matrix.SetRoute(0, route));
    frame.normalized = unity.Normalize(frame.raw);
    bass::ModulationFrame modulation = matrix.Process(frame, kFrameSeconds);
    assert(modulation.values[static_cast<size_t>(bass::ModulationDestination::ModeCoupling)] >= 0.0f);
    assert(!matrix.SetRoute(bass::kMaxModulationRoutes, route));
    return 0;
}
