#include <cmath>

#include "ResynthesisEngine.h"

namespace bass
{
namespace
{
constexpr float kPi = 3.14159265358979323846f;
constexpr float kRatios[ResynthesisEngine::kModeCount] = {
    1.0f, 1.37f, 1.93f, 2.71f, 3.89f,
};
constexpr float kModeWeights[ResynthesisEngine::kModeCount] = {
    0.58f, 0.30f, 0.22f, 0.16f, 0.11f,
};

float Feature(const ExpressionFrame& frame, ExpressionFeature feature)
{
    return GetExpressionValue(frame.normalized, feature);
}

float Clamp01(float value)
{
    return value < 0.0f ? 0.0f : (value > 1.0f ? 1.0f : value);
}
} // namespace

float ResynthesisEngine::Clamp(float value, float low, float high)
{
    return value < low ? low : (value > high ? high : value);
}

void ResynthesisEngine::Init(float sample_rate)
{
    sample_rate_ = sample_rate > 1000.0f ? sample_rate : 48000.0f;
    base_ = {};
    root_frequency_hz_ = 55.0f;
    excitation_amount_ = 0.0f;
    upper_mode_energy_ = 0.0f;
    coupling_ = 0.08f;
    feedback_ = 0.08f;
    nonlinearity_ = 0.12f;
    damping_ = 0.25f;
    ratio_spread_ = 0.0f;
    texture_ = 0.0f;
    frame_decay_ = 0.995f;
    pending_excitation_ = 0.0f;
    pending_attack_ = 0.0f;
    pending_brightness_ = 0.0f;
    pending_noise_ = 0.0f;
    pending_texture_ = 0.0f;
    harmonicity_ = 0.0f;
    attack_body_ = 0.0f;
    random_state_ = 0x13579bdfu;
    for(size_t i = 0; i < kModeCount; ++i)
    {
        mode_ratios_[i] = kRatios[i];
        mode_weights_[i] = kModeWeights[i];
        modes_[i] = {};
    }
    for(size_t i = 0; i < kMacroCount; ++i)
        macros_[i] = 0.0f;
}

void ResynthesisEngine::SetBaseParameters(const BaseParameters& parameters)
{
    base_.excitation_amount = Clamp(parameters.excitation_amount, 0.0f, 1.0f);
    base_.upper_mode_energy = Clamp(parameters.upper_mode_energy, 0.0f, 1.0f);
    base_.mode_coupling = Clamp(parameters.mode_coupling, 0.0f, 0.42f);
    base_.feedback = Clamp(parameters.feedback, 0.0f, 0.22f);
    base_.nonlinearity = Clamp(parameters.nonlinearity, 0.0f, 0.42f);
    base_.damping = Clamp(parameters.damping, 0.04f, 0.70f);
    base_.ratio_spread = Clamp(parameters.ratio_spread, -0.10f, 0.10f);
    base_.output_texture = Clamp(parameters.output_texture, 0.0f, 1.0f);
}

const ResynthesisEngine::BaseParameters& ResynthesisEngine::GetBaseParameters() const
{
    return base_;
}

bool ResynthesisEngine::SetBaseParameterNormalized(size_t index, float normalized)
{
    if(index >= kBaseParameterCount)
        return false;
    const float value = Clamp(normalized, 0.0f, 1.0f);
    switch(index)
    {
        case 0: base_.excitation_amount = value; break;
        case 1: base_.upper_mode_energy = value; break;
        case 2: base_.mode_coupling = value * 0.42f; break;
        case 3: base_.feedback = value * 0.22f; break;
        case 4: base_.nonlinearity = value * 0.42f; break;
        case 5: base_.damping = 0.04f + value * 0.66f; break;
        case 6: base_.ratio_spread = -0.10f + value * 0.20f; break;
        case 7: base_.output_texture = value; break;
        default: return false;
    }
    return true;
}

float ResynthesisEngine::GetBaseParameterNormalized(size_t index) const
{
    if(index >= kBaseParameterCount)
        return 0.0f;
    switch(index)
    {
        case 0: return base_.excitation_amount;
        case 1: return base_.upper_mode_energy;
        case 2: return base_.mode_coupling / 0.42f;
        case 3: return base_.feedback / 0.22f;
        case 4: return base_.nonlinearity / 0.42f;
        case 5: return (base_.damping - 0.04f) / 0.66f;
        case 6: return (base_.ratio_spread + 0.10f) / 0.20f;
        case 7: return base_.output_texture;
        default: return 0.0f;
    }
}

bool ResynthesisEngine::SetModeRatio(size_t index, float ratio)
{
    if(index >= kModeCount || ratio < 0.5f || ratio > 5.0f)
        return false;
    mode_ratios_[index] = ratio;
    return true;
}

float ResynthesisEngine::GetModeRatio(size_t index) const
{
    return index < kModeCount ? mode_ratios_[index] : 0.0f;
}

bool ResynthesisEngine::SetModeWeight(size_t index, float weight)
{
    if(index >= kModeCount || weight < 0.0f || weight > 1.0f)
        return false;
    mode_weights_[index] = weight;
    return true;
}

float ResynthesisEngine::GetModeWeight(size_t index) const
{
    return index < kModeCount ? mode_weights_[index] : 0.0f;
}

bool ResynthesisEngine::SetMacro(Macro macro, float value)
{
    const size_t index = static_cast<size_t>(macro);
    if(index >= kMacroCount)
        return false;
    macros_[index] = Clamp(value, 0.0f, 1.0f);
    return true;
}

float ResynthesisEngine::GetMacro(Macro macro) const
{
    const size_t index = static_cast<size_t>(macro);
    return index < kMacroCount ? macros_[index] : 0.0f;
}

void ResynthesisEngine::ConfigureDefaultRoutes(ModulationMatrix& matrix)
{
    ModulationRoute route = {};
    route.enabled = true;
    route.smoothing_seconds = 0.015f;

    route.source = ExpressionFeature::Amplitude;
    route.destination = ModulationDestination::ExcitationAmount;
    route.amount = 0.85f;
    matrix.SetRoute(0, route);

    route.source = ExpressionFeature::AttackStrength;
    route.destination = ModulationDestination::ExcitationComplexity;
    route.amount = 0.90f;
    route.smoothing_seconds = 0.0f;
    matrix.SetRoute(1, route);

    route.source = ExpressionFeature::Brightness;
    route.destination = ModulationDestination::UpperModeEnergy;
    route.amount = 0.80f;
    route.smoothing_seconds = 0.025f;
    matrix.SetRoute(2, route);

    route.source = ExpressionFeature::CandidateCompetition;
    route.destination = ModulationDestination::InstabilityInteraction;
    route.amount = 0.75f;
    route.smoothing_seconds = 0.040f;
    matrix.SetRoute(3, route);

    route.source = ExpressionFeature::OctaveTension;
    route.destination = ModulationDestination::ModeCoupling;
    route.amount = 0.80f;
    route.smoothing_seconds = 0.030f;
    matrix.SetRoute(4, route);

    route.source = ExpressionFeature::NoiseTransient;
    route.destination = ModulationDestination::StochasticExcitation;
    route.amount = 0.65f;
    route.smoothing_seconds = 0.020f;
    matrix.SetRoute(5, route);

    route.source = ExpressionFeature::PitchInstability;
    route.destination = ModulationDestination::RatioSpread;
    route.amount = 0.35f;
    route.smoothing_seconds = 0.030f;
    matrix.SetRoute(6, route);

    route.source = ExpressionFeature::DecayRate;
    route.destination = ModulationDestination::Damping;
    route.amount = 0.70f;
    route.smoothing_seconds = 0.050f;
    matrix.SetRoute(7, route);

    route.source = ExpressionFeature::PitchMotion;
    route.destination = ModulationDestination::StructuralMorph;
    route.amount = 0.22f;
    route.smoothing_seconds = 0.015f;
    matrix.SetRoute(8, route);

    route.source = ExpressionFeature::CandidateCompetition;
    route.destination = ModulationDestination::FeedbackAmount;
    route.amount = 0.45f;
    route.smoothing_seconds = 0.050f;
    matrix.SetRoute(9, route);

    route.source = ExpressionFeature::NoiseTransient;
    route.destination = ModulationDestination::Nonlinearity;
    route.amount = 0.50f;
    route.smoothing_seconds = 0.030f;
    matrix.SetRoute(10, route);

    route.source = ExpressionFeature::AttackStrength;
    route.destination = ModulationDestination::OutputTexture;
    route.amount = 0.25f;
    route.smoothing_seconds = 0.010f;
    matrix.SetRoute(11, route);
}

void ResynthesisEngine::InjectExcitation(float amount, float attack,
                                          float brightness, float noise,
                                          float texture)
{
    const float impulse = Clamp(amount, 0.0f, 1.0f) * (0.18f + 0.82f * attack);
    for(size_t i = 0; i < kModeCount; ++i)
    {
        const float upper = static_cast<float>(i) / static_cast<float>(kModeCount - 1);
        const float brightness_weight = (1.0f - upper) * (1.0f - brightness)
                                        + upper * brightness;
        modes_[i].energy += impulse * (0.35f + 0.65f * brightness_weight)
                             * (i == 0 ? 1.0f : 0.65f);
    }
    // A deterministic LFSR-like perturbation makes noisy attacks scatter
    // energy without introducing an unbounded noise source.
    random_state_ = random_state_ * 1664525u + 1013904223u;
    const float signed_noise = static_cast<float>((random_state_ >> 9) & 0x7fffff)
                               / 4194303.5f - 1.0f;
    modes_[1].energy += signed_noise * noise * texture * 0.025f;
    modes_[3].energy -= signed_noise * noise * texture * 0.018f;
}

void ResynthesisEngine::SetFrame(const ExpressionFrame& expression,
                                 const ModulationFrame& modulation,
                                 float frame_seconds)
{
    (void)frame_seconds;
    if(expression.pitch_valid && expression.pitch_hz > 20.0f
       && expression.pitch_hz < 1000.0f)
        root_frequency_hz_ = Clamp(expression.pitch_hz, 20.0f, 1000.0f);

    const size_t excitation = static_cast<size_t>(ModulationDestination::ExcitationAmount);
    const size_t complexity = static_cast<size_t>(ModulationDestination::ExcitationComplexity);
    const size_t upper = static_cast<size_t>(ModulationDestination::UpperModeEnergy);
    const size_t spectral = static_cast<size_t>(ModulationDestination::SpectralDistribution);
    const size_t instability = static_cast<size_t>(ModulationDestination::InstabilityInteraction);
    const size_t feedback = static_cast<size_t>(ModulationDestination::FeedbackAmount);
    const size_t nonlinear = static_cast<size_t>(ModulationDestination::Nonlinearity);
    const size_t coupling = static_cast<size_t>(ModulationDestination::ModeCoupling);
    const size_t stochastic = static_cast<size_t>(ModulationDestination::StochasticExcitation);
    const size_t damping = static_cast<size_t>(ModulationDestination::Damping);
    const size_t resonator_damping = static_cast<size_t>(ModulationDestination::ResonatorDamping);
    const size_t spread = static_cast<size_t>(ModulationDestination::RatioSpread);
    const size_t morph = static_cast<size_t>(ModulationDestination::StructuralMorph);
    const size_t output_texture = static_cast<size_t>(ModulationDestination::OutputTexture);

    const float amplitude = Clamp01(Feature(expression, ExpressionFeature::Amplitude));
    const float attack = Clamp01(Feature(expression, ExpressionFeature::AttackStrength));
    const float brightness = Clamp01(Feature(expression, ExpressionFeature::Brightness));
    const float noise = Clamp01(Feature(expression, ExpressionFeature::NoiseTransient));
    const float softness = macros_[static_cast<size_t>(Macro::Softness)];
    const float interaction = macros_[static_cast<size_t>(Macro::Interaction)];
    const float chaos = macros_[static_cast<size_t>(Macro::Chaos)];
    const float harmonicity = macros_[static_cast<size_t>(Macro::Harmonicity)];
    harmonicity_ = harmonicity;
    attack_body_ = macros_[static_cast<size_t>(Macro::AttackBody)];
    excitation_amount_ = Clamp(amplitude * (base_.excitation_amount
                                              + modulation.values[excitation]),
                                0.0f, 1.0f);
    upper_mode_energy_ = Clamp(base_.upper_mode_energy + 0.80f * brightness
                               + 0.30f * modulation.values[upper]
                               + 0.25f * modulation.values[spectral], 0.0f, 1.0f);
    upper_mode_energy_ = Clamp(upper_mode_energy_ * (1.0f - 0.35f * softness),
                               0.0f, 1.0f);
    coupling_ = Clamp(base_.mode_coupling + 0.22f * modulation.values[coupling]
                      + 0.16f * modulation.values[instability]
                      + 0.12f * interaction + 0.06f * chaos, 0.0f, 0.42f);
    feedback_ = Clamp(base_.feedback + 0.10f * modulation.values[feedback]
                          + 0.16f * modulation.values[instability],
                      0.0f, 0.22f);
    feedback_ = Clamp(feedback_ + 0.08f * interaction - 0.08f * softness,
                      0.0f, 0.22f);
    nonlinearity_ = Clamp(base_.nonlinearity
                               + 0.20f * (noise + modulation.values[morph])
                               + 0.12f * modulation.values[nonlinear]
                               - 0.10f * softness + 0.08f * chaos,
                           0.0f, 0.42f);
    damping_ = Clamp(base_.damping + 0.22f * amplitude + 0.20f * modulation.values[damping]
                         + 0.20f * modulation.values[resonator_damping]
                         + 0.15f * softness,
                     0.04f, 0.70f);
    ratio_spread_ = Clamp(base_.ratio_spread + 0.10f * modulation.values[spread], -0.10f, 0.10f);
    texture_ = Clamp(base_.output_texture + 0.75f * modulation.values[stochastic]
                     + 0.20f * modulation.values[morph]
                     + 0.20f * modulation.values[output_texture], 0.0f, 1.0f);
    // Process() applies this once per audio sample. Keeping the coefficient
    // in seconds (rather than analysis frames) prevents a 93 Hz control update
    // from accidentally turning the modes into a few-sample click.
    frame_decay_ = std::exp(-(2.0f + 5.0f * damping_) / sample_rate_);

    if(expression.pitch_valid && expression.pitch_hz > 0.0f)
    {
        const float impulse = excitation_amount_
                              * (0.35f + 0.65f * modulation.values[complexity])
                              * (1.0f + 0.50f * attack_body_);
        pending_excitation_ = Clamp(pending_excitation_ + impulse, 0.0f, 1.5f);
        pending_attack_ = attack;
        pending_brightness_ = brightness;
        pending_noise_ = noise;
        pending_texture_ = texture_;
    }
}

float ResynthesisEngine::Process()
{
    const float pending = pending_excitation_;
    pending_excitation_ = 0.0f;
    if(pending > 0.0f)
        InjectExcitation(pending, pending_attack_, pending_brightness_,
                         pending_noise_, pending_texture_);

    float output = 0.0f;
    float previous = 0.0f;
    for(size_t i = 0; i < kModeCount; ++i)
    {
        const float harmonic_ratio = static_cast<float>(i + 1);
        const float ratio_base = mode_ratios_[i] * (1.0f - harmonicity_)
                                 + harmonic_ratio * harmonicity_;
        const float ratio = Clamp(ratio_base * (1.0f + ratio_spread_
                                                 * static_cast<float>(i)), 0.5f, 5.0f);
        const float frequency = Clamp(root_frequency_hz_ * ratio, 20.0f,
                                      0.42f * sample_rate_);
        modes_[i].phase += frequency / sample_rate_;
        if(modes_[i].phase >= 1.0f)
            modes_[i].phase -= 1.0f;
        const float oscillator = std::sin(2.0f * kPi * modes_[i].phase);
        const float exchange = coupling_ * (previous - modes_[i].last_output);
        modes_[i].energy += exchange * 0.012f;
        modes_[i].energy *= frame_decay_;
        modes_[i].energy = Clamp(modes_[i].energy, -0.35f, 1.2f);
        const float shaped = std::tanh(oscillator * modes_[i].energy
                                       * (1.0f + nonlinearity_ * modes_[i].energy));
        modes_[i].last_output = shaped;
        output += shaped * mode_weights_[i]
                  * (i == 0 ? 1.0f : (0.35f + 0.65f * upper_mode_energy_));
        previous = shaped;
    }

    const float feedback_state = std::tanh(output * feedback_ * 2.5f);
    for(size_t i = 1; i < kModeCount; ++i)
        modes_[i].phase += feedback_state * 0.0004f * static_cast<float>(i);
    return Clamp(output * 0.72f, -0.92f, 0.92f);
}
} // namespace bass
