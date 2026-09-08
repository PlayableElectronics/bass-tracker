#include <cassert>
#include <cmath>

#include "PitchTracker.h"

namespace
{
bool Near(float value, float expected)
{
    return std::fabs(value - expected) < 1.0f;
}
} // namespace

int main()
{
    const bass::SignalState active = {0.20f, 0.60f, true, true};
    const bass::PitchCandidate e_family[] = {
        {74.1f, 0.986f, 162},
        {37.1f, 0.981f, 323},
    };
    const bass::PitchCandidate b_family[] = {
        {82.0f, 0.986f, 146},
        {41.0f, 0.981f, 293},
    };

    bass::PitchTracker tracker;
    tracker.Init();
    bass::PitchTrackResult result = tracker.Update(e_family, 2, active);
    assert(result.valid);
    assert(Near(result.frequency_hz, 37.1f));

    result = tracker.Update(e_family, 2, {0.18f, 0.10f, true, false});
    assert(result.valid);
    assert(Near(result.frequency_hz, 37.1f));

    bass::PitchTracker b_tracker;
    b_tracker.Init();
    result = b_tracker.Update(b_family, 2, active);
    assert(result.valid);
    assert(Near(result.frequency_hz, 41.0f));

    const bass::SignalState inactive = {0.0f, 0.0f, false, false};
    for(int i = 0; i < 9; ++i)
        result = b_tracker.Update(nullptr, 0, inactive);
    assert(result.valid);
    result = b_tracker.Update(nullptr, 0, inactive);
    assert(!result.valid);
    return 0;
}
