#include <cassert>
#include <cmath>

#include "AnalysisConfig.h"
#include "PitchTracker.h"

namespace
{
float Cents(float a, float b)
{
    return 1200.0f * std::log2(a / b);
}

bool Near(float value, float expected, float tolerance_hz = 1.0f)
{
    return std::fabs(value - expected) <= tolerance_hz;
}

bass::SignalState Active(bool onset = false)
{
    return {0.20f, 0.60f, true, onset};
}

float SumFrameMovementCents(const float* values, size_t count)
{
    float total = 0.0f;
    for(size_t i = 1; i < count; ++i)
        total += std::fabs(Cents(values[i], values[i - 1]));
    return total;
}
} // namespace

int main()
{
    // A weak octave harmonic must never turn a real low fundamental into an
    // arbitrary global preference for the higher candidate.
    const float low_fundamentals[] = {31.0f, 41.0f, 49.0f, 55.0f};
    for(const float low : low_fundamentals)
    {
        const bass::PitchCandidate real_low[] = {
            {low, 0.99f, 0},
            {low * 2.0f, 0.85f, 0},
        };
        bass::PitchTracker low_tracker;
        low_tracker.Init();
        bass::PitchTrackResult result = low_tracker.Update(real_low, 2, Active());
        assert(result.valid);
        assert(Near(result.frequency_hz, low));
        result = low_tracker.Update(real_low, 2, Active());
        assert(result.valid);
        assert(!result.family_promoted);
        assert(Near(result.frequency_hz, low));
    }

    // Recorded-family-style fixture: a 49-Hz raw winner has a near-equal
    // 98-Hz relative. octave_v1 keeps the raw winner for one causal frame,
    // then confirms the 98-Hz family member on the second frame.
    const bass::PitchCandidate octave_family[] = {
        {49.0f, 0.990f, 0},
        {98.0f, 0.930f, 0},
        {32.7f, 0.700f, 0},
    };
    bass::PitchTracker octave_tracker;
    octave_tracker.Init();
    bass::PitchTrackResult result = octave_tracker.Update(octave_family, 3, Active());
    assert(result.valid);
    assert(!result.family_promoted);
    assert(Near(result.pre_stability_frequency_hz, 49.0f));
    result = octave_tracker.Update(octave_family, 3, Active());
    assert(result.valid);
    assert(result.family_promoted);
    assert(result.stability_bypass);
    assert(Near(result.pre_stability_frequency_hz, 73.5f));
    for(int i = 0; i < 7; ++i)
        result = octave_tracker.Update(octave_family, 3, Active());
    assert(result.family_promoted);
    assert(Near(result.frequency_hz, 98.0f, 1.0f));

    // Parity fixture taken from the committed octave_v1 candidate trace at
    // 74.293-74.315 s. The 92.31-Hz candidate becomes eligible on the middle
    // frame and is accepted only after it persists on the final frame.
    const bass::PitchCandidate recorded_74293[] = {
        {46.153846f, 0.998974f, 0},
        {30.848329f, 0.928215f, 0},
        {92.307692f, 0.917897f, 0},
        {37.617554f, 0.256078f, 0},
    };
    const bass::PitchCandidate recorded_74304[] = {
        {46.153846f, 0.999212f, 0},
        {30.769230f, 0.927843f, 0},
        {92.307692f, 0.920811f, 0},
        {37.617554f, 0.272297f, 0},
    };
    const bass::PitchCandidate recorded_74315[] = {
        {46.153846f, 0.999454f, 0},
        {30.848329f, 0.930892f, 0},
        {92.307692f, 0.922282f, 0},
        {37.617554f, 0.265213f, 0},
    };
    bass::PitchTracker recorded_tracker;
    recorded_tracker.Init();
    result = recorded_tracker.Update(recorded_74293, 4, Active());
    assert(!result.family_promoted);
    assert(Near(result.pre_stability_frequency_hz, 46.153846f, 0.01f));
    result = recorded_tracker.Update(recorded_74304, 4, Active());
    assert(!result.family_promoted);
    assert(Near(result.pre_stability_frequency_hz, 46.153846f, 0.01f));
    result = recorded_tracker.Update(recorded_74315, 4, Active());
    assert(result.family_promoted);
    // The committed Mac trace reports 69.230769 Hz here: 46.153846 Hz plus
    // the exact selected 0.50 promoted-family slew toward 92.307692 Hz.
    assert(Near(result.pre_stability_frequency_hz, 69.230769f, 0.01f));
    assert(Near(result.frequency_hz, result.pre_stability_frequency_hz, 0.001f));

    // An isolated near-equal upper relative cannot survive the two-frame
    // promotion requirement.
    const bass::PitchCandidate low_only[] = {{49.0f, 0.990f, 0}};
    bass::PitchTracker persistence_tracker;
    persistence_tracker.Init();
    result = persistence_tracker.Update(low_only, 1, Active());
    result = persistence_tracker.Update(octave_family, 3, Active());
    assert(!result.family_promoted);
    assert(Near(result.pre_stability_frequency_hz, 49.0f));
    result = persistence_tracker.Update(low_only, 1, Active());
    assert(!result.family_promoted);
    result = persistence_tracker.Update(octave_family, 3, Active());
    assert(!result.family_promoted);

    // The adaptive one-pole reduces nearby sustain jitter in cents space.
    const float jitter_input[] = {100.0f, 100.6f, 99.4f, 100.4f,
                                  99.7f, 100.5f, 99.5f, 100.2f};
    float jitter_pre[sizeof(jitter_input) / sizeof(jitter_input[0])] = {};
    float jitter_final[sizeof(jitter_input) / sizeof(jitter_input[0])] = {};
    bass::PitchTracker jitter_tracker;
    jitter_tracker.Init();
    for(size_t i = 0; i < sizeof(jitter_input) / sizeof(jitter_input[0]); ++i)
    {
        const bass::PitchCandidate candidate[] = {{jitter_input[i], 0.99f, 0}};
        result = jitter_tracker.Update(candidate, 1, Active());
        assert(result.valid);
        jitter_pre[i] = result.pre_stability_frequency_hz;
        jitter_final[i] = result.frequency_hz;
        if(i > 0)
            assert(!result.stability_bypass);
    }
    assert(SumFrameMovementCents(jitter_final,
                                 sizeof(jitter_final) / sizeof(jitter_final[0]))
           < SumFrameMovementCents(jitter_pre,
                                   sizeof(jitter_pre) / sizeof(jitter_pre[0])));

    // A gradual slide develops a causal trend and bypasses the stable-note
    // smoother rather than becoming a lagging staircase.
    bass::PitchTracker slide_tracker;
    slide_tracker.Init();
    bool saw_slide_bypass = false;
    for(int i = 0; i < 10; ++i)
    {
        const bass::PitchCandidate candidate[] = {{100.0f + 2.5f * i, 0.99f, 0}};
        result = slide_tracker.Update(candidate, 1, Active());
        if(result.stability_bypass)
        {
            saw_slide_bypass = true;
            assert(Near(result.frequency_hz, result.pre_stability_frequency_hz,
                        0.001f));
        }
    }
    assert(saw_slide_bypass);

    // A sufficiently large real transition is immediately visible to the
    // final monitor trajectory.
    bass::PitchTracker transition_tracker;
    transition_tracker.Init();
    const bass::PitchCandidate one_hundred[] = {{100.0f, 0.99f, 0}};
    const bass::PitchCandidate two_hundred[] = {{200.0f, 0.99f, 0}};
    transition_tracker.Update(one_hundred, 1, Active());
    result = transition_tracker.Update(two_hundred, 1, Active());
    assert(result.stability_bypass);
    assert(Near(result.frequency_hz, result.pre_stability_frequency_hz,
                0.001f));

    // Onset is a direct adaptive-stability bypass, independently of family
    // scoring or the gate thresholds.
    bass::PitchTracker attack_tracker;
    attack_tracker.Init();
    attack_tracker.Update(one_hundred, 1, Active());
    const bass::PitchCandidate attack_candidate[] = {{100.5f, 0.99f, 0}};
    result = attack_tracker.Update(attack_candidate, 1, Active(true));
    assert(result.stability_bypass);
    assert(Near(result.frequency_hz, result.pre_stability_frequency_hz,
                0.001f));

    // The selected Mac acquisition/hold amplitudes remain unchanged.
    bass::PitchTracker calibrated_tracker;
    calibrated_tracker.Init();
    result = calibrated_tracker.Update(one_hundred, 1,
                                       {bass::kGateOnThreshold, 0.0f, true, false});
    assert(result.valid);
    result = calibrated_tracker.Update(one_hundred, 1,
                                       {bass::kGateOffThreshold, 0.0f, true, false});
    assert(result.valid);

    const bass::SignalState inactive = {0.0f, 0.0f, false, false};
    for(int i = 0; i < 9; ++i)
        result = calibrated_tracker.Update(nullptr, 0, inactive);
    assert(result.valid);
    result = calibrated_tracker.Update(nullptr, 0, inactive);
    assert(!result.valid);
    return 0;
}
