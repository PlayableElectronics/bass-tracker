#pragma once

#include <cstddef>
#include <cstdint>

#include "ExpressionBus.h"
#include "ModulationMatrix.h"

namespace bass
{
// A small bank of inharmonic, mutually interacting resonant voices. It is
// deliberately a dynamical object rather than a carrier/modulator synth.
class ResynthesisEngine
{
  public:
    static constexpr size_t kModeCount = 5;

    struct BaseParameters
    {
        float excitation_amount = 0.45f;
        float upper_mode_energy = 0.20f;
        float mode_coupling = 0.06f;
        float feedback = 0.035f;
        float nonlinearity = 0.08f;
        float damping = 0.16f;
        float ratio_spread = 0.0f;
        float output_texture = 0.15f;
    };

    void Init(float sample_rate);
    void SetBaseParameters(const BaseParameters& parameters);
    bool SetModeRatio(size_t index, float ratio);
    void SetFrame(const ExpressionFrame& expression,
                  const ModulationFrame& modulation,
                  float frame_seconds);
    float Process();

    static void ConfigureDefaultRoutes(ModulationMatrix& matrix);

  private:
    struct Mode
    {
        float phase = 0.0f;
        float energy = 0.0f;
        float last_output = 0.0f;
    };

    static float Clamp(float value, float low, float high);
    void InjectExcitation(float amount, float attack, float brightness,
                          float noise, float texture);

    float sample_rate_ = 48000.0f;
    BaseParameters base_ = {};
    volatile float root_frequency_hz_ = 55.0f;
    volatile float excitation_amount_ = 0.0f;
    volatile float upper_mode_energy_ = 0.0f;
    volatile float coupling_ = 0.08f;
    volatile float feedback_ = 0.08f;
    volatile float nonlinearity_ = 0.12f;
    volatile float damping_ = 0.25f;
    volatile float ratio_spread_ = 0.0f;
    volatile float texture_ = 0.0f;
    volatile float frame_decay_ = 0.995f;
    volatile float pending_excitation_ = 0.0f;
    volatile float pending_attack_ = 0.0f;
    volatile float pending_brightness_ = 0.0f;
    volatile float pending_noise_ = 0.0f;
    volatile float pending_texture_ = 0.0f;
    uint32_t random_state_ = 0x13579bdfu;
    float mode_ratios_[kModeCount] = {};
    Mode modes_[kModeCount] = {};
};
} // namespace bass
