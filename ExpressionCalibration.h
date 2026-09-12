#pragma once

#include <cstdint>

#include "ExpressionBus.h"

namespace bass
{
enum class CalibrationState : uint8_t
{
    Uncalibrated = 0,
    Calibrating,
    Frozen,
};

enum class CalibrationRangeMode : uint8_t
{
    Auto = 0,
    Manual,
    Locked,
};

struct CalibrationConfig
{
    float duration_seconds = 30.0f;
    float minimum_range_fraction = 0.02f;
};

struct FeatureCalibrationStatus
{
    uint32_t sample_count = 0;
    float mean = 0.0f;
    float standard_deviation = 0.0f;
    float learned_low = 0.0f;
    float learned_high = 1.0f;
    float active_low = 0.0f;
    float active_high = 1.0f;
    CalibrationRangeMode mode = CalibrationRangeMode::Auto;
};

struct CalibrationStatus
{
    CalibrationState state = CalibrationState::Uncalibrated;
    float elapsed_seconds = 0.0f;
    float duration_seconds = 30.0f;
    FeatureCalibrationStatus features[kExpressionFeatureCount] = {};
};

class ExpressionCalibration
{
  public:
    void Init(const CalibrationConfig& config = {});
    void Start(float duration_seconds = 0.0f);
    void Freeze();
    void Reset();
    void Update(const ExpressionValues& raw, float frame_seconds);
    ExpressionValues Normalize(const ExpressionValues& raw) const;
    CalibrationStatus Status() const;

    void SetManualRange(ExpressionFeature feature, float low, float high);
    void RestoreAuto(ExpressionFeature feature);
    void LockCurrentRange(ExpressionFeature feature);
    void SetFeatureMode(ExpressionFeature feature, CalibrationRangeMode mode);
    void SetDuration(float seconds);

  private:
    struct RunningRange
    {
        uint32_t sample_count = 0;
        float mean = 0.0f;
        float m2 = 0.0f;
        float soft_low = 0.0f;
        float soft_high = 1.0f;
        float learned_low = 0.0f;
        float learned_high = 1.0f;
        float manual_low = 0.0f;
        float manual_high = 1.0f;
        float locked_low = 0.0f;
        float locked_high = 1.0f;
        CalibrationRangeMode mode = CalibrationRangeMode::Auto;
        bool initialized = false;
    };

    void UpdateRange(RunningRange& range, float value, ExpressionFeature feature);
    void FinalizeRange(RunningRange& range, ExpressionFeature feature);
    void ActiveRange(const RunningRange& range,
                     float& low,
                     float& high) const;
    float CalibrationValue(const ExpressionValues& raw, ExpressionFeature feature) const;

    CalibrationConfig config_ = {};
    CalibrationState state_ = CalibrationState::Uncalibrated;
    float elapsed_seconds_ = 0.0f;
    RunningRange ranges_[kExpressionFeatureCount] = {};
};
} // namespace bass
